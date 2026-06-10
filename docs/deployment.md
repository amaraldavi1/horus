# Horus VMS — Guia de Implantação

## Requisitos

- Docker ≥ 24 e Docker Compose v2.
- Linux x86_64 (recomendado) ou ARM64.
- Disco dedicado ou volume amplo para `/media` (gravações).

## Instalação (qualquer cenário)

```bash
git clone <repo> horus && cd horus
cp .env.example .env
cp config/go2rtc/go2rtc.example.yaml config/go2rtc/go2rtc.yaml
openssl rand -hex 32        # → SECRET_KEY
openssl rand -hex 32        # → INTERNAL_API_TOKEN
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # → CREDENTIALS_KEY
# edite .env com os valores acima + POSTGRES_PASSWORD + ADMIN_PASSWORD
docker compose up -d --build
```

> O `go2rtc.yaml` é um arquivo de runtime: o go2rtc grava nele os streams
> registrados pela API — incluindo URLs RTSP com credenciais — e por isso ele
> fica fora do controle de versão (apenas o `.example` é versionado).

UI: `http://localhost` · API/Swagger: `http://localhost/api/v1/docs`.

### Armazenamento de mídia em disco dedicado

Por padrão `/media` é um volume Docker. Para usar um disco/NAS, troque no
`docker-compose.yml` (em `backend-api` e `video-engine`):

```yaml
volumes:
  - /mnt/vigilancia:/media
```

### HTTPS

Coloque `server.crt` e `server.key` em `config/nginx/certs/` e recrie o
container `frontend`. Sem certificados, o serviço atende somente em HTTP
(use um proxy externo com TLS, ex. Traefik/Caddy, se preferir).

### SQLite (instalação doméstica, sem Postgres)

No `.env`: `DATABASE_URL=sqlite+aiosqlite:////data/horus.db`, adicione um
volume para `/data` no `backend-api` e remova/ignore o serviço `postgres`.

---

## Cenário 1 — CPU-only (1–3 câmeras)

Nenhuma configuração extra: o `video-engine` detecta a ausência de
aceleradores e usa decodificação por software + YOLOv8n em CPU com FPS de
detecção reduzido (padrão 5 fps no substream). Verifique o caminho ativo em
**Configurações → Sistema** ou em `GET /api/v1/system/hardware`.

Dicas:
- Configure as câmeras com substream D1/CIF (ex. 704×480 a 5–10 fps).
- A gravação é remux puro (`-c copy`) — o custo de CPU vem só da detecção.

## Cenário 2 — Acelerado

### Intel/AMD (VAAPI / QuickSync) — decodificação
No `docker-compose.yml`, em `video-engine`, descomente:

```yaml
devices:
  - /dev/dri:/dev/dri
```

### NVIDIA (NVDEC + TensorRT) — decodificação e inferência
Instale o `nvidia-container-toolkit` no host e descomente o bloco `deploy`
do `video-engine`. Para inferência via GPU, instale a variante
`onnxruntime-gpu` na imagem (ver `video-engine/requirements.txt`).

### Coral TPU (EdgeTPU) — inferência
USB: descomente `- /dev/bus/usb:/dev/bus/usb`. PCIe: `- /dev/apex_0:/dev/apex_0`.
Coloque o modelo compilado para EdgeTPU em `video-engine/models/` (ver
`video-engine/models/README.md`).

Decodificação e inferência são independentes — qualquer combinação funciona
(ex.: QuickSync + Coral, ou NVDEC + CPU).

### Modelos de IA

Baixe `yolov8n.onnx` e monte em `/models` do `video-engine`:

```yaml
volumes:
  - ./video-engine/models:/models:ro
```

Sem modelo presente, o sistema opera apenas com detecção de movimento.

---

## MinIO (arquivamento opcional)

```bash
docker compose --profile archive up -d
```

Console em `http://localhost:9001`. Configure o destino de arquivamento por
câmera na UI (Câmeras → editar → armazenamento).

## Operação

- **Logs:** `docker compose logs -f video-engine backend-api`
- **Backup:** banco (`pg_dump`) + `/media`. Os metadados referenciam a mídia
  por caminho; restaure ambos juntos.
- **Atualização:** `git pull && docker compose up -d --build`
- **Retenção:** a rotação remove primeiro a gravação contínua mais antiga ao
  atingir `MAX_DISK_USAGE_PCT`; clipes de evento respeitam a retenção longa
  configurada por câmera.

## Solução de problemas

| Sintoma | Verificação |
|---|---|
| Câmera offline na grade | `docker compose logs video-engine`; teste a URL RTSP com `ffprobe` |
| WebRTC não conecta (cai p/ HLS) | UDP bloqueado — exponha a porta 8555/udp do go2rtc ou use `network_mode: host` |
| Sem eventos de movimento | Confira zonas de interesse, sensibilidade e `dwell_ms` |
| IA inativa | `GET /api/v1/system/hardware` e presença do modelo em `/models` |
| Disco cheio | Reduza retenção contínua; rotação automática age em `MAX_DISK_USAGE_PCT` |
