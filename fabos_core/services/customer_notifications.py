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

Configuration (environment; never hardcode keys):

- ``RESEND_API_KEY``   -- Resend API key. When unset, email payloads are
  logged instead of sent (dev-safe). This is the exact key name.
- ``RESEND_FROM_EMAIL`` -- optional sender override, e.g.
  "FABVEX <hello@fabvex.com>". Falls back to the ``notification_from_email``
  shop setting, then ``shop_email``. Without any from address the email
  channel is recorded as skipped (logged, not sent).

SMS is not wired to a provider yet: when a customer's preference includes
SMS, the SMS payload is logged and the record is marked
``pending_sms_provider`` so a future provider can claim it.

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
    """Resend implementation. Key comes only from ``RESEND_API_KEY``."""

    name = "resend"

    def __init__(self, api_key=None, api_url=None, timeout=10):
        self.api_key = api_key if api_key is not None else os.environ.get("RESEND_API_KEY", "").strip()
        self.api_url = api_url or RESEND_API_URL
        self.timeout = timeout

    def send_email(self, *, to, subject, text_body, from_email):
        if not self.api_key:
            raise NotificationSendError("RESEND_API_KEY is not configured")
        if not to:
            raise NotificationSendError("No recipient email address")
        if not from_email:
            raise NotificationSendError("No from address configured (RESEND_FROM_EMAIL or notification_from_email shop setting)")
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


def default_email_provider():
    """Resend when ``RESEND_API_KEY`` is configured, else the log fallback."""
    if os.environ.get("RESEND_API_KEY", "").strip():
        return ResendEmailProvider()
    return LoggingEmailProvider()


class CustomerNotificationService:
    def __init__(self, database, shop_settings=None, provider=None):
        self.database = database
        self.shop_settings = shop_settings
        self.provider = provider if provider is not None else default_email_provider()

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
        override = os.environ.get("RESEND_FROM_EMAIL", "").strip()
        if override:
            return override
        return str(
            self._setting("notification_from_email", "")
            or self._setting("shop_email", "")
        ).strip()

    def _shop_name(self):
        return str(self._setting("shop_name", "") or "FABVEX").strip() or "FABVEX"

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
                deep_link or "(no link)",
                "You're receiving this because you have a %s account. "
                "Manage these notifications in your account profile." % shop_name,
            )
            channels = {}

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
                            "(RESEND_FROM_EMAIL / notification_from_email)")
                    else:
                        try:
                            receipt = self.provider.send_email(
                                to=email, subject=subject, text_body=text_body,
                                from_email=from_email or "FABVEX <noreply@example.invalid>")
                            channels["email"] = {"status": receipt.get("status", "sent"),
                                                 "provider": receipt.get("provider")}
                        except NotificationSendError as exc:
                            channels["email"] = {"status": "failed", "error": str(exc)[:300]}
                            logger.warning("notification email failed for customer %s: %s",
                                           customer["id"], exc)

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
