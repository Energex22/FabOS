"""Proof-cycle notification hooks (Phase 1 of the FABVEX build plan).

Phase 1 only needs the hooks to exist and be observable: they log the event
so the flow is visible in the error/runtime log. Phase 2 (transactional
notifications + in-app notification center) will consume these hooks to
produce staff Action Center items and customer emails.

The decided direction for customer-facing words is AI-drafted +
staff-approved (see build plan); ``draft_proof_message`` is the stubbed seam
that future work will implement. Phase 1 never sends anything to customers.
"""
import logging

logger = logging.getLogger(__name__)


def notify_proof_changes_requested(proof):
    """Hook fired when a design proof transitions to ``changes_requested``.

    ``proof`` is the proof row dict returned by
    :meth:`DesignProofService._customer_action` (includes ``id``,
    ``quote_id``, ``quote_number``, ``design_version``, ``status`` and
    ``customer_comment``).

    Phase 1: logs the event and returns a small receipt dict. Phase 2 will
    turn this into a staff-facing notification (Action Center item / email).
    """
    proof = dict(proof or {})
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
