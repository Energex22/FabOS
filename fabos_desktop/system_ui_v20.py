"""Pass 20 hardening for System -> Activity and Logs & Version.

The legacy pages assumed every journal/log/version read would succeed. These
helpers keep the desktop shell usable when a database/log is partially damaged,
when an older database is opened, or when a background service is unavailable.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from fabos_desktop.system_ui import SystemReliabilityMixin


def _row_value(row, key, default=""):
    try:
        if hasattr(row, "keys") and key in row.keys():
            value = row[key]
        elif isinstance(row, dict):
            value = row.get(key, default)
        else:
            value = default
        return default if value is None else value
    except Exception:
        return default


def safe_activity_rows(operations, limit=250):
    try:
        rows = operations.recent_activity(limit)
        return list(rows or [])
    except Exception as exc:
        return [{"id": "system_activity_error", "created_at": "", "event_type": "ERROR",
                 "title": "Activity journal unavailable", "detail": str(exc),
                 "page": "Logs & Version", "undo_type": ""}]


def safe_log_rows(error_log, limit=500):
    try:
        rows = error_log.recent(limit)
        return list(rows or [])
    except Exception as exc:
        return [{"time": "", "level": "ERROR", "message": "Application log unavailable",
                 "detail": str(exc)}]


def build_activity_page(self):
    bar = tk.Frame(self.content, bg=self._c("bg"))
    bar.pack(fill="x", pady=(4, 10))
    self._button(bar, "Undo Last Safe Action", self._undo_last_action_v20, True).pack(side="left")
    self._button(bar, "Refresh", lambda: self.show_page("Activity")).pack(side="left", padx=7)
    self._button(bar, "Open Logs & Version", lambda: self.show_page("Logs & Version")).pack(side="left")

    card = self._card(self.content, "Activity Journal")
    card.pack(fill="both", expand=True)
    cols = ("time", "type", "title", "detail", "page", "undo")
    table = ttk.Treeview(card, columns=cols, show="headings", style="Dark.Treeview")
    for c, label, width in (("time", "Time", 140), ("type", "Event", 115),
                            ("title", "Action", 210), ("detail", "Details", 360),
                            ("page", "Area", 100), ("undo", "Undo", 70)):
        table.heading(c, text=label)
        table.column(c, width=width, anchor="w", stretch=(c == "detail"))

    rows = safe_activity_rows(self.core.operations, 250)
    for index, row in enumerate(rows):
        iid = str(_row_value(row, "id", "activity_%d" % index))
        if table.exists(iid):
            iid = "activity_%d" % index
        detail = str(_row_value(row, "detail", ""))
        table.insert("", "end", iid=iid, values=(
            str(_row_value(row, "created_at", ""))[:19],
            _row_value(row, "event_type", "INFO"),
            _row_value(row, "title", "Activity"),
            detail[:2000],
            _row_value(row, "page", ""),
            "Yes" if _row_value(row, "undo_type", "") else "",
        ), tags=("error" if _row_value(row, "event_type", "").upper() == "ERROR" else "body",))
    table.tag_configure("error", foreground=self._c("red"))
    table.tag_configure("body", foreground=self._c("text"))

    shell = tk.Frame(card, bg=self._c("surface"))
    shell.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    vscroll = ttk.Scrollbar(shell, orient="vertical", command=table.yview)
    hscroll = ttk.Scrollbar(shell, orient="horizontal", command=table.xview)
    table.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
    table.grid(row=0, column=0, sticky="nsew")
    vscroll.grid(row=0, column=1, sticky="ns")
    hscroll.grid(row=1, column=0, sticky="ew")
    shell.rowconfigure(0, weight=1)
    shell.columnconfigure(0, weight=1)


def undo_last_action_v20(self):
    try:
        action = next((x for x in safe_activity_rows(self.core.operations, 50)
                       if _row_value(x, "undo_type", "")), None)
        if not action:
            return messagebox.showinfo("Undo", "There is no recent FabOS action that can be undone.")
        import json
        payload = json.loads(_row_value(action, "undo_payload_json", "{}") or "{}")
        if _row_value(action, "undo_type", "") == "order_status":
            self.core.orders.set_status_internal(payload["order_id"], payload["old_status"], reason="desktop activity undo")
            with self.core.database.connect() as c:
                c.execute("UPDATE activity_journal SET undo_type=NULL,undo_payload_json=NULL WHERE id=?",
                          (_row_value(action, "id", ""),))
                c.commit()
            self.core.operations.log("undo", "Undid order status change",
                                     "Restored " + payload["old_status"], "Orders", payload["order_id"])
            self.show_page("Orders")
        else:
            messagebox.showinfo("Undo", "That action cannot be undone automatically.")
    except Exception as exc:
        try:
            self.core.error_log.error("Activity undo failed", exc, {"page": "Activity"})
        except Exception:
            pass
        messagebox.showerror("Undo", "FabOS could not undo that action. The failure was written to Logs & Version.\n\n%s" % exc)


def build_logs_version_page(self):
    try:
        info = self.core.diagnostics.version_info()
    except Exception as exc:
        info = {"fabos_version": "unknown", "schema_version": "unknown",
                "python": "unknown", "platform": "unknown"}
        try:
            self.core.error_log.error("Version information unavailable", exc, {"page": "Logs & Version"})
        except Exception:
            pass

    rows = safe_log_rows(self.core.error_log, 500)
    metrics = tk.Frame(self.content, bg=self._c("bg"))
    metrics.pack(fill="x", pady=(4, 10))
    cards = [
        ("FabOS", info.get("fabos_version", "unknown"), self._c("purple"), "Application version"),
        ("Schema", info.get("schema_version", "unknown"), self._c("blue"), "Database migration version"),
        ("Python", info.get("python", "unknown"), self._c("green"), "Runtime"),
        ("Log Entries", len(rows), self._c("orange"), "Recent application log"),
    ]
    for i, (title, value, color, detail) in enumerate(cards):
        c = self._metric_card(metrics, title, value, color, detail)
        c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 7, 0))
        metrics.columnconfigure(i, weight=1)

    bar = tk.Frame(self.content, bg=self._c("bg"))
    bar.pack(fill="x", pady=(0, 10))
    self._button(bar, "Export Diagnostics", self._export_diagnostics_v20, True).pack(side="left")
    self._button(bar, "Open Log Folder", lambda: self._open_path(self.core.settings.log_dir)).pack(side="left", padx=7)
    self._button(bar, "Test Latest Backup", self._test_latest_backup_v20).pack(side="left")
    self._button(bar, "Refresh", lambda: self.show_page("Logs & Version")).pack(side="left", padx=7)

    card = self._card(self.content, "Application Log")
    card.pack(fill="both", expand=True)
    cols = ("time", "level", "message", "detail")
    table = ttk.Treeview(card, columns=cols, show="headings", style="Dark.Treeview")
    for col, label, width in (("time", "Time", 145), ("level", "Level", 75),
                              ("message", "Message", 260), ("detail", "Details", 560)):
        table.heading(col, text=label)
        table.column(col, width=width, anchor="w", stretch=(col == "detail"))
    for i, row in enumerate(rows):
        detail = str(_row_value(row, "detail", "")).replace("\n", " ")[:2000]
        level = str(_row_value(row, "level", "INFO"))
        table.insert("", "end", iid="log_%d" % i,
                     values=(_row_value(row, "time", ""), level,
                             _row_value(row, "message", ""), detail),
                     tags=(level.lower(),))
    table.tag_configure("error", foreground=self._c("red"))
    table.tag_configure("warning", foreground=self._c("orange"))

    shell = tk.Frame(card, bg=self._c("surface"))
    shell.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    sy = ttk.Scrollbar(shell, orient="vertical", command=table.yview)
    sx = ttk.Scrollbar(shell, orient="horizontal", command=table.xview)
    table.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
    table.grid(row=0, column=0, sticky="nsew")
    sy.grid(row=0, column=1, sticky="ns")
    sx.grid(row=1, column=0, sticky="ew")
    shell.rowconfigure(0, weight=1)
    shell.columnconfigure(0, weight=1)


def export_diagnostics_v20(self):
    try:
        path = self.core.diagnostics.export()
        messagebox.showinfo("Diagnostics Exported", "FabOS diagnostics were saved to:\n\n%s\n\nAPI keys and secrets are redacted." % path)
    except Exception as exc:
        try:
            self.core.error_log.error("Diagnostics export failed", exc, {"page": "Logs & Version"})
        except Exception:
            pass
        messagebox.showerror("Diagnostics", "Diagnostics export failed.\n\n%s" % exc)


def test_latest_backup_v20(self):
    try:
        result = self.core.backups.test_latest()
        if result.get("valid"):
            messagebox.showinfo("Backup Test", "✓ Latest backup passed validation.\n\n" + result.get("detail", ""))
        else:
            messagebox.showerror("Backup Test", "Latest backup failed validation:\n\n" + result.get("detail", ""))
    except Exception as exc:
        try:
            self.core.error_log.error("Backup validation failed", exc, {"page": "Logs & Version"})
        except Exception:
            pass
        messagebox.showerror("Backup Test", "Backup validation failed.\n\n%s" % exc)


def apply():
    SystemReliabilityMixin._build_activity_page = build_activity_page
    SystemReliabilityMixin._undo_last_action_v20 = undo_last_action_v20
    SystemReliabilityMixin._build_logs_version_page = build_logs_version_page
    SystemReliabilityMixin._export_diagnostics_v20 = export_diagnostics_v20
    SystemReliabilityMixin._test_latest_backup_v20 = test_latest_backup_v20


apply()
