<?php

class CallCenterConfigPage
{
    public static function fieldDefinitions()
    {
        return array(
            'CALLCENTER_BRIDGE_API_TOKEN' => array(
                'label' => 'API Token',
                'type' => 'text',
                'help' => 'Token usado no header Authorization: Bearer <token>.',
                'required' => true,
            ),
            'CALLCENTER_BRIDGE_PANEL_WEBHOOK_URL' => array(
                'label' => 'Panel Webhook URL',
                'type' => 'url',
                'help' => 'URL opcional para o relay de eventos ao painel.',
                'required' => false,
            ),
            'CALLCENTER_BRIDGE_PANEL_WEBHOOK_TOKEN' => array(
                'label' => 'Panel Webhook Token',
                'type' => 'text',
                'help' => 'Token opcional enviado ao painel no relay.',
                'required' => false,
            ),
            'CALLCENTER_BRIDGE_STATE_ROOT' => array(
                'label' => 'State Root',
                'type' => 'text',
                'help' => 'Diretorio onde o bridge persiste snapshots e bindings.',
                'required' => true,
            ),
            'CALLCENTER_BRIDGE_DB_DSN' => array(
                'label' => 'DB DSN',
                'type' => 'text',
                'help' => 'DSN PDO usado para acessar o banco do callcenter.',
                'required' => true,
            ),
            'CALLCENTER_BRIDGE_DB_USER' => array(
                'label' => 'DB User',
                'type' => 'text',
                'help' => 'Usuario do banco do callcenter.',
                'required' => true,
            ),
            'CALLCENTER_BRIDGE_DB_PASSWORD' => array(
                'label' => 'DB Password',
                'type' => 'password',
                'help' => 'Senha do banco do callcenter.',
                'required' => true,
            ),
            'CALLCENTER_BRIDGE_SOURCE' => array(
                'label' => 'Source',
                'type' => 'text',
                'help' => 'Nome logico da origem dos eventos normalizados.',
                'required' => true,
            ),
            'CALLCENTER_BRIDGE_HTTP_TIMEOUT' => array(
                'label' => 'HTTP Timeout',
                'type' => 'number',
                'help' => 'Timeout em segundos para chamadas HTTP do relay.',
                'required' => true,
            ),
        );
    }

    public static function parseEnvFile($path)
    {
        $values = array();
        if (!is_string($path) || $path === '' || !is_file($path)) {
            return $values;
        }

        $lines = @file($path, FILE_IGNORE_NEW_LINES);
        if (!is_array($lines)) {
            return $values;
        }

        foreach ($lines as $line) {
            $line = trim((string) $line);
            if ($line === '' || $line[0] === '#') {
                continue;
            }

            $parts = explode('=', $line, 2);
            if (count($parts) !== 2) {
                continue;
            }

            $name = trim($parts[0]);
            if ($name === '') {
                continue;
            }

            $values[$name] = trim($parts[1]);
        }

        return $values;
    }

    public static function loadConfig($envPath, $examplePath)
    {
        $values = self::parseEnvFile($examplePath);
        foreach (self::parseEnvFile($envPath) as $key => $value) {
            $values[$key] = $value;
        }

        foreach (array_keys(self::fieldDefinitions()) as $fieldName) {
            if (!array_key_exists($fieldName, $values)) {
                $values[$fieldName] = '';
            }
        }

        return $values;
    }

    public static function saveConfig($envPath, $examplePath, $input)
    {
        $input = is_array($input) ? $input : array();
        $existing = self::parseEnvFile($envPath);
        $values = self::loadConfig($envPath, $examplePath);

        foreach (array_keys(self::fieldDefinitions()) as $fieldName) {
            $values[$fieldName] = self::sanitizeValue(
                $fieldName,
                array_key_exists($fieldName, $input) ? $input[$fieldName] : $values[$fieldName]
            );
        }

        foreach ($existing as $key => $value) {
            if (!array_key_exists($key, $values)) {
                $values[$key] = $value;
            }
        }

        $orderedKeys = array();
        foreach (self::parseEnvFile($examplePath) as $key => $value) {
            $orderedKeys[] = $key;
        }
        foreach ($existing as $key => $value) {
            if (!in_array($key, $orderedKeys, true)) {
                $orderedKeys[] = $key;
            }
        }
        foreach ($values as $key => $value) {
            if (!in_array($key, $orderedKeys, true)) {
                $orderedKeys[] = $key;
            }
        }

        $lines = array();
        foreach ($orderedKeys as $key) {
            if (!array_key_exists($key, $values)) {
                continue;
            }
            $lines[] = $key . '=' . $values[$key];
        }

        $directory = dirname($envPath);
        if (!is_dir($directory) && !@mkdir($directory, 0775, true) && !is_dir($directory)) {
            throw new RuntimeException('Unable to create config directory.');
        }

        $tempPath = $envPath . '.tmp';
        $bytes = @file_put_contents($tempPath, implode("\n", $lines) . "\n");
        if ($bytes === false) {
            throw new RuntimeException('Unable to write temporary config file.');
        }
        if (!@rename($tempPath, $envPath)) {
            @unlink($tempPath);
            throw new RuntimeException('Unable to replace config file.');
        }

        return $values;
    }

    public static function sanitizeValue($fieldName, $value)
    {
        $value = trim((string) $value);
        $value = str_replace(array("\r", "\n"), '', $value);

        if ($fieldName === 'CALLCENTER_BRIDGE_HTTP_TIMEOUT') {
            if ($value === '' || !preg_match('/^\d+$/', $value)) {
                return '10';
            }
        }

        return $value;
    }
}
