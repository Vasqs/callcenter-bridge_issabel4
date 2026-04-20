<?php

class CallCenterApiRouter
{
    public function match($method, $path)
    {
        $method = strtoupper(trim((string) $method));
        $path = '/' . ltrim(trim((string) $path), '/');

        $patterns = array(
            array('GET', '#^/v1/health$#', 'health'),
            array('GET', '#^/v1/agents$#', 'agents.list'),
            array('GET', '#^/v1/queues$#', 'queues.list'),
            array('GET', '#^/v1/calls/active$#', 'calls.active'),
            array('GET', '#^/v1/agents/(?P<agentId>[^/]+)/status$#', 'agents.status'),
            array('POST', '#^/v1/agents/(?P<agentId>[^/]+)/login$#', 'agents.login'),
            array('POST', '#^/v1/agents/(?P<agentId>[^/]+)/logout$#', 'agents.logout'),
            array('POST', '#^/v1/agents/(?P<agentId>[^/]+)/pause$#', 'agents.pause'),
            array('POST', '#^/v1/agents/(?P<agentId>[^/]+)/unpause$#', 'agents.unpause'),
            array('PATCH', '#^/v1/agents/(?P<agentId>[^/]+)/extension$#', 'agents.set_extension'),
            array('POST', '#^/v1/calls/originate$#', 'calls.originate'),
            array('POST', '#^/v1/calls/(?P<callId>[^/]+)/hangup$#', 'calls.hangup'),
            array('POST', '#^/v1/events/relay$#', 'events.relay'),
        );

        foreach ($patterns as $pattern) {
            list($expectedMethod, $regex, $operation) = $pattern;
            if ($method !== $expectedMethod) {
                continue;
            }

            if (preg_match($regex, $path, $matches) !== 1) {
                continue;
            }

            $params = array();
            foreach ($matches as $key => $value) {
                if (is_string($key)) {
                    $params[$key] = urldecode((string) $value);
                }
            }

            return array(
                'operation' => $operation,
                'params' => $params,
            );
        }

        return null;
    }
}
