# Horus VMS

Sistema de Gerenciamento de Vídeo (VMS) acessível exclusivamente via navegador,
inspirado em ZoneMinder, iSpy Connect e Frigate. Visualização ao vivo de baixa
latência (WebRTC), gravação eficiente por remux, detecção de movimento por
zonas e detecção de objetos por IA com fallback automático para CPU.

## Serviços

| Serviço | Tecnologia | Função |
|---|---|---|
| `video-engine` | Python + FFmpeg + OpenCV + ONNX Runtime | Decodificação, detecção de movimento/objetos, gravação, retenção |
| `go2rtc` | go2rtc | Ingestão RTSP/ONVIF → WebRTC (sub-segundo) e LL-HLS, sem transcodificar |
| `backend-api` | FastAPI | REST + WebSocket, autenticação JWT/RBAC, orquestração |
| `frontend` | React + TypeScript + Vite + Tailwind (Nginx) | SPA responsiva, tema claro/escuro |
| `postgres` / SQLite | PostgreSQL 16 | Apenas metadados — nunca mídia |
| `mosquitto` | Eclipse Mosquitto | Eventos de detecção em tempo real |
| `redis` | Redis 7 | Cache, rate limiting, status |
| `minio` (opcional) | MinIO | Arquivamento S3-compatível |

## Início rápido

```bash
cp .env.example .env
# preencha SECRET_KEY, POSTGRES_PASSWORD, INTERNAL_API_TOKEN,
# CREDENTIALS_KEY e ADMIN_PASSWORD (instruções no próprio arquivo)
docker compose up -d --build
```

Acesse `http://localhost` (ou `https://` se houver certificados em
`config/nginx/certs/`) e entre com `ADMIN_EMAIL` / `ADMIN_PASSWORD`.

Para o arquivamento opcional em MinIO: `docker compose --profile archive up -d`.

## Documentação

- [Arquitetura e justificativas](docs/architecture.md)
- [Implantação (CPU-only e acelerado)](docs/deployment.md)
- [Contratos entre serviços (MQTT, API interna, layout de mídia)](docs/CONTRACTS.md)
- API REST: OpenAPI/Swagger gerada pelo FastAPI em `/api/v1/docs` (atrás do proxy: `http://localhost/api/v1/docs`)

## Estrutura do repositório

```
backend/        # backend-api (FastAPI)
video-engine/   # núcleo de vídeo e IA (Python)
frontend/       # SPA (React + TS) + Nginx (proxy de /api e /go2rtc)
config/         # go2rtc, mosquitto, certificados nginx
docs/           # arquitetura, implantação, contratos
docker-compose.yml
```

## Escala recomendada

| Cenário | Decodificação | Detecção IA |
|---|---|---|
| 1–3 câmeras (doméstico) | CPU | CPU com modelo leve (YOLOv8n) |
| 4–8 câmeras | GPU integrada (QuickSync/VAAPI) | Coral TPU recomendado |
| 8+ câmeras (comercial) | GPU dedicada ou integrada | Coral TPU ou GPU NVIDIA |

O hardware é detectado automaticamente na inicialização do `video-engine` e
exibido em **Configurações → Sistema**; decodificação e inferência são
selecionadas de forma independente, com fallback para CPU.
