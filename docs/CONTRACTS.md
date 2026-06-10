# Horus VMS — Contratos entre Serviços

Este documento é a **fonte de verdade** dos contratos compartilhados entre
`backend-api`, `video-engine` e `frontend`. Qualquer mudança aqui exige
atualização coordenada dos três serviços.

---

## 1. Tópicos MQTT

Broker: `mosquitto:1883` (interno). Todos os payloads são JSON UTF-8.

| Tópico | Direção | Payload |
|---|---|---|
| `horus/events/{camera_id}` | engine → backend | Evento de detecção (ver §1.1) |
| `horus/status/{camera_id}` | engine → backend | Status da câmera (ver §1.2) |
| `horus/engine/hardware` | engine → backend (retained) | Relatório de hardware (ver §1.3) |
| `horus/engine/command` | backend → engine | Comando (ver §1.4) |
| `horus/recordings/{camera_id}` | engine → backend | Segmento de gravação finalizado (ver §1.5) |

### 1.1 Evento de detecção — `horus/events/{camera_id}`
```json
{
  "event_id": "uuid4",
  "camera_id": 1,
  "type": "motion | object",
  "label": "person | car | animal | null",
  "confidence": 0.92,
  "zone_id": 3,
  "started_at": "2026-06-10T12:00:00Z",
  "ended_at": "2026-06-10T12:00:14Z",
  "snapshot_path": "/media/snapshots/1/2026-06-10/uuid4.webp",
  "clip_path": "/media/events/1/2026-06-10/uuid4.mp4",
  "duration_s": 14.2
}
```
`ended_at`, `clip_path` e `duration_s` podem ser `null` no evento inicial
(`phase: "start"`); um segundo publish com `phase: "end"` completa o evento.
Campo `phase`: `"start" | "update" | "end"`.

### 1.2 Status da câmera — `horus/status/{camera_id}` (retained)
```json
{
  "camera_id": 1,
  "state": "online | offline | connecting | error",
  "recording": true,
  "in_event": false,
  "fps": 14.8,
  "decode_path": "vaapi | nvdec | qsv | cpu",
  "detect_path": "tensorrt | edgetpu | openvino | onnx-cpu | none",
  "error": null,
  "ts": "2026-06-10T12:00:00Z"
}
```

### 1.3 Hardware — `horus/engine/hardware` (retained)
```json
{
  "decode": {"nvdec": false, "vaapi": true, "qsv": true, "cpu": true},
  "inference": {"tensorrt": false, "edgetpu": false, "openvino": true, "onnx_cpu": true},
  "selected": {"decode": "vaapi", "inference": "onnx_cpu"},
  "gpus": ["Intel UHD 630"],
  "ts": "2026-06-10T12:00:00Z"
}
```

### 1.4 Comando — `horus/engine/command`
```json
{"action": "reload_cameras | reload_zones | restart_camera | ptz", "camera_id": 1, "params": {}}
```
O engine relê a configuração via API interna do backend
(`GET /internal/cameras`, autenticada por `INTERNAL_API_TOKEN`).

### 1.5 Segmento de gravação — `horus/recordings/{camera_id}`
```json
{
  "camera_id": 1,
  "path": "/media/recordings/1/2026-06-10/12-00-00.mp4",
  "started_at": "2026-06-10T12:00:00Z",
  "ended_at": "2026-06-10T12:00:30Z",
  "codec": "h265",
  "size_bytes": 5242880,
  "kind": "continuous | event"
}
```

---

## 2. API interna (backend → engine bootstrap)

O video-engine consome do backend (header `X-Internal-Token: $INTERNAL_API_TOKEN`):

- `GET /internal/cameras` — lista completa de câmeras habilitadas, com URLs
  descriptografadas, zonas e agendamentos embutidos.
- `POST /internal/recordings` — registra segmento (mesmo shape do §1.5; usado
  como fallback HTTP se o MQTT estiver indisponível).

Shape de `GET /internal/cameras`:
```json
[{
  "id": 1, "name": "Entrada", "protocol": "rtsp",
  "main_url": "rtsp://user:pass@10.0.0.10:554/ch0",
  "sub_url": "rtsp://user:pass@10.0.0.10:554/ch1",
  "codec": "h265", "ptz": false, "enabled": true,
  "recording_mode": "motion",
  "pre_buffer_s": 5, "segment_s": 30,
  "retention_days_continuous": 7, "retention_days_event": 30,
  "detect_objects": true, "detect_fps": 5,
  "zones": [{"id": 3, "kind": "include", "polygon": [[0.1,0.1],[0.9,0.1],[0.9,0.9],[0.1,0.9]],
             "sensitivity": 25, "min_area": 0.005, "dwell_ms": 500}],
  "schedule": {"timezone": "America/Sao_Paulo",
               "rules": [{"days": [0,1,2,3,4], "start": "08:00", "end": "18:00", "mode": "continuous"}]}
}]
```
Polígonos usam coordenadas **normalizadas 0..1** (independentes de resolução).

---

## 3. go2rtc

- Config em `config/go2rtc/go2rtc.yaml`. O backend gerencia streams
  dinamicamente via API do go2rtc (`PUT /api/streams?name=cam{id}&src=...`).
- Convenção de nomes: `cam{id}` (stream principal), `cam{id}_sub` (substream).
- Frontend consome: WebRTC `ws://go2rtc:1984/api/ws?src=cam{id}` (proxied) e
  LL-HLS `http://go2rtc:1984/api/stream.m3u8?src=cam{id}`.
- O backend expõe `GET /api/v1/cameras/{id}/stream` que retorna as URLs
  públicas (atrás do proxy nginx em `/go2rtc/`).

---

## 4. REST API pública

Prefixo `/api/v1`. Autenticação: `Authorization: Bearer <JWT>`.
JWT claims: `sub` (user id), `role` (`admin|operator|viewer`), `exp`.
Refresh token via cookie httpOnly ou body.

Endpoints (resumo — o backend gera OpenAPI completo):

- `POST /auth/login` `{email, password}` → `{access_token, refresh_token, user}`
- `POST /auth/refresh`, `POST /auth/logout`
- `GET|POST /cameras`, `GET|PUT|DELETE /cameras/{id}`
- `POST /cameras/discover` → lista ONVIF `[{ip, name, xaddr, manufacturer}]`
- `POST /cameras/test` `{url, protocol}` → `{ok, codec, width, height, error}`
- `POST /cameras/{id}/ptz` `{action: "move|stop|preset", pan, tilt, zoom, preset}`
- `GET /cameras/{id}/stream` → `{webrtc_url, hls_url, sub_webrtc_url, sub_hls_url}`
- `GET|POST /cameras/{id}/zones`, `PUT|DELETE /cameras/{id}/zones/{zid}`
- `GET|PUT /cameras/{id}/schedule`
- `GET /recordings?camera_id&from&to&kind` → segmentos p/ timeline
- `GET /recordings/{id}/export` → arquivo mp4 (download)
- `GET /recordings/{id}/play` → stream mp4 com range requests
- `GET /events?camera_id&type&label&zone_id&from&to&page&size`
- `GET /events/{id}`; `GET /events/{id}/snapshot`; `GET /events/{id}/clip`
- `GET|POST|PUT|DELETE /notifications`
- `GET|POST|PUT|DELETE /users` (admin)
- `GET /system/hardware`, `GET /system/storage`
- `GET /audit` (admin)
- `WS /ws/events` — push de eventos em tempo real `{type:"event", data:{...}}`
- `WS /ws/status` — push de status `{type:"status", data:{...}}`

Erros: `{detail: "mensagem"}` com HTTP status apropriado.
Paginação: `{items: [...], total, page, size}`.

---

## 5. RBAC

| Ação | admin | operator | viewer |
|---|---|---|---|
| Ver câmeras/eventos/gravações permitidas | ✓ | ✓ | ✓ |
| Exportar clipes | ✓ | ✓ | ✗ |
| PTZ | ✓ | ✓ | ✗ |
| CRUD câmeras/zonas/agenda/notificações | ✓ | ✗ | ✗ |
| CRUD usuários, retenção, auditoria | ✓ | ✗ | ✗ |

Permissão por câmera: tabela `camera_permissions(user_id, camera_id)`;
admin vê tudo; para os demais, vazio = nenhum acesso.

---

## 6. Layout de mídia em disco (`/media`)

```
/media/recordings/{camera_id}/{YYYY-MM-DD}/{HH-MM-SS}.mp4   # contínua (retenção curta)
/media/events/{camera_id}/{YYYY-MM-DD}/{event_id}.mp4       # clipes de evento (retenção longa)
/media/snapshots/{camera_id}/{YYYY-MM-DD}/{event_id}.webp   # snapshots WebP
```

---

## 7. Variáveis de ambiente compartilhadas

| Variável | Serviços | Descrição |
|---|---|---|
| `DATABASE_URL` | backend | `postgresql+asyncpg://...` ou `sqlite+aiosqlite:///...` |
| `REDIS_URL` | backend | `redis://redis:6379/0` |
| `MQTT_HOST`/`MQTT_PORT` | backend, engine | `mosquitto` / `1883` |
| `SECRET_KEY` | backend | assinatura JWT |
| `CREDENTIALS_KEY` | backend | chave Fernet p/ credenciais de câmeras |
| `INTERNAL_API_TOKEN` | backend, engine | autentica API interna |
| `BACKEND_URL` | engine | `http://backend-api:8000` |
| `GO2RTC_URL` | backend, engine | `http://go2rtc:1984` |
| `MEDIA_ROOT` | backend, engine | `/media` |
| `MAX_DISK_USAGE_PCT` | engine | gatilho da rotação de retenção (ex.: `90`) |
