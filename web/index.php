<?php

require_once __DIR__ . '/lib/CallCenterConfigPage.php';

function callcenter_bridge_h($value)
{
    return htmlspecialchars((string) $value, ENT_QUOTES, 'UTF-8');
}

function callcenter_bridge_base_url()
{
    $scheme = 'http';
    if (
        (isset($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== '' && $_SERVER['HTTPS'] !== 'off')
        || (isset($_SERVER['SERVER_PORT']) && (string) $_SERVER['SERVER_PORT'] === '443')
    ) {
        $scheme = 'https';
    }

    $host = isset($_SERVER['HTTP_HOST']) && $_SERVER['HTTP_HOST'] !== ''
        ? (string) $_SERVER['HTTP_HOST']
        : '127.0.0.1:8088';

    return $scheme . '://' . $host . '/modules/callcenter_bridge/api.php';
}

function callcenter_bridge_env_paths()
{
    return array(
        __DIR__ . '/module.env',
        '/workspace/modules/callcenter_bridge/module.env',
    );
}

function callcenter_bridge_example_paths()
{
    return array(
        __DIR__ . '/module.env.example',
        '/workspace/modules/callcenter_bridge/module.env.example',
    );
}

function callcenter_bridge_first_existing_path($paths)
{
    foreach ($paths as $path) {
        if (is_string($path) && $path !== '' && is_file($path)) {
            return $path;
        }
    }

    return is_array($paths) && isset($paths[0]) ? $paths[0] : '';
}

function _moduleContent(&$smarty, $module_name)
{
    $envPath = callcenter_bridge_first_existing_path(callcenter_bridge_env_paths());
    $examplePath = callcenter_bridge_first_existing_path(callcenter_bridge_example_paths());
    $fields = CallCenterConfigPage::fieldDefinitions();
    $values = CallCenterConfigPage::loadConfig($envPath, $examplePath);
    $message = '';
    $messageType = 'info';

    if (isset($_SERVER['REQUEST_METHOD']) && strtoupper((string) $_SERVER['REQUEST_METHOD']) === 'POST') {
        $submitted = array();
        foreach (array_keys($fields) as $fieldName) {
            $submitted[$fieldName] = isset($_POST[$fieldName]) ? $_POST[$fieldName] : '';
        }

        try {
            $values = CallCenterConfigPage::saveConfig($envPath, $examplePath, $submitted);
            $message = 'Configuracao salva em module.env.';
            $messageType = 'success';
        } catch (Exception $e) {
            foreach ($submitted as $fieldName => $fieldValue) {
                $values[$fieldName] = CallCenterConfigPage::sanitizeValue($fieldName, $fieldValue);
            }
            $message = 'Falha ao salvar configuracao: ' . $e->getMessage();
            $messageType = 'error';
        }
    }

    $apiBaseUrl = callcenter_bridge_base_url();
    $fieldsHtml = '';
    foreach ($fields as $fieldName => $fieldMeta) {
        $inputType = isset($fieldMeta['type']) ? $fieldMeta['type'] : 'text';
        $required = !empty($fieldMeta['required']) ? ' required' : '';
        $fieldsHtml .= '<div class="ccb-field">';
        $fieldsHtml .= '<label for="' . callcenter_bridge_h($fieldName) . '">' . callcenter_bridge_h($fieldMeta['label']) . '</label>';
        $fieldsHtml .= '<input'
            . ' id="' . callcenter_bridge_h($fieldName) . '"'
            . ' name="' . callcenter_bridge_h($fieldName) . '"'
            . ' type="' . callcenter_bridge_h($inputType) . '"'
            . ' value="' . callcenter_bridge_h(isset($values[$fieldName]) ? $values[$fieldName] : '') . '"'
            . $required
            . ' />';
        $fieldsHtml .= '<small>' . callcenter_bridge_h($fieldMeta['help']) . '</small>';
        $fieldsHtml .= '</div>';
    }

    $messageHtml = '';
    if ($message !== '') {
        $messageHtml = '<div class="ccb-alert ccb-alert-' . callcenter_bridge_h($messageType) . '">'
            . callcenter_bridge_h($message)
            . '</div>';
    }

    $html = <<<HTML
<style>
.ccb-wrap { max-width: 1100px; padding: 18px 24px 28px; font-family: Arial, Helvetica, sans-serif; color: #1f2937; }
.ccb-grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr); gap: 20px; align-items: start; }
.ccb-card { background: #fff; border: 1px solid #dbe3ea; border-radius: 10px; padding: 18px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05); }
.ccb-card h2, .ccb-card h3 { margin: 0 0 12px; }
.ccb-card p { margin: 0 0 12px; line-height: 1.5; }
.ccb-form { display: grid; gap: 14px; }
.ccb-field { display: grid; gap: 6px; }
.ccb-field label { font-weight: 700; font-size: 13px; }
.ccb-field input { width: 100%; border: 1px solid #c5d1dd; border-radius: 8px; padding: 10px 12px; font-size: 14px; }
.ccb-field small { color: #5b6470; line-height: 1.4; }
.ccb-actions { display: flex; justify-content: flex-end; }
.ccb-actions button { background: #0f766e; color: #fff; border: 0; border-radius: 8px; padding: 10px 18px; font-weight: 700; cursor: pointer; }
.ccb-code, .ccb-list code { display: block; white-space: pre-wrap; background: #0f172a; color: #e2e8f0; border-radius: 8px; padding: 12px; font-family: monospace; font-size: 13px; }
.ccb-list { margin: 0; padding-left: 18px; }
.ccb-list li { margin-bottom: 8px; }
.ccb-alert { border-radius: 8px; padding: 12px 14px; margin-bottom: 16px; font-weight: 700; }
.ccb-alert-success { background: #dcfce7; color: #166534; border: 1px solid #86efac; }
.ccb-alert-error { background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }
@media (max-width: 900px) { .ccb-grid { grid-template-columns: 1fr; } }
</style>
<div class="ccb-wrap">
    <div class="ccb-card" style="margin-bottom: 20px;">
        <h2>Callcenter Bridge API</h2>
        <p>Esta tela centraliza a configuracao local do bridge e resume o que um integrador precisa para consumir a API com seguranca.</p>
    </div>
    {$messageHtml}
    <div class="ccb-grid">
        <div class="ccb-card">
            <h3>Configuracao</h3>
            <form method="post" class="ccb-form">
                {$fieldsHtml}
                <div class="ccb-actions">
                    <button type="submit">Salvar configuracao</button>
                </div>
            </form>
        </div>
        <div class="ccb-card">
            <h3>Como consumir a API</h3>
            <p>Base local:</p>
            <div class="ccb-code">{$apiBaseUrl}</div>
            <p style="margin-top: 14px;">Header obrigatorio:</p>
            <div class="ccb-code">Authorization: Bearer {$values['CALLCENTER_BRIDGE_API_TOKEN']}</div>
            <p style="margin-top: 14px;">Endpoints principais:</p>
            <ul class="ccb-list">
                <li><code>GET /v1/health</code></li>
                <li><code>GET /v1/agents</code></li>
                <li><code>GET /v1/queues</code></li>
                <li><code>GET /v1/calls/active</code></li>
                <li><code>POST /v1/events/relay</code></li>
            </ul>
            <p style="margin-top: 14px;">Observacoes:</p>
            <ul class="ccb-list">
                <li>As rotas tambem aceitam <code>api.php?route=/v1/...</code> para casos com identificadores ECCP contendo barra.</li>
                <li>O relay usa <code>CALLCENTER_BRIDGE_PANEL_WEBHOOK_URL</code> e <code>CALLCENTER_BRIDGE_PANEL_WEBHOOK_TOKEN</code> quando preenchidos.</li>
                <li>O estado local e persistido em <code>CALLCENTER_BRIDGE_STATE_ROOT</code>.</li>
            </ul>
        </div>
    </div>
</div>
HTML;

    return $html;
}
