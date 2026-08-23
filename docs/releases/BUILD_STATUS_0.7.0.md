# Build Status

Compile exit code: 1

```
*** Error compiling './fabos_desktop/manufacturing_ui.py'...
  File "./fabos_desktop/manufacturing_ui.py", line 24
    fit=stl['width_mm']<=245 and stl['depth_mm']<=245 and stl['height_mm']<=260;canvas.create_text(180,85,text='3D MODEL PREVIEW
                                                                                                               ^
SyntaxError: unterminated string literal (detected at line 24)



```

Tests exit code: 0

```

test_vault_and_gcode (test_alpha07.T.test_vault_and_gcode) ... ok
test_db (test_core.Tests.test_db) ... ok
test_event (test_core.Tests.test_event) ... /mnt/data/WireVault_FabOS_Alpha_0.7.0_Complete/fabos_core/events/bus.py:6: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
  type:str; aggregate_type:str=''; aggregate_id:str=''; payload:dict=field(default_factory=dict); id:str=field(default_factory=lambda:str(uuid.uuid4())); occurred_at:str=field(default_factory=lambda:datetime.utcnow().isoformat()+'Z')
ok
test_match (test_core.Tests.test_match) ... ok
test_default_printer_and_status (test_production.ProductionTests.test_default_printer_and_status) ... ok
test_active_and_history_groups (test_quote_groups.QuoteGroupTests.test_active_and_history_groups) ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.130s

OK

```
