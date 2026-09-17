import tkinter as tk
from tkinter import ttk, messagebox


class AdministrationMixin:
    """Internal administration workspace for users, permissions, and shop controls."""

    def _build_administration_page(self):
        tabs = ttk.Notebook(self.content)
        tabs.pack(fill='both', expand=True)
        users = tk.Frame(tabs, bg=self._c('bg'))
        permissions = tk.Frame(tabs, bg=self._c('bg'))
        overview = tk.Frame(tabs, bg=self._c('bg'))
        tabs.add(users, text='Users & Accounts')
        tabs.add(permissions, text='Permissions')
        tabs.add(overview, text='Administration')
        self._build_admin_users(users)
        self._build_admin_permissions(permissions)
        self._build_admin_overview(overview)

    def _admin_user_payload(self, row):
        return {
            'id': row['id'],
            'username': row['username'],
            'email': row['email'] if 'email' in row.keys() else '',
            'account_type': row['account_type'] if 'account_type' in row.keys() else 'employee',
            'active': bool(row['active']),
            'created_at': row['created_at'] if 'created_at' in row.keys() else '',
            'last_login_at': row['last_login_at'] if 'last_login_at' in row.keys() else '',
        }

    def _build_admin_users(self, parent):
        bar = tk.Frame(parent, bg=self._c('bg'))
        bar.pack(fill='x', pady=(4, 10))
        self._button(bar, 'Refresh', self._admin_refresh_users, True).pack(side='left')
        self._button(bar, 'Reset Password', self._admin_reset_selected_password).pack(side='left', padx=7)
        self._button(bar, 'Revoke Sessions', self._admin_revoke_selected_sessions).pack(side='left')
        self._button(bar, 'Save Account', self._admin_save_selected).pack(side='left', padx=7)

        split = tk.PanedWindow(parent, orient='horizontal', bg=self._c('bg'), sashwidth=6, bd=0)
        split.pack(fill='both', expand=True)
        left = self._card(split, 'Accounts')
        right = self._card(split, 'Selected Account')
        split.add(left, minsize=540, stretch='always')
        split.add(right, minsize=420, stretch='always')

        self.admin_user_table = ttk.Treeview(
            left, columns=('username', 'type', 'active', 'last_login'),
            show='headings', style='Dark.Treeview', selectmode='browse')
        for col, title, width in [('username', 'Username', 180), ('type', 'Account Type', 125),
                                  ('active', 'Status', 80), ('last_login', 'Last Login', 160)]:
            self.admin_user_table.heading(col, text=title)
            self.admin_user_table.column(col, width=width, anchor='w')
        self.admin_user_table.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.admin_user_table.bind('<<TreeviewSelect>>', self._admin_select_user)

        self.admin_selected_label = tk.Label(right, text='Select an account', bg=self._c('surface'),
                                              fg=self._c('text'), font=('Segoe UI', 12, 'bold'), anchor='w')
        self.admin_selected_label.pack(fill='x', padx=16, pady=(14, 12))
        form = tk.Frame(right, bg=self._c('surface'))
        form.pack(fill='x', padx=16)
        self.admin_vars = {}

        def field(label, key):
            tk.Label(form, text=label, bg=self._c('surface'), fg=self._c('muted'),
                     font=('Segoe UI', 8, 'bold')).pack(anchor='w', pady=(4, 2))
            var = tk.StringVar()
            self.admin_vars[key] = var
            self._entry(form, var, 32).pack(fill='x', ipady=5, pady=(0, 8))

        field('Email', 'email')
        field('Username', 'username')
        type_row = tk.Frame(form, bg=self._c('surface'))
        type_row.pack(fill='x', pady=(0, 8))
        tk.Label(type_row, text='Account Type', bg=self._c('surface'), fg=self._c('muted'),
                 font=('Segoe UI', 8, 'bold')).pack(anchor='w')
        self.admin_vars['account_type'] = tk.StringVar(value='employee')
        ttk.Combobox(type_row, textvariable=self.admin_vars['account_type'],
                     values=['customer', 'employee', 'administrator'], state='readonly', width=28).pack(anchor='w', pady=(3, 0))
        self.admin_vars['active'] = tk.BooleanVar(value=True)
        tk.Checkbutton(form, text='Account active', variable=self.admin_vars['active'],
                       bg=self._c('surface'), fg=self._c('text'), activebackground=self._c('surface'),
                       activeforeground=self._c('text'), selectcolor=self._c('surface_alt')).pack(anchor='w', pady=(4, 8))

        self.admin_user_detail = tk.Label(right, text='', bg=self._c('surface'), fg=self._c('muted'),
                                          justify='left', anchor='w', wraplength=360)
        self.admin_user_detail.pack(fill='x', padx=16, pady=(4, 14))
        self._admin_refresh_users()

    def _admin_refresh_users(self):
        if not getattr(self, 'admin_user_table', None):
            return
        try:
            rows = self.core.accounts.list_users()
        except Exception as exc:
            messagebox.showerror('Administration', str(exc))
            return
        self._admin_users = {row['id']: row for row in rows}
        self.admin_user_table.delete(*self.admin_user_table.get_children())
        for row in rows:
            data = self._admin_user_payload(row)
            self.admin_user_table.insert('', 'end', iid=data['id'], values=(
                data['username'], data['account_type'], 'Active' if data['active'] else 'Disabled',
                data['last_login_at'] or 'Never'))

    def _admin_select_user(self, _event=None):
        selected = self.admin_user_table.selection() if getattr(self, 'admin_user_table', None) else ()
        if not selected:
            return
        row = self._admin_users.get(selected[0])
        if not row:
            return
        data = self._admin_user_payload(row)
        self.admin_selected_label.configure(text=data['username'])
        for key in ('email', 'username', 'account_type'):
            self.admin_vars[key].set(data[key] or '')
        self.admin_vars['active'].set(data['active'])
        self.admin_user_detail.configure(
            text='User ID: %s\nCreated: %s\nLast login: %s\n\nAccount type controls the default RBAC role. Individual permission overrides are managed on the Permissions tab.' %
                 (data['id'], data['created_at'] or 'Unknown', data['last_login_at'] or 'Never'))

    def _admin_selected_id(self):
        selected = self.admin_user_table.selection() if getattr(self, 'admin_user_table', None) else ()
        return selected[0] if selected else None

    def _admin_save_selected(self):
        user_id = self._admin_selected_id()
        if not user_id:
            return messagebox.showinfo('Administration', 'Select an account first.')
        try:
            email = self.admin_vars['email'].get().strip()
            account_type = self.admin_vars['account_type'].get().strip()
            active = bool(self.admin_vars['active'].get())
            self.core.accounts.update_account(user_id, email=email, account_type=account_type, active=active)
            self._admin_refresh_users()
            self.admin_user_table.selection_set(user_id)
            self._admin_select_user()
            messagebox.showinfo('Administration', 'Account changes saved.')
        except Exception as exc:
            messagebox.showerror('Administration', str(exc))

    def _admin_reset_selected_password(self):
        user_id = self._admin_selected_id()
        if not user_id:
            return messagebox.showinfo('Administration', 'Select an account first.')
        win = tk.Toplevel(self)
        win.title('Reset Password')
        win.geometry('420x230')
        win.configure(bg=self._c('bg'))
        win.transient(self)
        card = self._card(win, 'Reset Account Password')
        card.pack(fill='both', expand=True, padx=16, pady=16)
        var = tk.StringVar()
        tk.Label(card, text='New password (minimum 8 characters)', bg=self._c('surface'), fg=self._c('muted')).pack(anchor='w', padx=16, pady=(4, 4))
        entry = self._entry(card, var, 28, show='*')
        entry.pack(padx=16, fill='x', ipady=5)
        def save():
            try:
                self.core.auth.set_password(user_id, var.get())
                self.core.auth.revoke_user_sessions(user_id)
                win.destroy()
                messagebox.showinfo('Password Reset', 'Password changed and existing sessions revoked.')
            except Exception as exc:
                messagebox.showerror('Password Reset', str(exc))
        self._button(card, 'Save New Password', save, True).pack(anchor='e', padx=16, pady=14)

    def _admin_revoke_selected_sessions(self):
        user_id = self._admin_selected_id()
        if not user_id:
            return messagebox.showinfo('Administration', 'Select an account first.')
        count = self.core.auth.revoke_user_sessions(user_id)
        messagebox.showinfo('Sessions Revoked', '%d active session(s) were revoked.' % count)

    def _build_admin_permissions(self, parent):
        bar = tk.Frame(parent, bg=self._c('bg'))
        bar.pack(fill='x', pady=(4, 10))
        self._button(bar, 'Refresh', self._admin_refresh_permissions, True).pack(side='left')
        self._button(bar, 'Save Override', self._admin_save_permission_override).pack(side='left', padx=7)
        self._button(bar, 'Clear Override', self._admin_clear_permission_override).pack(side='left')

        split = tk.PanedWindow(parent, orient='horizontal', bg=self._c('bg'), sashwidth=6, bd=0)
        split.pack(fill='both', expand=True)
        left = self._card(split, 'User')
        right = self._card(split, 'Permission Overrides')
        split.add(left, minsize=300, stretch='never')
        split.add(right, minsize=600, stretch='always')

        self.admin_perm_users = ttk.Treeview(left, columns=('username', 'type'), show='headings', style='Dark.Treeview', selectmode='browse')
        self.admin_perm_users.heading('username', text='Username')
        self.admin_perm_users.heading('type', text='Type')
        self.admin_perm_users.column('username', width=150)
        self.admin_perm_users.column('type', width=110)
        self.admin_perm_users.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.admin_perm_users.bind('<<TreeviewSelect>>', self._admin_load_permissions)

        self.admin_perm_table = ttk.Treeview(right, columns=('permission', 'base', 'override', 'effective'), show='headings', style='Dark.Treeview', selectmode='browse')
        for col, title, width in [('permission', 'Permission', 230), ('base', 'Role Default', 110), ('override', 'Override', 110), ('effective', 'Effective', 110)]:
            self.admin_perm_table.heading(col, text=title)
            self.admin_perm_table.column(col, width=width, anchor='w')
        self.admin_perm_table.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.admin_perm_table.bind('<Double-1>', self._admin_toggle_permission)
        self._admin_refresh_permissions()

    def _admin_refresh_permissions(self):
        if not getattr(self, 'admin_perm_users', None):
            return
        rows = self.core.accounts.list_users()
        self._admin_perm_user_rows = {row['id']: row for row in rows}
        self.admin_perm_users.delete(*self.admin_perm_users.get_children())
        for row in rows:
            self.admin_perm_users.insert('', 'end', iid=row['id'], values=(row['username'], row['account_type']))
        self.admin_perm_table.delete(*self.admin_perm_table.get_children())

    def _admin_load_permissions(self, _event=None):
        selected = self.admin_perm_users.selection()
        if not selected:
            return
        user_id = selected[0]
        row = self._admin_perm_user_rows[user_id]
        account_type = row['account_type']
        try:
            effective = self.core.permissions.permissions_for_user(user_id, account_type)
            base = self.core.permissions.permissions_for_account_type(account_type)
            with self.core.database.connect() as conn:
                overrides = {x['permission']: bool(x['allowed']) for x in conn.execute(
                    'SELECT permission,allowed FROM user_permissions WHERE user_id=?', (user_id,)).fetchall()}
        except Exception as exc:
            messagebox.showerror('Permissions', str(exc))
            return
        self._admin_permission_state = {'user_id': user_id, 'overrides': overrides, 'base': base, 'effective': effective}
        self.admin_perm_table.delete(*self.admin_perm_table.get_children())
        for permission in self.core.permissions.all_permissions():
            override = overrides.get(permission)
            override_label = 'Allow' if override is True else ('Deny' if override is False else '—')
            self.admin_perm_table.insert('', 'end', iid=permission, values=(
                permission, 'Allow' if permission in base else 'Deny', override_label,
                'Allow' if permission in effective else 'Deny'))

    def _admin_toggle_permission(self, _event=None):
        selected = self.admin_perm_table.selection()
        state = getattr(self, '_admin_permission_state', None)
        if not selected or not state:
            return
        permission = selected[0]
        current = state['overrides'].get(permission)
        state['overrides'][permission] = True if current is not True else False
        self._admin_refresh_permission_row(permission)

    def _admin_refresh_permission_row(self, permission):
        state = self._admin_permission_state
        override = state['overrides'].get(permission)
        effective = permission in state['base'] if override is None else override
        self.admin_perm_table.item(permission, values=(permission,
            'Allow' if permission in state['base'] else 'Deny',
            'Allow' if override is True else ('Deny' if override is False else '—'),
            'Allow' if effective else 'Deny'))

    def _admin_save_permission_override(self):
        state = getattr(self, '_admin_permission_state', None)
        selected = self.admin_perm_table.selection()
        if not state or not selected:
            return messagebox.showinfo('Permissions', 'Select a user and permission first.')
        permission = selected[0]
        self.core.permissions.set_user_permission(state['user_id'], permission, state['overrides'].get(permission, True))
        self._admin_load_permissions()

    def _admin_clear_permission_override(self):
        state = getattr(self, '_admin_permission_state', None)
        selected = self.admin_perm_table.selection()
        if not state or not selected:
            return messagebox.showinfo('Permissions', 'Select a user and permission first.')
        permission = selected[0]
        self.core.permissions.clear_user_permission(state['user_id'], permission)
        self._admin_load_permissions()

    def _build_admin_overview(self, parent):
        cards = tk.Frame(parent, bg=self._c('bg'))
        cards.pack(fill='x', pady=(4, 10))
        users = self.core.accounts.list_users()
        counts = {
            'Administrators': sum(1 for row in users if row['account_type'] == 'administrator'),
            'Employees': sum(1 for row in users if row['account_type'] == 'employee'),
            'Customers': sum(1 for row in users if row['account_type'] == 'customer'),
            'Disabled': sum(1 for row in users if not int(row['active'])),
        }
        for i, (title, value) in enumerate(counts.items()):
            card = self._metric_card(cards, title, value, self._c('purple'), 'Current account count')
            card.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else 7, 0))
            cards.columnconfigure(i, weight=1)

        info = self._card(parent, 'What belongs here')
        info.pack(fill='both', expand=True)
        text = (
            'Administration is the internal control center for FabOS.\n\n'
            '• Users & Accounts — activate/disable accounts, change account type, reset passwords, and revoke sessions.\n'
            '• Permissions — inspect role defaults and apply per-user overrides.\n'
            '• Settings — business, pricing, production, storefront, payment, notification, and system configuration.\n'
            '• Audit & Activity — review changes and operational history without exposing any of this to Fabvex customers.\n\n'
            'Customer accounts remain customer-facing identities. Employees and administrators are internal accounts.'
        )
        tk.Label(info, text=text, bg=self._c('surface'), fg=self._c('muted'),
                 justify='left', anchor='nw', wraplength=850).pack(fill='both', expand=True, padx=18, pady=(0, 18))
