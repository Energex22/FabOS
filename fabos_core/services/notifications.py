"""Proof-cycle notification hooks (Phase 1 of the FABVEX build plan).

Phase 1 only needs the hooks to exist and be observable: they log the event
so the flow is visible in the error/runtime log. Phase 2 (transactional
notifications + in-app notification center) consumes these hooks to produce
customer notification records via
``fabos_core.services.customer_notifications.CustomerNotificationService``.

The decided direction for customer-facing words is AI-drafted +
staff-approved (see build plan); ``draft_proof_message`` is the stubbed seam
that future work will implement. Phase 2 customer emails use staff-written
templates only.
"""
import logging

logger = logging.getLogger(__name__)


def notify_proof_changes_requested(proof, service=None):
    """Hook fired when a design proof transitions to ``changes_requested``.

    ``proof`` is the proof row dict returned by
    :meth:`DesignProofService._customer_action` (includes ``id``,
    ``quote_id``, ``quote_number``, ``design_version``, ``status`` and
    ``customer_comment``).

    Phase 2: when a ``CustomerNotificationService`` is passed (as
    ``service``), this produces a real customer notification record -- a
    receipt confirming the change request was recorded -- plus delivery per
    the customer's channel preference. Without a service it keeps the Phase
    1 log-only behavior.
    """
    proof = dict(proof or {})
    if service is not None:
        try:
            record_id = service.notify_proof_changes_requested(proof)
        except Exception:
            logger.exception(
                "proof changes_requested notification failed for proof %s",
                proof.get("id"))
            record_id = None
        return {
            "notified": record_id is not None,
            "channel": "notification",
            "notification_id": record_id,
            "proof_id": proof.get("id"),
            "quote_id": proof.get("quote_id"),
            "quote_number": proof.get("quote_number"),
            "design_version": proof.get("design_version"),
        }
    receipt = {
        "notified": True,
        "channel": "log",
        "proof_id": proof.get("id"),
        "quote_id": proof.get("quote_id"),
        "quote_number": proof.get("quote_number"),
        "design_version": proof.get("design_version"),
    }
    logger.info(
        "proof changes_requested: proof_id=%s quote_id=%s quote_number=%s "
        "design_version=%s customer_comment=%r",
        receipt["proof_id"], receipt["quote_id"], receipt["quote_number"],
        receipt["design_version"], proof.get("customer_comment"),
    )
    return receipt


def draft_proof_message(proof, *, purpose):
    """AI-drafted customer messaging seam for the proof cycle.

    ``purpose`` names the message intent (e.g. ``"proof_sent"``,
    ``"changes_requested"``); ``proof`` is the proof payload dict the draft
    would describe.

    NOT IMPLEMENTED in Phase 1. This is where AI-drafted + staff-approved
    customer messaging will slot in later (proof-send is the decided first
    consumer). Deliberately raises so no caller can accidentally ship
    unreviewed AI copy to a customer before the approval workflow exists.
    """
    raise NotImplementedError(
        "draft_proof_message is a planned AI-drafting seam and is not "
        "implemented yet. Proof-cycle customer messaging is staff-written "
        "in Phase 1; this stub will be replaced when the AI-drafted + "
        "staff-approved messaging project lands."
    )
