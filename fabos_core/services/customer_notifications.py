"""Customer transactional notifications (Phase 2 of the FABVEX build plan).

Six customer-facing events create an in-app notification record and attempt
delivery per the customer's channel preference (``email``/``sms``/``both``,
default ``email``):

- quote_sent            -> /quote.html?id={quote_id}
- quote_expiring        -> /quote.html?id={quote_id}        (3 days remaining)
- proof_sent            -> /quote.html?id={quote_id}#proof
- proof_changes_requested -> /quote.html?id={quote_id}#proof  (customer receipt)
- payment_failed        -> /order.html?id={order_id}
- order_shipped         -> /order.html?id={order_id}
- order_cancelled       -> /order.html?id={order_id}

Configuration (shop settings first, environment as fallback; never hardcode keys):

- ``resend_api_key`` shop setting, else ``RESEND_API_KEY`` env var. When
  neither is set, email payloads are logged instead of sent (dev-safe).
- ``resend_from_email`` shop setting, else ``RESEND_FROM_EMAIL`` env var,
  else the ``notification_from_email`` shop setting, then ``shop_email``.
  Without any from address the email channel is recorded as skipped
  (logged, not sent).

Integration secrets live in the SQLite shop_settings table (see the secrets
posture comment in fabos_core/services/shop_settings.py) and are masked at
the API boundary; they are never returned in plaintext by any settings API.

SMS is not wired to a provider yet: when a customer's preference includes
SMS, the SMS payload is logged and the record is marked
``pending_sms_provider`` so a future provider can claim it.

Delivery is durable via a simple outbox: ``notify()`` only writes the
notification record plus the email payload to ``notification_outbox`` inside
its own quick transaction (fast, never raises — a network call never blocks
the triggering flow). The automation reconcile tick drains the outbox
(``drain_outbox``): send via the provider, mark sent/failed with a retry
count, exponential backoff, and a bounded number of attempts.

``notify()`` never raises: a notification must never break the business flow
that triggered it. Emit sites still wrap the call defensively.
"""
import json
import logging
import os
import urllib.request
import urllib.error
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

from fabos_core.services.shop_settings import ShopSettingsService


logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"

EVENT_TYPES = (
    "quote_sent",
    "quote_expiring",
    "proof_sent",
    "proof_changes_requested",
    "payment_failed",
    "order_shipped",
    "order_cancelled",
)

NOTIFICATION_PREFERENCES = ("email", "sms", "both")


def normalize_notification_preference(value):
    """Coerce a raw preference value to one of ``email``/``sms``/``both``."""
    value = str(value or "").strip().lower()
    return value if value in NOTIFICATION_PREFERENCES else "email"


def _money(cents):
    try:
        return "$%.2f" % (int(cents or 0) / 100.0)
    except (TypeError, ValueError):
        return "$0.00"


class NotificationSendError(Exception):
    """The email provider refused or failed to deliver."""


class NotificationProvider(ABC):
    """Email delivery seam. Only transactional email exists for now."""

    name = "base"

    @abstractmethod
    def send_email(self, *, to, subject, text_body, from_email):
        """Attempt delivery; return a receipt dict. Raise on failure."""


class ResendEmailProvider(NotificationProvider):
    """Resend implementation. Key comes from the ``resend_api_key`` shop
    setting first, falling back to the ``RESEND_API_KEY`` env var."""

    name = "resend"

    def __init__(self, api_key=None, api_url=None, timeout=10):
        if api_key is not None:
            self.api_key = api_key
        else:
            self.api_key = os.environ.get("RESEND_API_KEY", "").strip()
        self.api_url = api_url or RESEND_API_URL
        self.timeout = timeout

    def send_email(self, *, to, subject, text_body, from_email):
        if not self.api_key:
            raise NotificationSendError("RESEND_API_KEY is not configured")
        if not to:
            raise NotificationSendError("No recipient email address")
        if not from_email:
            raise NotificationSendError("No from address configured (resend_from_email shop setting or RESEND_FROM_EMAIL env)")
        payload = json.dumps({
            "from": from_email,
            "to": [to] if isinstance(to, str) else list(to),
            "subject": subject,
            "text": text_body,
        }).encode("utf-8")
        request = urllib.request.Request(
            self.api_url,
            data=payload,
            headers={
                "Authorization": "Bearer %s" % self.api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                receipt = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            raise NotificationSendError("Resend HTTP %s: %s" % (exc.code, detail)) from exc
        except Exception as exc:
            raise NotificationSendError("Resend request failed: %s" % exc) from exc
        return {"provider": "resend", "status": "sent", "id": receipt.get("id")}


class LoggingEmailProvider(NotificationProvider):
    """Dev-safe fallback: logs the email payload instead of sending it."""

    name = "log"

    def send_email(self, *, to, subject, text_body, from_email):
        logger.info(
            "notification email (logged, not sent): to=%s from=%s subject=%r body=%r",
            to, from_email, subject, text_body,
        )
        return {"provider": "log", "status": "logged"}


def default_email_provider(shop_settings=None):
    """Resend when an API key is configured, else the log fallback.

    The ``resend_api_key`` shop setting (changeable in the admin settings UI)
    wins; the ``RESEND_API_KEY`` environment variable is the fallback.
    """
    key = ""
    if shop_settings is not None:
        try:
            key = str(shop_settings.get("resend_api_key", "") or "").strip()
        except Exception:
            key = ""
    if not key:
        key = os.environ.get("RESEND_API_KEY", "").strip()
    if key:
        return ResendEmailProvider(api_key=key)
    return LoggingEmailProvider()


class CustomerNotificationService:
    def __init__(self, database, shop_settings=None, provider=None):
        self.database = database
        # Internal emit sites (quotes, payments, fulfillment, ...) construct
        # this service with only a database. Fall back to a DB-backed settings
        # reader so the admin-UI-configured keys apply everywhere, not just on
        # the HTTP paths that pass shop_settings explicitly.
        if shop_settings is None:
            try:
                shop_settings = ShopSettingsService(database)
            except Exception:
                shop_settings = None
        self.shop_settings = shop_settings
        self.provider = provider if provider is not None else default_email_provider(self.shop_settings)
        self._ensure_outbox_schema()

    OUTBOX_TABLE_SQL = """CREATE TABLE IF NOT EXISTS notification_outbox(
        id TEXT PRIMARY KEY,
        notification_id TEXT REFERENCES customer_notifications(id) ON DELETE CASCADE,
        to_email TEXT NOT NULL, subject TEXT NOT NULL, text_body TEXT NOT NULL,
        from_email TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'queued',
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_error TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""

    def _ensure_outbox_schema(self):
        """Idempotent outbox table creation (migration 60 is the durable path
        for existing databases; this covers ad-hoc/test constructions)."""
        try:
            with self.database.connect() as conn:
                conn.execute(self.OUTBOX_TABLE_SQL)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_notification_outbox_drain "
                    "ON notification_outbox(status, next_attempt_at)")
                conn.commit()
        except Exception:
            logger.exception("notification outbox schema ensure failed")

    # -- low-level helpers -------------------------------------------------
    def _row(self, sql, args=()):
        with self.database.connect() as conn:
            return conn.execute(sql, args).fetchone()

    def _customer(self, customer_id):
        if not customer_id:
            return None
        return self._row(
            "SELECT id,name,email,notification_preference FROM customers WHERE id=?",
            (str(customer_id),),
        )

    def _preference(self, customer):
        if not customer:
            return "email"
        try:
            return normalize_notification_preference(customer["notification_preference"])
        except (KeyError, IndexError):
            # Older databases without the migration still behave as email-only.
            return "email"

    def _setting(self, key, default=""):
        if self.shop_settings is None:
            return default
        try:
            return self.shop_settings.get(key, default) or default
        except Exception:
            return default

    def _from_email(self):
        # Documented order (module docstring): resend_from_email setting,
        # then RESEND_FROM_EMAIL env, then the notification_from_email /
        # shop_email settings. Settings win, matching the key posture.
        return str(
            self._setting("resend_from_email", "")
            or os.environ.get("RESEND_FROM_EMAIL", "").strip()
            or self._setting("notification_from_email", "")
            or self._setting("shop_email", "")
        ).strip()

    def _shop_name(self):
        return str(self._setting("shop_name", "") or "FABVEX").strip() or "FABVEX"

    def _absolute_link(self, deep_link):
        """Absolute URL for emails when ``public_base_url`` is configured.

        The in-app record keeps the frontend-relative ``deep_link``; only the
        emailed copy is absolutized. Empty setting (default) = current
        behavior: the relative path is used unchanged.
        """
        path = str(deep_link or "")
        if not path.startswith("/"):
            return path
        base = str(self._setting("public_base_url", "") or "").strip().rstrip("/")
        if not base:
            return path
        return base + path

    # -- the record + dispatch core ----------------------------------------
    def notify(self, event_type, customer_id, *, entity_type, entity_id,
               title, body, deep_link="", dedupe_key=None):
        """Create a notification record and dispatch per channel preference.

        Returns the record id, or ``None`` when the dedupe key already exists
        or the customer cannot be notified. Never raises.
        """
        try:
            if event_type not in EVENT_TYPES:
                logger.warning("unknown notification event_type=%r", event_type)
                return None
            customer = self._customer(customer_id)
            if not customer:
                logger.warning("notification %s skipped: customer %s not found", event_type, customer_id)
                return None
            if dedupe_key:
                existing = self._row(
                    "SELECT id FROM customer_notifications WHERE dedupe_key=?", (dedupe_key,))
                if existing:
                    return None

            preference = self._preference(customer)
            email = str(customer["email"] or "").strip()
            name = str(customer["name"] or "").strip()
            shop_name = self._shop_name()
            subject = "%s: %s" % (shop_name, title)
            text_body = "%s\n\n%s\n\nView: %s\n\n%s" % (
                "Hi %s," % name if name else "Hello,",
                body,
                self._absolute_link(deep_link) if deep_link else "(no link)",
                "You're receiving this because you have a %s account. "
                "Manage these notifications in your account profile." % shop_name,
            )
            channels = {}
            outbox = None  # filled below when an email is queued for the outbox

            if preference in ("email", "both"):
                if not email:
                    channels["email"] = {"status": "skipped", "reason": "no_email_on_file"}
                    logger.info("notification email skipped: customer %s has no email", customer["id"])
                else:
                    from_email = self._from_email()
                    if not from_email and isinstance(self.provider, ResendEmailProvider):
                        channels["email"] = {"status": "skipped", "reason": "no_from_address"}
                        logger.warning(
                            "notification email skipped: no from address configured "
                            "(resend_from_email / RESEND_FROM_EMAIL / notification_from_email)")
                    else:
                        # Durable outbox (final polish): the hook path only
                        # enqueues — fast, never raises, never blocks the
                        # triggering flow on a network call. The automation
                        # reconcile tick drains the outbox via drain_outbox().
                        outbox_id = str(uuid.uuid4())
                        outbox = {
                            "id": outbox_id,
                            "to_email": email,
                            "subject": subject,
                            "text_body": text_body,
                            "from_email": from_email or "FABVEX <noreply@example.invalid>",
                        }
                        channels["email"] = {"status": "queued", "outbox_id": outbox_id}

            if preference in ("sms", "both"):
                sms_payload = {"to": "customer:%s" % customer["id"], "event": event_type,
                               "title": title, "body": body, "deep_link": deep_link}
                logger.info("notification sms (pending provider): %r", sms_payload)
                channels["sms"] = {"status": "pending_sms_provider", "logged": True}

            record_id = str(uuid.uuid4())
            with self.database.connect() as conn:
                try:
                    conn.execute(
                        """INSERT INTO customer_notifications(
                           id,customer_id,event_type,entity_type,entity_id,title,body,
                           deep_link,channels_json,dedupe_key)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (record_id, customer["id"], event_type, entity_type, str(entity_id),
                         title, body, deep_link, json.dumps(channels, sort_keys=True), dedupe_key),
                    )
                    if outbox is not None:
                        # The email payload rides in the same transaction as
                        # the notification record: enqueue is atomic with the
                        # record, still fast, still never raises.
                        conn.execute(
                            """INSERT INTO notification_outbox(
                               id, notification_id, to_email, subject,
                               text_body, from_email)
                               VALUES(?,?,?,?,?,?)""",
                            (outbox["id"], record_id, outbox["to_email"],
                             outbox["subject"], outbox["text_body"],
                             outbox["from_email"]),
                        )
                    conn.commit()
                except Exception as exc:
                    # Lost a dedupe race (UNIQUE on dedupe_key) or any other
                    # insert failure: the notification still fired upstream.
                    # Log loudly: a silent drop here is very hard to debug
                    # (e.g. database-is-locked when called inside another
                    # connection's open write transaction).
                    conn.rollback()
                    logger.warning("customer_notifications insert failed (%s): %s",
                                   event_type, exc)
                    return None
            return record_id
        except Exception:
            logger.exception("notify(%s) failed for customer %s", event_type, customer_id)
            return None

    # -- outbox drain ------------------------------------------------------
    OUTBOX_MAX_ATTEMPTS = 5
    OUTBOX_BATCH_LIMIT = 25

    @staticmethod
    def _outbox_now():
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def drain_outbox(self, limit=OUTBOX_BATCH_LIMIT):
        """Send queued outbox emails via the configured provider.

        Called from the automation reconcile tick (operations_hub), which
        already fires the quote_expiring notification hooks. Bounded and
        failure-isolated: one bad email never blocks the rest, per-email
        failures are recorded with a retry count and exponential backoff,
        and this method never raises.

        Returns ``(sent, failed)`` counts.
        """
        self._recover_stale_sending_claims()
        sent = failed = 0
        try:
            with self.database.connect() as conn:
                rows = conn.execute(
                    """SELECT * FROM notification_outbox
                       WHERE status IN ('queued','failed')
                         AND next_attempt_at <= ?
                         AND attempts < ?
                       ORDER BY created_at ASC LIMIT ?""",
                    (self._outbox_now(), self.OUTBOX_MAX_ATTEMPTS,
                     max(1, int(limit or 1))),
                ).fetchall()
        except Exception:
            logger.exception("notification outbox drain query failed")
            return 0, 0
        for row in rows:
            if self._drain_one(dict(row)):
                sent += 1
            else:
                failed += 1
        return sent, failed

    # How long a 'sending' claim may live before the claiming drain is
    # assumed dead (crashed/killed between the claim and _outbox_done /
    # _outbox_retry). Recovery is deliberately conservative: a normal send
    # finishes in seconds.
    OUTBOX_STALE_CLAIM_MINUTES = 30

    def _recover_stale_sending_claims(self):
        """Re-queue outbox rows orphaned in 'sending' by a dead drain.

        _drain_one claims a row ('sending') before calling the provider. If
        the process dies in that window, no later drain would ever select the
        row again (only 'queued'/'failed' are selected), so the email would
        sit unsent forever. Stale claims go back to 'failed' with a short
        retry delay and one consumed attempt, so a permanently-crashing send
        still dead-letters via OUTBOX_MAX_ATTEMPTS instead of looping
        forever. Never raises.

        At-least-once caveat: if the crash happened after the provider
        accepted the email but before _outbox_done committed, recovery can
        produce one duplicate send. That window is milliseconds wide; the
        alternative is silent permanent loss.
        """
        try:
            with self.database.connect() as conn:
                conn.execute(
                    "UPDATE notification_outbox SET status='failed',"
                    " attempts=attempts+1,"
                    " next_attempt_at=datetime('now','+5 minutes'),"
                    " last_error=substr(COALESCE(last_error,'') ||"
                    " ' [recovered from stale sending claim]',1,500),"
                    " updated_at=CURRENT_TIMESTAMP"
                    " WHERE status='sending'"
                    " AND updated_at < datetime('now','-%d minutes')"
                    " AND attempts < ?"
                    % self.OUTBOX_STALE_CLAIM_MINUTES,
                    (self.OUTBOX_MAX_ATTEMPTS,),
                )
                conn.execute(
                    "UPDATE notification_outbox SET status='dead',"
                    " last_error=substr(COALESCE(last_error,'') ||"
                    " ' [stale sending claim, attempts exhausted]',1,500),"
                    " updated_at=CURRENT_TIMESTAMP"
                    " WHERE status='sending'"
                    " AND updated_at < datetime('now','-%d minutes')"
                    " AND attempts >= ?"
                    % self.OUTBOX_STALE_CLAIM_MINUTES,
                    (self.OUTBOX_MAX_ATTEMPTS,),
                )
                conn.commit()
        except Exception:
            logger.exception("notification outbox stale-claim recovery failed")

    def _drain_one(self, row):
        """Send one outbox row. Never raises; returns True on success."""
        outbox_id = str(row.get("id") or "")
        if not outbox_id:
            return False
        # Claim the row so two concurrent drains (two processes) can't
        # double-send the same email.
        try:
            with self.database.connect() as conn:
                cur = conn.execute(
                    "UPDATE notification_outbox SET status='sending',"
                    " updated_at=CURRENT_TIMESTAMP"
                    " WHERE id=? AND status IN ('queued','failed')",
                    (outbox_id,),
                )
                conn.commit()
                if cur.rowcount != 1:
                    return False
        except Exception:
            logger.exception("notification outbox claim failed for %s", outbox_id)
            return False
        try:
            receipt = self.provider.send_email(
                to=row.get("to_email"), subject=row.get("subject"),
                text_body=row.get("text_body"),
                from_email=row.get("from_email") or "FABVEX <noreply@example.invalid>",
            )
        except NotificationSendError as exc:
            self._outbox_retry(outbox_id, int(row.get("attempts") or 0) + 1,
                               str(exc)[:500])
            return False
        except Exception as exc:  # provider bug: retry later, never lose the row
            logger.exception("notification outbox provider error for %s", outbox_id)
            self._outbox_retry(outbox_id, int(row.get("attempts") or 0) + 1,
                               "unexpected: %s" % exc)
            return False
        self._outbox_done(outbox_id, receipt or {})
        return True
    def _outbox_retry(self, outbox_id, attempts, error):
        try:
            with self.database.connect() as conn:
                if attempts >= self.OUTBOX_MAX_ATTEMPTS:
                    conn.execute(
                        "UPDATE notification_outbox SET status='dead',"
                        " attempts=?, last_error=?, updated_at=CURRENT_TIMESTAMP"
                        " WHERE id=?",
                        (attempts, error, outbox_id),
                    )
                    logger.warning("notification outbox %s dead after %d attempts: %s",
                                   outbox_id, attempts, error)
                else:
                    backoff = min(3600, 30 * (2 ** max(0, attempts - 1)))
                    next_attempt = (datetime.now(timezone.utc)
                                    + timedelta(seconds=backoff)).strftime("%Y-%m-%d %H:%M:%S")
                    conn.execute(
                        "UPDATE notification_outbox SET status='failed',"
                        " attempts=?, next_attempt_at=?, last_error=?,"
                        " updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (attempts, next_attempt, error, outbox_id),
                    )
                conn.commit()
        except Exception:
            logger.exception("notification outbox retry bookkeeping failed for %s", outbox_id)
            return
        extra = {"error": error[:300]}
        if attempts >= self.OUTBOX_MAX_ATTEMPTS:
            extra["attempts"] = attempts
        self._update_notification_channel(
            self._outbox_notification_id(outbox_id), "failed", extra)

    def _outbox_done(self, outbox_id, receipt):
        try:
            with self.database.connect() as conn:
                conn.execute(
                    "UPDATE notification_outbox SET status='sent',"
                    " last_error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (outbox_id,),
                )
                conn.commit()
        except Exception:
            logger.exception("notification outbox sent bookkeeping failed for %s", outbox_id)
        self._update_notification_channel(
            self._outbox_notification_id(outbox_id),
            # Same status semantics as the old synchronous path: the
            # provider's reported status ("logged" for the dev fallback).
            receipt.get("status") or "sent",
            {"provider": receipt.get("provider")})

    def _outbox_notification_id(self, outbox_id):
        try:
            with self.database.connect() as conn:
                row = conn.execute(
                    "SELECT notification_id FROM notification_outbox WHERE id=?",
                    (outbox_id,)).fetchone()
                return str(row["notification_id"]) if row and row["notification_id"] else None
        except Exception:
            return None

    def _update_notification_channel(self, notification_id, channel_status, extra=None):
        """Reflect the drained email outcome on the notification record."""
        if not notification_id:
            return
        try:
            with self.database.connect() as conn:
                row = conn.execute(
                    "SELECT channels_json FROM customer_notifications WHERE id=?",
                    (notification_id,)).fetchone()
                if not row:
                    return
                try:
                    channels = json.loads(row["channels_json"] or "{}")
                except Exception:
                    channels = {}
                email = dict(channels.get("email") or {})
                email["status"] = channel_status
                if extra:
                    email.update(extra)
                channels["email"] = email
                conn.execute(
                    "UPDATE customer_notifications SET channels_json=? WHERE id=?",
                    (json.dumps(channels, sort_keys=True), notification_id))
                conn.commit()
        except Exception:
            logger.exception("failed to update notification channel status for %s",
                             notification_id)

    # -- event builders ----------------------------------------------------
    def notify_quote_sent(self, quote):
        quote = dict(quote or {})
        quote_id = quote.get("id")
        if not quote_id:
            return None
        number = quote.get("quote_number") or quote_id
        body = "Your quote %s for %s is ready for review." % (number, _money(quote.get("total_cents")))
        expires = str(quote.get("expires_at") or "").strip()
        if expires:
            body += " It expires on %s." % expires[:10]
        return self.notify(
            "quote_sent", quote.get("customer_id"),
            entity_type="quote", entity_id=quote_id,
            title="Quote %s is ready" % number,
            body=body,
            deep_link="/quote.html?id=%s" % quote_id,
            dedupe_key="quote_sent:%s" % quote_id,
        )

    def notify_quote_expiring(self, quote):
        quote = dict(quote or {})
        quote_id = quote.get("id")
        if not quote_id:
            return None
        number = quote.get("quote_number") or quote_id
        return self.notify(
            "quote_expiring", quote.get("customer_id"),
            entity_type="quote", entity_id=quote_id,
            title="Quote %s expires in 3 days" % number,
            body="Your quote %s for %s expires on %s. Accept it before then to lock in the price." % (
                number, _money(quote.get("total_cents")), str(quote.get("expires_at") or "")[:10]),
            deep_link="/quote.html?id=%s" % quote_id,
            dedupe_key="quote_expiring_3d:%s" % quote_id,
        )

    def notify_proof_sent(self, proof):
        proof = dict(proof or {})
        proof_id = proof.get("id")
        quote_id = proof.get("quote_id")
        if not proof_id or not quote_id:
            return None
        quote = self._row("SELECT id,quote_number,customer_id FROM quotes WHERE id=?", (quote_id,))
        if not quote:
            return None
        body = "Proof v%s for quote %s is ready for your review." % (
            proof.get("design_version"), quote["quote_number"])
        customer_note = str(proof.get("customer_note") or "").strip()
        if customer_note:
            body += " Note from the design team: %s" % customer_note
        return self.notify(
            "proof_sent", quote["customer_id"],
            entity_type="proof", entity_id=proof_id,
            title="Design proof ready for review",
            body=body,
            deep_link="/quote.html?id=%s#proof" % quote_id,
            dedupe_key="proof_sent:%s" % proof_id,
        )

    def notify_proof_changes_requested(self, proof):
        """Customer receipt: their change request was recorded."""
        proof = dict(proof or {})
        proof_id = proof.get("id")
        quote_id = proof.get("quote_id")
        if not proof_id or not quote_id:
            return None
        quote = self._row("SELECT id,quote_number,customer_id FROM quotes WHERE id=?", (quote_id,))
        if not quote:
            return None
        body = ("We've received your change request on proof v%s for quote %s. "
                "The design team will revise and send a new proof.") % (
                    proof.get("design_version"), quote["quote_number"])
        comment = str(proof.get("customer_comment") or "").strip()
        if comment:
            body += " Your comment: %s" % comment
        return self.notify(
            "proof_changes_requested", quote["customer_id"],
            entity_type="proof", entity_id=proof_id,
            title="Change request received",
            body=body,
            deep_link="/quote.html?id=%s#proof" % quote_id,
            dedupe_key="proof_changes_requested:%s" % proof_id,
        )

    def notify_payment_failed(self, payment, order=None):
        payment = dict(payment or {})
        payment_id = payment.get("id")
        order_id = payment.get("order_id") or (dict(order or {}).get("id"))
        if not payment_id or not order_id:
            return None
        order = self._row("SELECT id,order_number,customer_id FROM orders WHERE id=?", (order_id,))
        if not order:
            return None
        return self.notify(
            "payment_failed", order["customer_id"],
            entity_type="order", entity_id=order_id,
            title="Payment failed for order %s" % order["order_number"],
            body="A payment of %s for order %s failed. Please try again or contact us for help." % (
                _money(payment.get("amount_cents")), order["order_number"]),
            deep_link="/order.html?id=%s" % order_id,
            dedupe_key="payment_failed:%s" % payment_id,
        )

    def notify_order_shipped(self, order, fulfillment=None):
        order = dict(order or {})
        order_id = order.get("id")
        if not order_id:
            return None
        fulfillment = dict(fulfillment or {})
        carrier = str(fulfillment.get("carrier") or "").strip()
        tracking = str(fulfillment.get("tracking_number") or "").strip()
        body = "Your order %s has shipped." % (order.get("order_number") or order_id)
        if carrier or tracking:
            body += " %s" % " ".join(p for p in (
                ("Carrier: %s." % carrier) if carrier else "",
                ("Tracking: %s." % tracking) if tracking else "",
            ) if p)
        return self.notify(
            "order_shipped", order.get("customer_id"),
            entity_type="order", entity_id=order_id,
            title="Order %s has shipped" % (order.get("order_number") or ""),
            body=body.strip(),
            deep_link="/order.html?id=%s" % order_id,
            dedupe_key="order_shipped:%s" % (fulfillment.get("id") or order_id),
        )

    def notify_order_cancelled(self, order, reason="", refund_cents=0, refunded_cents=0):
        order = dict(order or {})
        order_id = order.get("id")
        if not order_id:
            return None
        number = order.get("order_number") or order_id
        parts = ["Your order %s has been cancelled." % number]
        reason = str(reason or "").strip()
        if reason:
            parts.append("Reason: %s" % reason)
        pending = max(0, int(refund_cents or 0) - int(refunded_cents or 0))
        if pending > 0:
            parts.append("A refund of %s will be issued to your original payment method "
                         "(typically 5-10 business days)." % _money(pending))
        if refunded_cents and int(refunded_cents) > 0:
            parts.append("%s has already been refunded." % _money(refunded_cents))
        return self.notify(
            "order_cancelled", order.get("customer_id"),
            entity_type="order", entity_id=order_id,
            title="Order %s cancelled" % number,
            body=" ".join(parts),
            deep_link="/order.html?id=%s" % order_id,
            dedupe_key="order_cancelled:%s" % order_id,
        )

    # -- customer API helpers ----------------------------------------------
    def list_for_customer(self, customer_id, page=1, per_page=25):
        try:
            page = max(1, int(page or 1))
        except (TypeError, ValueError):
            page = 1
        try:
            per_page = min(100, max(1, int(per_page or 25)))
        except (TypeError, ValueError):
            per_page = 25
        offset = (page - 1) * per_page
        with self.database.connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM customer_notifications WHERE customer_id=?",
                (str(customer_id),)).fetchone()[0]
            rows = conn.execute(
                """SELECT id,event_type,entity_type,entity_id,title,body,deep_link,
                          is_read,channels_json,created_at
                   FROM customer_notifications WHERE customer_id=?
                   ORDER BY is_read ASC, created_at DESC, id DESC LIMIT ? OFFSET ?""",
                (str(customer_id), per_page, offset)).fetchall()
        return [dict(r) for r in rows], int(total)

    def unread_count(self, customer_id):
        with self.database.connect() as conn:
            return int(conn.execute(
                "SELECT COUNT(*) FROM customer_notifications WHERE customer_id=? AND is_read=0",
                (str(customer_id),)).fetchone()[0])

    def mark_read(self, customer_id, notification_id):
        with self.database.connect() as conn:
            cur = conn.execute(
                "UPDATE customer_notifications SET is_read=1 WHERE id=? AND customer_id=?",
                (str(notification_id), str(customer_id)))
            conn.commit()
            return cur.rowcount > 0

    def mark_all_read(self, customer_id):
        with self.database.connect() as conn:
            cur = conn.execute(
                "UPDATE customer_notifications SET is_read=1 WHERE customer_id=? AND is_read=0",
                (str(customer_id),))
            conn.commit()
            return cur.rowcount
