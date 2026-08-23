# Build Status 0.4.0

Compile exit: 1

Tests exit: 0

```

test_db (test_core.Tests.test_db) ... ok
test_event (test_core.Tests.test_event) ... /mnt/data/WireVault_FabOS_Engineering_Package_0.4.0_Customers_Contrast/fabos_core/events/bus.py:6: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
  type:str; aggregate_type:str=''; aggregate_id:str=''; payload:dict=field(default_factory=dict); id:str=field(default_factory=lambda:str(uuid.uuid4())); occurred_at:str=field(default_factory=lambda:datetime.utcnow().isoformat()+'Z')
ok
test_match (test_core.Tests.test_match) ... ok

----------------------------------------------------------------------
Ran 3 tests in 0.031s

OK

```

Customer smoke exit: 0

```
{'products': 100, 'orders': 0, 'queued_jobs': 0, 'printers': 0, 'low_spools': 0}


```
