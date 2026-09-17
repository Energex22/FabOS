import tkinter as tk
from tkinter import ttk, messagebox, simpledialog


class AdministrationMixin:
    """Administrator workspace for account, role, permission and settings control."""

    def _build_admin_page(self):
        self._admin_users = {}
        bar = tk.Frame(self.content, bg=self._c('bg'))
        bar.pack(fill='x', pady=(4, 10))
        self._button(bar, 'Refresh', self._admin_refresh, True).pack(side='left')
        self._button(bar, 'Edit Selected', self._admin_edit_user).pack(side='left', padx=7)
        self._button(bar, 'Reset Password', self._admin_reset_password).pack(side='left')
        self._button(bar, 'Revoke Sessions', self._admin_revoke_sessions).pack(side='left', padx=7)
        self._button(bar, 'Permissions', self._admin_permissions).pack(side='left')
        self._button(bar, 'Settings', lambda: self.show_page('Settings')).pack(side='left', padx=7)

        metrics = tk.Frame(self.content, bg=self._c('bg'))
        metrics.pack(fill='x', pady=(0, 10))
        self._admin_metric_cards = {}
        for i, (key, title, color) in enumerate((
            ('total', 'Accounts', 'purple'), ('customers', 'Customers', 'blue'),
            ('employees', 'Employees', 'green'), ('administrators', 'Administrators', 'orange'))):
            card = self._metric_card(metrics, title, 0, self._c(color), 'Active accounts')
            card.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else 7, 0))
            metrics.columnconfigure(i, weight=1)
            self._admin_metric_cards[key] = card

        shell = self._card(self.content, 'Users & Accounts')
        shell.pack(fill='both', expand=True)
        self.admin_user_table = ttk.Treeview(
            shell, columns=('username', 'email', 'type', 'active', 'last_login', 'permissions'),
            show='headings', style='Dark.Treeview', selectmode='browse')
        for col, title, width in (
            ('username', 'Username', 150), ('email', 'Email', 230), ('type', 'Account Type', 120),
            ('active', 'Active', 70), ('last_login', 'Last Login', 145), ('permissions', 'Permissions', 430)):
            self.admin_user_table.heading(col, text=title)
            self.admin_user_table.column(col, width=width, anchor='w', stretch=(col == 'permissions'))
        self.admin_user_table.bind('<Double-1>', lambda _e: self._admin_edit_user())
        self.admin_user_table.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self._admin_refresh()

    def _admin_refresh(self):
        if not getattr(self, 'admin_user_table', None):
            return
        try:
            rows = self.core.accounts.list_users()
        except Exception as exc:
            messagebox.showerror('Administration', str(exc))
            return
        self.admin_user_table.delete(*self.admin_user_table.get_children())
        self._admin_users = {}
        counts = {'total': 0, 'customers': 0, 'employees': 0, 'administrators': 0}
        for i, row in enumerate(rows):
            iid = 'admin_user_%d' % i
            self._admin_users[iid] = row
            account_type = str(row['account_type'] or '')
            key = account_type + 's'
            counts['total'] += 1
            if key in counts:
                counts[key] += 1
            permissions = sorted(self.core.permissions.permissions_for_user(row['id'], account_type))
            self.admin_user_table.insert('', 'end', iid=iid, values=(
                row['username'], row['email'] or '', account_type.title(),
                'Yes' if row['active'] else 'No', row['last_login_at'] or 'Never',
                ', '.join(permissions)))
        for key, value in counts.items():
            card = self._admin_metric_cards.get(key)
            if card:
                for child in card.winfo_children():
                    if isinstance(child, tk.Label) and str(child.cget('font')).find('bold') >= 0:
                        child.configure(text=str(value))

    def _admin_selected(self):
        selection = self.admin_user_table.selection() if getattr(self, 'admin_user_table', None) else ()
        return self._admin_users.get(selection[0]) if selection else None

    def _admin_edit_user(self):
        row = self._admin_selected()
        if not row:
            messagebox.showinfo('Administration', 'Select an account first.')
            return
        win = tk.Toplevel(self)
        win.title('Edit Account')
        win.geometry('470x330')
        win.configure(bg=self._c('bg'))
        win.transient(self)
        card = self._card(win, 'Account Details')
        card.pack(fill='both', expand=True, padx=16, pady=16)
        tk.Label(card, text='Username: %s' % row['username'], bg=self._c('surface'), fg=self._c('muted')).pack(anchor='w', padx=16, pady=(14, 8))
        tk.Label(card, text='Email', bg=self._c('surface'), fg=self._c('text')).pack(anchor='w', padx=16)
        email = tk.StringVar(value=row['email'] or '')
        self._entry(card, email, 42).pack(fill='x', padx=16, pady=(4, 10), ipady=5)
        tk.Label(card, text='Account Type', bg=self._c('surface'), fg=self._c('text')).pack(anchor='w', padx=16)
        kind = tk.StringVar(value=row['account_type'])
        combo = ttk.Combobox(card, textvariable=kind, values=('customer', 'employee', 'administrator'), state='readonly')
        combo.pack(fill='x', padx=16, pady=(4, 10))
        active = tk.BooleanVar(value=bool(row['active']))
        tk.Checkbutton(card, text='Account active', variable=active, bg=self._c('surface'), fg=self._c('text'),
                       activebackground=self._c('surface'), activeforeground=self._c('text'), selectcolor=self._c('surface_alt')).pack(anchor='w', padx=16)

        def save():
            if row['id'] == self.core.auth.current_user_id() and (not active.get() or kind.get() != 'administrator'):
                messagebox.showerror('Administration', 'You cannot disable or demote your own administrator account.', parent=win)
                return
            try:
                administrators = self.core.accounts.list_users(account_type='administrator', active_only=True)
                if row['account_type'] == 'administrator' and (not active.get() or kind.get() != 'administrator') and len(administrators) <= 1:
                    raise ValueError('At least one active administrator account must remain.')
                self.core.accounts.update_account(row['id'], email=email.get(), account_type=kind.get(), active=active.get())
                win.destroy()
                self._admin_refresh()
            except Exception as exc:
                messagebox.showerror('Administration', str(exc), parent=win)
        self._button(card, 'Save Account', save, True).pack(anchor='e', padx=16, pady=14)

    def _admin_reset_password(self):
        row = self._admin_selected()
        if not row:
            messagebox.showinfo('Administration', 'Select an account first.')
            return
        password = simpledialog.askstring('Reset Password', 'Enter a new password (minimum 8 characters):', parent=self, show='*')
        if password is None:
            return
        try:
            self.core.auth.set_password(row['id'], password)
            revoked = self.core.auth.revoke_user_sessions(row['id'])
            messagebox.showinfo('Administration', 'Password changed. %d active session(s) revoked.' % revoked)
        except Exception as exc:
            messagebox.showerror('Administration', str(exc))

    def _admin_revoke_sessions(self):
        row = self._admin_selected()
        if not row:
            messagebox.showinfo('Administration', 'Select an account first.')
            return
        try:
            count = self.core.auth.revoke_user_sessions(row['id'])
            messagebox.showinfo('Administration', '%d active session(s) revoked.' % count)
        except Exception as exc:
            messagebox.showerror('Administration', str(exc))

    def _admin_permissions(self):
        row = self._admin_selected()
        if not row:
            messagebox.showinfo('Administration', 'Select an account first.')
            return
        win = tk.Toplevel(self)
        win.title('Permissions — %s' % row['username'])
        win.geometry('760x620')
        win.configure(bg=self._c('bg'))
        win.transient(self)
        card = self._card(win, 'Effective Permissions')
        card.pack(fill='both', expand=True, padx=16, pady=16)
        table = ttk.Treeview(card, columns=('permission', 'role', 'effective'), show='headings', style='Dark.Treeview')
        for col, title, width in (('permission', 'Permission', 390), ('role', 'Role Default', 120), ('effective', 'Effective', 120)):
            table.heading(col, text=title); table.column(col, width=width, anchor='w')
        table.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        defaults = set(self.core.permissions.permissions_for_account_type(row['account_type']))
        effective = set(self.core.permissions.permissions_for_user(row['id'], row['account_type']))
        for permission in sorted(self.core.permissions.all_permissions()):
            table.insert('', 'end', iid='p_' + permission.replace('.', '_'), values=(permission, 'Allow' if permission in defaults else '—', 'Allow' if permission in effective else 'Deny'))
        tk.Label(card, text='Role defaults are shown for reference. Per-user overrides are managed by the same permission service used by the API.',
                 bg=self._c('surface'), fg=self._c('muted'), wraplength=680, justify='left').pack(anchor='w', padx=12, pady=(0, 12))
