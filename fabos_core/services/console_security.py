"""Local console security for the FabOS operator desktop.

The desktop console is intentionally stricter than the customer/admin HTTP API:
only the designated owner account may unlock it, and Windows Remote Desktop/SSH
sessions are rejected when local-only mode is enabled.
"""

import ctypes
import os
import time


class ConsoleSecurityService:
    """Enforce owner-only, local-console access for the desktop shell."""

    REMOTE_SESSION_METRIC = 0x1000  # SM_REMOTESESSION

    MAX_FAILED_ATTEMPTS = 5
    LOCKOUT_SECONDS = 60

    def __init__(self, auth, accounts, shop_settings=None):
        self.auth = auth
        self.accounts = accounts
        self.shop_settings = shop_settings
        self._failed_attempts = 0
        self._locked_until = 0.0

    @classmethod
    def is_local_session(cls):
        """Return False for Windows RDP or SSH sessions.

        A local-only check can reliably reject Windows Remote Desktop and SSH,
        but it cannot identify every third-party remote-control application.
        """

        if os.name == "nt":
            try:
                if bool(ctypes.windll.user32.GetSystemMetrics(cls.REMOTE_SESSION_METRIC)):
                    return False
            except Exception:
                pass
            session_name = str(os.environ.get("SESSIONNAME") or "").strip().lower()
            if session_name.startswith("rdp-"):
                return False
        if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT"):
            return False
        return True

    def local_only_enabled(self):
        if not self.shop_settings:
            return True
        value = str(self.shop_settings.get("console_local_only", "true")).strip().lower()
        return value not in {"0", "false", "no", "off"}

    def idle_timeout_minutes(self):
        if not self.shop_settings:
            return 15
        try:
            return max(1, min(480, int(float(self.shop_settings.get("console_idle_timeout_minutes", "15")))))
        except (TypeError, ValueError):
            return 15

    def lock_enabled(self):
        if not self.shop_settings:
            return True
        value = str(self.shop_settings.get("console_lock_enabled", "true")).strip().lower()
        return value not in {"0", "false", "no", "off"}

    def authenticate_owner(self, identifier, password):
        now = time.monotonic()
        if now < self._locked_until:
            return None
        if self.local_only_enabled() and not self.is_local_session():
            return None
        identifier = (identifier or "").strip()
        user = (
            self.accounts.get_by_email(identifier)
            if "@" in identifier
            else self.accounts.get_by_username(identifier)
        )
        if not user or not int(user["active"]):
            return None
        if str(user["account_type"] or "").lower() != "administrator":
            return None
        if str(user["role"] or "").lower() != "owner":
            return None
        result = self.auth.login(identifier, password)
        if not result:
            self._failed_attempts += 1
            if self._failed_attempts >= self.MAX_FAILED_ATTEMPTS:
                self._locked_until = time.monotonic() + self.LOCKOUT_SECONDS
                self._failed_attempts = 0
            return None
        self._failed_attempts = 0
        self._locked_until = 0.0
        # Console authentication is intentionally owner-only even if another
        # administrator has otherwise valid FabOS credentials.
        return result

    def revoke(self, token):
        return self.auth.logout(token)
