<?php

require_once __DIR__ . '/lib/CallCenterApiRouter.php';
require_once __DIR__ . '/lib/CallCenterSnapshotDiffer.php';
require_once __DIR__ . '/lib/CallCenterStateStore.php';
require_once __DIR__ . '/lib/CallCenterRuntime.php';
require_once __DIR__ . '/lib/CallCenterService.php';

if (!function_exists('callcenter_bridge_hash_equals')) {
    function callcenter_bridge_hash_equals($knownString, $userString)
    {
        $knownString = (string) $knownString;
        $userString = (string) $userString;
        if (strlen($knownString) !== strlen($userString)) {
            return false;
        }

        $result = 0;
        $length = strlen($knownString);
        for ($i = 0; $i < $length; $i++) {
            $result |= ord($knownString[$i]) ^ ord($userString[$i]);
        }

        return $result === 0;
    }
}

$moduleEnvCandidates = array(
    dirname(__DIR__) . '/module.env',
    '/workspace/modules/callcenter_bridge/module.env',
);
foreach ($moduleEnvCandidates as $moduleEnvPath) {
    if (!is_file($moduleEnvPath)) {
        continue;
    }

    $lines = @file($moduleEnvPath, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    if (!is_array($lines)) {
        continue;
    }

    foreach ($lines as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#') {
            continue;
        }

        $parts = explode('=', $line, 2);
        if (count($parts) !== 2) {
            continue;
        }

        $name = trim($parts[0]);
        $value = trim($parts[1]);
        if ($name === '') {
            continue;
        }

        putenv($name . '=' . $value);
        $_ENV[$name] = $value;
    }

    break;
}

$method = isset($_SERVER['REQUEST_METHOD']) ? strtoupper((string) $_SERVER['REQUEST_METHOD']) : 'GET';
$requestUri = isset($_SERVER['REQUEST_URI']) ? (string) $_SERVER['REQUEST_URI'] : '/';
$scriptName = isset($_SERVER['SCRIPT_NAME']) ? (string) $_SERVER['SCRIPT_NAME'] : '';
$route = isset($_GET['route']) ? $_GET['route'] : null;

if (!is_string($route) || $route === '') {
    $path = parse_url($requestUri, PHP_URL_PATH);
    $route = is_string($path) ? $path : '/';
    if ($scriptName !== '' && substr($route, 0, strlen($scriptName)) === $scriptName) {
        $route = substr($route, strlen($scriptName));
    }
    if ($route === '') {
        $route = '/';
    }
}

$payload = array();
$rawInput = file_get_contents('php://input');
if (is_string($rawInput) && trim($rawInput) !== '') {
    $decoded = json_decode($rawInput, true);
    if (is_array($decoded)) {
        $payload = $decoded;
    }
}

$router = new CallCenterApiRouter();
$match = $router->match($method, $route);

header('Content-Type: application/json');

if ($match === null) {
    http_response_code(404);
    echo json_encode(array(
        'success' => false,
        'message' => 'route not found',
        'route' => $route,
    ));
    exit;
}

$token = trim((string) getenv('CALLCENTER_BRIDGE_API_TOKEN'));
if ($match['operation'] !== 'health') {
    $auth = '';
    if (isset($_SERVER['HTTP_AUTHORIZATION'])) {
        $auth = trim((string) $_SERVER['HTTP_AUTHORIZATION']);
    } elseif (isset($_SERVER['REDIRECT_HTTP_AUTHORIZATION'])) {
        $auth = trim((string) $_SERVER['REDIRECT_HTTP_AUTHORIZATION']);
    } elseif (function_exists('apache_request_headers')) {
        $headers = apache_request_headers();
        if (is_array($headers) && isset($headers['Authorization'])) {
            $auth = trim((string) $headers['Authorization']);
        }
    }
    $provided = '';
    if (preg_match('/^Bearer\s+(.+)$/i', $auth, $matches) === 1) {
        $provided = trim((string) $matches[1]);
    }

    if ($token === '' || $provided === '' || !callcenter_bridge_hash_equals($token, $provided)) {
        http_response_code(401);
        echo json_encode(array(
            'success' => false,
            'message' => 'unauthorized',
        ));
        exit;
    }
}

$service = new CallCenterService(
    new CallCenterRuntime(),
    new CallCenterStateStore()
);

try {
    $response = $service->handle($match['operation'], $match['params'], $payload);
    http_response_code(isset($response['status']) ? (int) $response['status'] : 200);
    if (isset($response['status'])) {
        unset($response['status']);
    }
    echo json_encode($response);
} catch (Exception $e) {
    http_response_code(500);
    echo json_encode(array(
        'success' => false,
        'message' => $e->getMessage(),
    ));
}
