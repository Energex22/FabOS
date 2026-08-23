from dataclasses import dataclass
from typing import Optional

@dataclass
class SalesFilter:
    query: str = ""
    status: Optional[str] = None
    archived: bool = False

ACTIVE_ORDER_STATUSES = {
    "quote", "awaiting_payment", "ready_for_production",
    "in_production", "qc", "packaging", "ready_to_ship"
}
HISTORY_ORDER_STATUSES = {"shipped", "completed", "cancelled"}

def is_history_status(status):
    return str(status or "").lower() in HISTORY_ORDER_STATUSES

def is_active_status(status):
    return str(status or "").lower() in ACTIVE_ORDER_STATUSES

def payment_label(paid, voided=False):
    if voided:
        return "Voided"
    return "Paid" if paid else "Unpaid"
