# Plugin SDK
Export `create_plugin()` returning a `FabOSPlugin`. Plugins use services and events rather than direct SQLite writes, keep network work off the UI thread, expose health state, cleanly stop, and ship reversible/backed-up migrations.
