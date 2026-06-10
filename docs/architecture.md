# Horus VMS — Arquitetura e Justificativas

## Visão geral

```
câmeras (RTSP/ONVIF/RTMP/MJPEG/USB)
   │
   ├──────────────► go2rtc ──── WebRTC / LL-HLS ────► navegador (ao vivo)
   │                  ▲
   ▼                  │ registro dinâmico de streams
video-engine ◄────────┤
   │  detecção de movimento (zonas) + objetos (IA)   │
   │  gravação por remux segmentado + retenção       │
   │                                                 │
   ├── MQTT (eventos, status, hardware, segmentos) ──► backend-api
   │                                                 │   │
   └── /media (clipes, snapshots) ◄──────────────────┘   ├─ PostgreSQL/SQLite (metadados)
                                                         ├─ Redis (cache, rate limit)
                                                         └─ WS + REST ────► frontend (SPA)
```

## Decisões e justificativas

### Processos separados para vídeo e API
O `video-engine` roda continuamente, independente de haver navegador aberto —
gravação e detecção não podem depender de sessão de usuário. A comunicação é
desacoplada via MQTT (eventos) e uma API interna mínima (bootstrap de
configuração), de modo que cada serviço pode reiniciar sem derrubar o outro.

### go2rtc para o ao vivo
Reempacota RTSP em WebRTC (latência sub-segundo) e LL-HLS **sem
transcodificar** quando o codec é compatível (H.264/H.265). Isso retira o
caminho ao vivo do Python por completo: o engine usa o stream para análise e
gravação, enquanto o navegador consome direto do go2rtc — mesma estratégia do
Frigate.

### Gravação por remux, nunca recodificar
O FFmpeg copia o bitstream da câmera (`-c copy`) em segmentos curtos
(10–60 s). Custo de CPU próximo de zero por câmera; a segmentação dá
indexação, reprodução parcial e exclusão granular. O buffer pré-evento é
implementado mantendo um anel de segmentos recentes: ao disparar um evento, os
segmentos que cobrem `[início − pré-buffer, fim]` são concatenados (também por
cópia) no clipe do evento.

### Detecção no substream
Movimento e IA rodam no substream de baixa resolução (D1/CIF), o que permite
várias câmeras por núcleo de CPU. A gravação usa o stream principal em alta
resolução. Os dois fluxos são independentes.

### Detecção de movimento por zonas
Subtração de fundo (MOG2) + máscaras poligonais normalizadas (interesse e
exclusão) + limiares de sensibilidade, área mínima e tempo de permanência
(dwell) — a combinação clássica do ZoneMinder para suprimir falsos positivos
(árvores, sombras, insetos).

### IA com fallback em cascata
ONNX Runtime como camada de abstração: TensorRT (NVIDIA) → EdgeTPU (Coral) →
OpenVINO (Intel/AMD) → CPU com YOLOv8n em FPS reduzido. Decodificação
(NVDEC/VAAPI/QSV/CPU) é detectada e selecionada de forma **independente** da
inferência; qualquer combinação funciona. O relatório de hardware é publicado
em tópico MQTT retido e exibido na UI.

### Metadados no banco, mídia no disco
Vídeo no banco destrói o desempenho de ambos. PostgreSQL (ou SQLite no cenário
doméstico) guarda apenas caminhos, timestamps e atributos, indexados por
câmera+tempo para a timeline. Retenções separadas: contínua curta/rotativa,
eventos longa; ao atingir o limite de disco, a rotação remove primeiro os
segmentos contínuos mais antigos.

### Segurança
JWT curto + refresh, RBAC (admin/operador/visualizador) com permissão por
câmera, credenciais de câmera cifradas com Fernet em repouso, rate limiting de
login via Redis, log de auditoria e HTTPS/WSS no proxy Nginx.

## Fluxo de um evento (movimento → navegador)

1. Worker da câmera detecta movimento sustentado dentro de uma zona de interesse.
2. Publica `horus/events/{id}` com `phase=start` + snapshot WebP já gravado.
3. Backend persiste o evento e o repassa via `WS /ws/events`; o frontend
   exibe a notificação/atualiza o feed em tempo real.
4. Cessado o movimento (período de silêncio), o engine concatena os segmentos
   (incluindo pré-buffer), grava o clipe em `/media/events/...` e publica
   `phase=end` com duração e caminho do clipe.
5. Backend completa o registro e dispara notificações (webhook/e-mail/push)
   conforme os filtros configurados.

## Modelo de dados

Entidades: `users`, `cameras` (credenciais cifradas), `camera_permissions`,
`zones` (polígonos normalizados), `recordings`, `events`, `schedules`,
`notifications`, `push_subscriptions`, `audit_log`. Esquema completo nas
migrações Alembic em `backend/alembic/`.
