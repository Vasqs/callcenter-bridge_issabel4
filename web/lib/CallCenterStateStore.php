<?php

class CallCenterStateStore
{
    private $stateRoot;

    public function __construct($stateRoot = null)
    {
        $default = '/var/lib/asterisk/issabel-module-state/callcenter_bridge';
        $this->stateRoot = rtrim((string) ($stateRoot ? $stateRoot : getenv('CALLCENTER_BRIDGE_STATE_ROOT')), '/');
        if ($this->stateRoot === '') {
            $this->stateRoot = $default;
        }
    }

    public function readAgentExtensions()
    {
        $data = $this->readJsonFile($this->stateRoot . '/agent_extensions.json');

        return is_array($data) ? $data : array();
    }

    public function setAgentExtension($agentId, $extension)
    {
        $extensions = $this->readAgentExtensions();
        $extensions[$agentId] = $extension;
        $this->writeJsonFile($this->stateRoot . '/agent_extensions.json', $extensions);
    }

    public function getAgentExtension($routeKey, $agentId = null)
    {
        $extensions = $this->readAgentExtensions();
        $routeStorageKey = $this->routeStorageKey($routeKey);

        if ($routeStorageKey !== null && isset($extensions[$routeStorageKey])) {
            return $extensions[$routeStorageKey];
        }

        $agentId = trim((string) $agentId);
        if ($agentId !== '' && isset($extensions[$agentId])) {
            return $extensions[$agentId];
        }

        return null;
    }

    public function persistAgentExtension($routeKey, $agentId, $extension)
    {
        $extensions = $this->readAgentExtensions();
        $routeStorageKey = $this->routeStorageKey($routeKey);

        if ($routeStorageKey !== null) {
            $extensions[$routeStorageKey] = $extension;
        }

        $agentId = trim((string) $agentId);
        if ($agentId !== '') {
            $extensions[$agentId] = $extension;
        }

        $this->writeJsonFile($this->stateRoot . '/agent_extensions.json', $extensions);
    }

    public function readLastSnapshot()
    {
        $data = $this->readJsonFile($this->stateRoot . '/last_snapshot.json');

        return is_array($data) ? $data : array('agents' => array(), 'calls' => array());
    }

    public function writeLastSnapshot(array $snapshot)
    {
        $this->writeJsonFile($this->stateRoot . '/last_snapshot.json', $snapshot);
    }

    public function readFocusedCallIds()
    {
        $data = $this->readJsonFile($this->stateRoot . '/focused_calls.json');

        return is_array($data) ? $data : array();
    }

    public function writeFocusedCallIds(array $focusedCalls)
    {
        $this->writeJsonFile($this->stateRoot . '/focused_calls.json', $focusedCalls);
    }

    private function readJsonFile($path)
    {
        if (!is_file($path)) {
            return null;
        }

        $decoded = json_decode((string) file_get_contents($path), true);

        return is_array($decoded) ? $decoded : null;
    }

    private function writeJsonFile($path, array $payload)
    {
        if (!is_dir($this->stateRoot)) {
            @mkdir($this->stateRoot, 0775, true);
        }

        $encoded = json_encode($payload);
        if ($encoded === false) {
            throw new RuntimeException('Unable to encode bridge state payload.');
        }

        $tempPath = $path . '.' . uniqid('tmp', true);
        if (file_put_contents($tempPath, $encoded, LOCK_EX) === false) {
            @unlink($tempPath);
            throw new RuntimeException('Unable to persist bridge state payload.');
        }

        if (!@rename($tempPath, $path)) {
            @unlink($tempPath);
            throw new RuntimeException('Unable to swap bridge state payload.');
        }
    }

    private function routeStorageKey($routeKey)
    {
        $routeKey = trim((string) $routeKey);

        if ($routeKey === '') {
            return null;
        }

        return 'route:' . $routeKey;
    }
}
