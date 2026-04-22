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
        $differ = $this->differ;
        if ($differ === null) {
            $source = getenv('CALLCENTER_BRIDGE_SOURCE');
            $differ = new CallCenterSnapshotDiffer($source ? $source : 'issabel-callcenter');
        }

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
                return $this->relay($differ, $payload);
        }

        return array(
            'status' => 404,
            'success' => false,
            'message' => 'operation not implemented',
        );
    }

    private function login($agentId, array $payload)
    {
        $agent = $this->resolveAgent($agentId);
        if (isset($agent['success']) && $agent['success'] === false) {
            return $agent;
        }
        $extension = isset($payload['extension']) ? trim((string) $payload['extension']) : '';
        if ($extension === '') {
            $extensions = $this->store->readAgentExtensions();
            $extension = isset($extensions[$agent['agent_id']]) ? (string) $extensions[$agent['agent_id']] : '';
        }

        if ($extension === '') {
            return array(
                'status' => 422,
                'success' => false,
                'message' => 'extension is required for agent login',
            );
        }

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

        $this->store->setAgentExtension($agent['agent_id'], $extension);

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
            $extensions = $this->store->readAgentExtensions();
            if (isset($extensions[$agent['agent_id']])) {
                $extension = trim((string) $extensions[$agent['agent_id']]);
            }
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
        $status = $this->runtime->getAgentStatus($agent['agent_id']);
        $status['route_key'] = $agent['route_key'];
        $status['requested_agent_ref'] = (string) $agentId;

        return array('success' => true, 'agent' => $status);
    }

    private function runAgentAction($agentId, $action, array $options = array())
    {
        $agent = $this->resolveAgent($agentId);
        if (isset($agent['success']) && $agent['success'] === false) {
            return $agent;
        }

        if ($action === 'logout') {
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

    private function resolveAgent($agentId)
    {
        try {
            $agent = $this->runtime->resolveAgentReference($agentId);
        } catch (Exception $e) {
            return array(
                'status' => 404,
                'success' => false,
                'message' => $e->getMessage(),
            );
        }

        if (isset($agent['success']) && $agent['success'] === false) {
            return $agent;
        }

        return $agent;
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
