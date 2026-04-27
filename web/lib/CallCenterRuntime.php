<?php

class CallCenterRuntime
{
    private $pdo;

    public function __construct()
    {
        $this->pdo = null;
    }

    public function health()
    {
        return array(
            'dialer_running' => $this->commandSucceeded('/etc/rc.d/init.d/issabeldialer status'),
            'asterisk_ready' => $this->commandSucceeded('asterisk -rx "core show version"'),
            'db_ready' => $this->commandSucceeded('mysqladmin --socket=/var/lib/mysql/mysql.sock ping'),
        );
    }

    public function listAgents()
    {
        $agents = array();
        $rows = $this->query('SELECT id, type, number, name, estatus FROM agent ORDER BY number ASC');
        foreach ($rows as $row) {
            $agentId = $row['type'] . '/' . $row['number'];
            $status = $this->safeAgentStatus($agentId);
            $agents[] = array(
                'agent_id' => $agentId,
                'route_key' => (string) $row['id'],
                'id' => (int) $row['id'],
                'type' => (string) $row['type'],
                'number' => (string) $row['number'],
                'name' => (string) $row['name'],
                'enabled' => ((string) $row['estatus']) === 'A',
                'status' => isset($status['status']) ? $status['status'] : 'unknown',
                'extension' => null,
                'queue' => null,
            );
        }

        return $agents;
    }

    public function listQueues()
    {
        $queues = $this->eccpCall('getincomingqueuelist');
        $queueNames = $this->flattenQueueNames($queues);
        $result = array();

        foreach ($queueNames as $queueName) {
            $result[] = array(
                'queue' => $queueName,
                'status' => $this->eccpCall('getincomingqueuestatus', array($queueName)),
            );
        }

        return $result;
    }

    public function listActiveCalls()
    {
        $calls = array();

        foreach ($this->query('SELECT uniqueid, queue, agentnum, event, Channel, ChannelClient FROM current_calls ORDER BY id ASC') as $row) {
            $channelClient = isset($row['ChannelClient']) ? (string) $row['ChannelClient'] : '';
            $calls[] = array(
                'call_id' => $row['uniqueid'] ? (string) $row['uniqueid'] : sha1(json_encode($row)),
                'queue' => (string) $row['queue'],
                'agent_id' => (string) $row['agentnum'],
                'status' => $this->normalizeCallEvent((string) $row['event']),
                'channel' => (string) $row['Channel'],
                'channel_client' => $channelClient,
                'phone' => $this->extractPhoneFromChannel($channelClient),
                'direction' => 'outbound',
            );
        }

        foreach ($this->query('SELECT uniqueid, callerid, hold FROM current_call_entry ORDER BY id ASC') as $row) {
            $calls[] = array(
                'call_id' => $row['uniqueid'] ? (string) $row['uniqueid'] : sha1(json_encode($row)),
                'queue' => 'incoming',
                'agent_id' => null,
                'status' => (isset($row['hold']) && $row['hold'] === 'S') ? 'hold' : 'ringing',
                'phone' => isset($row['callerid']) ? (string) $row['callerid'] : '',
                'direction' => 'incoming',
            );
        }

        return $calls;
    }

    public function getAgentStatus($agentId)
    {
        return array(
            'agent_id' => $agentId,
            'status' => isset($this->safeAgentStatus($agentId)['status']) ? $this->safeAgentStatus($agentId)['status'] : 'unknown',
            'raw_status' => $this->safeAgentStatus($agentId),
            'queues' => $this->eccpCall('getagentqueues', array($agentId)),
        );
    }

    public function getAgentCampaignContext($agentId, array $options = array())
    {
        $agent = $this->resolveAgentReference($agentId);
        $identifierType = isset($options['identifier_type']) ? trim((string) $options['identifier_type']) : 'cpf';
        if ($identifierType === '') {
            $identifierType = 'cpf';
        }

        $attributeColumn = isset($options['attribute_column']) ? (int) $options['attribute_column'] : 2;
        if ($attributeColumn <= 0) {
            $attributeColumn = 2;
        }

        $activeCall = $this->findActiveCampaignCallForAgent($agent);
        if (!is_array($activeCall)) {
            return null;
        }

        $identifierValue = $this->loadCampaignIdentifierValue($activeCall, $attributeColumn);
        $resolvedFrom = $identifierValue !== null ? 'call_attribute' : null;

        return array(
            'agent_id' => isset($agent['agent_id']) ? (string) $agent['agent_id'] : (string) $agentId,
            'extension' => isset($activeCall['extension']) ? (string) $activeCall['extension'] : '',
            'call_id' => isset($activeCall['call_id']) ? (string) $activeCall['call_id'] : '',
            'campaign_id' => isset($activeCall['campaign_id']) ? (string) $activeCall['campaign_id'] : '',
            'direction' => isset($activeCall['direction']) ? (string) $activeCall['direction'] : 'outbound',
            'phone' => isset($activeCall['phone']) ? (string) $activeCall['phone'] : '',
            'identifier_type' => $identifierType,
            'identifier_value' => $identifierValue,
            'source' => 'issabel-callcenter-bridge',
            'resolved_from' => $resolvedFrom,
        );
    }

    public function resolveAgentReference($reference)
    {
        $reference = trim((string) $reference);
        if ($reference === '') {
            throw new InvalidArgumentException('Agent reference is required');
        }

        if (preg_match('/^[0-9]+$/', $reference) === 1) {
            $agent = $this->findAgentRecord(
                'SELECT id, type, number, name, estatus, eccp_password, password FROM agent WHERE id = :id LIMIT 1',
                array(':id' => (int) $reference)
            );
            if ($agent !== null) {
                return $agent;
            }

            $agent = $this->findAgentRecord(
                'SELECT id, type, number, name, estatus, eccp_password, password FROM agent WHERE number = :number ORDER BY id ASC LIMIT 1',
                array(':number' => $reference)
            );
            if ($agent !== null) {
                return $agent;
            }

            throw new RuntimeException('Agent not found in call_center.agent');
        }

        if (strpos($reference, '/') !== false) {
            $parts = explode('/', $reference, 2);
            return $this->findAgentByTypeAndNumber($parts[0], $parts[1]);
        }

        if (preg_match('/^([A-Za-z]+)[:._-](.+)$/', $reference, $matches) === 1) {
            return $this->findAgentByTypeAndNumber($matches[1], $matches[2]);
        }

        $agent = $this->findAgentRecord(
            'SELECT id, type, number, name, estatus, eccp_password, password FROM agent WHERE number = :number ORDER BY id ASC LIMIT 1',
            array(':number' => $reference)
        );

        if ($agent !== null) {
            return $agent;
        }

        throw new RuntimeException('Agent not found in call_center.agent');
    }

    public function listPauses()
    {
        $rows = $this->query('SELECT id, name, description, status, tipo FROM `break` ORDER BY id ASC');
        $result = array();
        foreach ($rows as $row) {
            $result[] = array(
                'id' => (int) $row['id'],
                'name' => (string) $row['name'],
                'description' => isset($row['description']) ? (string) $row['description'] : '',
                'status' => isset($row['status']) ? (string) $row['status'] : '',
                'type' => isset($row['tipo']) ? (string) $row['tipo'] : '',
            );
        }

        return $result;
    }

    public function loginAgent($agentId, $extension)
    {
        return $this->eccpCall('loginagent', array($extension), $agentId, $this->resolveAgentPassword($agentId));
    }

    public function logoutAgent($agentId)
    {
        return $this->eccpCall('logoutagent', array(), $agentId, $this->resolveAgentPassword($agentId));
    }

    public function pauseAgent($agentId, $pauseId)
    {
        return $this->eccpCall('pauseagent', array($pauseId), $agentId, $this->resolveAgentPassword($agentId));
    }

    public function unpauseAgent($agentId)
    {
        return $this->eccpCall('unpauseagent', array(), $agentId, $this->resolveAgentPassword($agentId));
    }

    public function hangupAgentCall($agentId)
    {
        return $this->eccpCall('hangup', array(), $agentId, $this->resolveAgentPassword($agentId));
    }

    public function originateCall($agentId, $extension, $phone, $callId)
    {
        $extension = trim((string) $extension);
        $phone = trim((string) $phone);
        $context = getenv('CALLCENTER_BRIDGE_ORIGINATE_CONTEXT');
        if ($context === false || $context === '') {
            $context = 'from-internal';
        }

        if ($extension === '') {
            return array(
                'failure' => array(
                    'code' => '422',
                    'message' => 'Extension is required for originate',
                ),
            );
        }

        if ($phone === '' || preg_match('/^[0-9*#+]+$/', $phone) !== 1) {
            return array(
                'failure' => array(
                    'code' => '422',
                    'message' => 'Phone must contain only dialable characters',
                ),
            );
        }

        if (preg_match('/^[A-Za-z0-9_.-]+$/', $extension) !== 1) {
            return array(
                'failure' => array(
                    'code' => '422',
                    'message' => 'Extension contains invalid characters',
                ),
            );
        }

        if (preg_match('/^[A-Za-z0-9_.-]+$/', $context) !== 1) {
            return array(
                'failure' => array(
                    'code' => '500',
                    'message' => 'Originate context contains invalid characters',
                ),
            );
        }

        $command = sprintf(
            'asterisk -rx %s',
            escapeshellarg(sprintf('channel originate SIP/%s extension %s@%s', $extension, $phone, $context))
        );

        $output = array();
        $exitCode = 0;
        exec($command . ' 2>&1', $output, $exitCode);
        $message = trim(implode("\n", $output));

        if ($exitCode !== 0) {
            return array(
                'failure' => array(
                    'code' => (string) $exitCode,
                    'message' => $message !== '' ? $message : 'Asterisk originate failed',
                ),
            );
        }

        return array(
            'status' => 'queued',
            'agent_id' => $agentId,
            'extension' => $extension,
            'phone' => $phone,
            'call_id' => $callId,
            'message' => $message,
        );
    }

    public function buildSnapshot(CallCenterStateStore $store)
    {
        $agents = array();
        foreach ($this->listAgents() as $agent) {
            $agentId = isset($agent['agent_id']) ? (string) $agent['agent_id'] : '';
            $routeKey = isset($agent['route_key']) ? (string) $agent['route_key'] : '';
            $status = $this->getAgentStatus($agentId);
            $effectiveStatus = isset($status['status']) ? (string) $status['status'] : 'unknown';
            $pending = $store->getPendingLogin($routeKey, $agentId);
            if (is_array($pending)) {
                $startedAt = isset($pending['started_at']) ? strtotime((string) $pending['started_at']) : false;
                if ($effectiveStatus !== '' && $effectiveStatus !== 'offline' && $effectiveStatus !== 'unknown') {
                    $store->clearPendingLogin($routeKey, $agentId);
                } elseif ($startedAt !== false && (time() - $startedAt) <= 45) {
                    $effectiveStatus = 'logging';
                } else {
                    $store->clearPendingLogin($routeKey, $agentId);
                }
            }
            $agents[$agentId] = array(
                'status' => $effectiveStatus,
                'extension' => $store->getAgentExtension($routeKey, $agentId),
                'queue' => is_array($status['queues']) ? json_encode($status['queues']) : null,
            );
        }

        $calls = array();
        foreach ($this->listActiveCalls() as $call) {
            $callId = isset($call['call_id']) ? (string) $call['call_id'] : '';
            $calls[$callId] = array(
                'status' => isset($call['status']) ? (string) $call['status'] : 'unknown',
                'agent_id' => isset($call['agent_id']) ? (string) $call['agent_id'] : '',
                'phone' => isset($call['phone']) ? (string) $call['phone'] : '',
                'queue' => isset($call['queue']) ? (string) $call['queue'] : '',
                'direction' => isset($call['direction']) ? (string) $call['direction'] : '',
            );
        }

        return array(
            'agents' => $agents,
            'calls' => $calls,
        );
    }

    private function query($sql)
    {
        try {
            $stmt = $this->pdo()->query($sql);
            $rows = $stmt ? $stmt->fetchAll(PDO::FETCH_ASSOC) : array();
            return is_array($rows) ? $rows : array();
        } catch (Exception $e) {
            return array();
        }
    }

    private function queryPrepared($sql, array $params)
    {
        try {
            $stmt = $this->pdo()->prepare($sql);
            $stmt->execute($params);
            $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
            return is_array($rows) ? $rows : array();
        } catch (Exception $e) {
            return array();
        }
    }

    private function pdo()
    {
        if ($this->pdo instanceof PDO) {
            return $this->pdo;
        }

        $dsn = getenv('CALLCENTER_BRIDGE_DB_DSN');
        $user = getenv('CALLCENTER_BRIDGE_DB_USER');
        $password = getenv('CALLCENTER_BRIDGE_DB_PASSWORD');
        if ($dsn === false || $dsn === '') {
            $dsn = 'mysql:unix_socket=/var/lib/mysql/mysql.sock;dbname=call_center;charset=utf8';
        }
        if ($user === false || $user === '') {
            $user = 'root';
        }
        if ($password === false) {
            $password = 'iSsAbEl.2o17';
        }

        $this->pdo = new PDO($dsn, $user, $password, array(
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        ));

        return $this->pdo;
    }

    private function eccpCall($method, array $args = array(), $agentId = null, $password = null)
    {
        $eccpPath = '/var/www/html/modules/agent_console/libs/ECCP.class.php';
        if (!is_file($eccpPath)) {
            throw new RuntimeException('ECCP runtime not available');
        }

        require_once $eccpPath;

        $client = new ECCP();
        $response = $client->connect('localhost', 'agentconsole', 'agentconsole');
        if (isset($response->failure)) {
            throw new RuntimeException('Failed to connect to ECCP');
        }

        if ($agentId !== null) {
            $client->setAgentNumber($agentId);
        }

        if ($password !== null && $password !== '') {
            $client->setAgentPass($password);
        }

        try {
            $result = call_user_func_array(array($client, $method), $args);
        } catch (Exception $e) {
            $client->disconnect();
            throw $e;
        }

        $client->disconnect();

        return $this->xmlToArray($result);
    }

    private function safeAgentStatus($agentId)
    {
        try {
            return $this->eccpCall('getAgentStatus', array(), $agentId);
        } catch (Exception $e) {
            return array('status' => 'unknown');
        }
    }

    private function resolveAgentPassword($agentId)
    {
        $row = $this->resolveAgentReference($agentId);

        if (isset($row['eccp_password']) && $row['eccp_password'] !== '') {
            return (string) $row['eccp_password'];
        }

        if (isset($row['password']) && $row['password'] !== '') {
            return (string) $row['password'];
        }

        return '';
    }

    private function commandSucceeded($command)
    {
        $output = array();
        $exitCode = 0;
        exec($command . ' >/dev/null 2>&1', $output, $exitCode);
        return $exitCode === 0;
    }

    private function xmlToArray($value)
    {
        if ($value instanceof SimpleXMLElement) {
            $json = json_encode($value);
            $decoded = $json !== false ? json_decode($json, true) : null;
            return is_array($decoded) ? $decoded : array();
        }

        return is_array($value) ? $value : array('value' => $value);
    }

    private function flattenQueueNames(array $queues)
    {
        $names = array();
        array_walk_recursive($queues, function ($value) use (&$names) {
            if (is_string($value) && $value !== '' && preg_match('/^[A-Za-z0-9_-]+$/', $value) === 1) {
                $names[] = $value;
            }
        });

        return array_values(array_unique($names));
    }

    private function normalizeCallEvent($event)
    {
        $event = strtolower(trim((string) $event));
        if ($event === 'link' || $event === 'connect') {
            return 'answered';
        }
        if ($event === 'hangup' || $event === 'unlink') {
            return 'hangup';
        }
        if ($event === 'hold') {
            return 'hold';
        }
        if ($event === 'ringing') {
            return 'ringing';
        }

        return $event !== '' ? $event : 'unknown';
    }

    private function extractPhoneFromChannel($value)
    {
        $value = trim((string) $value);
        if ($value === '') {
            return '';
        }

        $digits = preg_replace('/\D+/', '', $value);
        if (is_string($digits) && $digits !== '') {
            return $digits;
        }

        if (preg_match('#^(?:SIP|PJSIP|Local)/([^@;-]+)#i', $value, $matches) === 1) {
            $candidate = preg_replace('/\D+/', '', (string) $matches[1]);
            return is_string($candidate) ? $candidate : '';
        }

        return '';
    }

    private function findActiveCampaignCallForAgent(array $agent)
    {
        $agentId = isset($agent['agent_id']) ? (string) $agent['agent_id'] : '';
        $agentNumber = isset($agent['number']) ? (string) $agent['number'] : '';
        $routeKey = isset($agent['route_key']) ? (string) $agent['route_key'] : '';

        $calls = $this->queryPrepared(
            'SELECT uniqueid, queue, agentnum, event, Channel, ChannelClient FROM current_calls WHERE agentnum IN (:agent_id, :agent_number, :route_key) ORDER BY id DESC',
            array(
                ':agent_id' => $agentId,
                ':agent_number' => $agentNumber,
                ':route_key' => $routeKey,
            )
        );

        if (!is_array($calls) || count($calls) === 0) {
            return null;
        }

        foreach ($calls as $row) {
            $callId = isset($row['uniqueid']) ? trim((string) $row['uniqueid']) : '';
            if ($callId === '') {
                continue;
            }

            $call = $this->loadCampaignCallRecord($callId);
            if (!is_array($call)) {
                continue;
            }

            return array(
                'call_id' => $callId,
                'campaign_id' => isset($call['campaign_id']) ? (string) $call['campaign_id'] : '',
                'phone' => $this->normalizeDigits(
                    isset($call['phone']) && $call['phone'] !== ''
                        ? $call['phone']
                        : (isset($row['ChannelClient']) ? $row['ChannelClient'] : '')
                ),
                'direction' => 'outbound',
                'extension' => $this->extractExtensionFromChannel(isset($row['Channel']) ? $row['Channel'] : ''),
            );
        }

        return null;
    }

    private function loadCampaignCallRecord($callId)
    {
        $rows = $this->queryPrepared(
            'SELECT id, id_campaign AS campaign_id, phone, status FROM calls WHERE uniqueid = :uniqueid ORDER BY id DESC LIMIT 1',
            array(':uniqueid' => $callId)
        );

        if (is_array($rows) && isset($rows[0]) && is_array($rows[0])) {
            return $rows[0];
        }

        return null;
    }

    private function loadCampaignIdentifierValue(array $activeCall, $attributeColumn)
    {
        $callId = isset($activeCall['call_id']) ? trim((string) $activeCall['call_id']) : '';
        if ($callId === '') {
            return null;
        }

        $call = $this->loadCampaignCallRecord($callId);
        if (!is_array($call) || !isset($call['id'])) {
            return null;
        }

        $rows = $this->queryPrepared(
            'SELECT value FROM call_attribute WHERE id_call = :id_call AND column_number = :column_number ORDER BY id DESC LIMIT 1',
            array(
                ':id_call' => (int) $call['id'],
                ':column_number' => (int) $attributeColumn,
            )
        );

        if (!is_array($rows) || !isset($rows[0]['value'])) {
            return null;
        }

        $digits = $this->normalizeDigits($rows[0]['value']);

        return $digits !== '' ? $digits : null;
    }

    private function normalizeDigits($value)
    {
        $digits = preg_replace('/\D+/', '', trim((string) $value));

        return is_string($digits) ? $digits : '';
    }

    private function extractExtensionFromChannel($value)
    {
        $value = trim((string) $value);
        if ($value === '') {
            return '';
        }

        if (preg_match('#^(?:SIP|PJSIP|Local)/([^@;-]+)#i', $value, $matches) === 1) {
            return trim((string) $matches[1]);
        }

        return '';
    }

    private function findAgentByTypeAndNumber($type, $number)
    {
        $type = trim((string) $type);
        $number = trim((string) $number);
        if ($type === '' || $number === '') {
            throw new InvalidArgumentException('Invalid agent reference');
        }

        $agent = $this->findAgentRecord(
            'SELECT id, type, number, name, estatus, eccp_password, password FROM agent WHERE type = :type AND number = :number LIMIT 1',
            array(':type' => $type, ':number' => $number)
        );

        if ($agent === null) {
            throw new RuntimeException('Agent not found in call_center.agent');
        }

        return $agent;
    }

    private function findAgentRecord($sql, array $params)
    {
        $stmt = $this->pdo()->prepare($sql);
        $stmt->execute($params);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);
        if (!is_array($row)) {
            return null;
        }

        $row['id'] = (int) $row['id'];
        $row['type'] = isset($row['type']) ? (string) $row['type'] : '';
        $row['number'] = isset($row['number']) ? (string) $row['number'] : '';
        $row['name'] = isset($row['name']) ? (string) $row['name'] : '';
        $row['agent_id'] = $row['type'] !== '' && $row['number'] !== '' ? $row['type'] . '/' . $row['number'] : '';
        $row['route_key'] = (string) $row['id'];

        return $row;
    }
}
