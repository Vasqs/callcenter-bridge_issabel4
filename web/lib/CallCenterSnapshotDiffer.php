<?php

class CallCenterSnapshotDiffer
{
    private $source;

    public function __construct($source)
    {
        $this->source = $source ? $source : 'issabel-callcenter';
    }

    public function diff(array $previous, array $current, $companyKey, array $previousFocusedCalls = array(), &$nextFocusedCalls = null)
    {
        $events = array();
        $occurredAt = gmdate('c');
        $nextFocused = array();

        $previousAgents = isset($previous['agents']) && is_array($previous['agents']) ? $previous['agents'] : array();
        $currentAgents = isset($current['agents']) && is_array($current['agents']) ? $current['agents'] : array();

        foreach ($currentAgents as $agentId => $agent) {
            $before = isset($previousAgents[$agentId]) && is_array($previousAgents[$agentId]) ? $previousAgents[$agentId] : array();
            $status = isset($agent['status']) ? (string) $agent['status'] : '';
            $beforeStatus = isset($before['status']) ? (string) $before['status'] : '';

            if ($status !== '' && $status !== $beforeStatus) {
                if ($status === 'paused') {
                    $eventType = 'agent.paused';
                } elseif ($status === 'offline') {
                    $eventType = 'agent.logged_out';
                } else {
                    $eventType = 'agent.status_snapshot';
                }

                $events[] = $this->event(
                    $eventType,
                    $companyKey,
                    $occurredAt,
                    array(
                        'agent_id' => $agentId,
                        'extension' => isset($agent['extension']) ? (string) $agent['extension'] : '',
                        'queue' => isset($agent['queue']) ? (string) $agent['queue'] : '',
                        'status' => $status,
                        'pause_code' => $status === 'paused' && isset($agent['pause_code']) ? $agent['pause_code'] : null,
                    )
                );
            }
        }

        $previousCalls = isset($previous['calls']) && is_array($previous['calls']) ? $previous['calls'] : array();
        $currentCalls = isset($current['calls']) && is_array($current['calls']) ? $current['calls'] : array();

        foreach ($currentCalls as $callId => $call) {
            $before = isset($previousCalls[$callId]) && is_array($previousCalls[$callId]) ? $previousCalls[$callId] : array();
            $status = isset($call['status']) ? (string) $call['status'] : '';
            $beforeStatus = isset($before['status']) ? (string) $before['status'] : '';

            if ($status !== '' && $status !== $beforeStatus) {
                $events[] = $this->event(
                    'call.' . $status,
                    $companyKey,
                    $occurredAt,
                    array(
                        'call_id' => $callId,
                        'agent_id' => isset($call['agent_id']) ? (string) $call['agent_id'] : '',
                        'queue' => isset($call['queue']) ? (string) $call['queue'] : '',
                        'status' => $status,
                        'phone' => isset($call['phone']) ? (string) $call['phone'] : '',
                        'direction' => isset($call['direction']) ? (string) $call['direction'] : '',
                    )
                );
            }
        }

        foreach ($previousCalls as $callId => $call) {
            if (array_key_exists($callId, $currentCalls)) {
                continue;
            }

            $events[] = $this->event(
                'call.hangup',
                $companyKey,
                $occurredAt,
                array(
                    'call_id' => $callId,
                    'agent_id' => isset($call['agent_id']) ? (string) $call['agent_id'] : '',
                    'queue' => isset($call['queue']) ? (string) $call['queue'] : '',
                    'status' => 'hangup',
                    'phone' => isset($call['phone']) ? (string) $call['phone'] : '',
                    'direction' => isset($call['direction']) ? (string) $call['direction'] : '',
                )
            );
        }

        $focusEvents = $this->buildFocusEvents($currentAgents, $currentCalls, $previousFocusedCalls, $companyKey, $occurredAt, $nextFocused);
        foreach ($focusEvents as $focusEvent) {
            $events[] = $focusEvent;
        }

        if (is_array($nextFocusedCalls)) {
            $nextFocusedCalls = $nextFocused;
        }

        return $events;
    }

    private function event($eventType, $companyKey, $occurredAt, array $payload)
    {
        $stable = $eventType . '|' . $companyKey . '|' .
            (isset($payload['agent_id']) ? $payload['agent_id'] : '') . '|' .
            (isset($payload['call_id']) ? $payload['call_id'] : '');

        return array(
            'event_id' => sha1($stable . '|' . $occurredAt),
            'event_type' => $eventType,
            'event' => $eventType,
            'occurred_at' => $occurredAt,
            'source' => $this->source,
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

    private function buildFocusEvents(array $currentAgents, array $currentCalls, array $previousFocusedCalls, $companyKey, $occurredAt, array &$nextFocused)
    {
        $events = array();

        foreach ($currentAgents as $agentId => $agent) {
            $focusCallId = $this->selectFocusedCallId($agentId, $agent, $currentCalls, $previousFocusedCalls);
            if ($focusCallId === null) {
                continue;
            }

            $nextFocused[$agentId] = $focusCallId;
            $call = isset($currentCalls[$focusCallId]) && is_array($currentCalls[$focusCallId]) ? $currentCalls[$focusCallId] : array();
            $events[] = $this->event(
                'call.focus',
                $companyKey,
                $occurredAt,
                array(
                    'agent_id' => $agentId,
                    'extension' => $this->resolveFocusExtension($agent, $call),
                    'call_id' => $focusCallId,
                    'queue' => isset($call['queue']) ? (string) $call['queue'] : '',
                    'status' => isset($call['status']) ? (string) $call['status'] : '',
                    'direction' => isset($call['direction']) ? (string) $call['direction'] : '',
                    'phone' => isset($call['phone']) ? (string) $call['phone'] : '',
                    'remote_number' => isset($call['phone']) ? (string) $call['phone'] : '',
                    'mode' => 'agent-fallback',
                )
            );
        }

        return $events;
    }

    private function selectFocusedCallId($agentId, array $agent, array $currentCalls, array $previousFocusedCalls)
    {
        $previousCallId = isset($previousFocusedCalls[$agentId]) ? (string) $previousFocusedCalls[$agentId] : '';
        if ($previousCallId !== '' && isset($currentCalls[$previousCallId]) && is_array($currentCalls[$previousCallId])) {
            $status = isset($currentCalls[$previousCallId]['status']) ? (string) $currentCalls[$previousCallId]['status'] : '';
            if ($status === 'answered' || $status === 'ringing') {
                return $previousCallId;
            }
        }

        $candidates = array();
        $agentExtension = isset($agent['extension']) ? (string) $agent['extension'] : '';
        $position = 0;
        foreach ($currentCalls as $callId => $call) {
            if (!is_array($call)) {
                continue;
            }

            $callAgentId = isset($call['agent_id']) ? (string) $call['agent_id'] : '';
            $callExtension = isset($call['extension']) ? (string) $call['extension'] : '';

            if ($callAgentId === $agentId) {
                $candidates[] = array('call_id' => $callId, 'call' => $call, 'bound' => true, 'position' => $position);
                $position++;
                continue;
            }

            if ($callAgentId === '' && $agentExtension !== '' && $callExtension === $agentExtension) {
                $candidates[] = array('call_id' => $callId, 'call' => $call, 'bound' => false, 'position' => $position);
            }

            $position++;
        }

        if (count($candidates) === 0) {
            return null;
        }

        usort($candidates, array($this, 'compareFocusCandidates'));

        return $candidates[0]['call_id'];
    }

    private function compareFocusCandidates(array $left, array $right)
    {
        $leftPriority = $this->focusPriority(isset($left['call']['status']) ? (string) $left['call']['status'] : '');
        $rightPriority = $this->focusPriority(isset($right['call']['status']) ? (string) $right['call']['status'] : '');
        if ($leftPriority !== $rightPriority) {
            return ($leftPriority < $rightPriority) ? -1 : 1;
        }

        if ($left['bound'] !== $right['bound']) {
            return $left['bound'] ? -1 : 1;
        }

        $leftPosition = isset($left['position']) ? (int) $left['position'] : 0;
        $rightPosition = isset($right['position']) ? (int) $right['position'] : 0;
        if ($leftPosition !== $rightPosition) {
            return ($leftPosition > $rightPosition) ? -1 : 1;
        }

        return strcmp((string) $right['call_id'], (string) $left['call_id']);
    }

    private function focusPriority($status)
    {
        if ($status === 'answered') {
            return 0;
        }
        if ($status === 'ringing') {
            return 1;
        }
        if ($status === 'hold') {
            return 2;
        }

        return 99;
    }

    private function resolveFocusExtension(array $agent, array $call)
    {
        if (isset($call['extension']) && (string) $call['extension'] !== '') {
            return (string) $call['extension'];
        }

        return isset($agent['extension']) ? (string) $agent['extension'] : '';
    }
}
