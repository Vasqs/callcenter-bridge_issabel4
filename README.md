# Issabel Callcenter Bridge

Wrapper local para o módulo `issabel-callcenter` com contrato HTTP estável para:

- login/logout de agente
- pausa/retorno
- status de agentes e filas
- chamadas ativas
- originate via ECCP `schedulecall`
- hangup via ECCP
- binding persistido de `ramal` por agente
- contexto de campanha estruturado por agente
- relay de snapshots/eventos para o `painel`

## Estrutura

```text
callcenter_bridge/
├── deploy/
│   └── systemd/
├── scripts/
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
- `http://127.0.0.1:8088/modules/callcenter_bridge/api.php/v1/agents/99/campaign-context`

Compatibilidade:

- `api.php?route=/v1/agents`

## Auth

Use `Authorization: Bearer <CALLCENTER_BRIDGE_API_TOKEN>`.

## Configuração

Copie `module.env.example` para `module.env` quando precisar sobrescrever defaults locais.

O relay para o painel usa:

- `CALLCENTER_BRIDGE_PANEL_WEBHOOK_URL`
- `CALLCENTER_BRIDGE_PANEL_WEBHOOK_TOKEN`

## Relay contínuo no host

Para manter o relay de eventos e contexto de campanha ativo sem depender de execução manual, o repositório inclui artefatos `systemd` e um instalador:

- `deploy/systemd/callcenter-bridge-relay.service`
- `deploy/systemd/callcenter-bridge-relay.timer`
- `deploy/systemd/callcenter-bridge-relay.sh.example`
- `scripts/install-callcenter-bridge-relay.sh`

Instalação no host do Issabel:

```bash
./scripts/install-callcenter-bridge-relay.sh
```

Contrato padrão:

- script final em `/usr/local/bin/callcenter-bridge-relay.sh`
- timer habilitado com `systemctl enable --now callcenter-bridge-relay.timer`
- cadence padrão de `1s`
- token lido de `module.env`
- relay local para `https://127.0.0.1/modules/callcenter_bridge/api.php/v1/events/relay`

## Notas

- O wrapper usa ECCP quando disponível no runtime Issabel.
- O `ramal` persistido pelo wrapper é um binding operacional para login/originate; não altera o schema nativo do callcenter.
- O bridge não habilita nem gerencia WebRTC de navegador no Issabel.
- O papel do bridge é API/webhook operacional para callcenter, estado de agente e compatibilidade com o PBX legado.
- O endpoint `campaign-context` expõe contexto estruturado de campanha para o painel sem vazar nomes internos do CRM.
- O relay pode enriquecer eventos `call.focus` e `call.answered` com `campaign_context`; integrações legadas por `External URL` continuam como fallback.
