# Build Status 0.7.2

Compile exit code: 0

```

Spreadsheet runtime warmup failed during python startup
Traceback (most recent call last):
  File "/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/patches/warm_spreadsheet_runtime_on_startup.py", line 26, in warm_spreadsheet_runtime_on_startup
  File "/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/spreadsheet_warmup.py", line 772, in warm_spreadsheet_runtime
  File "/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/rpc/connection.py", line 37, in get_or_create_client
  File "/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/rpc/daemon.py", line 124, in start_daemon
TimeoutError: Timed out waiting for artifact tool daemon socket. Set ARTIFACT_TOOL_RPC_DAEMON_STARTUP_TIMEOUT_S=<seconds> to increase the limit.

```

Test exit code: 0

```

Spreadsheet runtime warmup failed during python startup
Traceback (most recent call last):
  File "/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/patches/warm_spreadsheet_runtime_on_startup.py", line 26, in warm_spreadsheet_runtime_on_startup
  File "/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/spreadsheet_warmup.py", line 772, in warm_spreadsheet_runtime
  File "/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/rpc/connection.py", line 37, in get_or_create_client
  File "/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/rpc/daemon.py", line 124, in start_daemon
TimeoutError: Timed out waiting for artifact tool daemon socket. Set ARTIFACT_TOOL_RPC_DAEMON_STARTUP_TIMEOUT_S=<seconds> to increase the limit.
test_vault_and_gcode (test_alpha07.T.test_vault_and_gcode) ... ok
test_db (test_core.Tests.test_db) ... ok
test_event (test_core.Tests.test_event) ... /mnt/data/WireVault_FabOS_Alpha_0.7.2_Design_Vault_Workspace/fabos_core/events/bus.py:6: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
  type:str; aggregate_type:str=''; aggregate_id:str=''; payload:dict=field(default_factory=dict); id:str=field(default_factory=lambda:str(uuid.uuid4())); occurred_at:str=field(default_factory=lambda:datetime.utcnow().isoformat()+'Z')
ok
test_match (test_core.Tests.test_match) ... ok
test_versions_and_history_methods (test_design_workspace.DesignWorkspaceTests.test_versions_and_history_methods) ... ok
test_default_printer_and_status (test_production.ProductionTests.test_default_printer_and_status) ... ok
test_active_and_history_groups (test_quote_groups.QuoteGroupTests.test_active_and_history_groups) ... ok

----------------------------------------------------------------------
Ran 7 tests in 0.718s

OK

```

The package was compiled and core-tested in the build environment. Windows 7
visual acceptance still needs to be performed on the actual workstation.
