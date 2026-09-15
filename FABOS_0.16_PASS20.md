# FabOS 0.16 — Pass 20

## Security boundary

Pass 20 adds `SecurityService` as the provider-independent boundary that composes the existing authentication, account, and permission services. It resolves authenticated actors, enforces permissions, and provides customer/order ownership checks for future API adapters.

The existing business services remain the source of truth; this pass does not create a second business-logic layer.

## Order lifecycle hardening

Added `OrderService.set_status_internal()` for trusted in-process automation and safe desktop undo operations. It still validates the existing order transition graph. Interactive mutations continue to require an authenticated actor and `order.manage`.

## System page fixes

The desktop `System -> Activity` and `System -> Logs & Version` pages now use a hardened Pass 20 UI boundary:

- journal/log read failures render as an actionable error row instead of crashing the workspace;
- malformed or partial journal rows are tolerated;
- diagnostics/version failures fall back to safe display values and are logged;
- backup-test and diagnostics-export errors are caught and recorded;
- Activity undo uses the validated trusted transition path instead of bypassing the order lifecycle;
- System pages remain available even when the underlying log/journal data is unavailable.

The existing `system_ui.py` architecture was preserved. The hardening is isolated in `fabos_desktop/system_ui_v20.py` and activated by the package initializer.

## Verification

The Pass 20 commit triggered the existing FabOS GitHub Actions matrix. Python 3.11 completed successfully and Python 3.8 completed successfully on commit `2e2385c87e80c943e8736f9a4e2d0aa285a5bcb4`.
