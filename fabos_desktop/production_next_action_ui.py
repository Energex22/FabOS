from __future__ import absolute_import

def format_next_action(action):
    """Return a compact UI-safe representation of a next-action result."""
    if not action:
        return "No next action available."
    label = action.get("label", "Review production job")
    reason = action.get("reason", "")
    warnings = action.get("warnings") or []
    if warnings:
        return "%s — %s (%s)" % (label, reason, "; ".join([str(x) for x in warnings]))
    return "%s — %s" % (label, reason)
