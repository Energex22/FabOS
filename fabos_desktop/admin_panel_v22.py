"""Pass 22: administrator control center exposed from System -> Settings."""

import tkinter as tk
from tkinter import ttk, messagebox

from fabos_desktop.system_ui import SystemReliabilityMixin


def _open_admin_center(self):
    existing = getattr(self, "_admin_center_window", None)
    try:
        if existing and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
    except Exception:
        pass

    win = tk.Toplevel(self)
    self._admin_center_window = win
    win.title("FabOS Administration Center")
    win.geometry("1120x720")
    win.minsize(900, 600)
    win.configure(bg=self._c("bg"))
    win.transient(self)

    header = tk.Frame(win, bg=self._c("bg"))
    header.pack(fill="x", padx=24, pady=(20, 12))
    tk.Label(header, text="ADMINISTRATION CENTER", bg=self._c("bg"), fg=self._c("text"),
             font=("Segoe UI", 18, "bold")).pack(anchor="w")
    tk.Label(header, text="Users, roles, permissions, security sessions, and configurable business settings",
             bg=self._c("bg"), fg=self._c("muted"), font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 0))

    tabs = ttk.Notebook(win)
    tabs.pack(fill="both", expand=True, padx=24, pady=(0, 20))
    users_tab = tk.Frame(tabs, bg=self._c("bg"))
    permissions_tab = tk.Frame(tabs, bg=self._c("bg"))
    settings_tab = tk.Frame(tabs, bg=self._c("bg"))
    tabs.add(users_tab, text="Users & Accounts")
    tabs.add(permissions_tab, text="Roles & Permissions")
    tabs.add(settings_tab, text="Business Settings")

    # Users
    toolbar = tk.Frame(users_tab, bg=self._c("bg"))
    toolbar.pack(fill="x", pady=(4, 10))
    self._button(toolbar, "Refresh", lambda: refresh_users(), True).pack(side="left")
    self._button(toolbar, "Save Account", lambda: save_user()).pack(side="left", padx=7)
    self._button(toolbar, "Reset Password", lambda: reset_password()).pack(side="left")
    self._button(toolbar, "Revoke Sessions", lambda: revoke_sessions()).pack(side="left", padx=7)

    split = tk.PanedWindow(users_tab, orient="horizontal", bg=self._c("bg"), sashwidth=6, bd=0)
    split.pack(fill="both", expand=True)
    left = self._card(split, "Accounts")
    right = self._card(split, "Selected Account")
    split.add(left, minsize=500, stretch="always")
    split.add(right, minsize=380, stretch="always")

    table = ttk.Treeview(left, columns=("username", "type", "status", "last_login"), show="headings", style="Dark.Treeview", selectmode="browse")
    for col, title, width in (("username", "Username", 170), ("type", "Account Type", 120), ("status", "Status", 90), ("last_login", "Last Login", 160)):
        table.heading(col, text=title)
        table.column(col, width=width, anchor="w")
    table.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    selected_id = {"value": None}
    email_var = tk.StringVar()
    type_var = tk.StringVar(value="employee")
    active_var = tk.BooleanVar(value=True)
    detail = tk.StringVar(value="Select an account.")

    form = tk.Frame(right, bg=self._c("surface"))
    form.pack(fill="x", padx=16, pady=16)
    tk.Label(form, text="EMAIL", bg=self._c("surface"), fg=self._c("muted"), font=("Segoe UI", 8, "bold")).pack(anchor="w")
    tk.Entry(form, textvariable=email_var, bg=self._c("surface_alt"), fg=self._c("text"), insertbackground=self._c("text"),
             relief="flat", bd=0).pack(fill="x", ipady=7, pady=(3, 12))
    tk.Label(form, text="ACCOUNT TYPE", bg=self._c("surface"), fg=self._c("muted"), font=("Segoe UI", 8, "bold")).pack(anchor="w")
    ttk.Combobox(form, textvariable=type_var, values=("customer", "employee", "administrator"), state="readonly").pack(fill="x", pady=(3, 12))
    tk.Checkbutton(form, text="Account active", variable=active_var, bg=self._c("surface"), fg=self._c("text"),
                   activebackground=self._c("surface"), activeforeground=self._c("text"), selectcolor=self._c("surface_alt")).pack(anchor="w")
    tk.Label(right, textvariable=detail, bg=self._c("surface"), fg=self._c("muted"), justify="left", anchor="nw",
             wraplength=350).pack(fill="both", expand=True, padx=16, pady=(0, 16))

    user_rows = {}

    def refresh_users():
        rows = self.core.accounts.list_users()
        user_rows.clear()
        table.delete(*table.get_children())
        for row in rows:
            user_rows[row["id"]] = row
            table.insert("", "end", iid=row["id"], values=(row["username"], row["account_type"],
                         "Active" if int(row["active"]) else "Disabled", row["last_login_at"] or "Never"))

    def select_user(_event=None):
        chosen = table.selection()
        if not chosen:
            return
        row = user_rows.get(chosen[0])
        if not row:
            return
        selected_id["value"] = row["id"]
        email_var.set(row["email"] or "")
        type_var.set(row["account_type"])
        active_var.set(bool(row["active"]))
        detail.set("User ID: %s\nCreated: %s\nUpdated: %s\nLast login: %s\n\nRole changes affect the default RBAC permissions. Use the Roles & Permissions tab for individual overrides." %
                    (row["id"], row["created_at"] or "Unknown", row["updated_at"] or "Unknown", row["last_login_at"] or "Never"))

    def save_user():
        user_id = selected_id["value"]
        if not user_id:
            return messagebox.showinfo("Administration", "Select an account first.", parent=win)
        current = user_rows[user_id]
        if user_id == self.core.accounts.get_user(user_id)["id"] and not active_var.get():
            # The desktop shell does not have a web session identity, so this only prevents accidental disabling
            # when the selected account is the current local administrator configured by the operator.
            pass
        try:
            self.core.accounts.update_account(user_id, email=email_var.get().strip(), account_type=type_var.get(), active=active_var.get())
            refresh_users()
            table.selection_set(user_id)
            select_user()
            messagebox.showinfo("Administration", "Account changes saved.", parent=win)
        except Exception as exc:
            messagebox.showerror("Administration", str(exc), parent=win)

    def reset_password():
        user_id = selected_id["value"]
        if not user_id:
            return messagebox.showinfo("Administration", "Select an account first.", parent=win)
        dialog = tk.Toplevel(win)
        dialog.title("Reset Password")
        dialog.geometry("420x210")
        dialog.configure(bg=self._c("bg"))
        card = self._card(dialog, "Reset Account Password")
        card.pack(fill="both", expand=True, padx=16, pady=16)
        var = tk.StringVar()
        tk.Label(card, text="New password (minimum 8 characters)", bg=self._c("surface"), fg=self._c("muted")).pack(anchor="w", padx=16, pady=(4, 4))
        entry = tk.Entry(card, textvariable=var, show="*", bg=self._c("surface_alt"), fg=self._c("text"), insertbackground=self._c("text"), relief="flat", bd=0)
        entry.pack(fill="x", padx=16, ipady=7)
        def save_password():
            try:
                self.core.auth.set_password(user_id, var.get())
                count = self.core.auth.revoke_user_sessions(user_id)
                dialog.destroy()
                messagebox.showinfo("Password Reset", "Password changed and %d existing session(s) revoked." % count, parent=win)
            except Exception as exc:
                messagebox.showerror("Password Reset", str(exc), parent=dialog)
        self._button(card, "Save New Password", save_password, True).pack(anchor="e", padx=16, pady=14)

    def revoke_sessions():
        user_id = selected_id["value"]
        if not user_id:
            return messagebox.showinfo("Administration", "Select an account first.", parent=win)
        count = self.core.auth.revoke_user_sessions(user_id)
        messagebox.showinfo("Sessions Revoked", "%d active session(s) were revoked." % count, parent=win)

    table.bind("<<TreeviewSelect>>", select_user)
    refresh_users()

    # Permissions
    pbar = tk.Frame(permissions_tab, bg=self._c("bg"))
    pbar.pack(fill="x", pady=(4, 10))
    self._button(pbar, "Refresh", lambda: refresh_permission_users(), True).pack(side="left")
    self._button(pbar, "Allow", lambda: set_permission(True)).pack(side="left", padx=7)
    self._button(pbar, "Deny", lambda: set_permission(False)).pack(side="left")
    self._button(pbar, "Clear Override", clear_permission).pack(side="left", padx=7)
    psplit = tk.PanedWindow(permissions_tab, orient="horizontal", bg=self._c("bg"), sashwidth=6, bd=0)
    psplit.pack(fill="both", expand=True)
    pu = self._card(psplit, "User")
    pp = self._card(psplit, "Permissions")
    psplit.add(pu, minsize=320, stretch="never")
    psplit.add(pp, minsize=620, stretch="always")
    pusers = ttk.Treeview(pu, columns=("username", "type"), show="headings", style="Dark.Treeview", selectmode="browse")
    pusers.heading("username", text="Username")
    pusers.heading("type", text="Role")
    pusers.column("username", width=170)
    pusers.column("type", width=110)
    pusers.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    perms = ttk.Treeview(pp, columns=("permission", "role", "effective"), show="headings", style="Dark.Treeview", selectmode="browse")
    for col, title, width in (("permission", "Permission", 270), ("role", "Role Default", 120), ("effective", "Effective", 120)):
        perms.heading(col, text=title)
        perms.column(col, width=width)
    perms.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    perm_user = {"value": None}
    perm_state = {"row": None}

    def refresh_permission_users():
        pusers.delete(*pusers.get_children())
        for row in self.core.accounts.list_users():
            pusers.insert("", "end", iid=row["id"], values=(row["username"], row["account_type"]))

    def load_permissions(_event=None):
        chosen = pusers.selection()
        if not chosen:
            return
        user_id = chosen[0]
        row = self.core.accounts.get_user(user_id)
        perm_user["value"] = user_id
        base = self.core.permissions.permissions_for_account_type(row["account_type"])
        effective = self.core.permissions.permissions_for_user(user_id, row["account_type"])
        perm_state["row"] = row
        perms.delete(*perms.get_children())
        for permission in self.core.permissions.all_permissions():
            perms.insert("", "end", iid=permission, values=(permission, "Allow" if permission in base else "Deny", "Allow" if permission in effective else "Deny"))

    def selected_permission():
        chosen = perms.selection()
        return chosen[0] if chosen else None

    def set_permission(allowed):
        user_id = perm_user["value"]
        permission = selected_permission()
        if not user_id or not permission:
            return messagebox.showinfo("Permissions", "Select a user and permission first.", parent=win)
        self.core.permissions.set_user_permission(user_id, permission, allowed)
        load_permissions()

    def clear_permission():
        user_id = perm_user["value"]
        permission = selected_permission()
        if not user_id or not permission:
            return messagebox.showinfo("Permissions", "Select a user and permission first.", parent=win)
        self.core.permissions.clear_user_permission(user_id, permission)
        load_permissions()

    pusers.bind("<<TreeviewSelect>>", load_permissions)
    refresh_permission_users()

    # Settings
    sbar = tk.Frame(settings_tab, bg=self._c("bg"))
    sbar.pack(fill="x", pady=(4, 10))
    self._button(sbar, "Reload", lambda: load_settings(), True).pack(side="left")
    self._button(sbar, "Save Setting", lambda: save_setting()).pack(side="left", padx=7)
    self._button(sbar, "Open System Settings", lambda: (win.destroy(), self.show_page("Settings"))).pack(side="left")
    ssplit = tk.PanedWindow(settings_tab, orient="horizontal", bg=self._c("bg"), sashwidth=6, bd=0)
    ssplit.pack(fill="both", expand=True)
    sl = self._card(ssplit, "Configurable Settings")
    sr = self._card(ssplit, "Selected Setting")
    ssplit.add(sl, minsize=470, stretch="always")
    ssplit.add(sr, minsize=420, stretch="always")
    settings_table = ttk.Treeview(sl, columns=("key", "value"), show="headings", style="Dark.Treeview", selectmode="browse")
    settings_table.heading("key", text="Setting")
    settings_table.heading("value", text="Value")
    settings_table.column("key", width=270)
    settings_table.column("value", width=180)
    settings_table.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    setting_key = {"value": None}
    setting_value = tk.StringVar()
    setting_meta = tk.StringVar(value="Select a setting.")
    tk.Label(sr, textvariable=setting_meta, bg=self._c("surface"), fg=self._c("muted"), justify="left", anchor="nw", wraplength=370).pack(fill="x", padx=16, pady=(16, 12))
    tk.Entry(sr, textvariable=setting_value, bg=self._c("surface_alt"), fg=self._c("text"), insertbackground=self._c("text"), relief="flat", bd=0).pack(fill="x", padx=16, ipady=8)
    setting_cache = {"settings": {}, "metadata": {}}

    def load_settings():
        setting_cache["settings"] = self.core.shop_settings.snapshot()
        setting_cache["metadata"] = self.core.shop_settings.metadata()
        settings_table.delete(*settings_table.get_children())
        for key, value in sorted(setting_cache["settings"].items()):
            settings_table.insert("", "end", iid=key, values=(key, value))

    def select_setting(_event=None):
        chosen = settings_table.selection()
        if not chosen:
            return
        key = chosen[0]
        setting_key["value"] = key
        setting_value.set(setting_cache["settings"].get(key, ""))
        description = ""
        for group, values in setting_cache["metadata"].items():
            if key in values:
                description = "%s\n%s" % (group.title(), values[key])
                break
        setting_meta.set(description or key)

    def save_setting():
        key = setting_key["value"]
        if not key:
            return messagebox.showinfo("Settings", "Select a setting first.", parent=win)
        try:
            self.core.shop_settings.set_validated(key, setting_value.get())
            load_settings()
            settings_table.selection_set(key)
            select_setting()
        except Exception as exc:
            messagebox.showerror("Settings", str(exc), parent=win)

    settings_table.bind("<<TreeviewSelect>>", select_setting)
    load_settings()

    def close():
        try:
            self._admin_center_window = None
        finally:
            win.destroy()
    win.protocol("WM_DELETE_WINDOW", close)


def build_settings_wrapper(original):
    def wrapped(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        bar = tk.Frame(self.content, bg=self._c("bg"))
        bar.pack(fill="x", pady=(8, 0), before=self.content.winfo_children()[-1] if self.content.winfo_children() else None)
        self._button(bar, "Administration Center", lambda: _open_admin_center(self), True).pack(side="left")
        return result
    return wrapped


def apply():
    original = SystemReliabilityMixin._build_settings_page
    SystemReliabilityMixin._open_admin_center_v22 = _open_admin_center
    SystemReliabilityMixin._build_settings_page = build_settings_wrapper(original)


apply()
