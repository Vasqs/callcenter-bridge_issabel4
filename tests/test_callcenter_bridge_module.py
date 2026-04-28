import json
import tempfile
import subprocess
import textwrap
import unittest
from datetime import datetime, timezone
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
            MODULE_ROOT / "deploy" / "systemd" / "callcenter-bridge-relay.service",
            MODULE_ROOT / "deploy" / "systemd" / "callcenter-bridge-relay.timer",
            MODULE_ROOT / "deploy" / "systemd" / "callcenter-bridge-relay.sh.example",
            MODULE_ROOT / "scripts" / "install-callcenter-bridge-relay.sh",
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
                ['GET', '/v1/agents/Agent%2F1/campaign-context'],
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
                "agents.campaign_context",
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
        self.assertEqual(resolved[12]["params"]["callId"], "call-001")

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

    def test_callcenter_bridge_relay_installer_contract_exists(self) -> None:
        install_script = MODULE_ROOT / "scripts" / "install-callcenter-bridge-relay.sh"
        service_unit = MODULE_ROOT / "deploy" / "systemd" / "callcenter-bridge-relay.service"
        timer_unit = MODULE_ROOT / "deploy" / "systemd" / "callcenter-bridge-relay.timer"
        relay_script_example = MODULE_ROOT / "deploy" / "systemd" / "callcenter-bridge-relay.sh.example"

        install_text = install_script.read_text()
        service_text = service_unit.read_text()
        timer_text = timer_unit.read_text()
        relay_text = relay_script_example.read_text()

        self.assertIn("callcenter-bridge-relay.service", install_text)
        self.assertIn("callcenter-bridge-relay.timer", install_text)
        self.assertIn("callcenter-bridge-relay.sh", install_text)
        self.assertIn("systemctl enable --now callcenter-bridge-relay.timer", install_text)

        self.assertIn("ExecStart=/usr/local/bin/callcenter-bridge-relay.sh", service_text)
        self.assertIn("OnUnitActiveSec=1s", timer_text)
        self.assertIn("callcenter-bridge-relay.service", timer_text)
        self.assertIn("CALLCENTER_BRIDGE_MODULE_ENV_PATH", relay_text)
        self.assertIn("CALLCENTER_BRIDGE_LOCAL_RELAY_URL", relay_text)
        self.assertIn("/modules/callcenter_bridge/api.php/v1/events/relay", relay_text)
        self.assertIn("CALLCENTER_BRIDGE_API_TOKEN", relay_text)

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
                public $pendingLogins = [];
                public function readAgentExtensions() {{ return $this->extensions; }}
                public function setAgentExtension($agentId, $extension) {{ $this->extensions[$agentId] = $extension; }}
                public function getAgentExtension($routeKey, $agentId = null) {{
                    if ($routeKey !== null && isset($this->extensions['route:' . $routeKey])) {{
                        return $this->extensions['route:' . $routeKey];
                    }}
                    return $agentId !== null && isset($this->extensions[$agentId]) ? $this->extensions[$agentId] : null;
                }}
                public function persistAgentExtension($routeKey, $agentId, $extension) {{
                    if ($routeKey !== null && $routeKey !== '') {{
                        $this->extensions['route:' . $routeKey] = $extension;
                    }}
                    if ($agentId !== null && $agentId !== '') {{
                        $this->extensions[$agentId] = $extension;
                    }}
                }}
                public function readLastSnapshot() {{ return $this->lastSnapshot; }}
                public function writeLastSnapshot($snapshot) {{ $this->lastSnapshot = $snapshot; }}
                public function readFocusedCallIds() {{ return $this->focusedCalls; }}
                public function writeFocusedCallIds($focusedCalls) {{ $this->focusedCalls = $focusedCalls; }}
                public function readPendingLogins() {{ return $this->pendingLogins; }}
                public function persistPendingLogin($routeKey, $agentId, $extension) {{
                    $payload = [
                        'route_key' => $routeKey,
                        'agent_id' => $agentId,
                        'extension' => $extension,
                        'started_at' => gmdate('c'),
                    ];
                    if ($routeKey !== null && $routeKey !== '') {{
                        $this->pendingLogins['route:' . $routeKey] = $payload;
                    }}
                    if ($agentId !== null && $agentId !== '') {{
                        $this->pendingLogins[$agentId] = $payload;
                    }}
                }}
                public function getPendingLogin($routeKey, $agentId = null) {{
                    if ($routeKey !== null && isset($this->pendingLogins['route:' . $routeKey])) {{
                        return $this->pendingLogins['route:' . $routeKey];
                    }}
                    return $agentId !== null && isset($this->pendingLogins[$agentId]) ? $this->pendingLogins[$agentId] : null;
                }}
                public function clearPendingLogin($routeKey, $agentId = null) {{
                    if ($routeKey !== null && $routeKey !== '') {{
                        unset($this->pendingLogins['route:' . $routeKey]);
                    }}
                    if ($agentId !== null && $agentId !== '') {{
                        unset($this->pendingLogins[$agentId]);
                    }}
                }}
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
                public $pendingLogins = [];
                public function readAgentExtensions() {{ return $this->extensions; }}
                public function setAgentExtension($agentId, $extension) {{ $this->extensions[$agentId] = $extension; }}
                public function getAgentExtension($routeKey, $agentId = null) {{
                    if ($routeKey !== null && isset($this->extensions['route:' . $routeKey])) {{
                        return $this->extensions['route:' . $routeKey];
                    }}
                    return $agentId !== null && isset($this->extensions[$agentId]) ? $this->extensions[$agentId] : null;
                }}
                public function persistAgentExtension($routeKey, $agentId, $extension) {{
                    if ($routeKey !== null && $routeKey !== '') {{
                        $this->extensions['route:' . $routeKey] = $extension;
                    }}
                    if ($agentId !== null && $agentId !== '') {{
                        $this->extensions[$agentId] = $extension;
                    }}
                }}
                public function readLastSnapshot() {{ return ['agents' => [], 'calls' => []]; }}
                public function writeLastSnapshot($snapshot) {{ return null; }}
                public function readPendingLogins() {{ return $this->pendingLogins; }}
                public function persistPendingLogin($routeKey, $agentId, $extension) {{
                    $payload = [
                        'route_key' => $routeKey,
                        'agent_id' => $agentId,
                        'extension' => $extension,
                        'started_at' => gmdate('c'),
                    ];
                    if ($routeKey !== null && $routeKey !== '') {{
                        $this->pendingLogins['route:' . $routeKey] = $payload;
                    }}
                    if ($agentId !== null && $agentId !== '') {{
                        $this->pendingLogins[$agentId] = $payload;
                    }}
                }}
                public function getPendingLogin($routeKey, $agentId = null) {{
                    if ($routeKey !== null && isset($this->pendingLogins['route:' . $routeKey])) {{
                        return $this->pendingLogins['route:' . $routeKey];
                    }}
                    return $agentId !== null && isset($this->pendingLogins[$agentId]) ? $this->pendingLogins[$agentId] : null;
                }}
                public function clearPendingLogin($routeKey, $agentId = null) {{
                    if ($routeKey !== null && $routeKey !== '') {{
                        unset($this->pendingLogins['route:' . $routeKey]);
                    }}
                    if ($agentId !== null && $agentId !== '') {{
                        unset($this->pendingLogins[$agentId]);
                    }}
                }}
            }}

            $runtime = new FakeRuntimeForServiceTest();
            $store = new FakeStoreForServiceTest();
            $service = new CallCenterService($runtime, $store);

            $setExtension = $service->handle('agents.set_extension', ['agentId' => 'Agent-1'], ['extension' => '1001']);
            $status = $service->handle('agents.status', ['agentId' => '1'], []);
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
        self.assertEqual(payload["extensions"]["route:1"], "1001")
        self.assertEqual(payload["extensions"]["Agent/1"], "1001")
        self.assertEqual(payload["login"]["agent_id"], "Agent/1")
        self.assertEqual(payload["login"]["extension"], "1001")
        self.assertEqual(payload["originate"]["agent_id"], "Agent/1")
        self.assertEqual(payload["originate"]["extension"], "1001")
        self.assertEqual(payload["hangup"]["agent_id"], "Agent/1")
        self.assertEqual(payload["status"]["agent"]["extension"], "1001")
        self.assertEqual(
            [call["method"] for call in payload["runtime_calls"]],
            ["loginAgent", "originateCall", "hangupAgentCall"],
        )
        self.assertEqual(payload["runtime_calls"][1]["extension"], "1001")

    def test_callcenter_bridge_runtime_prefers_agent_number_for_plain_numeric_refs(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterRuntime.php")!r};

            class FakeRuntimeForNumericPreferenceTest extends CallCenterRuntime {{
                public function __construct() {{}}

                public function findAgentRecord($sql, array $params = array()) {{
                    if (strpos($sql, 'WHERE number = :number') !== false && isset($params[':number']) && $params[':number'] === '34') {{
                        return [
                            'agent_id' => 'Agent/34',
                            'route_key' => '17',
                            'id' => 17,
                            'type' => 'Agent',
                            'number' => '34',
                            'name' => 'Agent 34',
                            'enabled' => true,
                            'estatus' => 'A',
                        ];
                    }}

                    if (strpos($sql, 'WHERE id = :id') !== false && isset($params[':id']) && (int) $params[':id'] === 34) {{
                        return [
                            'agent_id' => 'Agent/19',
                            'route_key' => '34',
                            'id' => 34,
                            'type' => 'Agent',
                            'number' => '19',
                            'name' => 'Agent 19',
                            'enabled' => true,
                            'estatus' => 'A',
                        ];
                    }}

                    return null;
                }}
            }}

            class RuntimeProbe extends FakeRuntimeForNumericPreferenceTest {{
                public function findAgentRecord($sql, array $params = array()) {{
                    return parent::findAgentRecord($sql, $params);
                }}
            }}

            $runtime = new RuntimeProbe();
            $plain = $runtime->resolveAgentReference('34');
            $explicit = $runtime->resolveAgentReference('route:34');

            echo json_encode([
                'plain' => $plain,
                'explicit' => $explicit,
            ], JSON_UNESCAPED_SLASHES);
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plain"]["number"], "34")
        self.assertEqual(payload["plain"]["id"], 17)
        self.assertEqual(payload["explicit"]["number"], "19")
        self.assertEqual(payload["explicit"]["id"], 34)

    def test_callcenter_bridge_service_prefers_route_lookup_for_plain_numeric_agent_actions(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterRuntime.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterStateStore.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterService.php")!r};

            class FakeRuntimeForNumericServiceResolutionTest extends CallCenterRuntime {{
                public $resolvedRefs = [];
                public $loginCalls = [];

                public function __construct() {{}}

                public function resolveAgentReference($reference) {{
                    $this->resolvedRefs[] = $reference;

                    if ($reference === 'route:34') {{
                        return [
                            'agent_id' => 'Agent/19',
                            'route_key' => '34',
                            'id' => 34,
                            'type' => 'Agent',
                            'number' => '19',
                        ];
                    }}

                    if ($reference === '34') {{
                        return [
                            'agent_id' => 'Agent/34',
                            'route_key' => '17',
                            'id' => 17,
                            'type' => 'Agent',
                            'number' => '34',
                        ];
                    }}

                    throw new RuntimeException('Agent not found in call_center.agent');
                }}

                public function loginAgent($agentId, $extension) {{
                    $this->loginCalls[] = ['agent_id' => $agentId, 'extension' => $extension];
                    return ['ok' => true];
                }}
            }}

            class FakeStoreForNumericServiceResolutionTest extends CallCenterStateStore {{
                public function __construct() {{}}
                public function persistAgentExtension($routeKey, $agentId, $extension) {{ return null; }}
                public function persistPendingLogin($routeKey, $agentId, $extension) {{ return null; }}
                public function getAgentExtension($routeKey, $agentId = null) {{ return null; }}
            }}

            $runtime = new FakeRuntimeForNumericServiceResolutionTest();
            $service = new CallCenterService($runtime, new FakeStoreForNumericServiceResolutionTest());
            $response = $service->handle('agents.login', ['agentId' => '34'], ['extension' => '1001']);

            echo json_encode([
                'response' => $response,
                'resolved_refs' => $runtime->resolvedRefs,
                'login_calls' => $runtime->loginCalls,
            ], JSON_UNESCAPED_SLASHES);
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        payload = json.loads(proc.stdout)
        self.assertTrue(payload["response"]["success"])
        self.assertEqual(payload["response"]["agent_id"], "Agent/19")
        self.assertEqual(payload["response"]["route_key"], "34")
        self.assertEqual(payload["resolved_refs"], ["route:34"])
        self.assertEqual(payload["login_calls"][0]["agent_id"], "Agent/19")

    def test_callcenter_bridge_service_falls_back_to_plain_numeric_when_route_lookup_is_missing(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterRuntime.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterStateStore.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterService.php")!r};

            class FakeRuntimeForNumericServiceFallbackTest extends CallCenterRuntime {{
                public $resolvedRefs = [];

                public function __construct() {{}}

                public function resolveAgentReference($reference) {{
                    $this->resolvedRefs[] = $reference;

                    if ($reference === 'route:2001') {{
                        throw new RuntimeException('Agent not found in call_center.agent');
                    }}

                    if ($reference === '2001') {{
                        return [
                            'agent_id' => 'Agent/2001',
                            'route_key' => '88',
                            'id' => 88,
                            'type' => 'Agent',
                            'number' => '2001',
                        ];
                    }}

                    throw new RuntimeException('Agent not found in call_center.agent');
                }}

                public function getAgentStatus($agentId) {{
                    return [
                        'agent_id' => $agentId,
                        'status' => 'offline',
                        'raw_status' => ['status' => 'offline'],
                        'queues' => [],
                    ];
                }}
            }}

            class FakeStoreForNumericServiceFallbackTest extends CallCenterStateStore {{
                public function __construct() {{}}
                public function getAgentExtension($routeKey, $agentId = null) {{ return null; }}
                public function getPendingLogin($routeKey, $agentId = null) {{ return null; }}
            }}

            $runtime = new FakeRuntimeForNumericServiceFallbackTest();
            $service = new CallCenterService($runtime, new FakeStoreForNumericServiceFallbackTest());
            $response = $service->handle('agents.status', ['agentId' => '2001'], []);

            echo json_encode([
                'response' => $response,
                'resolved_refs' => $runtime->resolvedRefs,
            ], JSON_UNESCAPED_SLASHES);
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        payload = json.loads(proc.stdout)
        self.assertTrue(payload["response"]["success"])
        self.assertEqual(payload["response"]["agent"]["agent_id"], "Agent/2001")
        self.assertEqual(payload["resolved_refs"], ["route:2001", "2001"])

    def test_callcenter_bridge_service_exposes_pending_login_as_logging(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterRuntime.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterStateStore.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterSnapshotDiffer.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterService.php")!r};

            class FakeRuntimeForPendingLoginTest extends CallCenterRuntime {{
                public function __construct() {{}}
                public function resolveAgentReference($reference) {{
                    return ['agent_id' => 'Agent/90', 'route_key' => '90'];
                }}
                public function getAgentStatus($agentId) {{
                    return [
                        'agent_id' => $agentId,
                        'status' => 'offline',
                        'raw_status' => ['status' => 'offline'],
                        'queues' => [],
                    ];
                }}
            }}

            class FakeStoreForPendingLoginTest extends CallCenterStateStore {{
                public function __construct() {{}}
                public $pendingLogins = [
                    'route:90' => [
                        'route_key' => '90',
                        'agent_id' => 'Agent/90',
                        'extension' => '1001',
                        'started_at' => '{datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}',
                    ],
                ];
                public function readPendingLogins() {{ return $this->pendingLogins; }}
                public function persistPendingLogin($routeKey, $agentId, $extension) {{ return null; }}
                public function getPendingLogin($routeKey, $agentId = null) {{
                    if ($routeKey !== null && isset($this->pendingLogins['route:' . $routeKey])) {{
                        return $this->pendingLogins['route:' . $routeKey];
                    }}
                    return $agentId !== null && isset($this->pendingLogins[$agentId]) ? $this->pendingLogins[$agentId] : null;
                }}
                public function clearPendingLogin($routeKey, $agentId = null) {{
                    if ($routeKey !== null && $routeKey !== '') {{
                        unset($this->pendingLogins['route:' . $routeKey]);
                    }}
                    if ($agentId !== null && $agentId !== '') {{
                        unset($this->pendingLogins[$agentId]);
                    }}
                }}
            }}

            $service = new CallCenterService(new FakeRuntimeForPendingLoginTest(), new FakeStoreForPendingLoginTest());
            $response = $service->handle('agents.status', ['agentId' => '90'], []);

            echo json_encode($response, JSON_UNESCAPED_SLASHES);
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        payload = json.loads(proc.stdout)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["agent"]["status"], "logging")
        self.assertTrue(payload["agent"]["raw_status"]["bridge_pending_login"])

    def test_callcenter_bridge_service_returns_structured_campaign_context(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterRuntime.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterStateStore.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterSnapshotDiffer.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterService.php")!r};

            class FakeRuntimeForCampaignContextTest extends CallCenterRuntime {{
                public function __construct() {{}}
                public function resolveAgentReference($reference) {{
                    return ['agent_id' => 'Agent/99', 'route_key' => '99'];
                }}
                public function getAgentCampaignContext($agentId, array $options = array()) {{
                    return [
                        'agent_id' => $agentId,
                        'extension' => '1001',
                        'call_id' => 'call-ctx-001',
                        'campaign_id' => '2',
                        'direction' => 'outbound',
                        'phone' => '71999998888',
                        'identifier_type' => $options['identifier_type'],
                        'identifier_value' => '12345678909',
                        'source' => 'issabel-callcenter-bridge',
                        'resolved_from' => 'call_attribute',
                    ];
                }}
            }}

            class FakeStoreForCampaignContextTest extends CallCenterStateStore {{
                public function __construct() {{}}
                public function readPendingLogins() {{ return []; }}
                public function persistPendingLogin($routeKey, $agentId, $extension) {{ return null; }}
                public function getPendingLogin($routeKey, $agentId = null) {{ return null; }}
                public function clearPendingLogin($routeKey, $agentId = null) {{ return null; }}
            }}

            $service = new CallCenterService(new FakeRuntimeForCampaignContextTest(), new FakeStoreForCampaignContextTest());
            $response = $service->handle('agents.campaign_context', ['agentId' => '99'], [
                'identifier_type' => 'cpf',
                'attribute_column' => 2,
            ]);

            echo json_encode($response, JSON_UNESCAPED_SLASHES);
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        payload = json.loads(proc.stdout)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["agent_id"], "Agent/99")
        self.assertEqual(payload["context"]["call_id"], "call-ctx-001")
        self.assertEqual(payload["context"]["identifier_type"], "cpf")
        self.assertEqual(payload["context"]["identifier_value"], "12345678909")

    def test_callcenter_bridge_relay_enriches_focus_events_with_campaign_context(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterRuntime.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterStateStore.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterSnapshotDiffer.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterService.php")!r};

            class FakeRuntimeForRelayCampaignTest extends CallCenterRuntime {{
                public function __construct() {{}}
                public function buildSnapshot($store) {{ return ['agents' => [], 'calls' => []]; }}
                public function getAgentCampaignContext($agentId, array $options = array()) {{
                    return [
                        'agent_id' => $agentId,
                        'extension' => '1001',
                        'call_id' => 'call-focus-001',
                        'campaign_id' => '2',
                        'direction' => 'outbound',
                        'phone' => '71999998888',
                        'identifier_type' => 'cpf',
                        'identifier_value' => '12345678909',
                        'source' => 'issabel-callcenter-bridge',
                        'resolved_from' => 'call_attribute',
                    ];
                }}
            }}

            class FakeStoreForRelayCampaignTest extends CallCenterStateStore {{
                public function __construct() {{}}
                public function readLastSnapshot() {{ return ['agents' => [], 'calls' => []]; }}
                public function writeLastSnapshot($snapshot) {{ return null; }}
                public function readFocusedCallIds() {{ return []; }}
                public function writeFocusedCallIds($snapshot) {{ return null; }}
                public function readPendingLogins() {{ return []; }}
                public function persistPendingLogin($routeKey, $agentId, $extension) {{ return null; }}
                public function getPendingLogin($routeKey, $agentId = null) {{ return null; }}
                public function clearPendingLogin($routeKey, $agentId = null) {{ return null; }}
            }}

            class FakeDifferForRelayCampaignTest extends CallCenterSnapshotDiffer {{
                public function __construct() {{}}
                public function diff($previous, $current, $companyKey, $previousFocusedCalls = array(), &$nextFocusedCalls = null) {{
                    return [[
                        'event_id' => 'evt-focus-001',
                        'event_type' => 'call.focus',
                        'event' => 'call.focus',
                        'occurred_at' => '2026-04-22T12:00:00Z',
                        'source' => 'issabel-callcenter',
                        'company_key' => $companyKey,
                        'agent_id' => 'Agent/99',
                        'extension' => '1001',
                        'call_id' => 'call-focus-001',
                        'queue' => 'sales',
                        'status' => 'answered',
                        'state' => 'answered',
                        'direction' => 'outbound',
                        'phone' => '71999998888',
                        'remote_number' => '71999998888',
                        'mode' => 'agent-fallback',
                        'payload' => [],
                    ]];
                }}
            }}

            $service = new CallCenterService(
                new FakeRuntimeForRelayCampaignTest(),
                new FakeStoreForRelayCampaignTest(),
                new FakeDifferForRelayCampaignTest()
            );

            $response = $service->handle('events.relay', [], [
                'company_key' => 'demo',
                'identifier_type' => 'cpf',
                'attribute_column' => 2,
            ]);

            echo json_encode($response, JSON_UNESCAPED_SLASHES);
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        payload = json.loads(proc.stdout)
        event = payload["events"][0]
        self.assertEqual(event["event_type"], "call.focus")
        self.assertEqual(event["campaign_context"]["identifier_type"], "cpf")
        self.assertEqual(event["payload"]["campaign_context"]["identifier_value"], "12345678909")

    def test_callcenter_bridge_relay_synthesizes_focus_event_from_campaign_context_when_diff_is_empty(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterRuntime.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterStateStore.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterSnapshotDiffer.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterService.php")!r};

            class FakeRuntimeForSyntheticFocusTest extends CallCenterRuntime {{
                public function __construct() {{}}
                public function buildSnapshot($store) {{
                    return [
                        'agents' => [
                            'Agent/1' => ['status' => 'oncall', 'extension' => '1001'],
                        ],
                        'calls' => [],
                    ];
                }}
                public function getAgentCampaignContext($agentId, array $options = array()) {{
                    return [
                        'agent_id' => $agentId,
                        'extension' => '1001',
                        'call_id' => 'eccp-focus-001',
                        'campaign_id' => '2',
                        'direction' => 'outbound',
                        'phone' => '71999998888',
                        'identifier_type' => 'cpf',
                        'identifier_value' => '12345678909',
                        'source' => 'issabel-callcenter-bridge',
                        'resolved_from' => 'call_attribute',
                    ];
                }}
            }}

            class FakeStoreForSyntheticFocusTest extends CallCenterStateStore {{
                public function __construct() {{}}
                public function readLastSnapshot() {{ return ['agents' => [], 'calls' => []]; }}
                public function writeLastSnapshot($snapshot) {{ return null; }}
                public function readFocusedCallIds() {{ return []; }}
                public function writeFocusedCallIds($snapshot) {{ return null; }}
                public function readPendingLogins() {{ return []; }}
                public function persistPendingLogin($routeKey, $agentId, $extension) {{ return null; }}
                public function getPendingLogin($routeKey, $agentId = null) {{ return null; }}
                public function clearPendingLogin($routeKey, $agentId = null) {{ return null; }}
            }}

            class FakeDifferForSyntheticFocusTest extends CallCenterSnapshotDiffer {{
                public function __construct() {{}}
                public function diff($previous, $current, $companyKey, $previousFocusedCalls = array(), &$nextFocusedCalls = null) {{
                    return [];
                }}
            }}

            $service = new CallCenterService(
                new FakeRuntimeForSyntheticFocusTest(),
                new FakeStoreForSyntheticFocusTest(),
                new FakeDifferForSyntheticFocusTest()
            );

            $response = $service->handle('events.relay', [], [
                'company_key' => 'demo',
                'identifier_type' => 'cpf',
                'attribute_column' => 2,
            ]);

            echo json_encode($response, JSON_UNESCAPED_SLASHES);
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        payload = json.loads(proc.stdout)
        self.assertEqual(len(payload["events"]), 1)
        event = payload["events"][0]
        self.assertEqual(event["event_type"], "call.focus")
        self.assertEqual(event["agent_id"], "Agent/1")
        self.assertEqual(event["call_id"], "eccp-focus-001")
        self.assertEqual(event["phone"], "71999998888")
        self.assertEqual(event["status"], "answered")
        self.assertEqual(event["campaign_context"]["identifier_value"], "12345678909")
        self.assertEqual(event["payload"]["campaign_context"]["call_id"], "eccp-focus-001")

    def test_callcenter_bridge_relay_suppresses_stale_hangup_when_agent_remains_oncall(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterRuntime.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterStateStore.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterSnapshotDiffer.php")!r};
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterService.php")!r};

            class FakeRuntimeForStaleHangupSuppressionTest extends CallCenterRuntime {{
                public function __construct() {{}}
                public function buildSnapshot($store) {{
                    return [
                        'agents' => [
                            'Agent/1' => ['status' => 'oncall', 'extension' => '1001'],
                        ],
                        'calls' => [],
                    ];
                }}
                public function getAgentCampaignContext($agentId, array $options = array()) {{
                    return [
                        'agent_id' => $agentId,
                        'extension' => '1001',
                        'call_id' => 'eccp-focus-001',
                        'campaign_id' => '2',
                        'direction' => 'outbound',
                        'phone' => '71999998888',
                        'identifier_type' => 'cpf',
                        'identifier_value' => '12345678909',
                        'source' => 'issabel-callcenter-bridge',
                        'resolved_from' => 'call_attribute',
                    ];
                }}
            }}

            class FakeStoreForStaleHangupSuppressionTest extends CallCenterStateStore {{
                public function __construct() {{}}
                public function readLastSnapshot() {{
                    return [
                        'agents' => [
                            'Agent/1' => ['status' => 'oncall', 'extension' => '1001'],
                        ],
                        'calls' => [
                            'old-call-id' => [
                                'status' => 'answered',
                                'agent_id' => 'Agent/1',
                                'phone' => '71999998888',
                                'direction' => 'outbound',
                            ],
                        ],
                    ];
                }}
                public function writeLastSnapshot($snapshot) {{ return null; }}
                public function readFocusedCallIds() {{ return ['Agent/1' => 'old-call-id']; }}
                public function writeFocusedCallIds($snapshot) {{ return null; }}
                public function readPendingLogins() {{ return []; }}
                public function persistPendingLogin($routeKey, $agentId, $extension) {{ return null; }}
                public function getPendingLogin($routeKey, $agentId = null) {{ return null; }}
                public function clearPendingLogin($routeKey, $agentId = null) {{ return null; }}
            }}

            class FakeDifferForStaleHangupSuppressionTest extends CallCenterSnapshotDiffer {{
                public function __construct() {{}}
                public function diff($previous, $current, $companyKey, $previousFocusedCalls = array(), &$nextFocusedCalls = null) {{
                    return [[
                        'event_id' => 'evt-hangup-001',
                        'event_type' => 'call.hangup',
                        'event' => 'call.hangup',
                        'occurred_at' => '2026-04-28T12:00:00Z',
                        'source' => 'issabel-callcenter',
                        'company_key' => $companyKey,
                        'agent_id' => 'Agent/1',
                        'extension' => '1001',
                        'call_id' => 'old-call-id',
                        'queue' => '500',
                        'status' => 'hangup',
                        'state' => 'hangup',
                        'direction' => 'outbound',
                        'phone' => '71999998888',
                        'remote_number' => '71999998888',
                        'mode' => 'agent-fallback',
                        'payload' => [],
                    ]];
                }}
            }}

            $service = new CallCenterService(
                new FakeRuntimeForStaleHangupSuppressionTest(),
                new FakeStoreForStaleHangupSuppressionTest(),
                new FakeDifferForStaleHangupSuppressionTest()
            );

            $response = $service->handle('events.relay', [], [
                'company_key' => 'demo',
                'identifier_type' => 'cpf',
                'attribute_column' => 2,
            ]);

            echo json_encode($response, JSON_UNESCAPED_SLASHES);
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        payload = json.loads(proc.stdout)
        event_types = [event["event_type"] for event in payload["events"]]
        self.assertEqual(event_types, ["call.focus"])
        self.assertEqual(payload["events"][0]["call_id"], "eccp-focus-001")

    def test_callcenter_bridge_runtime_uses_eccp_callinfo_when_current_calls_is_empty(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterRuntime.php")!r};

            class FakeRuntimeForEccpActiveCallsTest extends CallCenterRuntime {{
                public function __construct() {{}}

                protected function query($sql) {{
                    if (strpos($sql, 'FROM agent ORDER BY number ASC') !== false) {{
                        return [[
                            'id' => 1,
                            'type' => 'Agent',
                            'number' => '1',
                            'name' => 'Agent 1',
                            'estatus' => 'A',
                        ]];
                    }}

                    if (strpos($sql, 'FROM current_calls') !== false) {{
                        return [];
                    }}

                    if (strpos($sql, 'FROM current_call_entry') !== false) {{
                        return [];
                    }}

                    return [];
                }}

                protected function queryPrepared($sql, array $params) {{
                    if (strpos($sql, 'FROM calls WHERE id = :id LIMIT 1') !== false) {{
                        return [[
                            'id' => 22774,
                            'campaign_id' => '2',
                            'phone' => '71996028538',
                            'status' => 'Success',
                            'uniqueid' => '1777388719.872',
                        ]];
                    }}

                    return [];
                }}

                protected function safeAgentStatus($agentId) {{
                    return [
                        'status' => 'oncall',
                        'extension' => '1001',
                        'callinfo' => [
                            'calltype' => 'outgoing',
                            'callid' => '22774',
                            'campaign_id' => '2',
                            'queuenumber' => '500',
                            'callnumber' => '71996028538',
                            'callstatus' => 'Success',
                        ],
                    ];
                }}
            }}

            $runtime = new FakeRuntimeForEccpActiveCallsTest();
            echo json_encode($runtime->listActiveCalls(), JSON_UNESCAPED_SLASHES);
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        payload = json.loads(proc.stdout)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["call_id"], "1777388719.872")
        self.assertEqual(payload[0]["agent_id"], "Agent/1")
        self.assertEqual(payload[0]["queue"], "500")
        self.assertEqual(payload[0]["status"], "answered")
        self.assertEqual(payload[0]["phone"], "71996028538")
        self.assertEqual(payload[0]["direction"], "outbound")
        self.assertEqual(payload[0]["extension"], "1001")

    def test_callcenter_bridge_runtime_agent_status_tolerates_missing_eccp_queue_socket(self) -> None:
        script = textwrap.dedent(
            f"""
            <?php
            require_once {str(MODULE_ROOT / "web" / "lib" / "CallCenterRuntime.php")!r};

            class FakeRuntimeForAgentStatusQueueFallbackTest extends CallCenterRuntime {{
                public function __construct() {{}}

                protected function safeAgentStatus($agentId) {{
                    return [
                        'status' => 'oncall',
                        'extension' => '1001',
                    ];
                }}

                protected function safeAgentQueues($agentId) {{
                    return [];
                }}
            }}

            $runtime = new FakeRuntimeForAgentStatusQueueFallbackTest();
            echo json_encode($runtime->getAgentStatus('Agent/1'), JSON_UNESCAPED_SLASHES);
            """
        )

        proc = self.run_php(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        payload = json.loads(proc.stdout)
        self.assertEqual(payload["agent_id"], "Agent/1")
        self.assertEqual(payload["status"], "oncall")
        self.assertEqual(payload["raw_status"]["extension"], "1001")
        self.assertEqual(payload["queues"], [])

if __name__ == "__main__":
    unittest.main()
