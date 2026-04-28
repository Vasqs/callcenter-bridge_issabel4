<?php

class CallCenterService
{
    private $runtime;
    private $store;
    private $differ;

    public function __construct(CallCenterRuntime $runtime, CallCenterStateStore $store, $differ = null)
    {
        $this->runtime = $runtime;
        $this->store = $store;
        $this->differ = $differ;
    }

    public function handle($operation, array $params, array $payload)
    {
        switch ($operation) {
            case 'health':
                return array('success' => true, 'health' => $this->runtime->health());
            case 'agents.list':
                return array('success' => true, 'agents' => $this->applyStoredExtensions($this->runtime->listAgents()));
            case 'queues.list':
                return array('success' => true, 'queues' => $this->runtime->listQueues(), 'pauses' => $this->runtime->listPauses());
            case 'calls.active':
                return array('success' => true, 'calls' => $this->runtime->listActiveCalls());
            case 'agents.status':
                return $this->agentStatus($params['agentId']);
            case 'agents.campaign_context':
                return $this->campaignContext($params['agentId'], $payload);
            case 'agents.login':
                return $this->login($params['agentId'], $payload);
            case 'agents.logout':
                return $this->runAgentAction($params['agentId'], 'logout');
            case 'agents.pause':
                $pauseId = isset($payload['pause_id']) ? $payload['pause_id'] : (isset($payload['pause_code']) ? $payload['pause_code'] : '1');
                return $this->runAgentAction($params['agentId'], 'pause', array('pause_id' => (string) $pauseId));
            case 'agents.unpause':
                return $this->runAgentAction($params['agentId'], 'unpause');
            case 'agents.set_extension':
                return $this->setExtension($params['agentId'], $payload);
            case 'calls.originate':
                return $this->originate($payload);
            case 'calls.hangup':
                return $this->hangup($params['callId'], $payload);
            case 'events.relay':
                return $this->relay($this->snapshotDiffer(), $payload);
        }

        return array(
            'status' => 404,
            'success' => false,
            'message' => 'operation not implemented',
        );
    }

    private function snapshotDiffer()
    {
        if ($this->differ instanceof CallCenterSnapshotDiffer) {
            return $this->differ;
        }

        $source = getenv('CALLCENTER_BRIDGE_SOURCE');

        return new CallCenterSnapshotDiffer($source ? $source : 'issabel-callcenter');
    }

    private function login($agentId, array $payload)
    {
        $agent = $this->resolveAgent($agentId);
        if (isset($agent['success']) && $agent['success'] === false) {
            return $agent;
        }
        $extension = isset($payload['extension']) ? trim((string) $payload['extension']) : '';
        if ($extension === '') {
            $extension = (string) $this->storedAgentExtension($agent);
        }

        if ($extension === '') {
            return array(
                'status' => 422,
                'success' => false,
                'message' => 'extension is required for agent login',
            );
        }

        $this->store->persistAgentExtension($agent['route_key'], $agent['agent_id'], $extension);
        $this->store->persistPendingLogin($agent['route_key'], $agent['agent_id'], $extension);

        return array(
            'success' => true,
            'agent_id' => $agent['agent_id'],
            'route_key' => $agent['route_key'],
            'result' => $this->runtime->loginAgent($agent['agent_id'], $extension),
            'extension' => $extension,
        );
    }

    private function setExtension($agentId, array $payload)
    {
        $agent = $this->resolveAgent($agentId);
        if (isset($agent['success']) && $agent['success'] === false) {
            return $agent;
        }
        $extension = isset($payload['extension']) ? trim((string) $payload['extension']) : '';
        if ($extension === '') {
            return array(
                'status' => 422,
                'success' => false,
                'message' => 'extension is required',
            );
        }

        $this->store->persistAgentExtension($agent['route_key'], $agent['agent_id'], $extension);

        return array(
            'success' => true,
            'agent_id' => $agent['agent_id'],
            'route_key' => $agent['route_key'],
            'extension' => $extension,
        );
    }

    private function originate(array $payload)
    {
        $agentId = isset($payload['agent_id']) ? trim((string) $payload['agent_id']) : '';
        $phone = '';
        if (isset($payload['phone'])) {
            $phone = trim((string) $payload['phone']);
        } elseif (isset($payload['destination_number'])) {
            $phone = trim((string) $payload['destination_number']);
        }
        $callId = isset($payload['call_id']) ? trim((string) $payload['call_id']) : '';

        if ($agentId === '' || $phone === '') {
            return array(
                'status' => 422,
                'success' => false,
                'message' => 'agent_id and phone are required',
            );
        }

        $agent = $this->resolveAgent($agentId);
        if (isset($agent['success']) && $agent['success'] === false) {
            return $agent;
        }

        $extension = isset($payload['extension']) ? trim((string) $payload['extension']) : '';
        if ($extension === '') {
            $extension = trim((string) $this->storedAgentExtension($agent));
        }

        if ($extension === '') {
            $status = $this->runtime->getAgentStatus($agent['agent_id']);
            if (isset($status['raw_status']['extension'])) {
                $extension = trim((string) $status['raw_status']['extension']);
            }
        }

        if ($extension === '') {
            return array(
                'status' => 422,
                'success' => false,
                'message' => 'extension is required for originate',
            );
        }

        return array(
            'success' => true,
            'agent_id' => $agent['agent_id'],
            'route_key' => $agent['route_key'],
            'extension' => $extension,
            'result' => $this->runtime->originateCall($agent['agent_id'], $extension, $phone, $callId !== '' ? $callId : null),
        );
    }

    private function relay(CallCenterSnapshotDiffer $differ, array $payload)
    {
        $companyKey = isset($payload['company_key']) ? trim((string) $payload['company_key']) : 'default';
        $webhookUrl = isset($payload['webhook_url']) ? trim((string) $payload['webhook_url']) : trim((string) getenv('CALLCENTER_BRIDGE_PANEL_WEBHOOK_URL'));
        $webhookToken = isset($payload['webhook_token']) ? trim((string) $payload['webhook_token']) : trim((string) getenv('CALLCENTER_BRIDGE_PANEL_WEBHOOK_TOKEN'));

        $current = (isset($payload['snapshot']) && is_array($payload['snapshot']))
            ? $payload['snapshot']
            : $this->runtime->buildSnapshot($this->store);

        $previous = $this->store->readLastSnapshot();
        $previousFocusedCalls = method_exists($this->store, 'readFocusedCallIds')
            ? $this->store->readFocusedCallIds()
            : array();
        $nextFocusedCalls = array();
        $events = $differ->diff($previous, $current, $companyKey, is_array($previousFocusedCalls) ? $previousFocusedCalls : array(), $nextFocusedCalls);
        $events = $this->appendSyntheticFocusEvents($events, $current, $companyKey, $payload, is_array($previousFocusedCalls) ? $previousFocusedCalls : array(), $nextFocusedCalls);
        $events = $this->suppressStaleHangupEvents($events, $current);
        $events = $this->enrichRelayEventsWithCampaignContext($events, $payload);
        $this->store->writeLastSnapshot($current);
        if (method_exists($this->store, 'writeFocusedCallIds')) {
            $this->store->writeFocusedCallIds(is_array($nextFocusedCalls) ? $nextFocusedCalls : array());
        }

        $delivered = null;
        if ($webhookUrl !== '' && count($events) > 0) {
            $delivered = $this->postJson($webhookUrl, $events, $webhookToken);
        }

        return array(
            'success' => true,
            'events' => $events,
            'delivered' => $delivered,
        );
    }

    private function campaignContext($agentId, array $payload)
    {
        $agent = $this->resolveAgent($agentId);
        if (isset($agent['success']) && $agent['success'] === false) {
            return $agent;
        }

        $options = $this->campaignContextOptions($payload);
        $context = $this->runtime->getAgentCampaignContext($agent['agent_id'], $options);

        return array(
            'success' => true,
            'agent_id' => $agent['agent_id'],
            'route_key' => $agent['route_key'],
            'context' => is_array($context) ? $context : null,
        );
    }

    private function enrichRelayEventsWithCampaignContext(array $events, array $payload)
    {
        if (count($events) === 0) {
            return $events;
        }

        $options = $this->campaignContextOptions($payload);

        foreach ($events as $index => $event) {
            if (!is_array($event)) {
                continue;
            }

            $eventType = isset($event['event_type']) ? (string) $event['event_type'] : '';
            if ($eventType !== 'call.focus' && $eventType !== 'call.answered') {
                continue;
            }

            $agentId = isset($event['agent_id']) ? trim((string) $event['agent_id']) : '';
            if ($agentId === '') {
                continue;
            }

            try {
                $context = $this->runtime->getAgentCampaignContext($agentId, $options);
            } catch (Exception $e) {
                $context = null;
            }

            if (!is_array($context)) {
                continue;
            }

            $events[$index]['campaign_context'] = $context;
            $payloadData = isset($events[$index]['payload']) && is_array($events[$index]['payload'])
                ? $events[$index]['payload']
                : array();
            $payloadData['campaign_context'] = $context;
            $events[$index]['payload'] = $payloadData;
        }

        return $events;
    }

    private function campaignContextOptions(array $payload)
    {
        $identifierType = isset($payload['identifier_type']) ? trim((string) $payload['identifier_type']) : '';
        if ($identifierType === '') {
            $identifierType = 'cpf';
        }

        $attributeColumn = isset($payload['attribute_column']) ? (int) $payload['attribute_column'] : 2;
        if ($attributeColumn <= 0) {
            $attributeColumn = 2;
        }

        return array(
            'identifier_type' => $identifierType,
            'attribute_column' => $attributeColumn,
        );
    }

    private function appendSyntheticFocusEvents(array $events, array $current, $companyKey, array $payload, array $previousFocusedCalls, array &$nextFocusedCalls)
    {
        $agents = isset($current['agents']) && is_array($current['agents']) ? $current['agents'] : array();
        if (count($agents) === 0) {
            return $events;
        }

        $calls = isset($current['calls']) && is_array($current['calls']) ? $current['calls'] : array();
        $options = $this->campaignContextOptions($payload);
        $seenFocusAgents = array();

        foreach ($events as $event) {
            if (!is_array($event)) {
                continue;
            }

            if ((string) (isset($event['event_type']) ? $event['event_type'] : '') !== 'call.focus') {
                continue;
            }

            $agentId = trim((string) (isset($event['agent_id']) ? $event['agent_id'] : ''));
            if ($agentId !== '') {
                $seenFocusAgents[$agentId] = true;
            }
        }

        foreach ($agents as $agentId => $agent) {
            $agentId = trim((string) $agentId);
            if ($agentId === '' || isset($seenFocusAgents[$agentId])) {
                continue;
            }

            $status = strtolower(trim((string) (isset($agent['status']) ? $agent['status'] : '')));
            if ($status !== 'oncall') {
                continue;
            }

            try {
                $context = $this->runtime->getAgentCampaignContext($agentId, $options);
            } catch (Exception $e) {
                $context = null;
            }

            if (!is_array($context)) {
                continue;
            }

            $callId = trim((string) (isset($context['call_id']) ? $context['call_id'] : ''));
            if ($callId === '') {
                continue;
            }

            $previousCallId = isset($previousFocusedCalls[$agentId]) ? trim((string) $previousFocusedCalls[$agentId]) : '';
            if ($previousCallId !== '' && $previousCallId === $callId) {
                $nextFocusedCalls[$agentId] = $callId;
                continue;
            }

            $call = isset($calls[$callId]) && is_array($calls[$callId]) ? $calls[$callId] : array();
            $phone = trim((string) (isset($context['phone']) ? $context['phone'] : (isset($call['phone']) ? $call['phone'] : '')));
            $direction = trim((string) (isset($context['direction']) ? $context['direction'] : (isset($call['direction']) ? $call['direction'] : 'outbound')));
            $queue = trim((string) (isset($call['queue']) ? $call['queue'] : ''));
            $extension = trim((string) (isset($context['extension']) ? $context['extension'] : (isset($agent['extension']) ? $agent['extension'] : '')));

            $events[] = $this->buildRelayEvent(
                'call.focus',
                $companyKey,
                array(
                    'agent_id' => $agentId,
                    'extension' => $extension,
                    'call_id' => $callId,
                    'queue' => $queue,
                    'status' => 'answered',
                    'direction' => $direction !== '' ? $direction : 'outbound',
                    'phone' => $phone,
                    'remote_number' => $phone,
                    'mode' => 'agent-fallback',
                    'campaign_context' => $context,
                )
            );
            $nextFocusedCalls[$agentId] = $callId;
        }

        return $events;
    }

    private function suppressStaleHangupEvents(array $events, array $current)
    {
        if (count($events) === 0) {
            return $events;
        }

        $agents = isset($current['agents']) && is_array($current['agents']) ? $current['agents'] : array();
        $activeFocusByAgent = array();

        foreach ($events as $event) {
            if (!is_array($event)) {
                continue;
            }

            if ((string) (isset($event['event_type']) ? $event['event_type'] : '') !== 'call.focus') {
                continue;
            }

            $agentId = trim((string) (isset($event['agent_id']) ? $event['agent_id'] : ''));
            $callId = trim((string) (isset($event['call_id']) ? $event['call_id'] : ''));
            if ($agentId === '' || $callId === '') {
                continue;
            }

            $status = strtolower(trim((string) (isset($agents[$agentId]['status']) ? $agents[$agentId]['status'] : '')));
            if ($status === 'oncall') {
                $activeFocusByAgent[$agentId] = $callId;
            }
        }

        if (count($activeFocusByAgent) === 0) {
            return $events;
        }

        $filtered = array();
        foreach ($events as $event) {
            if (!is_array($event)) {
                $filtered[] = $event;
                continue;
            }

            $eventType = (string) (isset($event['event_type']) ? $event['event_type'] : '');
            if ($eventType !== 'call.hangup') {
                $filtered[] = $event;
                continue;
            }

            $agentId = trim((string) (isset($event['agent_id']) ? $event['agent_id'] : ''));
            $callId = trim((string) (isset($event['call_id']) ? $event['call_id'] : ''));
            if ($agentId !== '' && isset($activeFocusByAgent[$agentId]) && $activeFocusByAgent[$agentId] !== $callId) {
                continue;
            }

            $filtered[] = $event;
        }

        return $filtered;
    }

    private function buildRelayEvent($eventType, $companyKey, array $payload)
    {
        $occurredAt = gmdate('c');
        $stable = $eventType . '|' . $companyKey . '|' .
            (isset($payload['agent_id']) ? $payload['agent_id'] : '') . '|' .
            (isset($payload['call_id']) ? $payload['call_id'] : '');

        return array(
            'event_id' => sha1($stable . '|' . $occurredAt),
            'event_type' => $eventType,
            'event' => $eventType,
            'occurred_at' => $occurredAt,
            'source' => getenv('CALLCENTER_BRIDGE_SOURCE') ? getenv('CALLCENTER_BRIDGE_SOURCE') : 'issabel-callcenter',
            'company_key' => $companyKey,
            'agent_id' => isset($payload['agent_id']) ? $payload['agent_id'] : null,
            'extension' => isset($payload['extension']) ? $payload['extension'] : null,
            'call_id' => isset($payload['call_id']) ? $payload['call_id'] : null,
            'queue' => isset($payload['queue']) ? $payload['queue'] : null,
            'status' => isset($payload['status']) ? $payload['status'] : null,
            'state' => isset($payload['status']) ? $payload['status'] : null,
            'pause_code' => isset($payload['pause_code']) ? $payload['pause_code'] : null,
            'direction' => isset($payload['direction']) ? $payload['direction'] : null,
            'phone' => isset($payload['phone']) ? $payload['phone'] : null,
            'remote_number' => isset($payload['remote_number']) ? $payload['remote_number'] : (isset($payload['phone']) ? $payload['phone'] : null),
            'mode' => isset($payload['mode']) ? $payload['mode'] : 'agent-fallback',
            'payload' => $payload,
        );
    }

    private function applyStoredExtensions(array $agents)
    {
        $extensions = $this->store->readAgentExtensions();
        foreach ($agents as $index => $agent) {
            $agentId = isset($agent['agent_id']) ? (string) $agent['agent_id'] : '';
            if ($agentId !== '' && isset($extensions[$agentId])) {
                $agents[$index]['extension'] = $extensions[$agentId];
            }
        }

        return $agents;
    }

    private function agentStatus($agentId)
    {
        $agent = $this->resolveAgent($agentId);
        if (isset($agent['success']) && $agent['success'] === false) {
            return $agent;
        }
        $status = $this->applyPendingLoginStatus($agent, $this->runtime->getAgentStatus($agent['agent_id']));
        $status['route_key'] = $agent['route_key'];
        $status['requested_agent_ref'] = (string) $agentId;
        $storedExtension = $this->storedAgentExtension($agent);
        if ($storedExtension !== null && trim((string) $storedExtension) !== '') {
            $status['extension'] = (string) $storedExtension;
            if (!isset($status['raw_status']['extension']) || trim((string) $status['raw_status']['extension']) === '') {
                $status['raw_status']['extension'] = (string) $storedExtension;
            }
        }

        return array('success' => true, 'agent' => $status);
    }

    private function runAgentAction($agentId, $action, array $options = array())
    {
        $agent = $this->resolveAgent($agentId);
        if (isset($agent['success']) && $agent['success'] === false) {
            return $agent;
        }

        if ($action === 'logout') {
            $this->store->clearPendingLogin($agent['route_key'], $agent['agent_id']);
            $result = $this->runtime->logoutAgent($agent['agent_id']);
        } elseif ($action === 'pause') {
            $result = $this->runtime->pauseAgent($agent['agent_id'], $options['pause_id']);
        } else {
            $result = $this->runtime->unpauseAgent($agent['agent_id']);
        }

        return array(
            'success' => true,
            'agent_id' => $agent['agent_id'],
            'route_key' => $agent['route_key'],
            'result' => $result,
        );
    }

    private function hangup($callId, array $payload)
    {
        if (!isset($payload['agent_id']) || trim((string) $payload['agent_id']) === '') {
            return array(
                'status' => 422,
                'success' => false,
                'message' => 'agent_id is required',
            );
        }

        $agent = $this->resolveAgent((string) $payload['agent_id']);
        if (isset($agent['success']) && $agent['success'] === false) {
            return $agent;
        }

        return array(
            'success' => true,
            'call_id' => $callId,
            'agent_id' => $agent['agent_id'],
            'route_key' => $agent['route_key'],
            'result' => $this->runtime->hangupAgentCall($agent['agent_id']),
        );
    }

    private function applyPendingLoginStatus(array $agent, array $status)
    {
        $pending = $this->store->getPendingLogin(
            isset($agent['route_key']) ? $agent['route_key'] : null,
            isset($agent['agent_id']) ? $agent['agent_id'] : null
        );

        if (!is_array($pending)) {
            return $status;
        }

        $currentStatus = isset($status['status']) ? trim((string) $status['status']) : '';
        if ($currentStatus !== '' && $currentStatus !== 'offline' && $currentStatus !== 'unknown') {
            $this->store->clearPendingLogin($agent['route_key'], $agent['agent_id']);
            return $status;
        }

        $startedAt = isset($pending['started_at']) ? strtotime((string) $pending['started_at']) : false;
        if ($startedAt === false || (time() - $startedAt) > 45) {
            $this->store->clearPendingLogin($agent['route_key'], $agent['agent_id']);
            return $status;
        }

        $status['status'] = 'logging';
        if (!isset($status['raw_status']) || !is_array($status['raw_status'])) {
            $status['raw_status'] = array();
        }
        $status['raw_status']['status'] = 'logging';
        $status['raw_status']['bridge_pending_login'] = true;
        $status['raw_status']['pending_login_started_at'] = $pending['started_at'];

        return $status;
    }

    private function resolveAgent($agentId)
    {
        $references = $this->agentResolutionCandidates($agentId);
        $lastException = null;

        foreach ($references as $reference) {
            try {
                $agent = $this->runtime->resolveAgentReference($reference);
                if (isset($agent['success']) && $agent['success'] === false) {
                    return $agent;
                }

                return $agent;
            } catch (Exception $e) {
                $lastException = $e;
            }
        }

        return array(
            'status' => 404,
            'success' => false,
            'message' => $lastException ? $lastException->getMessage() : 'Agent not found in call_center.agent',
        );
    }

    private function agentResolutionCandidates($agentId)
    {
        $agentId = trim((string) $agentId);
        if ($agentId === '') {
            return array($agentId);
        }

        if (preg_match('/^[0-9]+$/', $agentId) === 1) {
            return array('route:' . $agentId, $agentId);
        }

        return array($agentId);
    }

    private function storedAgentExtension(array $agent)
    {
        return $this->store->getAgentExtension(
            isset($agent['route_key']) ? $agent['route_key'] : null,
            isset($agent['agent_id']) ? $agent['agent_id'] : null
        );
    }

    private function postJson($url, array $events, $token)
    {
        if (!function_exists('curl_init')) {
            return array('status' => 0, 'body' => null, 'error' => 'curl extension not available');
        }

        $headers = array('Content-Type: application/json');
        if ($token !== '') {
            $headers[] = 'Authorization: Bearer ' . $token;
        }

        $ch = curl_init($url);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($events));
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, (int) (getenv('CALLCENTER_BRIDGE_HTTP_TIMEOUT') ? getenv('CALLCENTER_BRIDGE_HTTP_TIMEOUT') : 10));

        $verifyTls = getenv('CALLCENTER_BRIDGE_VERIFY_TLS');
        if ($verifyTls !== false && $verifyTls !== '' && in_array(strtolower((string) $verifyTls), array('0', 'false', 'no', 'off'), true)) {
            curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
            curl_setopt($ch, CURLOPT_SSL_VERIFYHOST, 0);
        }

        $body = curl_exec($ch);
        $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $error = curl_error($ch);
        curl_close($ch);

        return array(
            'status' => $status,
            'body' => $body,
            'error' => $error !== '' ? $error : null,
        );
    }
}
