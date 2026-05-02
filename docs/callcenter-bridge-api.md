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
- `POST /login` não espera mais de forma síncrona pelo canal técnico de confirmação; quando o runtime retorna `logging`, o bridge persiste um pending login e a confirmação vem pelo status/relay subsequente.

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
- reutiliza cache curto de `campaign_context` por `agent_id + call_id` para evitar lookups repetidos entre ticks

Eventos já normalizados pelo diff:

- `agent.paused`
- `agent.logged_out`
- `agent.status_snapshot`
- `call.answered`
- `call.hangup`

### Campaign context por agente

- `GET /v1/agents/{agentId}/campaign-context`

Query params opcionais:

- `identifier_type` default `cpf`
- `attribute_column` default `2`

Resposta:

```json
{
  "success": true,
  "context": {
    "agent_id": "Agent/99",
    "extension": "1001",
    "call_id": "1692380000.10",
    "campaign_id": "2",
    "direction": "outbound",
    "phone": "5571999999999",
    "identifier_type": "cpf",
    "identifier_value": "12345678909",
    "source": "issabel-callcenter-bridge",
    "resolved_from": "call_attribute"
  }
}
```

Observações:

- o bridge resolve apenas contexto estruturado de campanha para integrações do painel
- ele não replica genericamente qualquer `campaign_external_url.urltemplate`
- quando não houver chamada de campanha ativa para o agente, retorna `context: null`
- eventos `call.focus` e `call.answered` podem sair enriquecidos com `campaign_context`

## Estado local

O módulo persiste em `CALLCENTER_BRIDGE_STATE_ROOT`:

- `agent_extensions.json`
- `last_snapshot.json`
- `campaign_context_cache.json`

Esses arquivos vivem por padrão em:

- `/var/lib/asterisk/issabel-module-state/callcenter_bridge`

## Variáveis

Veja `module.env.example`.

## Relay contínuo no host

Para produção, o relay pode rodar continuamente no host via `systemd` sem depender de execução manual:

- `deploy/systemd/callcenter-bridge-relay.service`
- `deploy/systemd/callcenter-bridge-relay.timer`
- `deploy/systemd/callcenter-bridge-relay.sh.example`
- `scripts/install-callcenter-bridge-relay.sh`

Instalação:

```bash
./scripts/install-callcenter-bridge-relay.sh
```

Contrato padrão do instalador:

- script em `/usr/local/bin/callcenter-bridge-relay.sh`
- timer `callcenter-bridge-relay.timer`
- frequência `OnUnitActiveSec=1s`
- frequência sobrescrevível via `CALLCENTER_BRIDGE_RELAY_INTERVAL_SECONDS`
- URL local `https://127.0.0.1/modules/callcenter_bridge/api.php/v1/events/relay`
- token carregado do `module.env` do módulo
