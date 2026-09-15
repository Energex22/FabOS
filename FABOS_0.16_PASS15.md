# FabOS 0.16 — Pass 15
## RBAC Permission Foundation

Pass 15 continues the existing FabOS architecture and makes the account model usable by a provider-independent authorization layer.

### Added
- `PermissionService` with stable permission keys and default customer/employee/administrator role permissions.
- Incremental migration 37 for `permissions`, `role_permissions`, and `user_permissions` tables.
- Per-user permission overrides with explicit allow/deny values.
- Application wiring for both `AccountService` and `PermissionService`.
- Regression tests for role defaults, invalid permissions, and user-level grant/revoke behavior.

### Compatibility
- The existing `users.role` field remains untouched.
- Existing business and production services remain in place.
- Permission checks are provider-independent and do not assume a web framework or identity provider.
- SQLite/Python 3.8-compatible SQL patterns are used; no newer UPSERT syntax was introduced.
- The historical duplicate migration number 31 remains unchanged.

### Verification status
- Changes are committed to GitHub `main`.
- The repository connector available in this environment does not provide a direct local test runner, so the new tests have been added but not executed here.

### Next
Pass 16 should build the authentication/session foundation on top of the account and permission services, including password verification, login/logout, session revocation, and reset-token boundaries without coupling FabOS to a specific identity provider.
