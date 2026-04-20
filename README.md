# Issabel Callcenter Bridge

Wrapper local para o módulo `issabel-callcenter` com contrato HTTP estável para:

- login/logout de agente
- pausa/retorno
- status de agentes e filas
- chamadas ativas
- originate via ECCP `schedulecall`
- hangup via ECCP
- binding persistido de `ramal` por agente
- relay de snapshots/eventos para o `painel`

## Estrutura

```text
callcenter_bridge/
├── web/
│   ├── api.php
│   └── lib/
├── hooks/
│   └── apply.sh
└── module.env.example
```

## URL

- `http://127.0.0.1:8088/modules/callcenter_bridge/api.php/v1/health`
- `http://127.0.0.1:8088/modules/callcenter_bridge/api.php/v1/agents`

Compatibilidade:

- `api.php?route=/v1/agents`

## Auth

Use `Authorization: Bearer <CALLCENTER_BRIDGE_API_TOKEN>`.

## Configuração

Copie `module.env.example` para `module.env` quando precisar sobrescrever defaults locais.

O relay para o painel usa:

- `CALLCENTER_BRIDGE_PANEL_WEBHOOK_URL`
- `CALLCENTER_BRIDGE_PANEL_WEBHOOK_TOKEN`

## Notas

- O wrapper usa ECCP quando disponível no runtime Issabel.
- O `ramal` persistido pelo wrapper é um binding operacional para login/originate; não altera o schema nativo do callcenter.
- O bridge não habilita nem gerencia WebRTC de navegador no Issabel.
- O papel do bridge é API/webhook operacional para callcenter, estado de agente e compatibilidade com o PBX legado.
