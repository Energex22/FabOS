# FabOS 0.16 — Pass 16
## Authentication & Sessions

Pass 16 adds provider-independent authentication on top of the existing identity/account and RBAC foundations. The existing users table, account associations, business services, and production architecture remain intact.

### Added
- PBKDF2-HMAC-SHA256 password hashing using the Python standard library.
- Password verification and password replacement through `AuthService`.
- Username or email login.
- Hashed bearer-style session tokens; raw tokens are never stored in the database.
- Session expiration and explicit revocation.
- Revoke-all-sessions for a user.
- `users.last_login_at` updates after successful login.
- Password-reset token creation with expiration and single-use consumption.
- Password reset revokes existing sessions.
- Migration 38 for `auth_sessions` and `password_reset_tokens`.
- Application wiring through `self.auth`.
- Regression tests covering hashing, login, email login, logout, reset, expiration boundaries, and session revocation behavior.

### Compatibility
- Uses only Python standard-library cryptography primitives already available to the supported Python 3.8 environment.
- Existing legacy password hashes remain untouched until a user explicitly changes their password.
- No external authentication provider is required.
- No frontend/API endpoints were introduced yet.
- Existing business and production services remain authoritative.

### Security boundary
`AuthService` owns credentials and sessions. It does not decide business permissions; that remains the responsibility of `PermissionService`. API/session adapters in later passes should authenticate through `AuthService` and authorize through `PermissionService` rather than duplicating either system.

### Verification note
Regression tests were committed, but they have not been executed in this GitHub-only environment. No passing test count is claimed.

### Next
Pass 17 should harden controlled order-state transitions and customer data isolation before exposing the business services through the API boundary.
