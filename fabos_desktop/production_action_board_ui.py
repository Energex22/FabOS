from __future__ import absolute_import

def format_action_board(board):
    board = board or {}
    counts = board.get("counts") or {}
    rows = board.get("rows") or []
    summary = (
        "Jobs: %s | Blocked: %s | Monitor: %s | Assign printer: %s | Preflight: %s"
        % (
            counts.get("total", 0),
            counts.get("blocked", 0),
            counts.get("monitor", 0),
            counts.get("assign_printer", 0),
            counts.get("preflight", 0),
        )
    )
    return {
        "summary": summary,
        "rows": [
            {
                "job_id": row.get("job_id"),
                "action": row.get("label", "Review"),
                "status": row.get("status", ""),
                "safe_to_start": bool(row.get("safe_to_start")),
            }
            for row in rows
        ],
    }
