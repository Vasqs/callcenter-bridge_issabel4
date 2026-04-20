import json
import tempfile
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_ROOT = ROOT


class CallcenterBridgeModuleTests(unittest.TestCase):
    def run_php(self, script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["php"],
            input=script,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

    def test_callcenter_bridge_module_contract_exists(self) -> None:
        expected_paths = [
            MODULE_ROOT / "README.md",
            MODULE_ROOT / "index.php",
            MODULE_ROOT / "api.php",
            MODULE_ROOT / "menu.xml",
            MODULE_ROOT / "web" / "index.php",
            MODULE_ROOT / "web" / "menu.xml",
            MODULE_ROOT / "web" / "api.php",
            MODULE_ROOT / "web" / "lib" / "CallCenterConfigPage.php",
            MODULE_ROOT / "web" / "lib" / "CallCenterApiRouter.php",
            MODULE_ROOT / "web" / "lib" / "CallCenterSnapshotDiffer.php",
            MODULE_ROOT / "web" / "lib" / "CallCenterService.php",
            MODULE_ROOT / "hooks" / "apply.sh",
            MODULE_ROOT / "module.env.example",
        ]

        for path in expected_paths:
            self.assertTrue(path.exists(), f"{path} must exist")

    def test_apply_hook_does_not_force_webrtc_flags_for_extension_1001(self) -> None:
        apply_hook = (MODULE_ROOT / "hooks" / "apply.sh").read_text()

        self.assertNotIn("dtlsenable=yes", apply_hook)
        self.assertNotIn("icesupport=yes", apply_hook)
        self.assertNotIn("transport=udp,ws,wss", apply_hook)
        self.assertIn("remove_legacy_webrtc_block", apply_hook)
        self.assertIn("sqlite3 /var/www/db/menu.db", apply_hook)
        self.assertIn("callcenter_bridge", apply_hook)
        self.assertIn("DELETE FROM menu WHERE id='callcenter_bridge'", apply_hook)
        self.assertIn("INSERT INTO menu", apply_hook)
        self.assertIn("WHERE NOT EXISTS", apply_hook)
        self.assertIn("sqlite3 /var/www/db/acl.db", apply_hook)
        self.assertIn("INSERT INTO acl_resource", apply_hook)
        self.assertIn("INSERT INTO acl_group_permission", apply_hook)
        self.assertIn("ln -s", apply_hook)
        self.assertIn("callcenter_bridge", apply_hook)

    def test_standalone_entrypoints_wrap_web_payload(self) -> None:
        root_index = (MODULE_ROOT / "index.php").read_text()
        root_api = (MODULE_ROOT / "api.php").read_text()
        root_menu = (MODULE_ROOT / "menu.xml").read_text()

        self.assertIn("__DIR__ . '/web/index.php'", root_index)
        self.assertIn("__DIR__ . '/web/api.php'", root_api)
        self.assertIn("<item id=\"callcenter_bridge\">", root_menu)

    def test_callcenter_bridge_menu_exposes_admin_entry(self) -> None:
        menu_xml = (MODULE_ROOT / "web" / "menu.xml").read_text()

        self.assertIn("<item id=\"callcenter_bridge\">", menu_xml)
        self.assertIn("<type>module</type>", menu_xml)
        self.assertIn("<id_parent>pbxconfig</id_parent>", menu_xml)
        self.assertIn("<resource id=\"callcenter_bridge\">", menu_xml)

    def test_callcenter_bridge_index_uses_same_env_candidates_as_api(self) -> None:
        index_php = (MODULE_ROOT / "web" / "index.php").read_text()

        self.assertIn("__DIR__ . '/module.env'", index_php)
        self.assertIn("/workspace/modules/callcenter_bridge/module.env", index_php)
        self.assertNotIn("dirname(__DIR__)", index_php)

    def test_callcenter_bridge_config_page_loads_defaults_and_persists_env(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterConfigPage.php")!r};

            $tmpDir = sys_get_temp_dir() . '/callcenter-bridge-config-' . bin2hex(random_bytes(4));
            mkdir($tmpDir, 0777, true);
            $examplePath = $tmpDir . '/module.env.example';
            $envPath = $tmpDir . '/module.env';

            file_put_contents($examplePath, implode("\n", [
                'CALLCENTER_BRIDGE_API_TOKEN=change-me',
                'CALLCENTER_BRIDGE_PANEL_WEBHOOK_URL=',
                'CALLCENTER_BRIDGE_PANEL_WEBHOOK_TOKEN=',
                'CALLCENTER_BRIDGE_HTTP_TIMEOUT=10',
                '',
            ]));

            file_put_contents($envPath, implode("\n", [
                'CALLCENTER_BRIDGE_API_TOKEN=existing-token',
                'CALLCENTER_BRIDGE_HTTP_TIMEOUT=15',
                'CALLCENTER_BRIDGE_EXTRA_FLAG=keep-me',
                '',
            ]));

            $loaded = CallCenterConfigPage::loadConfig($envPath, $examplePath);
            CallCenterConfigPage::saveConfig(
                $envPath,
                $examplePath,
                [
                    'CALLCENTER_BRIDGE_API_TOKEN' => 'updated-token',
                    'CALLCENTER_BRIDGE_PANEL_WEBHOOK_URL' => 'https://painel.local/webhook',
                    'CALLCENTER_BRIDGE_PANEL_WEBHOOK_TOKEN' => 'panel-secret',
                    'CALLCENTER_BRIDGE_HTTP_TIMEOUT' => '25',
                ]
            );

            echo json_encode([
                'loaded' => $loaded,
                'saved' => CallCenterConfigPage::parseEnvFile($envPath),
                'raw' => file_get_contents($envPath),
            ], JSON_UNESCAPED_SLASHES);
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        payload = json.loads(proc.stdout)
        self.assertEqual(payload["loaded"]["CALLCENTER_BRIDGE_API_TOKEN"], "existing-token")
        self.assertEqual(payload["loaded"]["CALLCENTER_BRIDGE_PANEL_WEBHOOK_URL"], "")
        self.assertEqual(payload["loaded"]["CALLCENTER_BRIDGE_HTTP_TIMEOUT"], "15")
        self.assertEqual(payload["saved"]["CALLCENTER_BRIDGE_API_TOKEN"], "updated-token")
        self.assertEqual(payload["saved"]["CALLCENTER_BRIDGE_PANEL_WEBHOOK_URL"], "https://painel.local/webhook")
        self.assertEqual(payload["saved"]["CALLCENTER_BRIDGE_PANEL_WEBHOOK_TOKEN"], "panel-secret")
        self.assertEqual(payload["saved"]["CALLCENTER_BRIDGE_HTTP_TIMEOUT"], "25")
        self.assertEqual(payload["saved"]["CALLCENTER_BRIDGE_EXTRA_FLAG"], "keep-me")
        self.assertIn("CALLCENTER_BRIDGE_EXTRA_FLAG=keep-me", payload["raw"])

    def test_callcenter_bridge_router_resolves_expected_routes(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterApiRouter.php")!r};

            $router = new CallCenterApiRouter();
            $routes = [
                ['GET', '/v1/health'],
                ['GET', '/v1/agents'],
                ['GET', '/v1/queues'],
                ['GET', '/v1/calls/active'],
                ['GET', '/v1/agents/Agent%2F1/status'],
                ['POST', '/v1/agents/Agent%2F1/login'],
                ['POST', '/v1/agents/Agent%2F1/logout'],
                ['POST', '/v1/agents/Agent%2F1/pause'],
                ['POST', '/v1/agents/Agent%2F1/unpause'],
                ['PATCH', '/v1/agents/Agent%2F1/extension'],
                ['POST', '/v1/calls/originate'],
                ['POST', '/v1/calls/call-001/hangup'],
                ['POST', '/v1/events/relay'],
            ];

            $resolved = [];
            foreach ($routes as [$method, $path]) {{
                $resolved[] = $router->match($method, $path);
            }}

            echo json_encode($resolved, JSON_UNESCAPED_SLASHES);
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        resolved = json.loads(proc.stdout)
        self.assertEqual(
            [item["operation"] for item in resolved],
            [
                "health",
                "agents.list",
                "queues.list",
                "calls.active",
                "agents.status",
                "agents.login",
                "agents.logout",
                "agents.pause",
                "agents.unpause",
                "agents.set_extension",
                "calls.originate",
                "calls.hangup",
                "events.relay",
            ],
        )
        self.assertEqual(resolved[4]["params"]["agentId"], "Agent/1")
        self.assertEqual(resolved[11]["params"]["callId"], "call-001")

    def test_callcenter_bridge_snapshot_differ_emits_normalized_events(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterSnapshotDiffer.php")!r};

            $differ = new CallCenterSnapshotDiffer('issabel-callcenter');
            $previous = [
                'agents' => [
                    'Agent/1' => ['status' => 'offline', 'extension' => '1001', 'queue' => 'ventas'],
                ],
                'calls' => [
                    'old-call' => ['status' => 'ringing', 'agent_id' => 'Agent/2', 'phone' => '5571999999999'],
                ],
            ];
            $current = [
                'agents' => [
                    'Agent/1' => ['status' => 'paused', 'extension' => '1001', 'queue' => 'ventas', 'pause_code' => 'break'],
                    'Agent/2' => ['status' => 'online', 'extension' => '1002', 'queue' => 'suporte'],
                ],
                'calls' => [
                    'call-001' => ['status' => 'answered', 'agent_id' => 'Agent/1', 'phone' => '5571888877777', 'queue' => 'ventas', 'direction' => 'outbound'],
                ],
            ];

            echo json_encode(
                $differ->diff($previous, $current, 'company-demo'),
                JSON_UNESCAPED_SLASHES
            );
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        events = json.loads(proc.stdout)
        event_types = [event["event_type"] for event in events]

        self.assertIn("agent.paused", event_types)
        self.assertIn("agent.status_snapshot", event_types)
        self.assertIn("call.answered", event_types)
        self.assertIn("call.hangup", event_types)

        paused_event = next(event for event in events if event["event_type"] == "agent.paused")
        self.assertEqual(paused_event["agent_id"], "Agent/1")
        self.assertEqual(paused_event["pause_code"], "break")
        self.assertEqual(paused_event["company_key"], "company-demo")

        hangup_event = next(event for event in events if event["event_type"] == "call.hangup")
        self.assertEqual(hangup_event["call_id"], "old-call")

    def test_callcenter_bridge_snapshot_differ_adds_event_and_remote_number_aliases(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterSnapshotDiffer.php")!r};

            $differ = new CallCenterSnapshotDiffer('issabel-callcenter');
            $events = $differ->diff(
                ['agents' => [], 'calls' => []],
                [
                    'agents' => [],
                    'calls' => [
                        'call-001' => [
                            'status' => 'answered',
                            'agent_id' => 'Agent/1',
                            'phone' => '5571888877777',
                            'direction' => 'outbound',
                        ],
                    ],
                ],
                'company-demo'
            );

            echo json_encode($events, JSON_UNESCAPED_SLASHES);
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        events = json.loads(proc.stdout)
        answered_event = next(event for event in events if event["event_type"] == "call.answered")
        self.assertEqual(answered_event["event"], "call.answered")
        self.assertEqual(answered_event["remote_number"], "5571888877777")

    def test_callcenter_bridge_snapshot_differ_emits_focus_events_with_policy_rules(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterSnapshotDiffer.php")!r};

            $differ = new CallCenterSnapshotDiffer('issabel-callcenter');
            $previous = [
                'agents' => [
                    'Agent/1' => ['status' => 'online', 'extension' => '1001'],
                ],
                'calls' => [
                    'focus-old' => [
                        'status' => 'ringing',
                        'agent_id' => 'Agent/1',
                        'extension' => '1001',
                        'phone' => '11111',
                        'direction' => 'incoming',
                    ],
                ],
            ];
            $current1 = [
                'agents' => [
                    'Agent/1' => ['status' => 'online', 'extension' => '1001'],
                ],
                'calls' => [
                    'focus-old' => [
                        'status' => 'ringing',
                        'agent_id' => 'Agent/1',
                        'extension' => '1001',
                        'phone' => '11111',
                        'direction' => 'incoming',
                    ],
                    'answered-bound' => [
                        'status' => 'answered',
                        'agent_id' => 'Agent/1',
                        'extension' => '1001',
                        'phone' => '22222',
                        'direction' => 'outbound',
                    ],
                ],
            ];
            $current2 = [
                'agents' => [
                    'Agent/1' => ['status' => 'online', 'extension' => '1001'],
                ],
                'calls' => [
                    'answered-older' => [
                        'status' => 'answered',
                        'agent_id' => 'Agent/1',
                        'extension' => '1001',
                        'phone' => '44444',
                        'direction' => 'outbound',
                    ],
                    'answered-newer' => [
                        'status' => 'answered',
                        'agent_id' => 'Agent/1',
                        'extension' => '1001',
                        'phone' => '55555',
                        'direction' => 'outbound',
                    ],
                    'answered-agentless-latest' => [
                        'status' => 'answered',
                        'agent_id' => '',
                        'extension' => '1001',
                        'phone' => '66666',
                        'direction' => 'outbound',
                    ],
                ],
            ];

            $previousFocused = ['Agent/1' => 'focus-old'];
            $nextFocused1 = [];
            $events1 = $differ->diff($previous, $current1, 'company-demo', $previousFocused, $nextFocused1);
            $nextFocused2 = [];
            $events2 = $differ->diff($current1, $current2, 'company-demo', $nextFocused1, $nextFocused2);

            echo json_encode(
                [
                    'events1' => $events1,
                    'events2' => $events2,
                    'nextFocused1' => $nextFocused1,
                    'nextFocused2' => $nextFocused2,
                ],
                JSON_UNESCAPED_SLASHES
            );
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        payload = json.loads(proc.stdout)
        focus1 = next(event for event in payload["events1"] if event["event_type"] == "call.focus")
        focus2 = next(event for event in payload["events2"] if event["event_type"] == "call.focus")

        self.assertEqual(payload["nextFocused1"]["Agent/1"], "focus-old")
        self.assertEqual(payload["nextFocused2"]["Agent/1"], "answered-newer")

        self.assertEqual(focus1["event_type"], "call.focus")
        self.assertEqual(focus1["event"], "call.focus")
        self.assertEqual(focus1["state"], "ringing")
        self.assertEqual(focus1["agent_id"], "Agent/1")
        self.assertEqual(focus1["extension"], "1001")
        self.assertEqual(focus1["call_id"], "focus-old")
        self.assertEqual(focus1["direction"], "incoming")
        self.assertEqual(focus1["phone"], "11111")
        self.assertEqual(focus1["remote_number"], "11111")
        self.assertEqual(focus1["mode"], "agent-fallback")
        self.assertEqual(focus1["source"], "issabel-callcenter")

        self.assertEqual(focus2["call_id"], "answered-newer")
        self.assertEqual(focus2["state"], "answered")
        self.assertEqual(focus2["phone"], "55555")

    def test_callcenter_bridge_snapshot_differ_prioritizes_answered_before_agent_binding(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterSnapshotDiffer.php")!r};

            $differ = new CallCenterSnapshotDiffer('issabel-callcenter');
            $nextFocused = [];
            $events = $differ->diff(
                ['agents' => [], 'calls' => []],
                [
                    'agents' => [
                        'Agent/1' => ['status' => 'online', 'extension' => '1001'],
                    ],
                    'calls' => [
                        'ringing-bound' => [
                            'status' => 'ringing',
                            'agent_id' => 'Agent/1',
                            'extension' => '1001',
                            'phone' => '11111',
                            'direction' => 'incoming',
                        ],
                        'answered-agentless' => [
                            'status' => 'answered',
                            'agent_id' => '',
                            'extension' => '1001',
                            'phone' => '22222',
                            'direction' => 'outbound',
                        ],
                    ],
                ],
                'company-demo',
                [],
                $nextFocused
            );

            echo json_encode(
                [
                    'events' => $events,
                    'nextFocused' => $nextFocused,
                ],
                JSON_UNESCAPED_SLASHES
            );
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        payload = json.loads(proc.stdout)
        focus = next(event for event in payload["events"] if event["event_type"] == "call.focus")

        self.assertEqual(payload["nextFocused"]["Agent/1"], "answered-agentless")
        self.assertEqual(focus["call_id"], "answered-agentless")
        self.assertEqual(focus["phone"], "22222")

    def test_callcenter_bridge_service_relay_persists_focused_calls_between_cycles(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterRuntime.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterStateStore.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterSnapshotDiffer.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterService.php")!r};

            class FakeRuntimeForFocusRelayTest extends CallCenterRuntime {{
                public function __construct() {{}}
                public function health() {{ return []; }}
                public function listAgents() {{ return []; }}
                public function listQueues() {{ return []; }}
                public function listPauses() {{ return []; }}
                public function listActiveCalls() {{ return []; }}
                public function buildSnapshot($store) {{ return ['agents' => [], 'calls' => []]; }}
                public function resolveAgentReference($reference) {{ throw new RuntimeException('not used'); }}
                public function getAgentStatus($agentId) {{ return ['agent_id' => $agentId, 'status' => 'offline', 'raw_status' => [], 'queues' => []]; }}
                public function loginAgent($agentId, $extension) {{ return ['ok' => true]; }}
                public function logoutAgent($agentId) {{ return ['ok' => true]; }}
                public function pauseAgent($agentId, $pauseId) {{ return ['ok' => true]; }}
                public function unpauseAgent($agentId) {{ return ['ok' => true]; }}
                public function hangupAgentCall($agentId) {{ return ['ok' => true]; }}
                public function originateCall($agentId, $extension, $phone, $callId) {{ return ['ok' => true]; }}
            }}

            class FakeStoreForFocusRelayTest extends CallCenterStateStore {{
                public function __construct() {{}}
                public $extensions = [];
                public $lastSnapshot = ['agents' => [], 'calls' => []];
                public $focusedCalls = ['Agent/1' => 'focus-old'];
                public function readAgentExtensions() {{ return $this->extensions; }}
                public function setAgentExtension($agentId, $extension) {{ $this->extensions[$agentId] = $extension; }}
                public function readLastSnapshot() {{ return $this->lastSnapshot; }}
                public function writeLastSnapshot($snapshot) {{ $this->lastSnapshot = $snapshot; }}
                public function readFocusedCallIds() {{ return $this->focusedCalls; }}
                public function writeFocusedCallIds($focusedCalls) {{ $this->focusedCalls = $focusedCalls; }}
            }}

            $runtime = new FakeRuntimeForFocusRelayTest();
            $store = new FakeStoreForFocusRelayTest();
            $service = new CallCenterService($runtime, $store);

            $snapshot1 = [
                'agents' => ['Agent/1' => ['status' => 'online', 'extension' => '1001']],
                'calls' => [
                    'focus-old' => ['status' => 'ringing', 'agent_id' => 'Agent/1', 'phone' => '11111', 'direction' => 'incoming'],
                    'answered-bound' => ['status' => 'answered', 'agent_id' => 'Agent/1', 'phone' => '22222', 'direction' => 'outbound'],
                ],
            ];
            $snapshot2 = [
                'agents' => ['Agent/1' => ['status' => 'online', 'extension' => '1001']],
                'calls' => [
                    'answered-older' => ['status' => 'answered', 'agent_id' => 'Agent/1', 'phone' => '44444', 'direction' => 'outbound'],
                    'answered-newer' => ['status' => 'answered', 'agent_id' => 'Agent/1', 'phone' => '55555', 'direction' => 'outbound'],
                ],
            ];

            $relay1 = $service->handle('events.relay', [], ['company_key' => 'company-demo', 'snapshot' => $snapshot1]);
            $relay2 = $service->handle('events.relay', [], ['company_key' => 'company-demo', 'snapshot' => $snapshot2]);

            $focus1 = null;
            foreach ($relay1['events'] as $event) {{
                if ($event['event_type'] === 'call.focus') {{
                    $focus1 = $event;
                    break;
                }}
            }}
            $focus2 = null;
            foreach ($relay2['events'] as $event) {{
                if ($event['event_type'] === 'call.focus') {{
                    $focus2 = $event;
                    break;
                }}
            }}

            echo json_encode([
                'focus1' => $focus1,
                'focus2' => $focus2,
                'focused_calls' => $store->focusedCalls,
            ], JSON_UNESCAPED_SLASHES);
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        payload = json.loads(proc.stdout)
        self.assertIsNotNone(payload["focus1"])
        self.assertIsNotNone(payload["focus2"])
        self.assertEqual(payload["focus1"]["call_id"], "focus-old")
        self.assertEqual(payload["focus2"]["call_id"], "answered-newer")
        self.assertEqual(payload["focused_calls"]["Agent/1"], "answered-newer")

    def test_callcenter_bridge_state_store_writes_json_atomically(self) -> None:
        store_code = (MODULE_ROOT / "web" / "lib" / "CallCenterStateStore.php").read_text()

        self.assertIn("LOCK_EX", store_code)
        self.assertIn("rename($tempPath, $path)", store_code)

    def test_callcenter_bridge_service_resolves_numeric_and_alias_agent_refs(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterRuntime.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterStateStore.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterSnapshotDiffer.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterService.php")!r};

            class FakeRuntimeForServiceTest extends CallCenterRuntime {{
                public function __construct() {{}}
                public $calls = [];

                public function health() {{ return []; }}
                public function listAgents() {{
                    return [[
                        'agent_id' => 'Agent/1',
                        'route_key' => '1',
                        'id' => 1,
                        'type' => 'Agent',
                        'number' => '1',
                        'name' => '1',
                        'enabled' => true,
                        'status' => 'offline',
                        'extension' => null,
                        'queue' => null,
                    ]];
                }}
                public function listQueues() {{ return []; }}
                public function listPauses() {{ return []; }}
                public function listActiveCalls() {{ return []; }}
                public function buildSnapshot($store) {{ return ['agents' => [], 'calls' => []]; }}
                public function resolveAgentReference($reference) {{
                    if ($reference === '1' || $reference === 'Agent-1' || $reference === 'Agent/1') {{
                        return ['agent_id' => 'Agent/1', 'route_key' => '1'];
                    }}
                    throw new RuntimeException('missing');
                }}
                public function getAgentStatus($agentId) {{
                    return ['agent_id' => $agentId, 'status' => 'offline', 'raw_status' => ['status' => 'offline'], 'queues' => []];
                }}
                public function loginAgent($agentId, $extension) {{
                    $this->calls[] = ['method' => 'loginAgent', 'agent_id' => $agentId, 'extension' => $extension];
                    return ['ok' => true];
                }}
                public function logoutAgent($agentId) {{
                    $this->calls[] = ['method' => 'logoutAgent', 'agent_id' => $agentId];
                    return ['ok' => true];
                }}
                public function pauseAgent($agentId, $pauseId) {{
                    $this->calls[] = ['method' => 'pauseAgent', 'agent_id' => $agentId, 'pause_id' => $pauseId];
                    return ['ok' => true];
                }}
                public function unpauseAgent($agentId) {{
                    $this->calls[] = ['method' => 'unpauseAgent', 'agent_id' => $agentId];
                    return ['ok' => true];
                }}
                public function hangupAgentCall($agentId) {{
                    $this->calls[] = ['method' => 'hangupAgentCall', 'agent_id' => $agentId];
                    return ['ok' => true];
                }}
                public function originateCall($agentId, $extension, $phone, $callId) {{
                    $this->calls[] = ['method' => 'originateCall', 'agent_id' => $agentId, 'extension' => $extension, 'phone' => $phone, 'call_id' => $callId];
                    return ['ok' => true];
                }}
            }}

            class FakeStoreForServiceTest extends CallCenterStateStore {{
                public function __construct() {{}}
                public $extensions = [];
                public function readAgentExtensions() {{ return $this->extensions; }}
                public function setAgentExtension($agentId, $extension) {{ $this->extensions[$agentId] = $extension; }}
                public function readLastSnapshot() {{ return ['agents' => [], 'calls' => []]; }}
                public function writeLastSnapshot($snapshot) {{ return null; }}
            }}

            $runtime = new FakeRuntimeForServiceTest();
            $store = new FakeStoreForServiceTest();
            $service = new CallCenterService($runtime, $store);

            $status = $service->handle('agents.status', ['agentId' => '1'], []);
            $setExtension = $service->handle('agents.set_extension', ['agentId' => 'Agent-1'], ['extension' => '1001']);
            $login = $service->handle('agents.login', ['agentId' => '1'], []);
            $originate = $service->handle('calls.originate', [], ['agent_id' => '1', 'phone' => '71986322652']);
            $hangup = $service->handle('calls.hangup', ['callId' => 'call-1'], ['agent_id' => '1']);

            echo json_encode([
                'status' => $status,
                'setExtension' => $setExtension,
                'login' => $login,
                'originate' => $originate,
                'hangup' => $hangup,
                'runtime_calls' => $runtime->calls,
                'extensions' => $store->extensions,
            ], JSON_UNESCAPED_SLASHES);
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"]["agent"]["agent_id"], "Agent/1")
        self.assertEqual(payload["status"]["agent"]["route_key"], "1")
        self.assertEqual(payload["setExtension"]["agent_id"], "Agent/1")
        self.assertEqual(payload["setExtension"]["route_key"], "1")
        self.assertEqual(payload["extensions"]["Agent/1"], "1001")
        self.assertEqual(payload["login"]["agent_id"], "Agent/1")
        self.assertEqual(payload["login"]["extension"], "1001")
        self.assertEqual(payload["originate"]["agent_id"], "Agent/1")
        self.assertEqual(payload["originate"]["extension"], "1001")
        self.assertEqual(payload["hangup"]["agent_id"], "Agent/1")
        self.assertEqual(
            [call["method"] for call in payload["runtime_calls"]],
            ["loginAgent", "originateCall", "hangupAgentCall"],
        )
        self.assertEqual(payload["runtime_calls"][1]["extension"], "1001")

if __name__ == "__main__":
    unittest.main()
