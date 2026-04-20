# Callcenter Bridge API

O módulo local `callcenter_bridge` expõe um wrapper HTTP em volta do runtime ECCP do `issabel-callcenter`.

O bridge não é responsável por habilitar WebRTC de navegador no Issabel. O papel dele é controle operacional, ingestão/relay de eventos e compatibilidade com o callcenter/PBX legado.

Base local:

- `http://127.0.0.1:8088/modules/callcenter_bridge/api.php`

Compatibilidade de rota:

- `api.php/v1/...`
- `api.php?route=/v1/...`

Auth:

- `Authorization: Bearer <CALLCENTER_BRIDGE_API_TOKEN>`

## Endpoints

### Health

- `GET /v1/health`

Resposta:

```json
{
  "success": true,
  "health": {
    "dialer_running": true,
    "asterisk_ready": true,
    "db_ready": true
  }
}
```

### Agents

- `GET /v1/agents`
- `GET /v1/agents/{agentId}/status`
- `POST /v1/agents/{agentId}/login`
- `POST /v1/agents/{agentId}/logout`
- `POST /v1/agents/{agentId}/pause`
- `POST /v1/agents/{agentId}/unpause`
- `PATCH /v1/agents/{agentId}/extension`

Exemplos:

```json
{
  "extension": "1001"
}
```

```json
{
  "pause_id": "1"
}
```

Observações:

- `GET /v1/agents` retorna `agent_id` no formato ECCP e `route_key` seguro para uso nas rotas por path.
- `agentId` nas rotas aceita:
  - `route_key` numérico vindo da listagem, por exemplo `1`
  - alias sem barra como `Agent-1`, `Agent:1`, `SIP-1001`
  - o formato ECCP original `Agent/1` ou `SIP/1001` apenas quando a chamada usar `api.php?route=...`, porque a variante `api.php/v1/...` passa pelo Apache e perde a barra no path
- `PATCH /extension` persiste o binding operacional do ramal no wrapper; esse valor é reutilizado no login se o payload não trouxer `extension`.

### Calls

- `GET /v1/calls/active`
- `POST /v1/calls/originate`
- `POST /v1/calls/{callId}/hangup`

Originate:

```json
{
  "agent_id": "Agent/1",
  "phone": "5571999999999",
  "call_id": "panel-call-001"
}
```

Observações:

- o originate usa ECCP `schedulecall` com o mesmo agente como alvo operacional
- o hangup usa ECCP `hangup` e requer `agent_id` no corpo

### Queues

- `GET /v1/queues`

Retorna:

- filas vindas de `getincomingqueuelist` + `getincomingqueuestatus`
- pausas cadastradas na tabela `call_center.break`

### Relay de eventos

- `POST /v1/events/relay`

Payload opcional:

```json
{
  "company_key": "company-demo",
  "webhook_url": "https://painel.test/webhooks/issabel/callcenter/events",
  "webhook_token": "secret"
}
```

Comportamento:

- lê o último snapshot salvo em `CALLCENTER_BRIDGE_STATE_ROOT`
- gera um snapshot atual de agentes e chamadas
- produz eventos normalizados por diff
- opcionalmente envia esses eventos para o `painel`

Eventos já normalizados pelo diff:

- `agent.paused`
- `agent.logged_out`
- `agent.status_snapshot`
- `call.answered`
- `call.hangup`

## Estado local

O módulo persiste em `CALLCENTER_BRIDGE_STATE_ROOT`:

- `agent_extensions.json`
- `last_snapshot.json`

Esses arquivos vivem por padrão em:

- `/var/lib/asterisk/issabel-module-state/callcenter_bridge`

## Variáveis

Veja `module.env.example`.
