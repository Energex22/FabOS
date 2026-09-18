"""Provider-independent authentication and session service for FabOS."""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta


class AuthService:
    """Authenticate existing FabOS users without coupling to a provider."""

    ITERATIONS = 180000
    SALT_BYTES = 16
    TOKEN_BYTES = 32
    SESSION_DAYS = 7
    RESET_HOURS = 1

    def __init__(self, database, accounts):
        self.database = database
        self.accounts = accounts

    def hash_password(self, password):
        if not isinstance(password, str) or len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        salt = os.urandom(self.SALT_BYTES)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, self.ITERATIONS)
        return "pbkdf2_sha256$%d$%s$%s" % (
            self.ITERATIONS,
            salt.hex(),
            digest.hex(),
        )

    def verify_password(self, password, stored_hash):
        if not isinstance(password, str) or not stored_hash:
            return False
        try:
            algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            iterations = int(iterations)
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(digest_hex)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(actual, expected)
        except (TypeError, ValueError):
            return False

    def set_password(self, user_id, password):
        password_hash = self.hash_password(password)
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE users SET password_hash=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (password_hash, user_id),
            )
            if cursor.rowcount != 1:
                raise KeyError("User not found")
            # A password change invalidates every existing session for the account.
            # This keeps direct/admin password changes consistent with the reset flow.
            connection.execute(
                "UPDATE auth_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE user_id=? AND revoked_at IS NULL",
                (user_id,),
            )
            connection.commit()
        return True

    def login(self, identifier, password, ip_address=None, user_agent=None):
        identifier = (identifier or "").strip()
        user = self.accounts.get_by_email(identifier) if "@" in identifier else self.accounts.get_by_username(identifier)
        if not user or not int(user["active"]):
            return None
        if not self.verify_password(password, user["password_hash"]):
            return None
        token = secrets.token_urlsafe(self.TOKEN_BYTES)
        expires_at = datetime.utcnow() + timedelta(days=self.SESSION_DAYS)
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO auth_sessions(id,user_id,token_hash,expires_at,ip_address,user_agent) VALUES(?,?,?,?,?,?)",
                (secrets.token_hex(16), user["id"], self._token_hash(token), expires_at.isoformat(), ip_address, user_agent),
            )
            connection.execute(
                "UPDATE users SET last_login_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (user["id"],),
            )
            connection.commit()
        return {"token": token, "expires_at": expires_at.isoformat(), "user": self.accounts.account_summary(user["id"])}

    def authenticate(self, token):
        if not token:
            return None
        token_hash = self._token_hash(token)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT s.*,u.active FROM auth_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.revoked_at IS NULL",
                (token_hash,),
            ).fetchone()
        if not row or not int(row["active"]):
            return None
        try:
            expires_at = datetime.fromisoformat(row["expires_at"])
        except ValueError:
            return None
        if expires_at <= datetime.utcnow():
            self.revoke(token)
            return None
        return self.accounts.get_user(row["user_id"])

    def logout(self, token):
        return self.revoke(token)

    def revoke(self, token):
        if not token:
            return False
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE auth_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE token_hash=? AND revoked_at IS NULL",
                (self._token_hash(token),),
            )
            connection.commit()
            return cursor.rowcount == 1

    def revoke_user_sessions(self, user_id):
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE auth_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE user_id=? AND revoked_at IS NULL",
                (user_id,),
            )
            connection.commit()
            return cursor.rowcount

    def request_password_reset(self, identifier):
        identifier = (identifier or "").strip()
        user = self.accounts.get_by_email(identifier) if "@" in identifier else self.accounts.get_by_username(identifier)
        if not user or not user["email"] or not int(user["active"]):
            return None
        token = secrets.token_urlsafe(self.TOKEN_BYTES)
        expires_at = datetime.utcnow() + timedelta(hours=self.RESET_HOURS)
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE password_reset_tokens SET used_at=CURRENT_TIMESTAMP WHERE user_id=? AND used_at IS NULL",
                (user["id"],),
            )
            connection.execute(
                "INSERT INTO password_reset_tokens(id,user_id,token_hash,expires_at) VALUES(?,?,?,?)",
                (secrets.token_hex(16), user["id"], self._token_hash(token), expires_at.isoformat()),
            )
            connection.commit()
        return {"token": token, "expires_at": expires_at.isoformat(), "user_id": user["id"]}

    def reset_password(self, token, new_password):
        if not token:
            return False
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM password_reset_tokens WHERE token_hash=? AND used_at IS NULL",
                (self._token_hash(token),),
            ).fetchone()
        if not row:
            return False
        try:
            if datetime.fromisoformat(row["expires_at"]) <= datetime.utcnow():
                return False
        except ValueError:
            return False
        password_hash = self.hash_password(new_password)
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE users SET password_hash=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (password_hash, row["user_id"]),
            )
            connection.execute(
                "UPDATE password_reset_tokens SET used_at=CURRENT_TIMESTAMP WHERE id=?",
                (row["id"],),
            )
            connection.execute(
                "UPDATE auth_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE user_id=? AND revoked_at IS NULL",
                (row["user_id"],),
            )
            connection.commit()
        return True

    @staticmethod
    def _token_hash(token):
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
