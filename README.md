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
- cadence configurável via `CALLCENTER_BRIDGE_RELAY_INTERVAL_SECONDS`
- token lido de `module.env`
- relay local para `https://127.0.0.1/modules/callcenter_bridge/api.php/v1/events/relay`

## Notas

- O wrapper usa ECCP quando disponível no runtime Issabel.
- O `ramal` persistido pelo wrapper é um binding operacional para login/originate; não altera o schema nativo do callcenter.
- O login de agente não bloqueia mais esperando a confirmação do canal; o bridge persiste o estado pendente e expõe `status=logging` até a reconciliação posterior.
- O bridge não habilita nem gerencia WebRTC de navegador no Issabel.
- O papel do bridge é API/webhook operacional para callcenter, estado de agente e compatibilidade com o PBX legado.
- O endpoint `campaign-context` expõe contexto estruturado de campanha para o painel sem vazar nomes internos do CRM.
- O relay pode enriquecer eventos `call.focus` e `call.answered` com `campaign_context`; esse contexto agora usa cache curto para evitar lookups repetidos entre ticks adjacentes.
- `CALLCENTER_BRIDGE_LOG_RELAY_TIMINGS=1` habilita telemetria simples do relay no log do PHP.
- Backlog operacional: tratar falhas de origem no tronco/provedor antes da entrada em fila. Em 2026-05-05, a campanha `fullconsig` (`id=4`) tentou discar via `SIP/saida_89`; o peer SIP estava `OK`, mas o provedor respondeu `SIP/2.0 402 Payment Required` com `Q.850 cause=21 Call Rejected`. No banco `call_center.calls`, essas tentativas apareceram como `failure_cause=127` e `failure_cause_txt=Interworking, unspecified`. Isso não deve ser classificado como falha de agente, voice-bar ou Reverb; o bridge deve futuramente expor erro estruturado de `trunk_origination` e recomendação operacional de alerta/pausa da campanha quando o padrão se repetir.
