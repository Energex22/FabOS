# FabOS 0.16 — Pass 14
## Identity & Account Foundation

Pass 14 begins the web-readiness hardening work without replacing the existing FabOS architecture.

### Added
- Incremental migration 36 for account identity metadata.
- `users.email` for future account login/recovery flows.
- `users.account_type` with the planned `customer`, `employee`, and `administrator` categories.
- `users.updated_at` and `users.last_login_at` placeholders for the upcoming authentication/session layer.
- `customer_accounts` for one-to-one user/customer association.
- `employee_profiles` for department/position metadata separate from authentication.
- `AccountService` for account lookup, account updates, customer linking, employee profiles, and account summaries.
- Regression tests covering account lookup, customer isolation at the association layer, employee profiles, and account-type validation.

### Compatibility
- Existing `users.role` is preserved.
- Existing password hashes are preserved.
- Existing owner/admin/employee/customer role values are mapped to the new account type during migration.
- No existing business service was replaced.
- No API endpoints were added yet; authentication and authorization remain later passes.

### Important implementation note
- The existing migration history contains an older duplicate migration number 31. It is intentionally not renumbered or rewritten in this pass. Migration 36 is appended without changing historical migration IDs.

### Next
Pass 15 should establish the permission/RBAC foundation on top of this account model, while preserving the legacy role field for compatibility.