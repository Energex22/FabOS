import tkinter as tk
from tkinter import messagebox, ttk, filedialog
from datetime import datetime
from pathlib import Path
import webbrowser
import shutil
import os
import uuid
import re
import threading
from urllib.request import Request, urlopen
from urllib.parse import urljoin, urlparse

from fabos_core.application import FabOSApplication
from fabos_core.events.bus import Event
from fabos_desktop.commerce_ui import CommerceMixin
from fabos_desktop.production_ui import ProductionMixin
from fabos_desktop.manufacturing_ui import ManufacturingMixin
from fabos_desktop.printer_ui import PrinterAutomationMixin
from fabos_desktop.inventory_ui import InventoryProfitMixin
from fabos_desktop.invoice_ui import InvoiceMixin
from fabos_desktop.system_ui import SystemReliabilityMixin
from fabos_desktop.product_print_ui import ProductPrintMixin


COLORS = {
    "bg": "#0a0b12",
    "sidebar": "#11121c",
    "surface": "#151725",
    "surface_alt": "#1b1d2d",
    "border": "#292c40",
    "text": "#f5f3ff",
    "muted": "#9a9daf",
    "purple": "#8b5cf6",
    "purple_dark": "#6d42d8",
    "blue": "#38bdf8",
    "green": "#34d399",
    "orange": "#fb923c",
    "red": "#f87171",
}


class FabOSDesktop(SystemReliabilityMixin, ProductPrintMixin, InvoiceMixin, InventoryProfitMixin, PrinterAutomationMixin, ManufacturingMixin, ProductionMixin, CommerceMixin, tk.Tk):
    """Windows 7-compatible dark desktop shell for the FabOS core."""

    def __init__(self) -> None:
        super().__init__()
        self.title("WireVault FabOS")
        self.geometry("1360x820")
        self.minsize(1040, 680)
        self.configure(bg=COLORS["bg"])
        self.core = FabOSApplication()
        self.active_page = "Dashboard"
        self.report_callback_exception=self._report_callback_exception
        self.product_sort_column = "name"
        self.product_sort_descending = False
        self.product_table = None
        self.product_detail_panel = None
        self.customer_sort_column = "name"
        self.customer_sort_descending = False
        self.customer_table = None
        self.quote_sort_column = "created"
        self.quote_sort_descending = True
        self.quote_table = None
        self.order_sort_column = "created"
        self.order_sort_descending = True
        self.order_table = None
        self.nav_buttons = {}
        self._auto_image_sync_started = False
        self._auto_image_sync_running = False
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self._configure_styles()
        self._build_shell()
        self._bind_global_shortcuts()
        self.show_page("Dashboard")
        self.after(1200,self._refresh_notification_badge)
        self.after(1600,self._refresh_system_footer)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        # Windows 7 can ignore inherited ttk foregrounds depending on the active
        # system theme. Configure both the default Treeview class and the named
        # dark style, then force foreground colors for every widget state.
        for tree_style in ("Treeview", "Dark.Treeview"):
            style.configure(
                tree_style,
                background=COLORS["surface"],
                fieldbackground=COLORS["surface"],
                foreground=COLORS["text"],
                rowheight=30,
                borderwidth=0,
                relief="flat",
                font=("Segoe UI", 9),
            )
            style.map(
                tree_style,
                background=[("selected", COLORS["purple_dark"]),
                            ("!selected", COLORS["surface"])],
                foreground=[("selected", "#ffffff"),
                            ("!selected", COLORS["text"])],
            )
        for heading_style in ("Treeview.Heading", "Dark.Treeview.Heading"):
            style.configure(
                heading_style,
                background=COLORS["surface_alt"],
                foreground="#ffffff",
                relief="flat",
                font=("Segoe UI", 9, "bold"),
            )
            style.map(
                heading_style,
                background=[("active", COLORS["purple_dark"]),
                            ("!active", COLORS["surface_alt"])],
                foreground=[("active", "#ffffff"),
                            ("!active", "#ffffff")],
            )
        style.configure(
            "Purple.Horizontal.TProgressbar",
            troughcolor=COLORS["surface_alt"],
            background=COLORS["purple"],
            bordercolor=COLORS["surface_alt"],
            lightcolor=COLORS["purple"],
            darkcolor=COLORS["purple"],
        )
        # Force readable foregrounds across native ttk widgets on the dark theme.
        style.configure("TCombobox", fieldbackground=COLORS["surface_alt"],
                        background=COLORS["surface_alt"], foreground=COLORS["text"],
                        arrowcolor=COLORS["text"], bordercolor=COLORS["border"])
        style.map("TCombobox", fieldbackground=[("readonly", COLORS["surface_alt"])],
                  foreground=[("readonly", COLORS["text"])],
                  selectbackground=[("readonly", COLORS["purple_dark"])],
                  selectforeground=[("readonly", "white")])
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=COLORS["surface_alt"],
                        foreground=COLORS["text"], padding=(14, 8))
        style.map("TNotebook.Tab", background=[("selected", COLORS["purple_dark"])],
                  foreground=[("selected", "white")])
        style.configure("Vertical.TScrollbar", background=COLORS["surface_alt"],
                        troughcolor=COLORS["surface"], arrowcolor=COLORS["text"])
        style.configure("Horizontal.TScrollbar", background=COLORS["surface_alt"],
                        troughcolor=COLORS["surface"], arrowcolor=COLORS["text"])
        self.option_add("*TCombobox*Listbox.background", COLORS["surface_alt"])
        self.option_add("*TCombobox*Listbox.foreground", COLORS["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", COLORS["purple_dark"])
        self.option_add("*TCombobox*Listbox.selectForeground", "white")

    def _build_shell(self) -> None:
        self.sidebar = tk.Frame(self, bg=COLORS["sidebar"], width=230)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        brand = tk.Frame(self.sidebar, bg=COLORS["sidebar"])
        brand.pack(fill="x", padx=22, pady=(24, 26))
        tk.Label(
            brand, text="WIREVAULT", bg=COLORS["sidebar"], fg=COLORS["text"],
            font=("Segoe UI", 14, "bold"), anchor="w"
        ).pack(fill="x")
        tk.Label(
            brand, text="FABRICATION OS", bg=COLORS["sidebar"], fg=COLORS["purple"],
            font=("Segoe UI", 9, "bold"), anchor="w"
        ).pack(fill="x", pady=(3, 0))

        workspaces = [
            ("Dashboard", "▦", "Dashboard"),
            ("Catalog", "◫", "Products"),
            ("Business", "$", "Quotes"),
            ("Production", "▶", "Production"),
            ("Inventory", "◉", "Filament"),
            ("System", "⚙", "Settings"),
        ]
        nav = tk.Frame(self.sidebar, bg=COLORS["sidebar"])
        nav.pack(fill="both", expand=True, padx=12)
        for workspace, icon, default_page in workspaces:
            button = tk.Button(
                nav, text="  %s   %s" % (icon, workspace), anchor="w",
                bg=COLORS["sidebar"], fg=COLORS["muted"], activebackground=COLORS["surface_alt"],
                activeforeground=COLORS["text"], bd=0, relief="flat",
                font=("Segoe UI", 10), padx=10, pady=12,
                command=lambda selected=default_page: self.show_page(selected),
            )
            button.pack(fill="x", pady=3)
            self.nav_buttons[workspace] = button

        footer = tk.Frame(self.sidebar, bg=COLORS["sidebar"])
        footer.pack(fill="x", padx=20, pady=18)
        tk.Label(footer, text="SYSTEM STATUS", bg=COLORS["sidebar"], fg=COLORS["muted"],
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x")
        self.system_status_label=tk.Label(footer,text="●  Checking…",bg=COLORS["sidebar"],fg=COLORS["muted"],
                 font=("Segoe UI",9),anchor="w")
        self.system_status_label.pack(fill="x",pady=(6,0))
        self.system_status_label.configure(cursor="hand2")
        self.system_status_label.bind("<Button-1>",lambda _e:self.show_page("Backup & Health"))

        self.main = tk.Frame(self, bg=COLORS["bg"])
        self.main.pack(side="right", fill="both", expand=True)

        self.header = tk.Frame(self.main, bg=COLORS["bg"], height=78)
        self.header.pack(fill="x", padx=28, pady=(18, 0))
        self.header.pack_propagate(False)

        title_group = tk.Frame(self.header, bg=COLORS["bg"])
        title_group.pack(side="left", fill="y")
        self.page_title = tk.Label(title_group, text="Dashboard", bg=COLORS["bg"], fg=COLORS["text"],
                                   font=("Segoe UI", 21, "bold"), anchor="w")
        self.page_title.pack(anchor="w")
        self.page_subtitle = tk.Label(title_group, text="Your fabrication business at a glance",
                                      bg=COLORS["bg"], fg=COLORS["muted"],
                                      font=("Segoe UI", 9), anchor="w")
        self.page_subtitle.pack(anchor="w", pady=(4, 0))

        tools = tk.Frame(self.header, bg=COLORS["bg"])
        tools.pack(side="right", fill="y")
        search_wrap = tk.Frame(tools, bg=COLORS["surface"], highlightbackground=COLORS["border"],
                               highlightthickness=1)
        search_wrap.pack(side="left", padx=(0, 12), pady=8)
        self.search_var = tk.StringVar()
        search = tk.Entry(search_wrap, textvariable=self.search_var, bg=COLORS["surface"],
                          fg=COLORS["text"], insertbackground=COLORS["text"], selectbackground=COLORS["purple_dark"], selectforeground="white", bd=0,
                          font=("Segoe UI", 10), width=28)
        search.pack(side="left", padx=12, pady=9)
        search.bind("<Return>", lambda _event: self.global_search())
        tk.Button(search_wrap, text="Search", bg=COLORS["surface"], fg=COLORS["muted"],
                  activebackground=COLORS["surface_alt"], activeforeground=COLORS["text"],
                  bd=0, command=self.global_search).pack(side="right", padx=8)
        self.notification_button=tk.Button(
            tools,text="🔔 0",bg=COLORS["surface_alt"],fg=COLORS["text"],bd=0,
            activebackground=COLORS["border"],activeforeground="white",
            font=("Segoe UI",10,"bold"),padx=12,pady=10,command=self._show_notifications)
        self.notification_button.pack(side="left",pady=8,padx=(0,8))
        tk.Button(tools, text="+  New", bg=COLORS["purple"], fg="white", bd=0,
                  activebackground=COLORS["purple_dark"], activeforeground="white",
                  font=("Segoe UI", 10, "bold"), padx=18, pady=10,
                  command=self.quick_add).pack(side="left", pady=8)

        self.content = tk.Frame(self.main, bg=COLORS["bg"])
        self.content.pack(fill="both", expand=True, padx=28, pady=(4, 24))

    def _clear_content(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()


    WORKSPACES = {
        "Dashboard": ("Dashboard", ["Dashboard"]),
        "Products": ("Catalog", ["Products", "Design Vault"]),
        "Design Vault": ("Catalog", ["Products", "Design Vault"]),
        "Customers": ("Business", ["Customers", "Quotes", "Orders", "Invoices", "Analytics"]),
        "Quotes": ("Business", ["Customers", "Quotes", "Orders", "Invoices", "Analytics"]),
        "Orders": ("Business", ["Customers", "Quotes", "Orders", "Invoices", "Analytics"]),
        "Invoices": ("Business", ["Customers", "Quotes", "Orders", "Invoices", "Analytics"]),
        "Analytics": ("Business", ["Customers", "Quotes", "Orders", "Invoices", "Analytics"]),
        "Production": ("Production", ["Production", "Printers", "QC"]),
        "Printers": ("Production", ["Production", "Printers", "QC"]),
        "QC": ("Production", ["Production", "Printers", "QC"]),
        "Filament": ("Inventory", ["Filament"]),
        "Backup & Health": ("System", ["Backup & Health", "Activity", "Logs & Version", "Settings", "Automation", "Plugins"]),
        "Activity": ("System", ["Backup & Health", "Activity", "Logs & Version", "Settings", "Automation", "Plugins"]),
        "Logs & Version": ("System", ["Backup & Health", "Activity", "Logs & Version", "Settings", "Automation", "Plugins"]),
        "Automation": ("System", ["Backup & Health", "Activity", "Logs & Version", "Settings", "Automation", "Plugins"]),
        "Plugins": ("System", ["Backup & Health", "Activity", "Logs & Version", "Settings", "Automation", "Plugins"]),
        "Settings": ("System", ["Backup & Health", "Activity", "Logs & Version", "Settings", "Automation", "Plugins"]),
    }

    def _workspace_name(self, page_name):
        return self.WORKSPACES.get(page_name, (page_name, [page_name]))[0]

    def _build_workspace_tabs(self, page_name):
        workspace, pages = self.WORKSPACES.get(page_name, (page_name, [page_name]))
        if workspace == "Dashboard" or len(pages) <= 1:
            return
        tabs = tk.Frame(self.content, bg=COLORS["bg"])
        tabs.pack(fill="x", pady=(0, 12))
        for page in pages:
            selected = page == page_name
            button = tk.Button(
                tabs, text=page, bd=0, relief="flat",
                bg=COLORS["purple_dark"] if selected else COLORS["surface_alt"],
                fg="white" if selected else COLORS["muted"],
                activebackground=COLORS["purple"] if selected else COLORS["border"],
                activeforeground="white",
                font=("Segoe UI", 9, "bold" if selected else "normal"),
                padx=16, pady=8,
                command=lambda target=page: self.show_page(target),
            )
            button.pack(side="left", padx=(0, 6))

    def _report_callback_exception(self,exc_type,exc_value,exc_tb):
        try:self.core.error_log.error("Tkinter callback exception",exc_value,{"page":self.active_page})
        except Exception:pass
        messagebox.showerror(
            "FabOS Error",
            "FabOS hit an unexpected error on %s.\n\n%s\n\n"
            "The details were saved to the FabOS log. Open System → Logs & Version to review or export diagnostics."%
            (self.active_page,str(exc_value)))

    def _empty_state(self,parent,title,detail="",action_text=None,action=None):
        box=tk.Frame(parent,bg=COLORS["surface"]);box.pack(fill="both",expand=True,padx=16,pady=16)
        tk.Label(box,text=title,bg=COLORS["surface"],fg=COLORS["text"],font=("Segoe UI",12,"bold")).pack(pady=(40,6))
        if detail:tk.Label(box,text=detail,bg=COLORS["surface"],fg=COLORS["muted"],wraplength=620,justify="center").pack()
        if action_text and action:self._button(box,action_text,action,True).pack(pady=14)

    def _build_logs_version_page(self):
        info=self.core.diagnostics.version_info()
        metrics=tk.Frame(self.content,bg=COLORS["bg"]);metrics.pack(fill="x",pady=(4,10))
        cards=[
            ("FabOS",info["fabos_version"],COLORS["purple"],"Application version"),
            ("Schema",info["schema_version"],COLORS["blue"],"Database migration version"),
            ("Python",info["python"],COLORS["green"],"Runtime"),
            ("Log Entries",len(self.core.error_log.recent(500)),COLORS["orange"],"Recent application log"),
        ]
        for i,(title,value,color,detail) in enumerate(cards):
            c=self._metric_card(metrics,title,value,color,detail);c.grid(row=0,column=i,sticky="nsew",padx=(0 if i==0 else 7,0));metrics.columnconfigure(i,weight=1)

        bar=tk.Frame(self.content,bg=COLORS["bg"]);bar.pack(fill="x",pady=(0,10))
        self._button(bar,"Export Diagnostics",self._export_diagnostics,True).pack(side="left")
        self._button(bar,"Open Log Folder",lambda:self._open_path(self.core.settings.log_dir)).pack(side="left",padx=7)
        self._button(bar,"Test Latest Backup",self._test_latest_backup).pack(side="left")
        self._button(bar,"Refresh",lambda:self.show_page("Logs & Version")).pack(side="left",padx=7)

        card=self._card(self.content,"Application Log");card.pack(fill="both",expand=True)
        cols=("time","level","message","detail")
        table=ttk.Treeview(card,columns=cols,show="headings",style="Dark.Treeview")
        for col,label,width in [("time","Time",145),("level","Level",75),("message","Message",250),("detail","Details",520)]:
            table.heading(col,text=label);table.column(col,width=width,anchor="w",stretch=(col=="detail"))
        for i,row in enumerate(self.core.error_log.recent(500)):
            detail=(row.get("detail") or "").replace("\n"," ")[:1000]
            table.insert("","end",iid="log_%d"%i,values=(row.get("time",""),row.get("level",""),row.get("message",""),detail),
                         tags=(str(row.get("level","")).lower(),))
        table.tag_configure("error",foreground=COLORS["red"]);table.tag_configure("warning",foreground=COLORS["orange"])
        shell=tk.Frame(card,bg=COLORS["surface"]);shell.pack(fill="both",expand=True,padx=12,pady=(0,12))
        sy=ttk.Scrollbar(shell,orient="vertical",command=table.yview);sx=ttk.Scrollbar(shell,orient="horizontal",command=table.xview)
        table.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        table.grid(row=0,column=0,sticky="nsew");sy.grid(row=0,column=1,sticky="ns");sx.grid(row=1,column=0,sticky="ew")
        shell.rowconfigure(0,weight=1);shell.columnconfigure(0,weight=1)

    def _export_diagnostics(self):
        try:
            path=self.core.diagnostics.export()
            messagebox.showinfo("Diagnostics Exported","FabOS diagnostics were saved to:\n\n%s\n\nAPI keys and secrets are redacted."%path)
        except Exception as exc:
            try:self.core.error_log.error("Diagnostics export failed",exc)
            except Exception:pass
            messagebox.showerror("Diagnostics",str(exc))

    def _test_latest_backup(self):
        result=self.core.backups.test_latest()
        if result.get("valid"):messagebox.showinfo("Backup Test","✓ Latest backup passed validation.\n\n"+result.get("detail",""))
        else:messagebox.showerror("Backup Test","Latest backup failed validation:\n\n"+result.get("detail",""))

    def _open_path(self,path):
        try:
            import os
            if hasattr(os,"startfile"):os.startfile(str(path))
        except Exception as exc:messagebox.showerror("Open Folder",str(exc))

    def show_page(self, page_name: str) -> None:
        self.active_page = page_name
        workspace = self._workspace_name(page_name)
        self.page_title.configure(text=workspace)
        subtitles = {
            "Dashboard": "Your fabrication business at a glance",
            "Products": "Products, images, licensing and one-click printing",
            "Design Vault": "Models, versions, manufacturing files and print profiles",
            "Customers": "Customer records, preferences and lifetime activity",
            "Quotes": "Active quotes, quote history and approvals",
            "Orders": "Track approved customer work through delivery",
            "Invoices": "Billing and payment records",
            "Analytics": "Profitability, tracked costs and manufacturing performance",
            "Production": "Schedule and monitor manufacturing jobs",
            "Printers": "Live OctoPrint status, temperatures and printer control",
            "QC": "Inspect completed prints before orders become ready",
            "Filament": "Spools, costs, consumption and predicted shortages",
            "Automation": "Rules and event-driven shop workflows",
            "Plugins": "Optional integrations and FabOS modules",
            "Backup & Health": "Backups, restore points and FabOS diagnostics",
            "Activity": "Business and production activity history with safe undo hooks",
            "Logs & Version": "FabOS version, errors, diagnostics and upgrade information",
            "Settings": "Application and integration preferences",
        }
        self.page_subtitle.configure(text=subtitles.get(page_name, "FabOS workspace"))
        for name, button in self.nav_buttons.items():
            if name == workspace:
                button.configure(bg=COLORS["purple_dark"], fg="white", font=("Segoe UI", 10, "bold"))
            else:
                button.configure(bg=COLORS["sidebar"], fg=COLORS["muted"], font=("Segoe UI", 10))

        self._clear_content()
        try:
            self._build_workspace_tabs(page_name)
            builders = {
                "Dashboard": self._build_dashboard,
                "Products": self._build_products_page,
                "Customers": self._build_customers_page,
                "Quotes": self._build_quotes_page,
                "Orders": self._build_orders_page,
                "Production": self._build_production_page,
                "Design Vault": self._build_design_vault_page,
                "QC": self._build_qc_page,
                "Printers": self._build_printers_page,
                "Filament": self._build_filament_page,
                "Analytics": self._build_analytics_page,
                "Invoices": self._build_invoices_page,
                "Backup & Health": self._build_backup_health_page,
                "Activity": self._build_activity_page,
                "Logs & Version": self._build_logs_version_page,
                "Settings": self._build_settings_page,
            }
            builder=builders.get(page_name)
            if builder:
                builder()
            else:
                self._build_module_page(page_name)
        except Exception as exc:
            try:self.core.error_log.error("Workspace build failed",exc,{"page":page_name})
            except Exception:pass
            self._render_workspace_error(page_name,exc)

    def _render_workspace_error(self,page_name,exc):
        self._clear_content()
        card=self._card(self.content,"Workspace Error")
        card.pack(fill="both",expand=True,padx=4,pady=4)
        tk.Label(card,text="This workspace could not be opened.",
                 bg=COLORS["surface"],fg=COLORS["red"],
                 font=("Segoe UI",14,"bold")).pack(anchor="w",padx=18,pady=(18,6))
        tk.Label(card,text=str(exc),bg=COLORS["surface"],fg=COLORS["text"],
                 wraplength=850,justify="left").pack(anchor="w",padx=18,pady=(0,5))
        tk.Label(card,text="FabOS logged the full error. You can retry this page, open the log, or export diagnostics without closing FabOS.",
                 bg=COLORS["surface"],fg=COLORS["muted"],wraplength=850,justify="left").pack(anchor="w",padx=18,pady=(0,16))
        buttons=tk.Frame(card,bg=COLORS["surface"]);buttons.pack(anchor="w",padx=18,pady=(0,18))
        self._button(buttons,"Retry",lambda:self.show_page(page_name),True).pack(side="left")
        self._button(buttons,"Open Logs",lambda:self.show_page("Logs & Version")).pack(side="left",padx=7)
        self._button(buttons,"Export Diagnostics",self._export_diagnostics).pack(side="left")

    def _card(self, parent, title="", bg=None):
        frame = tk.Frame(parent, bg=bg or COLORS["surface"], highlightbackground=COLORS["border"],
                         highlightthickness=1)
        if title:
            tk.Label(frame, text=title, bg=bg or COLORS["surface"], fg=COLORS["text"],
                     font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x", padx=16, pady=(14, 8))
        return frame

    def _metric_card(self, parent, title, value, accent, detail):
        card = self._card(parent)
        top = tk.Frame(card, bg=COLORS["surface"])
        top.pack(fill="x", padx=16, pady=(14, 2))
        tk.Label(top, text=title.upper(), bg=COLORS["surface"], fg=COLORS["muted"],
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
        tk.Label(top, text="●", bg=COLORS["surface"], fg=accent,
                 font=("Segoe UI", 11)).pack(side="right")
        tk.Label(card, text=str(value), bg=COLORS["surface"], fg=COLORS["text"],
                 font=("Segoe UI", 25, "bold"), anchor="w").pack(fill="x", padx=16)
        tk.Label(card, text=detail, bg=COLORS["surface"], fg=accent,
                 font=("Segoe UI", 8), anchor="w").pack(fill="x", padx=16, pady=(4, 14))
        return card

    def _bind_dashboard_link(self, widget, target_page):
        def open_page(_event=None):
            self.show_page(target_page)
        try:
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", open_page)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._bind_dashboard_link(child, target_page)

    def _scrollable_frame(self,parent,bg=None,height=None):
        """Create a mouse-wheel scrollable vertical content frame."""
        bg=bg or COLORS["surface"]
        shell=tk.Frame(parent,bg=bg)
        shell.pack(fill="both",expand=True,padx=4,pady=(0,6))
        canvas=tk.Canvas(shell,bg=bg,highlightthickness=0,borderwidth=0,
                         height=height if height else 1)
        scrollbar=ttk.Scrollbar(shell,orient="vertical",command=canvas.yview)
        inner=tk.Frame(canvas,bg=bg)
        window_id=canvas.create_window((0,0),window=inner,anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def sync_region(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            needed=inner.winfo_reqheight()>max(1,canvas.winfo_height())
            if needed and not scrollbar.winfo_ismapped():
                scrollbar.pack(side="right",fill="y")
            elif not needed and scrollbar.winfo_ismapped():
                scrollbar.pack_forget()

        def sync_width(event):
            canvas.itemconfigure(window_id,width=event.width)
            sync_region()

        inner.bind("<Configure>",sync_region)
        canvas.bind("<Configure>",sync_width)
        canvas.pack(side="left",fill="both",expand=True)

        def wheel(event):
            if getattr(event,"delta",0):
                canvas.yview_scroll(int(-1*(event.delta/120)),"units")
            elif getattr(event,"num",None)==4:
                canvas.yview_scroll(-1,"units")
            elif getattr(event,"num",None)==5:
                canvas.yview_scroll(1,"units")
            return "break"

        def bind_tree(widget):
            widget.bind("<MouseWheel>",wheel,add="+")
            widget.bind("<Button-4>",wheel,add="+")
            widget.bind("<Button-5>",wheel,add="+")
            for child in widget.winfo_children():
                bind_tree(child)

        def enter(_event=None):
            bind_tree(inner)
            canvas.bind("<MouseWheel>",wheel,add="+")
            canvas.bind("<Button-4>",wheel,add="+")
            canvas.bind("<Button-5>",wheel,add="+")
        canvas.bind("<Enter>",enter)
        inner.bind("<Enter>",enter)
        return inner,canvas,scrollbar

    def _build_dashboard(self) -> None:
        summary=self.core.summary()
        try:items=self.core.operations.refresh_notifications()
        except Exception:items=[]

        recovered=list(getattr(self.core,'recovered_jobs',[]) or [])
        if recovered:
            recovery=self._card(self.content,"Startup Recovery")
            recovery.pack(fill="x",pady=(4,10))
            row=tk.Frame(recovery,bg=COLORS["surface"]);row.pack(fill="x",padx=16,pady=(0,12))
            tk.Label(row,text="✓ FabOS reconciled %d active print job%s after the previous unclean shutdown."%
                     (len(recovered),"" if len(recovered)==1 else "s"),
                     bg=COLORS["surface"],fg=COLORS["orange"],font=("Segoe UI",9,"bold"),
                     anchor="w").pack(side="left",fill="x",expand=True)
            self._button(row,"Review Production",lambda:self.show_page("Production")).pack(side="right")

        metrics=tk.Frame(self.content,bg=COLORS["bg"])
        metrics.pack(fill="x",pady=(4,12))
        low_threshold=self.core.shop_settings.get("filament_low_threshold_g","250")
        cards=[
            ("Open Orders",summary.get("orders",0),COLORS["blue"],"Active customer work","Orders"),
            ("Queued Jobs",summary.get("queued_jobs",0),COLORS["purple"],"Waiting for production","Production"),
            ("Needs Attention",sum(1 for x in items if x["severity"] in ("high","medium")),COLORS["orange"],"Action Center items","Dashboard"),
            ("Printers",summary.get("printers",0),COLORS["green"],"Configured machines","Printers"),
            ("Low Filament",summary.get("low_spools",0),COLORS["red"],"Below %sg"%low_threshold,"Filament"),
        ]
        for col,(title,value,accent,detail,target) in enumerate(cards):
            card=self._metric_card(metrics,title,value,accent,detail)
            card.grid(row=0,column=col,sticky="nsew",padx=(0 if col==0 else 6,0))
            self._bind_dashboard_link(card, target)
            metrics.columnconfigure(col,weight=1)

        print_next=self._card(self.content,"Print Next")
        print_next.pack(fill="x",pady=(0,10))
        self._build_print_next_card(print_next)

        body=tk.Frame(self.content,bg=COLORS["bg"])
        body.pack(fill="both",expand=True)
        body.columnconfigure(0,weight=3);body.columnconfigure(1,weight=2)
        body.rowconfigure(0,weight=1)

        action=self._card(body,"Action Center")
        action.grid(row=0,column=0,sticky="nsew",padx=(0,7))
        self._build_action_center(action,items)

        right=tk.Frame(body,bg=COLORS["bg"])
        right.grid(row=0,column=1,sticky="nsew",padx=(7,0))
        printers=self._card(right,"Live Printers");printers.pack(fill="x",pady=(0,10))
        self._build_printer_panel(printers)
        activity=self._card(right,"Activity");activity.pack(fill="both",expand=True)
        self._build_activity(activity)
        self._schedule_dashboard_refresh()

    def _build_production_overview(self, parent) -> None:
        columns = ("job", "product", "printer", "status", "progress")
        table = ttk.Treeview(parent, columns=columns, show="headings", style="Dark.Treeview", height=7)
        table.tag_configure("body", foreground=COLORS["text"], background=COLORS["surface"])
        headings = ["Job", "Product", "Printer", "Status", "Progress"]
        widths = [90, 210, 130, 110, 90]
        for name, heading, width in zip(columns, headings, widths):
            table.heading(name, text=heading)
            table.column(name, width=width, anchor="w")
        rows = self._dashboard_jobs()
        for row in rows:
            table.insert("", "end", values=row, tags=("body",))
        table.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        table.bind("<Double-1>", lambda _e: self.show_page("Production"))
        table.configure(cursor="hand2")

    def _dashboard_jobs(self):
        try:
            with self.core.database.connect() as conn:
                rows = conn.execute(
                    """SELECT substr(j.id,1,8), COALESCE(p.name,'Custom Job'),
                       COALESCE(pr.name,'Unassigned'), j.status,
                       CASE WHEN j.actual_minutes IS NOT NULL THEN '100%'
                            WHEN j.status='printing' THEN 'Active' ELSE '—' END
                       FROM print_jobs j
                       LEFT JOIN products p ON p.id=j.product_id
                       LEFT JOIN printers pr ON pr.id=j.printer_id
                       ORDER BY j.created_at DESC LIMIT 7"""
                ).fetchall()
            if rows:
                return [tuple(row) for row in rows]
        except Exception:
            pass
        return [
            ("—", "No production jobs yet", "Unassigned", "Ready", "—"),
            ("TIP", "Create an order, then schedule its print", "", "", ""),
        ]

    def _build_printer_panel(self,parent) -> None:
        try:
            rows=list(self.core.printer_automation.list())
        except Exception:
            rows=[]
        holder,canvas,scrollbar=self._scrollable_frame(parent,COLORS["surface"],height=235)
        if not rows:
            tk.Label(holder,text="No printers configured.",bg=COLORS["surface"],fg=COLORS["muted"]).pack(anchor="w",padx=16,pady=14)
            return
        for p in rows:
            line=tk.Frame(holder,bg=COLORS["surface"],cursor="hand2")
            line.pack(fill="x",padx=14,pady=6)
            self._bind_dashboard_link(line,"Printers")
            left=tk.Frame(line,bg=COLORS["surface"]);left.pack(side="left",fill="x",expand=True)
            state=str(p["octoprint_state_text"] or p["status"] or "Unknown")
            file=str(p["octoprint_current_file"] or "")
            tk.Label(left,text=p["name"],bg=COLORS["surface"],fg=COLORS["text"],font=("Segoe UI",9,"bold"),anchor="w").pack(fill="x")
            detail=state
            if file:detail+=" • "+file
            tk.Label(left,text=detail,bg=COLORS["surface"],fg=COLORS["muted"],font=("Segoe UI",8),anchor="w").pack(fill="x")
            temp="%.0f° / %.0f°"%(float(p["nozzle_temp"] or 0),float(p["bed_temp"] or 0))
            leftsec=float(p["print_time_left_seconds"] or 0)
            if leftsec>0:temp+=" • %dh %02dm left"%(int(leftsec)//3600,(int(leftsec)%3600)//60)
            color=COLORS["green"] if str(p["status"]).lower() in ("idle","online","operational") else (COLORS["purple"] if str(p["status"]).lower()=="printing" else COLORS["orange"])
            tk.Label(line,text=temp,bg=COLORS["surface_alt"],fg=color,font=("Segoe UI",8,"bold"),padx=8,pady=5).pack(side="right")

    def _build_activity(self,parent) -> None:
        try:rows=self.core.operations.recent_activity(7)
        except Exception:rows=[]
        if not rows:
            try:
                with self.core.database.connect() as conn:
                    rows=conn.execute("""SELECT event_type,event_type title,payload_json detail,
                      '' page,aggregate_id entity_id,occurred_at created_at
                      FROM domain_events ORDER BY occurred_at DESC LIMIT 7""").fetchall()
            except Exception:rows=[]
        holder,canvas,scrollbar=self._scrollable_frame(parent,COLORS["surface"],height=230)
        if not rows:
            tk.Label(holder,text="Activity will appear here as FabOS works.",bg=COLORS["surface"],fg=COLORS["muted"]).pack(anchor="w",padx=16,pady=14)
            return
        for r in rows:
            row=tk.Frame(holder,bg=COLORS["surface"],cursor="hand2");row.pack(fill="x",padx=10,pady=5)
            title=(r["title"] if "title" in r.keys() else str(r["event_type"]).replace("."," ").title())
            tk.Label(row,text="●",bg=COLORS["surface"],fg=COLORS["purple"]).pack(side="left",padx=(0,7))
            tk.Label(row,text=title,bg=COLORS["surface"],fg=COLORS["text"],font=("Segoe UI",8),anchor="w").pack(side="left",fill="x",expand=True)
            tk.Label(row,text=str(r["created_at"])[:16],bg=COLORS["surface"],fg=COLORS["muted"],font=("Segoe UI",7)).pack(side="right")

    def _schedule_dashboard_refresh(self):
        self._dashboard_refresh_token=getattr(self,"_dashboard_refresh_token",0)+1
        token=self._dashboard_refresh_token
        try:seconds=max(3,int(float(self.core.shop_settings.get("dashboard_auto_refresh_seconds","5") or 5)))
        except Exception:seconds=5
        self.after(seconds*1000,lambda:self._dashboard_refresh_tick(token))

    def _dashboard_refresh_tick(self,token):
        if token!=getattr(self,"_dashboard_refresh_token",None) or self.active_page!="Dashboard":return
        self.show_page("Dashboard")

    def _refresh_system_footer(self):
        if getattr(self,"_system_footer_busy",False):
            self.after(15000,self._refresh_system_footer);return
        self._system_footer_busy=True
        def worker():
            try:
                checks=self.core.operations.system_ready()
                fails=sum(1 for x in checks if x["status"]=="fail")
                warns=sum(1 for x in checks if x["status"]=="warn")
                if fails:text,color="●  %d system issue%s"%(fails,"" if fails==1 else "s"),COLORS["red"]
                elif warns:text,color="⚠  %d warning%s — click for details"%(warns,"" if warns==1 else "s"),COLORS["orange"]
                else:text,color="●  FabOS ready",COLORS["green"]
            except Exception:
                text,color="●  Core online",COLORS["green"]
            def apply():
                self._system_footer_busy=False
                try:self.system_status_label.configure(text=text,fg=color)
                except Exception:return
                self.after(15000,self._refresh_system_footer)
            self.after(0,apply)
        threading.Thread(target=worker,name='FabOS-SystemHealth',daemon=True).start()

    def _build_activity_page(self):
        bar=tk.Frame(self.content,bg=COLORS["bg"]);bar.pack(fill="x",pady=(4,10))
        self._button(bar,"Undo Last Safe Action",self._undo_last_action,True).pack(side="left")
        self._button(bar,"Refresh",lambda:self.show_page("Activity")).pack(side="left",padx=7)
        card=self._card(self.content,"Activity Journal");card.pack(fill="both",expand=True)
        cols=("time","type","title","detail","page","undo")
        table=ttk.Treeview(card,columns=cols,show="headings",style="Dark.Treeview")
        for c,label,w in [("time","Time",140),("type","Event",115),("title","Action",190),
                          ("detail","Details",320),("page","Area",90),("undo","Undo",70)]:
            table.heading(c,text=label);table.column(c,width=w,anchor="w",stretch=(c=="detail"))
        for row in self.core.operations.recent_activity(250):
            table.insert("","end",iid=row["id"],values=(
                str(row["created_at"])[:19],row["event_type"],row["title"],row["detail"] or "",
                row["page"] or "","Yes" if row["undo_type"] else ""))
        table_shell=tk.Frame(card,bg=COLORS["surface"]);table_shell.pack(fill="both",expand=True,padx=12,pady=(0,12))
        vscroll=ttk.Scrollbar(table_shell,orient="vertical",command=table.yview)
        hscroll=ttk.Scrollbar(table_shell,orient="horizontal",command=table.xview)
        table.configure(yscrollcommand=vscroll.set,xscrollcommand=hscroll.set)
        table.grid(row=0,column=0,sticky="nsew");vscroll.grid(row=0,column=1,sticky="ns")
        hscroll.grid(row=1,column=0,sticky="ew")
        table_shell.rowconfigure(0,weight=1);table_shell.columnconfigure(0,weight=1)

    def _build_print_next_card(self,parent):
        try:choice=self.core.operations.print_next()
        except Exception:choice=None
        body=tk.Frame(parent,bg=COLORS["surface"]);body.pack(fill="x",padx=16,pady=(0,14))
        if not choice:
            tk.Label(body,text="No production job is immediately runnable.",bg=COLORS["surface"],fg=COLORS["muted"],font=("Segoe UI",10)).pack(side="left")
            self._button(body,"Open Production",lambda:self.show_page("Production")).pack(side="right")
            return
        j=choice["job"];p=choice["printer"];s=choice["spool"];ready=choice["readiness"]
        left=tk.Frame(body,bg=COLORS["surface"]);left.pack(side="left",fill="x",expand=True)
        with self.core.database.connect() as c:
            product=c.execute("SELECT name FROM products WHERE id=?",(j["product_id"],)).fetchone()
        name=product["name"] if product else "Production Job"
        tk.Label(left,text="%s  •  %s"%(name,j["order_number"]),bg=COLORS["surface"],fg=COLORS["text"],font=("Segoe UI",12,"bold"),anchor="w").pack(fill="x")
        need=float(j["estimated_filament_g"] or 0);after=float(s["remaining_g"] or 0)-need
        detail="%s • %s %s • %s"%(p["name"],s["material"],s["color"] or "",ready["reason"])
        if need>0:detail+=" • %.0fg → %.0fg remaining"%(need,after)
        tk.Label(left,text=detail,bg=COLORS["surface"],fg=COLORS["muted"],anchor="w").pack(fill="x",pady=(3,0))
        self._button(body,"▶ PRINT NEXT",self._dashboard_print_next,True).pack(side="right",padx=(12,0))

    def _dashboard_print_next(self):
        choice=self.core.operations.print_next()
        if not choice:return messagebox.showinfo("Print Next","No production job is ready right now.")
        j=choice["job"];r=choice["readiness"]
        self._print_selected_product(
            product_id=j["product_id"],printer_id=j["printer_id"],spool_id=j["spool_id"],
            existing_job_id=j["id"],preferred_gcode=r.get("gcode"))

    def _build_action_center(self,parent,items=None):
        items=items if items is not None else self.core.operations.action_items()
        holder,canvas,scrollbar=self._scrollable_frame(parent,COLORS["surface"],height=360)
        if not items:
            tk.Label(holder,text="✓ Nothing needs attention right now.",bg=COLORS["surface"],fg=COLORS["green"],font=("Segoe UI",10,"bold")).pack(anchor="w",padx=16,pady=16)
            return
        rank={"high":0,"medium":1,"info":2}
        for item in sorted(items,key=lambda x:rank.get(x["severity"],9)):
            row=tk.Frame(holder,bg=COLORS["surface"],cursor="hand2");row.pack(fill="x",padx=10,pady=5)
            color={"high":COLORS["red"],"medium":COLORS["orange"],"info":COLORS["blue"]}.get(item["severity"],COLORS["muted"])
            tk.Label(row,text="●",bg=COLORS["surface"],fg=color,font=("Segoe UI",10)).pack(side="left",padx=(0,8))
            left=tk.Frame(row,bg=COLORS["surface"]);left.pack(side="left",fill="x",expand=True)
            tk.Label(left,text=item["title"],bg=COLORS["surface"],fg=COLORS["text"],font=("Segoe UI",9,"bold"),anchor="w").pack(fill="x")
            tk.Label(left,text=item["detail"],bg=COLORS["surface"],fg=COLORS["muted"],font=("Segoe UI",8),anchor="w",wraplength=620,justify="left").pack(fill="x")
            tk.Button(row,text="Open",bg=COLORS["surface_alt"],fg=COLORS["text"],bd=0,
                      command=lambda x=item:self._open_action_item(x)).pack(side="right",padx=(8,0))

    def _open_action_item(self,item):
        page=item.get("page") or "Dashboard"
        self.show_page(page)
        entity=item.get("id")
        if entity:
            self.after(120,lambda:self._select_entity_with_fallback(page,entity))

    def _select_entity_with_fallback(self,page,entity_id):
        self._select_entity_on_active_page(entity_id)
        # History/attention records may not exist in the default tab after opening a workspace.
        try:
            if page=="Products" and getattr(self,"product_table",None) and not self.product_table.exists(entity_id):
                self._switch_product_view("attention");self._select_entity_on_active_page(entity_id)
            elif page=="Quotes" and getattr(self,"quote_table",None) and not self.quote_table.exists(entity_id):
                self._switch_quote_view("history");self._select_entity_on_active_page(entity_id)
            elif page=="Orders" and getattr(self,"order_table",None) and not self.order_table.exists(entity_id):
                self._switch_order_view("history");self._select_entity_on_active_page(entity_id)
        except Exception:pass

    def _select_entity_on_active_page(self,entity_id):
        tables=[
            getattr(self,"product_table",None),getattr(self,"order_table",None),
            getattr(self,"quote_table",None),getattr(self,"production_table",None),
            getattr(self,"printer_table",None),getattr(self,"invoice_table",None),
            getattr(self,"qc_table",None),getattr(self,"filament_table",None),
            getattr(self,"customer_table",None)
        ]
        for table in tables:
            try:
                if table and table.exists(entity_id):
                    table.selection_set(entity_id);table.see(entity_id);return
            except Exception:pass

    def _refresh_notification_badge(self):
        if getattr(self,"_notification_refresh_busy",False):
            self.after(5000,self._refresh_notification_badge);return
        self._notification_refresh_busy=True
        def worker():
            try:count=self.core.operations.unread_count()
            except Exception:count=0
            def apply():
                self._notification_refresh_busy=False
                try:self.notification_button.configure(text="🔔 %d"%count,fg=COLORS["orange"] if count else COLORS["text"])
                except Exception:return
                self.after(5000,self._refresh_notification_badge)
            self.after(0,apply)
        threading.Thread(target=worker,name='FabOS-Notifications',daemon=True).start()

    def _show_notifications(self):
        rows=self.core.operations.notifications(True,100)
        win=tk.Toplevel(self);win.title("FabOS Notifications");win.geometry("760x560")
        win.minsize(600,420);win.configure(bg=COLORS["bg"]);win.transient(self)
        card=self._card(win,"Notifications");card.pack(fill="both",expand=True,padx=16,pady=16)
        top=tk.Frame(card,bg=COLORS["surface"]);top.pack(fill="x",padx=12,pady=(0,6))
        tk.Label(top,text="%d unread notification%s"%(len(rows),"" if len(rows)==1 else "s"),
                 bg=COLORS["surface"],fg=COLORS["muted"]).pack(side="left")
        self._button(top,"Mark All Read",
                     lambda:(self.core.operations.mark_all_notifications_read(),win.destroy()),
                     False).pack(side="right")
        holder,canvas,scrollbar=self._scrollable_frame(card,COLORS["surface"],height=430)
        if not rows:
            tk.Label(holder,text="✓ No unread notifications.",bg=COLORS["surface"],fg=COLORS["green"]).pack(anchor="w",padx=14,pady=14)
            return
        for n in rows:
            row=tk.Frame(holder,bg=COLORS["surface"]);row.pack(fill="x",padx=8,pady=6)
            color=COLORS["red"] if n["severity"]=="high" else COLORS["orange"]
            tk.Label(row,text="●",bg=COLORS["surface"],fg=color).pack(side="left",padx=(0,8))
            left=tk.Frame(row,bg=COLORS["surface"]);left.pack(side="left",fill="x",expand=True)
            tk.Label(left,text=n["title"],bg=COLORS["surface"],fg=COLORS["text"],font=("Segoe UI",9,"bold"),anchor="w").pack(fill="x")
            tk.Label(left,text=n["body"] or "",bg=COLORS["surface"],fg=COLORS["muted"],anchor="w",wraplength=500,justify="left").pack(fill="x")
            def open_notification(row=n):
                self.core.operations.mark_notification_read(row["id"]);win.destroy()
                self._open_action_item({"page":row["page"],"id":row["entity_id"]})
            tk.Button(row,text="Open",bg=COLORS["surface_alt"],fg=COLORS["text"],bd=0,
                      command=open_notification).pack(side="right",padx=(8,0))

    def _bind_global_shortcuts(self):
        self.bind_all("<Control-f>",lambda _e:self._focus_global_search())
        self.bind_all("<Control-p>",lambda _e:self._shortcut_print())
        self.bind_all("<F5>",lambda _e:self.show_page(self.active_page))
        self.bind_all("<Control-n>",lambda _e:self.quick_add())
        self.bind_all("<Control-z>",lambda _e:self._undo_last_action())

    def _focus_global_search(self):
        try:
            for child in self.header.winfo_children():
                for widget in child.winfo_children():
                    if isinstance(widget,tk.Frame):
                        for inner in widget.winfo_children():
                            if isinstance(inner,tk.Entry) and str(inner.cget("textvariable"))==str(self.search_var):
                                inner.focus_set();inner.select_range(0,"end");return
        except Exception:pass

    def _shortcut_print(self):
        if self.active_page=="Products":self._print_selected_product()
        elif self.active_page=="Production":self._production_start_print()
        else:self._dashboard_print_next()

    def _undo_last_action(self):
        try:
            action=next((x for x in self.core.operations.recent_activity(50) if x["undo_type"]),None)
            if not action:
                return messagebox.showinfo("Undo","There is no recent FabOS action that can be undone.")
            payload=__import__("json").loads(action["undo_payload_json"] or "{}")
            if action["undo_type"]=="order_status":
                self.core.orders.set_status(payload["order_id"],payload["old_status"])
                with self.core.database.connect() as c:
                    c.execute("UPDATE activity_journal SET undo_type=NULL,undo_payload_json=NULL WHERE id=?",(action["id"],));c.commit()
                self.core.operations.log("undo","Undid order status change","Restored "+payload["old_status"],"Orders",payload["order_id"])
                self.show_page("Orders")
            else:
                messagebox.showinfo("Undo","That action cannot be undone automatically.")
        except Exception as exc:messagebox.showerror("Undo",str(exc))

    def _build_actions(self, parent) -> None:
        actions = [
            ("New Quote", lambda: self.show_page("Quotes")),
            ("Add Product", lambda: self.show_page("Products")),
            ("Schedule Print", lambda: self.show_page("Production")),
            ("Add Filament", lambda: self.show_page("Filament")),
            ("Create Backup", lambda: self.show_page("Backup & Health")),
            ("View Printers", lambda: self.show_page("Printers")),
        ]
        grid = tk.Frame(parent, bg=COLORS["surface"])
        grid.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        for index, (label, command) in enumerate(actions):
            button = tk.Button(
                grid, text=label, command=command, bg=COLORS["surface_alt"], fg=COLORS["text"],
                activebackground=COLORS["purple_dark"], activeforeground="white",
                bd=0, relief="flat", font=("Segoe UI", 9, "bold"), pady=13
            )
            button.grid(row=index // 2, column=index % 2, sticky="nsew", padx=5, pady=5)
        for col in range(2):
            grid.columnconfigure(col, weight=1)
        for row in range(3):
            grid.rowconfigure(row, weight=1)

    def _build_module_page(self, page_name: str) -> None:
        toolbar = tk.Frame(self.content, bg=COLORS["bg"])
        toolbar.pack(fill="x", pady=(4, 12))
        tk.Button(toolbar, text="+ Add Record", bg=COLORS["purple"], fg="white", bd=0,
                  activebackground=COLORS["purple_dark"], activeforeground="white",
                  font=("Segoe UI", 9, "bold"), padx=16, pady=9,
                  command=lambda: self.publish_test_event(page_name + ".add")).pack(side="left")
        tk.Button(toolbar, text="Refresh", bg=COLORS["surface_alt"], fg=COLORS["text"], bd=0,
                  activebackground=COLORS["border"], activeforeground="white",
                  font=("Segoe UI", 9), padx=16, pady=9,
                  command=lambda: self.show_page(page_name)).pack(side="left", padx=8)

        card = self._card(self.content, page_name + " Workspace")
        card.pack(fill="both", expand=True)
        tk.Label(
            card,
            text=("This screen is connected to the shared FabOS engineering core. "
                  "The dark production interface is now the permanent desktop shell; "
                  "each detailed workflow can be implemented inside this layout without redesigning it again."),
            bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 10),
            justify="left", wraplength=760, anchor="w"
        ).pack(fill="x", padx=18, pady=(4, 18))
        self._build_placeholder_table(card, page_name)

    def _build_placeholder_table(self, parent, page_name):
        columns = ("name", "status", "updated")
        table = ttk.Treeview(parent, columns=columns, show="headings", style="Dark.Treeview")
        table.tag_configure("body", foreground=COLORS["text"], background=COLORS["surface"])
        for column, heading, width in (("name", page_name + " Record", 420),
                                       ("status", "Status", 180),
                                       ("updated", "Last Updated", 180)):
            table.heading(column, text=heading)
            table.column(column, width=width, anchor="w")
        table.insert("", "end", values=("Module ready for workflow implementation", "Core connected", datetime.now().strftime("%Y-%m-%d %H:%M")), tags=("body",))
        table.pack(fill="both", expand=True, padx=16, pady=(0, 16))


    def _build_customers_page(self) -> None:
        toolbar = tk.Frame(self.content, bg=COLORS["bg"])
        toolbar.pack(fill="x", pady=(4, 10))
        tk.Button(toolbar, text="+ Add Customer", bg=COLORS["purple"], fg="white", bd=0,
                  activebackground=COLORS["purple_dark"], activeforeground="white",
                  font=("Segoe UI", 9, "bold"), padx=15, pady=9,
                  command=self._add_customer).pack(side="left")
        for label, command in (("Edit", self._edit_customer), ("Details", self._customer_details),
                               ("Delete", self._delete_customer)):
            tk.Button(toolbar, text=label, bg=COLORS["surface_alt"], fg=COLORS["text"], bd=0,
                      activebackground=COLORS["border"], activeforeground="white",
                      font=("Segoe UI", 9), padx=13, pady=9, command=command).pack(side="left", padx=(7, 0))

        filters = self._card(self.content)
        filters.pack(fill="x", pady=(0, 10))
        row = tk.Frame(filters, bg=COLORS["surface"])
        row.pack(fill="x", padx=14, pady=11)
        tk.Label(row, text="Search customers", bg=COLORS["surface"], fg=COLORS["muted"],
                 font=("Segoe UI", 9)).pack(side="left")
        self.customer_query = tk.StringVar()
        entry = tk.Entry(row, textvariable=self.customer_query, bg=COLORS["surface_alt"],
                         fg=COLORS["text"], insertbackground=COLORS["text"], selectbackground=COLORS["purple_dark"], selectforeground="white", relief="flat",
                         width=38, font=("Segoe UI", 9))
        entry.pack(side="left", padx=(8, 14), ipady=6)
        entry.bind("<KeyRelease>", lambda _e: self._refresh_customers())
        self.customer_count = tk.Label(row, text="", bg=COLORS["surface"], fg=COLORS["purple"],
                                       font=("Segoe UI", 9, "bold"))
        self.customer_count.pack(side="right")

        card = self._card(self.content, "Customers")
        card.pack(fill="both", expand=True)
        columns = ("name", "email", "phone", "quotes", "orders", "value", "created")
        self.customer_table = ttk.Treeview(card, columns=columns, show="headings",
                                           style="Dark.Treeview", selectmode="browse")
        self.customer_table.tag_configure("body", foreground=COLORS["text"], background=COLORS["surface"])
        labels = {"name":"Customer", "email":"Email", "phone":"Phone", "quotes":"Quotes",
                  "orders":"Orders", "value":"Lifetime Value", "created":"Added"}
        widths = {"name":220,"email":240,"phone":140,"quotes":75,"orders":75,"value":120,"created":135}
        for col in columns:
            self.customer_table.heading(col, text=labels[col], command=lambda c=col: self._sort_customers(c))
            self.customer_table.column(col, width=widths[col], minwidth=65, anchor="w")
        ybar=ttk.Scrollbar(card,orient="vertical",command=self.customer_table.yview)
        xbar=ttk.Scrollbar(card,orient="horizontal",command=self.customer_table.xview)
        self.customer_table.configure(yscrollcommand=ybar.set,xscrollcommand=xbar.set)
        self.customer_table.pack(side="left",fill="both",expand=True,padx=(12,0),pady=(0,12))
        ybar.pack(side="right",fill="y",padx=(0,12),pady=(0,12))
        xbar.pack(side="bottom",fill="x",padx=12,pady=(0,12))
        self.customer_table.bind("<Double-1>", lambda _e: self._customer_details())
        self._refresh_customers()

    def _sort_customers(self, column):
        if self.customer_sort_column == column:
            self.customer_sort_descending = not self.customer_sort_descending
        else:
            self.customer_sort_column = column
            self.customer_sort_descending = False
        self._refresh_customers()

    def _refresh_customers(self):
        if not self.customer_table: return
        for item in self.customer_table.get_children(): self.customer_table.delete(item)
        rows=self.core.customers.list(self.customer_query.get().strip(),self.customer_sort_column,
                                      self.customer_sort_descending)
        for row in rows:
            self.customer_table.insert("","end",iid=row["id"],tags=("body",),values=(
                row["name"],row["email"] or "",row["phone"] or "",row["quote_count"],
                row["order_count"],"$%.2f" % ((row["lifetime_value"] or 0)/100.0),
                str(row["created_at"] or "")[:10]))
        labels={"name":"Customer","email":"Email","phone":"Phone","quotes":"Quotes",
                "orders":"Orders","value":"Lifetime Value","created":"Added"}
        arrow=" ▼" if self.customer_sort_descending else " ▲"
        for col,label in labels.items():
            self.customer_table.heading(col,text=label+(arrow if col==self.customer_sort_column else ""),
                                        command=lambda c=col:self._sort_customers(c))
        self.customer_count.configure(text="%d customers" % len(rows))

    def _selected_customer_id(self):
        selected=self.customer_table.selection() if self.customer_table else ()
        if not selected:
            messagebox.showinfo("Customers","Select a customer first."); return None
        return selected[0]

    def _add_customer(self): self._customer_form()

    def _edit_customer(self):
        customer_id=self._selected_customer_id()
        if customer_id: self._customer_form(customer_id)

    def _customer_form(self, customer_id=None):
        record=self.core.customers.get(customer_id) if customer_id else None
        win=tk.Toplevel(self); win.title("Edit Customer" if record else "Add Customer")
        win.geometry("640x590"); win.minsize(540,470); win.configure(bg=COLORS["bg"]); win.transient(self)
        body=tk.Frame(win,bg=COLORS["surface"]); body.pack(fill="both",expand=True,padx=16,pady=(16,8))
        canvas=tk.Canvas(body,bg=COLORS["surface"],highlightthickness=0)
        bar=ttk.Scrollbar(body,orient="vertical",command=canvas.yview)
        form=tk.Frame(canvas,bg=COLORS["surface"])
        form.bind("<Configure>",lambda _e:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0),window=form,anchor="nw",width=570); canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left",fill="both",expand=True); bar.pack(side="right",fill="y")
        fields={}
        for key,label in (("name","Customer Name"),("email","Email"),("phone","Phone")):
            tk.Label(form,text=label,bg=COLORS["surface"],fg=COLORS["muted"],anchor="w",
                     font=("Segoe UI",9)).pack(fill="x",padx=18,pady=(14,4))
            var=tk.StringVar(value=(record[key] if record and record[key] else "")); fields[key]=var
            tk.Entry(form,textvariable=var,bg=COLORS["surface_alt"],fg=COLORS["text"],
                     insertbackground=COLORS["text"],selectbackground=COLORS["purple_dark"],
                     selectforeground="white",relief="flat",font=("Segoe UI",10)).pack(fill="x",padx=18,ipady=7)
        tk.Label(form,text="Customer Notes / Preferences",bg=COLORS["surface"],fg=COLORS["muted"],
                 anchor="w",font=("Segoe UI",9)).pack(fill="x",padx=18,pady=(14,4))
        notes=tk.Text(form,height=10,bg=COLORS["surface_alt"],fg=COLORS["text"],
                      insertbackground=COLORS["text"],selectbackground=COLORS["purple_dark"],
                      selectforeground="white",relief="flat",wrap="word",font=("Segoe UI",9))
        notes.pack(fill="both",expand=True,padx=18,pady=(0,16))
        if record: notes.insert("1.0",record["notes"] or "")
        buttons=tk.Frame(win,bg=COLORS["bg"]); buttons.pack(fill="x",padx=16,pady=(0,16))
        def save():
            try:
                self.core.customers.save({"name":fields["name"].get(),"email":fields["email"].get(),
                                          "phone":fields["phone"].get(),"notes":notes.get("1.0","end").strip()},customer_id)
            except Exception as exc:
                messagebox.showerror("Could not save customer",str(exc),parent=win); return
            win.destroy(); self._refresh_customers()
        tk.Button(buttons,text="Save Customer",command=save,bg=COLORS["purple"],fg="white",bd=0,
                  padx=18,pady=10,font=("Segoe UI",9,"bold")).pack(side="right")
        tk.Button(buttons,text="Cancel",command=win.destroy,bg=COLORS["surface_alt"],fg=COLORS["text"],
                  bd=0,padx=18,pady=10).pack(side="right",padx=(0,8))

    def _customer_details(self):
        customer_id=self._selected_customer_id()
        if not customer_id:return
        record=self.core.customers.get(customer_id); quotes,orders=self.core.customers.activity(customer_id)
        win=tk.Toplevel(self); win.title(record["name"]); win.geometry("850x620"); win.configure(bg=COLORS["bg"])
        header=tk.Frame(win,bg=COLORS["surface"],padx=20,pady=16); header.pack(fill="x")
        tk.Label(header,text=record["name"],bg=COLORS["surface"],fg=COLORS["text"],
                 font=("Segoe UI",18,"bold")).pack(anchor="w")
        tk.Label(header,text="%s  •  %s" % (record["email"] or "No email",record["phone"] or "No phone"),
                 bg=COLORS["surface"],fg=COLORS["muted"],font=("Segoe UI",9)).pack(anchor="w",pady=(4,0))
        notebook=ttk.Notebook(win); notebook.pack(fill="both",expand=True,padx=16,pady=16)
        overview=tk.Frame(notebook,bg=COLORS["surface"]); qtab=tk.Frame(notebook,bg=COLORS["surface"]); otab=tk.Frame(notebook,bg=COLORS["surface"])
        notebook.add(overview,text="Overview"); notebook.add(qtab,text="Quotes (%d)"%len(quotes)); notebook.add(otab,text="Orders (%d)"%len(orders))
        tk.Label(overview,text=record["notes"] or "No customer notes yet.",bg=COLORS["surface_alt"],
                 fg=COLORS["text"],justify="left",anchor="nw",wraplength=730,padx=14,pady=14).pack(fill="both",expand=True,padx=18,pady=18)
        self._customer_activity_table(qtab,quotes,("quote_number","status","total_cents","created_at"),("Quote","Status","Total","Created"))
        self._customer_activity_table(otab,orders,("order_number","status","total_cents","created_at"),("Order","Status","Total","Created"))

    def _customer_activity_table(self,parent,rows,keys,labels):
        table=ttk.Treeview(parent,columns=keys,show="headings",style="Dark.Treeview")
        table.tag_configure("body", foreground=COLORS["text"], background=COLORS["surface"])
        for key,label in zip(keys,labels): table.heading(key,text=label); table.column(key,width=160,anchor="w")
        for row in rows:
            vals=[]
            for key in keys:
                value=row[key]
                if key=="total_cents": value="$%.2f"%((value or 0)/100.0)
                vals.append(value or "")
            table.insert("","end",values=vals,tags=("body",))
        table.pack(fill="both",expand=True,padx=12,pady=12)

    def _delete_customer(self):
        customer_id=self._selected_customer_id()
        if not customer_id:return
        record=self.core.customers.get(customer_id)
        if not messagebox.askyesno("Delete customer","Delete '%s'?"%record["name"]):return
        try:self.core.customers.delete(customer_id)
        except Exception as exc:messagebox.showerror("Could not delete customer",str(exc));return
        self._refresh_customers()


    def _build_products_page(self) -> None:
        toolbar = tk.Frame(self.content, bg=COLORS["bg"])
        toolbar.pack(fill="x", pady=(4, 10))
        tk.Button(toolbar, text="▶ Print", bg=COLORS["purple"], fg="white", bd=0,
                  activebackground=COLORS["purple_dark"], activeforeground="white",
                  font=("Segoe UI", 9, "bold"), padx=16, pady=9,
                  command=self._print_selected_product).pack(side="left")
        tk.Button(toolbar, text="+ Add Product", bg=COLORS["surface_alt"], fg=COLORS["text"], bd=0,
                  activebackground=COLORS["border"], activeforeground="white",
                  font=("Segoe UI", 9), padx=13, pady=9,
                  command=self._add_product).pack(side="left", padx=(7,0))
        tk.Button(toolbar, text="Edit", bg=COLORS["surface_alt"], fg=COLORS["text"], bd=0,
                  activebackground=COLORS["border"], activeforeground="white",
                  font=("Segoe UI", 9), padx=13, pady=9,
                  command=self._edit_product).pack(side="left", padx=(7,0))
        tk.Button(toolbar,text="Card View",bg=COLORS["surface_alt"],fg=COLORS["text"],bd=0,
                  activebackground=COLORS["border"],activeforeground="white",
                  font=("Segoe UI",9),padx=13,pady=9,command=self._product_card_gallery).pack(side="left",padx=(7,0))
        more = tk.Menubutton(toolbar, text="More ▾", bg=COLORS["surface_alt"], fg=COLORS["text"],
                             activebackground=COLORS["border"], activeforeground="white",
                             bd=0, relief="flat", font=("Segoe UI",9), padx=13, pady=9)
        menu = tk.Menu(more, tearoff=0, bg=COLORS["surface_alt"], fg=COLORS["text"],
                       activebackground=COLORS["purple_dark"], activeforeground="white")
        menu.add_command(label="Full Details", command=self._product_details)
        menu.add_command(label="Preview Image", command=self._product_preview)
        menu.add_command(label="Card Gallery", command=self._product_card_gallery)
        menu.add_command(label="Manage Images", command=self._manage_product_images)
        menu.add_command(label="Import / Replace Print File", command=self._import_downloaded_product_model)
        menu.add_command(label="Manage Model / Part Set", command=self._manage_product_model_set)
        menu.add_command(label="Manage Saved G-code", command=self._manage_product_gcode_library)
        menu.add_command(label="Download Model in Browser", command=self._download_product_model_browser)
        menu.add_command(label="Open Design Vault", command=self._open_selected_product_design)
        menu.add_command(label="Open Source Website", command=self._open_product_source)
        menu.add_separator()
        menu.add_command(label="Delete Product", command=self._delete_product)
        more.configure(menu=menu)
        more.pack(side="left", padx=(7,0))

        self.product_view=tk.StringVar(value="ready")
        tabs=tk.Frame(self.content,bg=COLORS["bg"])
        tabs.pack(fill="x",pady=(0,8))
        self.product_tab_buttons={}
        for label,value in [("Ready to Print","ready"),("Needs Attention","attention")]:
            button=tk.Button(
                tabs,text=label,bd=0,padx=18,pady=9,font=("Segoe UI",9,"bold"),
                command=lambda v=value:self._switch_product_view(v)
            )
            button.pack(side="left",padx=(0,6))
            self.product_tab_buttons[value]=button
        self._style_product_tabs()

        filters = self._card(self.content)
        filters.pack(fill="x", pady=(0, 10))
        row = tk.Frame(filters, bg=COLORS["surface"])
        row.pack(fill="x", padx=14, pady=11)
        tk.Label(row, text="Search", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(side="left")
        self.product_query = tk.StringVar()
        entry = tk.Entry(row, textvariable=self.product_query, bg=COLORS["surface_alt"], fg=COLORS["text"],
                         insertbackground=COLORS["text"], selectbackground=COLORS["purple_dark"], selectforeground="white", relief="flat", width=31, font=("Segoe UI", 9))
        entry.pack(side="left", padx=(7, 16), ipady=6)
        entry.bind("<KeyRelease>", lambda _e: self._refresh_products())
        tk.Label(row, text="Category", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(side="left")
        self.product_category = tk.StringVar(value="All")
        categories = ["All"] + self.core.products.categories()
        category_box = ttk.Combobox(row, textvariable=self.product_category, values=categories, state="readonly", width=22)
        category_box.pack(side="left", padx=(7, 16)); category_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh_products())
        tk.Label(row, text="License", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(side="left")
        self.product_license = tk.StringVar(value="All")
        license_box = ttk.Combobox(row, textvariable=self.product_license,
                                   values=["All", "verified", "review_required"], state="readonly", width=17)
        license_box.pack(side="left", padx=(7, 10)); license_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh_products())
        self.product_count = tk.Label(row, text="", bg=COLORS["surface"], fg=COLORS["purple"], font=("Segoe UI", 9, "bold"))
        self.product_count.pack(side="right")

        split = tk.PanedWindow(self.content, orient="horizontal", bg=COLORS["bg"],
                               sashwidth=6, sashrelief="flat", bd=0)
        split.pack(fill="both", expand=True)
        card = self._card(split, "Products")
        detail_card = self._card(split, "Selected Product")
        split.add(card, minsize=430, stretch="always")
        split.add(detail_card, minsize=300, stretch="always")
        self.product_detail_panel = tk.Frame(detail_card, bg=COLORS["surface"])
        self.product_detail_panel.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        # Keep the chooser compact. Secondary fields live in the dossier at right.
        columns = ("name", "category", "print_ready", "price", "time", "status")
        self.product_table = ttk.Treeview(card, columns=columns, show="headings",
                                          style="Dark.Treeview", selectmode="browse")
        labels = {"name":"Product", "category":"Category", "print_ready":"Print File",
                  "price":"Price", "time":"Print Time", "status":"License"}
        widths = {"name":190, "category":100, "print_ready":115, "price":72, "time":82, "status":85}
        for col in columns:
            self.product_table.heading(col, text=labels[col],
                                       command=lambda c=col: self._sort_products(c))
            self.product_table.column(col, width=widths[col], minwidth=55,
                                      anchor="w", stretch=(col in ("name","category")))
        scroll_y = ttk.Scrollbar(card, orient="vertical", command=self.product_table.yview)
        self.product_table.configure(yscrollcommand=scroll_y.set)
        self.product_table.pack(side="left", fill="both", expand=True,
                                padx=(12,0), pady=(0,12))
        scroll_y.pack(side="right", fill="y", padx=(0,12), pady=(0,12))
        self.product_table.bind("<Double-1>", lambda _e: self._product_details())
        self.product_table.bind("<<TreeviewSelect>>", lambda _e: self._embedded_product_details())
        self.product_table.bind("<Button-3>", self._product_context_menu)
        self.product_table.tag_configure("verified", foreground=COLORS["green"],
                                         background=COLORS["surface"])
        self.product_table.tag_configure("review_required", foreground=COLORS["orange"],
                                         background=COLORS["surface"])
        self.product_table.tag_configure("ready_print", foreground=COLORS["green"],
                                         background=COLORS["surface"])
        self.product_table.tag_configure("needs_attention", foreground=COLORS["orange"],
                                         background=COLORS["surface"])
        self._refresh_products()
        self._start_auto_image_sync()

    def _switch_product_view(self,view):
        self.product_view.set(view)
        self._style_product_tabs()
        self._refresh_products()

    def _style_product_tabs(self):
        active=self.product_view.get()
        for value,button in self.product_tab_buttons.items():
            selected=value==active
            button.configure(
                bg=COLORS["purple"] if selected else COLORS["surface_alt"],
                fg="white" if selected else COLORS["text"],
                activebackground=COLORS["purple_dark"] if selected else COLORS["border"],
                activeforeground="white"
            )

    def _sort_products(self, column: str) -> None:
        if self.product_sort_column == column:
            self.product_sort_descending = not self.product_sort_descending
        else:
            self.product_sort_column = column
            self.product_sort_descending = False
        self._refresh_products()

    def _refresh_products(self) -> None:
        if not self.product_table:
            return
        for item in self.product_table.get_children():
            self.product_table.delete(item)

        all_rows=self.core.products.list(
            self.product_query.get().strip(),self.product_category.get(),
            self.product_license.get(),self.product_sort_column,
            self.product_sort_descending)
        readiness=self.core.design_vault.product_print_status_map([r["id"] for r in all_rows])
        group=self.product_view.get() if getattr(self,"product_view",None) else "ready"

        rows=[]
        for row in all_rows:
            ready=readiness.get(row["id"],{}).get("ready",False)
            if group=="ready" and not ready:continue
            if group=="attention" and ready:continue
            rows.append(row)

        for row in rows:
            info=readiness.get(row["id"],{})
            minutes=int(row["estimated_minutes"] or 0)
            time_text="%dh %02dm"%(minutes//60,minutes%60) if minutes else "—"
            if info.get("has_stl") and info.get("has_gcode"):
                file_text="STL + G-code"
            elif info.get("has_stl"):
                file_text="STL Ready"
            elif info.get("has_gcode"):
                file_text="G-code Ready"
            else:
                file_text="Needs File"
            values=(row["name"],row["category"] or "",file_text,
                    "$%.2f"%((row["price_cents"] or 0)/100.0),time_text,
                    "Verified" if row["license_status"]=="verified" else "Review")
            tag="ready_print" if info.get("ready") else "needs_attention"
            self.product_table.insert("","end",iid=row["id"],values=values,tags=(tag,))

        arrow=" ▼" if self.product_sort_descending else " ▲"
        headings={"name":"Product","category":"Category","print_ready":"Print File",
                  "price":"Price","time":"Print Time","status":"License"}
        for col,label in headings.items():
            heading_text=label+(arrow if col==self.product_sort_column else "")
            if col!="print_ready":
                self.product_table.heading(
                    col,text=heading_text,
                    command=lambda c=col:self._sort_products(c))
            else:
                # Do not pass command=None here. Older Tk/Tkinter builds
                # can raise: TclError: value for "-command" missing.
                self.product_table.heading(col,text=heading_text)

        label="ready product" if group=="ready" else "needs attention"
        self.product_count.configure(text="%d %s%s"%(len(rows),label,"" if len(rows)==1 else "s"))
        if self.product_table.selection():
            self._embedded_product_details()
        elif rows:
            self.product_table.selection_set(rows[0]["id"])
            self._embedded_product_details(rows[0]["id"])
        else:
            self._embedded_product_details(None)

    def _embedded_product_details(self, product_id=None):
        panel = getattr(self, "product_detail_panel", None)
        if not panel:
            return
        for child in panel.winfo_children():
            child.destroy()
        if product_id is None:
            selected = self.product_table.selection() if self.product_table else ()
            product_id = selected[0] if selected else None
        if not product_id:
            tk.Label(panel, text="Select a product to view its complete dossier.",
                     bg=COLORS["surface"], fg=COLORS["muted"], wraplength=300,
                     justify="left").pack(anchor="w", pady=12)
            return
        product = self.core.products.get(product_id)
        if not product:
            return
        image_area = tk.Frame(panel, bg=COLORS["surface_alt"], height=190)
        image_area.pack(fill="x", pady=(4, 12))
        image_area.pack_propagate(False)
        image = None
        try:
            image = self._load_primary_product_image(product_id, (300, 180))
        except Exception:
            image = None
        if image:
            label = tk.Label(image_area, image=image, bg=COLORS["surface_alt"])
            label.image = image
            label.pack(expand=True)
        else:
            tk.Label(image_area, text="No usable image yet\nBackground sync will retry the source page.",
                     bg=COLORS["surface_alt"], fg=COLORS["muted"], justify="center").pack(expand=True)

        tk.Label(panel, text=product["name"], bg=COLORS["surface"], fg=COLORS["text"],
                 font=("Segoe UI", 15, "bold"), wraplength=300, justify="left").pack(anchor="w")
        tk.Label(panel, text="%s • %s" % (product["sku"] or "No SKU", product["category"] or "Uncategorized"),
                 bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="w", pady=(3, 10))
        status_color = COLORS["green"] if product["license_status"] == "verified" else COLORS["orange"]
        tk.Label(panel, text=product["license_status"].replace("_", " ").upper(),
                 bg=COLORS["surface_alt"], fg=status_color, font=("Segoe UI", 8, "bold"),
                 padx=9, pady=4).pack(anchor="w", pady=(0, 10))
        try:
            model_status=self.core.design_vault.product_model_status(product_id)
        except Exception:
            model_status={'ready':False,'count':0,'primary_name':'','primary_kind':''}
        try:
            print_status=self.core.design_vault.product_print_status(product_id)
        except Exception:
            print_status={'ready':False,'has_stl':False,'has_gcode':False,'gcode_count':0,'reason':'Needs STL or G-code'}
        if model_status.get('ready') and model_status.get('model_mode')=='part_set':
            model_text="Part Set ✓ — %d part%s / %d piece%s"%(model_status.get('part_count',0),
                '' if model_status.get('part_count',0)==1 else 's',model_status.get('piece_count',0),
                '' if model_status.get('piece_count',0)==1 else 's')
        elif model_status.get('ready'):
            model_text="Single Model ✓ — %s"%model_status['primary_name']
        else:
            model_text=(("%s local model file%s — STL needed for one-click Cura print"%(model_status.get('count',0),
                '' if model_status.get('count',0)==1 else 's')) if model_status.get('count') else "Not imported")
        print_file_text=print_status.get('reason','Needs STL or G-code')
        if print_status.get('has_gcode') and print_status.get('gcode_count',0)>1:
            print_file_text+=" (%d saved G-codes)"%print_status.get('gcode_count',0)
        values = [
            ("Print file", print_file_text),
            ("Model", model_text),
            ("Price", "$%.2f" % ((product["price_cents"] or 0) / 100.0)),
            ("Print time", self._format_minutes(product["estimated_minutes"])),
            ("Filament", "%.0f g" % (product["estimated_filament_g"] or 0)),
            ("Designer", product["designer"] or "—"),
            ("License", product["license_name"] or "—"),
            ("Images", str(len(self.core.products.images(product_id)))),
            ("Design files", str(len(self.core.products.files(product_id)))),
            ("Variants", str(len(self.core.products.variants(product_id)))),
        ]
        for label_text, value in values:
            line = tk.Frame(panel, bg=COLORS["surface"])
            line.pack(fill="x", pady=2)
            tk.Label(line, text=label_text, bg=COLORS["surface"], fg=COLORS["muted"],
                     width=13, anchor="w").pack(side="left")
            tk.Label(line, text=str(value), bg=COLORS["surface"], fg=COLORS["text"],
                     anchor="w", wraplength=180, justify="left").pack(side="left", fill="x", expand=True)
        drop=tk.Label(panel,text="Drop STL / G-code here  •  or click to import",
                      bg=COLORS["surface_alt"],fg=COLORS["muted"],bd=1,relief="solid",
                      padx=10,pady=9,cursor="hand2")
        drop.pack(fill="x",pady=(10,4))
        drop.bind("<Button-1>",lambda _e:self._import_downloaded_product_model())
        try:
            if hasattr(drop,"drop_target_register") and hasattr(drop,"dnd_bind"):
                drop.drop_target_register("DND_Files")
                drop.dnd_bind("<<Drop>>",lambda e:self._product_drop_files(e.data))
        except Exception:
            pass

        tk.Button(panel, text="▶ Print" if print_status.get('ready') else "Import STL / G-code",
                  bg=COLORS["purple"], fg="white", bd=0,
                  activebackground=COLORS["purple_dark"], activeforeground="white",
                  padx=12, pady=8,
                  command=self._print_selected_product if print_status.get('ready') else self._import_downloaded_product_model).pack(fill="x", pady=(14, 5))
        tk.Button(panel, text="Import / Replace Print File", bg=COLORS["surface_alt"], fg=COLORS["text"], bd=0,
                  activebackground=COLORS["border"], activeforeground="white",
                  padx=12, pady=8, command=self._import_downloaded_product_model).pack(fill="x", pady=3)
        tk.Button(panel, text="Manage Model / Part Set", bg=COLORS["surface_alt"], fg=COLORS["text"], bd=0,
                  activebackground=COLORS["border"], activeforeground="white",
                  padx=12, pady=8, command=self._manage_product_model_set).pack(fill="x", pady=3)
        tk.Button(panel, text="Manage Saved G-code", bg=COLORS["surface_alt"], fg=COLORS["text"], bd=0,
                  activebackground=COLORS["border"], activeforeground="white",
                  padx=12, pady=8, command=self._manage_product_gcode_library).pack(fill="x", pady=3)
        tk.Button(panel, text="Download Model in Browser", bg=COLORS["surface_alt"], fg=COLORS["text"], bd=0,
                  activebackground=COLORS["border"], activeforeground="white",
                  padx=12, pady=8, command=self._download_product_model_browser).pack(fill="x", pady=3)
        tk.Button(panel, text="Open Full Details", bg=COLORS["surface_alt"], fg=COLORS["text"], bd=0,
                  activebackground=COLORS["border"], activeforeground="white",
                  padx=12, pady=8, command=self._product_details).pack(fill="x", pady=3)
        tk.Button(panel, text="Manage Images", bg=COLORS["surface_alt"], fg=COLORS["text"], bd=0,
                  activebackground=COLORS["border"], activeforeground="white",
                  padx=12, pady=8, command=self._manage_product_images).pack(fill="x", pady=3)
        tk.Button(panel, text="Open Design Vault", bg=COLORS["surface_alt"], fg=COLORS["text"], bd=0,
                  activebackground=COLORS["border"], activeforeground="white",
                  padx=12, pady=8, command=self._open_selected_product_design).pack(fill="x", pady=3)
        tk.Button(panel, text="Open Source Page", bg=COLORS["surface_alt"], fg=COLORS["text"], bd=0,
                  activebackground=COLORS["border"], activeforeground="white",
                  padx=12, pady=8, command=self._open_product_source).pack(fill="x", pady=3)

    @staticmethod
    def _format_minutes(value):
        if not value:
            return "—"
        value = int(value)
        return "%dh %02dm" % (value // 60, value % 60)

    def _load_primary_product_image(self, product_id, max_size=(300, 180)):
        """Compatibility wrapper used by the embedded Product Dossier."""
        image_row = self._preferred_product_image(product_id)
        if not image_row:
            return None
        path = self._resolve_product_image_path(image_row)
        return self._load_display_photo(path, max_size)

    def _manage_product_images(self):
        """Open the shared image manager for the currently selected product."""
        product_id = self._selected_product_id()
        if not product_id:
            return
        record = self.core.products.get(product_id)
        if not record:
            return
        self._product_image_manager(product_id, record["name"], self)


    def _manage_product_gcode_library(self):
        product_id=self._selected_product_id()
        if not product_id:return
        product=self.core.products.get(product_id)
        if not product:return

        win=tk.Toplevel(self)
        win.title("Saved G-code — "+product["name"])
        win.geometry("900x520");win.minsize(760,430)
        win.configure(bg=COLORS["bg"]);win.transient(self);win.grab_set()

        card=self._card(win,"Saved G-code Library")
        card.pack(fill="both",expand=True,padx=16,pady=16)

        cols=("file","verified","material","temps","layer","time","created")
        table=ttk.Treeview(card,columns=cols,show="headings",style="Dark.Treeview",selectmode="browse")
        specs=[
            ("file","File",220),("verified","Verified",80),("material","Material",85),("temps","Nozzle / Bed",110),
            ("layer","Layer",70),("time","Time",85),("created","Saved",110)
        ]
        for col,label,width in specs:
            table.heading(col,text=label);table.column(col,width=width,anchor="w",stretch=(col=="file"))
        table.pack(fill="both",expand=True,padx=12,pady=(12,8))

        info=tk.Label(card,text="",bg=COLORS["surface"],fg=COLORS["muted"],
                      anchor="w",justify="left",wraplength=820)
        info.pack(fill="x",padx=12,pady=(0,8))

        def refresh():
            table.delete(*table.get_children())
            rows=self.core.design_vault.gcode_library(product_id)
            for row in rows:
                path=Path(row["stored_path"])
                try:h=self.core.cura.gcode_profile_hints(path)
                except Exception:h={}
                mins=h.get("estimated_minutes")
                time_text=("%dh %02dm"%(int(mins)//60,int(mins)%60)) if mins else "—"
                temps="%s / %s°C"%(
                    "—" if h.get("hotend") is None else "%g"%h["hotend"],
                    "—" if h.get("bed") is None else "%g"%h["bed"])
                layer="—" if h.get("layer_height") is None else "%.2f mm"%h["layer_height"]
                verification=self.core.gcode_verification.current(path)
                verified="✓ Yes" if verification and verification["valid"] else "Not verified"
                table.insert("","end",iid=row["id"],values=(
                    row["original_name"],verified,h.get("material") or "Unknown",temps,layer,time_text,
                    str(row["created_at"] or "")[:16]),tags=("body",))
            info.configure(text=("%d saved G-code file%s. FabOS can reuse these directly from the Catalog print screen."%
                                 (len(rows),"" if len(rows)==1 else "s")))

        def verify_selected():
            sel=table.selection()
            if not sel:return messagebox.showinfo("Saved G-code","Select a G-code file first.",parent=win)
            row=next((r for r in self.core.design_vault.gcode_library(product_id) if r["id"]==sel[0]),None)
            if not row:return
            info.configure(text="Verifying G-code in background…")
            def worker():
                try:
                    path=Path(row["stored_path"])
                    result=self.core.gcode_verification.verify(path,product_id=product_id,asset_id=row["id"])
                    hints=result["hints"]
                    check=result["validation"]
                    bounds=check.get("bounds") or {}
                    lines=[
                        ("✓ Safe for Vyper XY bounds" if check.get("valid") else "✗ Safety check failed"),
                        "Material: %s"%(hints.get("material") or "Unknown"),
                        "Temperatures: nozzle %s°C / bed %s°C"%(
                            "—" if hints.get("hotend") is None else "%g"%hints["hotend"],
                            "—" if hints.get("bed") is None else "%g"%hints["bed"]),
                        "Layer height: %s"%("—" if hints.get("layer_height") is None else "%.2f mm"%hints["layer_height"]),
                        "XY range: X %.2f–%.2f / Y %.2f–%.2f mm"%(bounds.get("min_x",0),bounds.get("max_x",0),bounds.get("min_y",0),bounds.get("max_y",0))
                    ]
                    if hints.get("estimated_minutes"):
                        mins=int(hints["estimated_minutes"]);lines.append("Estimated time: %dh %02dm"%(mins//60,mins%60))
                    if not check.get("valid"):lines.extend("Problem: "+x for x in check.get("problems",[]))
                    text="  •  ".join(lines)
                except Exception as exc:text="Verification failed: "+str(exc)
                def apply():
                    if win.winfo_exists():
                        info.configure(text=text);refresh()
                self.after(0,apply)
            threading.Thread(target=worker,name="FabOS-GCodeVerify",daemon=True).start()

        def delete_selected():
            sel=table.selection()
            if not sel:return messagebox.showinfo("Saved G-code","Select a G-code file first.",parent=win)
            name=table.item(sel[0],"values")[0]
            if not messagebox.askyesno("Delete Saved G-code",
                                       "Delete %s from this product's Design Vault?\\n\\nThe original file outside FabOS is not affected."%name,
                                       parent=win):
                return
            try:
                self.core.design_vault.delete_product_gcode(product_id,sel[0])
                refresh();self._refresh_products()
                if getattr(self,"product_table",None) and self.product_table.exists(product_id):
                    self.product_table.selection_set(product_id)
                    self._embedded_product_details(product_id)
            except Exception as exc:
                messagebox.showerror("Saved G-code",str(exc),parent=win)

        buttons=tk.Frame(card,bg=COLORS["surface"]);buttons.pack(fill="x",padx=12,pady=(0,12))
        self._button(buttons,"Delete Selected",delete_selected).pack(side="right")
        self._button(buttons,"Verify Selected",verify_selected,True).pack(side="right",padx=7)
        self._button(buttons,"Close",win.destroy).pack(side="left")
        refresh()

    def _manage_product_model_set(self):
        product_id=self._selected_product_id()
        if not product_id:return
        product=self.core.products.get(product_id)
        did=self.core.design_vault.ensure_product(product_id)
        summary=self.core.design_vault.model_set_summary(did)

        win=tk.Toplevel(self);win.title("Manage Model Set — "+product["name"])
        win.geometry("850x650");win.minsize(720,520);win.configure(bg=COLORS["bg"]);win.transient(self);win.grab_set()

        top=self._card(win,"Model Type")
        top.pack(fill="x",padx=16,pady=(16,10))
        row=tk.Frame(top,bg=COLORS["surface"]);row.pack(fill="x",padx=14,pady=10)
        tk.Label(row,text="How should FabOS treat these STL files?",bg=COLORS["surface"],fg=COLORS["text"],
                 font=("Segoe UI",10,"bold")).pack(side="left")
        mode=tk.StringVar(value="Part Set" if summary["mode"]=="part_set" else "Single Model")
        combo=ttk.Combobox(row,textvariable=mode,values=["Single Model","Part Set"],state="readonly",width=18)
        combo.pack(side="right")

        helpbox=tk.Label(top,
            text=("Single Model = one STL is the printable product; other files can be alternates/reference.  "
                  "Part Set = multiple STL parts and quantities combine into one finished product and FabOS can arrange the complete set on one Vyper plate."),
            bg=COLORS["surface"],fg=COLORS["muted"],wraplength=760,justify="left")
        helpbox.pack(anchor="w",padx=14,pady=(0,12))

        card=self._card(win,"Parts")
        card.pack(fill="both",expand=True,padx=16,pady=(0,10))
        cols=("part","file","qty","included","size")
        table=ttk.Treeview(card,columns=cols,show="headings",style="Dark.Treeview",selectmode="browse")
        for c,label,w in [("part","Part Name",190),("file","STL File",240),("qty","Qty",55),
                          ("included","Complete Set",90),("size","Footprint",140)]:
            table.heading(c,text=label);table.column(c,width=w,anchor="w",stretch=(c in ("part","file")))
        table.pack(fill="both",expand=True,padx=12,pady=12)

        def refresh():
            table.delete(*table.get_children())
            parts=self.core.design_vault.model_parts(did)
            for p in parts:
                size="%.1f × %.1f mm"%((p["width_mm"] or 0),(p["depth_mm"] or 0))
                table.insert("","end",iid=p["id"],values=(p["part_name"],p["original_name"],p["quantity"],
                    "Yes" if p["include_in_complete_set"] else "No",size),tags=("body",))
            current=self.core.design_vault.model_set_summary(did)
            mode.set("Part Set" if current["mode"]=="part_set" else "Single Model")

        def save_mode(*_):
            self.core.design_vault.set_model_mode(did,"part_set" if mode.get()=="Part Set" else "single")
            refresh()
        combo.bind("<<ComboboxSelected>>",save_mode)

        def edit_part():
            sel=table.selection()
            if not sel:return messagebox.showinfo("Model Set","Select a part first.",parent=win)
            part=next((p for p in self.core.design_vault.model_parts(did) if p["id"]==sel[0]),None)
            if not part:return
            ew=tk.Toplevel(win);ew.title("Edit Part");ew.geometry("480x330");ew.configure(bg=COLORS["bg"]);ew.transient(win);ew.grab_set()
            body=self._card(ew,"Part Settings");body.pack(fill="both",expand=True,padx=16,pady=16)
            name=tk.StringVar(value=part["part_name"]);qty=tk.StringVar(value=str(part["quantity"]))
            included=tk.BooleanVar(value=bool(part["include_in_complete_set"]))
            for label,var in [("Part Name",name),("Quantity in One Finished Product",qty)]:
                tk.Label(body,text=label,bg=COLORS["surface"],fg=COLORS["muted"]).pack(anchor="w",padx=14,pady=(10,3))
                self._entry(body,var,35).pack(fill="x",padx=14,ipady=5)
            tk.Checkbutton(body,text="Include in Complete Set plate",variable=included,bg=COLORS["surface"],fg=COLORS["text"],
                           selectcolor=COLORS["surface_alt"],activebackground=COLORS["surface"],activeforeground=COLORS["text"]).pack(anchor="w",padx=14,pady=12)
            def save():
                try:
                    self.core.design_vault.update_model_part(part["id"],name.get(),int(qty.get()),included.get())
                    ew.destroy();refresh();self._embedded_product_details(product_id)
                except Exception as exc:messagebox.showerror("Part",str(exc),parent=ew)
            self._button(body,"Save Part",save,True).pack(anchor="e",padx=14,pady=12)

        def preview_plate():
            try:
                self.core.design_vault.set_model_mode(did,"part_set")
                result=self.core.model_plate.build_complete_set(product_id)
                lines=[]
                for p in result["placements"]:
                    lines.append("%s #%d  →  X %.1f  Y %.1f%s"%(p["part_name"],p["copy"],p["x"],p["y"],
                        "  rotated 90°" if p["rot90"] else ""))
                messagebox.showinfo(
                    "Complete Set Fits Vyper",
                    "FabOS successfully arranged %d pieces on the 245 × 245 mm Vyper plate.\\n"
                    "Used area: %.1f × %.1f mm\\n\\n%s\\n\\nGenerated plate:\\n%s"%
                    (result["pieces"],result["used_w"],result["used_d"],"\\n".join(lines),result["path"]),parent=win)
                mode.set("Part Set");refresh();self._embedded_product_details(product_id)
            except Exception as exc:
                messagebox.showerror("Plate Layout",str(exc),parent=win)

        buttons=tk.Frame(win,bg=COLORS["bg"]);buttons.pack(fill="x",padx=16,pady=(0,16))
        self._button(buttons,"Preview Complete Set on Vyper",preview_plate,True).pack(side="right")
        self._button(buttons,"Edit Selected Part",edit_part).pack(side="right",padx=7)
        self._button(buttons,"Close",win.destroy).pack(side="left")
        table.bind("<Double-1>",lambda _e:edit_part())
        refresh()

    def _download_product_model_browser(self):
        product_id=self._selected_product_id()
        if not product_id:return
        product=self.core.products.get(product_id)
        url=str(product['source_url'] or '').strip() if product else ''
        if not url:
            return messagebox.showwarning("Download Model","This product does not have a source website saved.")
        try:
            import webbrowser
            webbrowser.open(url)
            messagebox.showinfo(
                "Download Model",
                "The model source has been opened in your browser.\n\n"
                "Download the STL normally from the website. When it finishes, return to FabOS and click "
                "Import / Replace Model. You only have to do this once for this product."
            )
        except Exception as exc:
            messagebox.showerror("Download Model",str(exc))

    def _import_downloaded_product_model(self):
        product_id=self._selected_product_id()
        if not product_id:return
        product=self.core.products.get(product_id)
        if not product:return
        from tkinter import filedialog
        paths=filedialog.askopenfilenames(
            title="Import Print File — "+product["name"],
            filetypes=[
                ("Printable files","*.stl *.3mf *.step *.stp *.gcode *.gco *.gc"),
                ("STL files","*.stl"),
                ("G-code files","*.gcode *.gco *.gc"),
                ("3MF files","*.3mf"),
                ("STEP files","*.step *.stp"),
                ("All files","*.*")
            ]
        )
        if not paths:return
        try:
            result=self.core.design_vault.import_product_print_files(product_id,paths)
            model_status=self.core.design_vault.product_model_status(product_id)
            message=(
                "Print files saved to Design Vault.\n\n"
                "STL files: %d\n"
                "Saved G-code files: %d\n"
                "Catalog status: %s\n\n"
                "FabOS will reuse these local files for future Catalog and Production prints."
                %(result.get('stl_count',0),result.get('gcode_count',0),result.get('reason','Ready'))
            )
            messagebox.showinfo("Print File Imported",message)
            if model_status.get('suggest_part_set'):
                if messagebox.askyesno(
                    "Multiple STL Files",
                    "FabOS found multiple different STL files for this product.\n\n"
                    "Are these separate parts that combine into ONE finished product?\n\n"
                    "Choose Yes for things like Head + Chest + Arms + Legs.\n"
                    "Choose No if the files are alternate versions/options of the same product."
                ):
                    self.core.design_vault.set_model_mode(model_status['design_id'],'part_set')
                else:
                    self.core.design_vault.set_model_mode(model_status['design_id'],'single')
            self._refresh_products()
            if self.product_table.exists(product_id):
                self.product_table.selection_set(product_id)
                self._embedded_product_details(product_id)
        except Exception as exc:
            messagebox.showerror("Import Print File",str(exc))


    def _open_selected_product_design(self):
        product_id = self._selected_product_id()
        if not product_id:
            return
        try:
            design_id = self.core.design_vault.ensure_product(product_id)
            self.show_page("Design Vault")
            if getattr(self, "vault_table", None):
                self.vault_detail_select(design_id)
        except Exception as exc:
            messagebox.showerror("Design Vault", str(exc))

    def _product_drop_files(self,data):
        product_id=self._selected_product_id()
        if not product_id:return
        try:
            paths=list(self.tk.splitlist(data))
            result=self.core.design_vault.import_product_print_files(product_id,paths)
            messagebox.showinfo("Files Imported","%s\n\nThe Catalog readiness view has been updated."%result.get("reason","Files imported."))
            self._refresh_products()
        except Exception as exc:messagebox.showerror("Import Files",str(exc))

    def _product_card_gallery(self):
        rows=self.core.products.list(
            self.product_query.get().strip() if getattr(self,"product_query",None) else "",
            self.product_category.get() if getattr(self,"product_category",None) else "All",
            self.product_license.get() if getattr(self,"product_license",None) else "All",
            "name",False)
        readiness=self.core.design_vault.product_print_status_map([r["id"] for r in rows])
        group=self.product_view.get() if getattr(self,"product_view",None) else "ready"
        rows=[r for r in rows if bool(readiness.get(r["id"],{}).get("ready"))==(group=="ready")]

        win=tk.Toplevel(self);win.title("Catalog Card Gallery");win.geometry("1050x720")
        win.minsize(760,520);win.configure(bg=COLORS["bg"]);win.transient(self)
        outer=tk.Frame(win,bg=COLORS["bg"]);outer.pack(fill="both",expand=True,padx=14,pady=14)
        canvas=tk.Canvas(outer,bg=COLORS["bg"],highlightthickness=0)
        scroll=ttk.Scrollbar(outer,orient="vertical",command=canvas.yview)
        holder=tk.Frame(canvas,bg=COLORS["bg"])
        holder.bind("<Configure>",lambda _e:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0),window=holder,anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left",fill="both",expand=True);scroll.pack(side="right",fill="y")
        self._product_gallery_images=[]

        def open_product(pid,do_print=False):
            win.destroy();self.show_page("Products")
            def select():
                try:
                    if self.product_table.exists(pid):
                        self.product_table.selection_set(pid);self.product_table.see(pid)
                        self._embedded_product_details(pid)
                        if do_print:self._print_selected_product(product_id=pid)
                except Exception:pass
            self.after(120,select)

        for i,row in enumerate(rows):
            card=self._card(holder)
            card.grid(row=i//3,column=i%3,sticky="nsew",padx=6,pady=6)
            holder.columnconfigure(i%3,weight=1)
            image_row=self._preferred_product_image(row["id"])
            image_path=self._resolve_product_image_path(image_row) if image_row else None
            shown=False
            if image_path and Path(image_path).exists():
                try:
                    from PIL import Image,ImageTk
                    im=Image.open(image_path);im.thumbnail((250,150))
                    photo=ImageTk.PhotoImage(im);self._product_gallery_images.append(photo)
                    tk.Label(card,image=photo,bg=COLORS["surface"]).pack(fill="x",padx=10,pady=(10,6))
                    shown=True
                except Exception:pass
            if not shown:
                tk.Label(card,text="3D",bg=COLORS["surface_alt"],fg=COLORS["purple"],
                         font=("Segoe UI",28,"bold"),height=4).pack(fill="x",padx=10,pady=(10,6))
            tk.Label(card,text=row["name"],bg=COLORS["surface"],fg=COLORS["text"],
                     font=("Segoe UI",11,"bold"),wraplength=260,justify="left").pack(anchor="w",padx=12)
            info=readiness.get(row["id"],{})
            status=("STL + G-code" if info.get("has_stl") and info.get("has_gcode") else
                    "STL Ready" if info.get("has_stl") else
                    "G-code Ready" if info.get("has_gcode") else "Needs File")
            tk.Label(card,text="%s • $%.2f"%(status,(row["price_cents"] or 0)/100.0),
                     bg=COLORS["surface"],fg=COLORS["green"] if info.get("ready") else COLORS["orange"]).pack(anchor="w",padx=12,pady=(4,8))
            buttons=tk.Frame(card,bg=COLORS["surface"]);buttons.pack(fill="x",padx=10,pady=(0,10))
            tk.Button(buttons,text="Details",bg=COLORS["surface_alt"],fg=COLORS["text"],bd=0,
                      command=lambda pid=row["id"]:open_product(pid,False)).pack(side="left")
            if info.get("ready"):
                tk.Button(buttons,text="Print",bg=COLORS["purple"],fg="white",bd=0,
                          command=lambda pid=row["id"]:open_product(pid,True)).pack(side="right")
        if not rows:
            tk.Label(holder,text="No products in this Catalog view.",bg=COLORS["bg"],fg=COLORS["muted"]).pack(padx=20,pady=20)

    def _product_context_menu(self, event):
        if not getattr(self, "product_table", None):
            return
        row = self.product_table.identify_row(event.y)
        if row:
            self.product_table.selection_set(row)
            self._embedded_product_details(row)
        menu = tk.Menu(self, tearoff=0, bg=COLORS["surface_alt"], fg=COLORS["text"],
                       activebackground=COLORS["purple_dark"], activeforeground="white")
        menu.add_command(label="Print", command=self._print_selected_product)
        menu.add_command(label="Edit", command=self._edit_product)
        menu.add_command(label="Full Details", command=self._product_details)
        menu.add_command(label="Import / Replace Print File", command=self._import_downloaded_product_model)
        menu.add_command(label="Manage Model / Part Set", command=self._manage_product_model_set)
        menu.add_command(label="Manage Saved G-code", command=self._manage_product_gcode_library)
        menu.add_command(label="Download Model in Browser", command=self._download_product_model_browser)
        menu.add_command(label="Design Vault", command=self._open_selected_product_design)
        menu.add_command(label="Open Source", command=self._open_product_source)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _selected_product_id(self):
        selected = self.product_table.selection() if self.product_table else ()
        if not selected:
            messagebox.showinfo("Products", "Select a product first.")
            return None
        return selected[0]

    def _add_product(self):
        self._product_editor(None)

    def _edit_product(self):
        product_id = self._selected_product_id()
        if product_id:
            self._product_editor(product_id)

    def _product_editor(self, product_id):
        record = self.core.products.get(product_id) if product_id else None
        win = tk.Toplevel(self); win.title("Edit Product" if record else "Add Product")
        win.configure(bg=COLORS["bg"]); win.geometry("720x670"); win.minsize(600, 520); win.transient(self); win.grab_set()
        outer = tk.Frame(win, bg=COLORS["bg"]); outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=COLORS["bg"], highlightthickness=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        form = tk.Frame(canvas, bg=COLORS["surface"])
        form.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=form, anchor="nw", width=675); canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(16,0), pady=16); bar.pack(side="right", fill="y", padx=(0,16), pady=16)
        fields = {}
        specs = [("sku","SKU"),("name","Product Name"),("category","Category"),("designer","Designer"),
                 ("source_url","Model Source URL"),("license_name","License"),("price","Selling Price ($)"),
                 ("hours","Estimated Print Hours"),("filament","Estimated Filament (g)")]
        for key, label in specs:
            tk.Label(form, text=label, bg=COLORS["surface"], fg=COLORS["muted"], anchor="w", font=("Segoe UI",9)).pack(fill="x", padx=18, pady=(12,4))
            var = tk.StringVar()
            fields[key] = var
            tk.Entry(form, textvariable=var, bg=COLORS["surface_alt"], fg=COLORS["text"], insertbackground=COLORS["text"], selectbackground=COLORS["purple_dark"], selectforeground="white", relief="flat", font=("Segoe UI",10)).pack(fill="x", padx=18, ipady=7)
        tk.Label(form, text="Commercial License Status", bg=COLORS["surface"], fg=COLORS["muted"], anchor="w", font=("Segoe UI",9)).pack(fill="x", padx=18, pady=(12,4))
        status = tk.StringVar(value="review_required"); fields["license_status"] = status
        ttk.Combobox(form, textvariable=status, values=["verified","review_required"], state="readonly").pack(fill="x", padx=18)
        tk.Label(form, text="Description / Customization / Notes", bg=COLORS["surface"], fg=COLORS["muted"], anchor="w", font=("Segoe UI",9)).pack(fill="x", padx=18, pady=(12,4))
        description = tk.Text(form, height=7, bg=COLORS["surface_alt"], fg=COLORS["text"], insertbackground=COLORS["text"], selectbackground=COLORS["purple_dark"], selectforeground="white", relief="flat", wrap="word", font=("Segoe UI",9))
        description.pack(fill="x", padx=18, pady=(0,14))
        if record:
            for key in ("sku","name","category","designer","source_url","license_name","license_status"):
                fields[key].set(record[key] or "")
            fields["price"].set("%.2f" % ((record["price_cents"] or 0)/100.0))
            fields["hours"].set("%.2f" % ((record["estimated_minutes"] or 0)/60.0))
            fields["filament"].set(str(record["estimated_filament_g"] or ""))
            description.insert("1.0", record["description"] or "")
        buttons = tk.Frame(win, bg=COLORS["bg"]); buttons.pack(fill="x", padx=16, pady=(0,16))
        def save():
            try:
                payload = {k:v.get().strip() for k,v in fields.items()}
                payload["description"] = description.get("1.0", "end").strip()
                if not payload["name"]:
                    raise ValueError("Product name is required.")
                self.core.products.save(payload, product_id)
            except Exception as exc:
                messagebox.showerror("Could not save product", str(exc), parent=win); return
            win.destroy(); self._refresh_products()
        tk.Button(buttons, text="Save Product", command=save, bg=COLORS["purple"], fg="white", bd=0, padx=18, pady=10, font=("Segoe UI",9,"bold")).pack(side="right")
        tk.Button(buttons, text="Cancel", command=win.destroy, bg=COLORS["surface_alt"], fg=COLORS["text"], bd=0, padx=18, pady=10).pack(side="right", padx=(0,8))

    def _resolve_product_image_path(self, image_row):
        """Resolve catalog-relative and user/downloaded image paths."""
        raw = str(image_row["path"] or "")
        root = Path(__file__).resolve().parents[1]
        candidates = []
        if raw.startswith("Catalog_Images/"):
            candidates.append(root / "data" / "catalog" / raw)
        path = Path(raw)
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.extend([root / raw, root / "data" / raw, path])
        for candidate in candidates:
            try:
                if candidate.exists():
                    return candidate.resolve()
            except OSError:
                pass
        return candidates[0] if candidates else path

    def _is_placeholder_image(self, image_row):
        raw = str(image_row["path"] or "").replace("\\", "/")
        attr = str(image_row["attribution"] or "").lower()
        return raw.startswith("Catalog_Images/") or "catalog preview card" in attr

    def _preferred_product_image(self, product_id):
        images = list(self.core.products.images(product_id))
        if not images:
            return None
        # A real primary image wins. Otherwise prefer any real image over the generated catalog card.
        for row in images:
            if row["is_primary"] and not self._is_placeholder_image(row):
                return row
        for row in images:
            if not self._is_placeholder_image(row):
                return row
        return images[0]

    def _load_display_photo(self, path, max_size=(760, 500)):
        """Load and scale common image formats. Pillow is optional but recommended."""
        try:
            from PIL import Image, ImageTk
            image = Image.open(str(path))
            image.thumbnail(max_size, Image.LANCZOS)
            return ImageTk.PhotoImage(image)
        except ImportError:
            try:
                photo = tk.PhotoImage(file=str(path))
                # Reduce oversized PNG/GIF images with integer subsampling.
                sx = max(1, int(photo.width() / max_size[0]) + (1 if photo.width() > max_size[0] else 0))
                sy = max(1, int(photo.height() / max_size[1]) + (1 if photo.height() > max_size[1] else 0))
                factor = max(sx, sy)
                return photo.subsample(factor, factor) if factor > 1 else photo
            except tk.TclError:
                return None
        except Exception:
            return None

    def _render_image_panel(self, parent, image_row, product_name, max_size=(760, 500)):
        for child in parent.winfo_children():
            child.destroy()
        if not image_row:
            tk.Label(parent, text="No product image is attached yet.", bg=COLORS["surface"],
                     fg=COLORS["muted"], font=("Segoe UI", 11)).pack(expand=True)
            return
        path = self._resolve_product_image_path(image_row)
        if not path.exists():
            tk.Label(parent, text="Image file was not found:\n%s" % path, bg=COLORS["surface"],
                     fg=COLORS["orange"], font=("Segoe UI", 10), justify="center").pack(expand=True)
            return
        photo = self._load_display_photo(path, max_size=max_size)
        if photo:
            label = tk.Label(parent, image=photo, bg=COLORS["surface"])
            label.image = photo
            label.pack(expand=True, padx=8, pady=8)
        else:
            tk.Label(parent, text="FabOS could not decode this image format.\nUse Open Full Size or install Pillow.\n\n%s" % path,
                     bg=COLORS["surface"], fg=COLORS["text"], font=("Segoe UI", 10), justify="center").pack(expand=True)

    def _product_details(self):
        product_id = self._selected_product_id()
        if not product_id:
            return
        record = self.core.products.get(product_id)
        win = tk.Toplevel(self)
        win.title(record["name"])
        win.geometry("1040x720")
        win.configure(bg=COLORS["bg"])
        win.transient(self)

        header = tk.Frame(win, bg=COLORS["surface"], padx=20, pady=16)
        header.pack(fill="x")
        tk.Label(header, text=record["name"], bg=COLORS["surface"], fg=COLORS["text"],
                 font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(header, text="%s  •  %s" % (record["sku"] or "No SKU", record["category"] or "Uncategorized"),
                 bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 0))

        notebook = ttk.Notebook(win)
        notebook.pack(fill="both", expand=True, padx=16, pady=16)
        overview = tk.Frame(notebook, bg=COLORS["surface"])
        images_tab = tk.Frame(notebook, bg=COLORS["surface"])
        files = tk.Frame(notebook, bg=COLORS["surface"])
        variants = tk.Frame(notebook, bg=COLORS["surface"])
        image_rows = self.core.products.images(product_id)
        notebook.add(overview, text="Overview")
        notebook.add(images_tab, text="Images (%d)" % len(image_rows))
        notebook.add(files, text="Files (%d)" % len(self.core.products.files(product_id)))
        notebook.add(variants, text="Variants (%d)" % len(self.core.products.variants(product_id)))

        # Product image is now visible directly on Overview.
        left = tk.Frame(overview, bg=COLORS["surface"], width=390)
        left.pack(side="left", fill="both", padx=(18, 8), pady=18)
        left.pack_propagate(False)
        overview_image = tk.Frame(left, bg=COLORS["surface_alt"], highlightbackground=COLORS["border"], highlightthickness=1)
        overview_image.pack(fill="both", expand=True)
        self._render_image_panel(overview_image, self._preferred_product_image(product_id), record["name"], max_size=(350, 420))
        tk.Button(left, text="Manage Images", command=lambda: self._product_image_manager(product_id, record["name"], win),
                  bg=COLORS["purple"], fg="white", bd=0, padx=14, pady=9,
                  font=("Segoe UI", 9, "bold")).pack(fill="x", pady=(10, 0))

        right = tk.Frame(overview, bg=COLORS["surface"])
        right.pack(side="left", fill="both", expand=True, padx=(8, 18), pady=18)
        details = [
            ("Designer", record["designer"]), ("License", record["license_name"]),
            ("Verification", record["license_status"].replace("_", " ").title()),
            ("Selling price", "$%.2f" % ((record["price_cents"] or 0) / 100.0)),
            ("Print time", "%.2f hours" % ((record["estimated_minutes"] or 0) / 60.0)),
            ("Filament", "%.1f g" % (record["estimated_filament_g"] or 0)),
        ]
        for label, value in details:
            line = tk.Frame(right, bg=COLORS["surface"])
            line.pack(fill="x", pady=6)
            tk.Label(line, text=label, bg=COLORS["surface"], fg=COLORS["muted"], width=16, anchor="w").pack(side="left")
            tk.Label(line, text=str(value or "—"), bg=COLORS["surface"], fg=COLORS["text"], anchor="w").pack(side="left", fill="x", expand=True)
        tk.Label(right, text=record["description"] or "No notes yet.", bg=COLORS["surface_alt"], fg=COLORS["text"],
                 justify="left", anchor="nw", wraplength=510, padx=14, pady=14).pack(fill="both", expand=True, pady=(12, 0))

        self._build_product_images_tab(images_tab, product_id, record["name"], win)
        self._simple_records(files, self.core.products.files(product_id), [("kind", "Type"), ("path", "File"), ("version", "Version")])
        self._simple_records(variants, self.core.products.variants(product_id), [("name", "Variant"), ("material", "Material"), ("color", "Color"), ("size", "Size")])

    def _build_product_images_tab(self, parent, product_id, product_name, details_window=None):
        for child in parent.winfo_children():
            child.destroy()
        toolbar = tk.Frame(parent, bg=COLORS["surface"])
        toolbar.pack(fill="x", padx=12, pady=(12, 4))
        viewer = tk.Frame(parent, bg=COLORS["surface_alt"], highlightbackground=COLORS["border"], highlightthickness=1)
        viewer.pack(side="left", fill="both", expand=True, padx=(12, 6), pady=(6, 12))
        side = tk.Frame(parent, bg=COLORS["surface"], width=300)
        side.pack(side="right", fill="y", padx=(6, 12), pady=(6, 12))
        side.pack_propagate(False)
        rows = list(self.core.products.images(product_id))
        listbox = tk.Listbox(side, bg=COLORS["surface_alt"], fg=COLORS["text"], selectbackground=COLORS["purple_dark"],
                            selectforeground="white", relief="flat", font=("Segoe UI", 9), exportselection=False)
        listbox.pack(fill="both", expand=True)
        for row in rows:
            name = Path(str(row["path"])).name
            flags = []
            if row["is_primary"]: flags.append("PRIMARY")
            if self._is_placeholder_image(row): flags.append("PLACEHOLDER")
            listbox.insert("end", ("[%s] " % ", ".join(flags) if flags else "") + name)

        def selected_row():
            sel = listbox.curselection()
            return rows[sel[0]] if sel else (rows[0] if rows else None)

        def show_selected(_event=None):
            self._render_image_panel(viewer, selected_row(), product_name, max_size=(650, 520))

        def refresh():
            self._build_product_images_tab(parent, product_id, product_name, details_window)

        def add_local():
            filename = filedialog.askopenfilename(parent=parent.winfo_toplevel(), title="Choose product image",
                                                  filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp *.bmp"), ("All files", "*.*")])
            if not filename: return
            root = Path(__file__).resolve().parents[1]
            dest_dir = root / "data" / "product_images" / product_id
            dest_dir.mkdir(parents=True, exist_ok=True)
            src = Path(filename)
            dest = dest_dir / (str(uuid.uuid4())[:8] + "_" + src.name)
            shutil.copy2(str(src), str(dest))
            self.core.products.add_image(product_id, str(dest), attribution="User-added product image", make_primary=True)
            refresh()

        def fetch_web():
            record = self.core.products.get(product_id)
            page_url = record["source_url"]
            if not page_url:
                messagebox.showinfo("Fetch Web Image", "This product does not have a source webpage.", parent=parent.winfo_toplevel()); return
            try:
                if not self._fetch_and_promote_web_image(product_id):
                    if self.core.products.has_real_image(product_id):
                        messagebox.showinfo("Web image", "A real product image is already attached.", parent=parent.winfo_toplevel())
                    else:
                        raise ValueError("No usable webpage preview image was found.")
                refresh()
            except Exception as exc:
                messagebox.showerror("Could not fetch preview", str(exc), parent=parent.winfo_toplevel())

        def set_primary():
            row = selected_row()
            if not row: return
            self.core.products.set_primary_image(product_id, row["id"])
            refresh()

        def open_full():
            row = selected_row()
            if not row: return
            path = self._resolve_product_image_path(row)
            if path.exists():
                try: os.startfile(str(path))
                except Exception: webbrowser.open(path.as_uri())

        def remove():
            row = selected_row()
            if not row: return
            if self._is_placeholder_image(row):
                messagebox.showinfo("Keep placeholder", "The bundled catalog card is retained as a last-resort fallback.", parent=parent.winfo_toplevel()); return
            if messagebox.askyesno("Remove image", "Remove this image from the product?", parent=parent.winfo_toplevel()):
                self.core.products.delete_image(product_id, row["id"])
                refresh()

        for text, command in (("Fetch Web Image", fetch_web), ("Add Your Image", add_local), ("Set Primary", set_primary),
                              ("Open Full Size", open_full), ("Remove", remove)):
            tk.Button(toolbar, text=text, command=command, bg=COLORS["purple"] if text in ("Fetch Web Image", "Add Your Image") else COLORS["surface_alt"],
                      fg="white" if text in ("Fetch Web Image", "Add Your Image") else COLORS["text"], bd=0, padx=12, pady=8).pack(side="left", padx=(0, 7))
        listbox.bind("<<ListboxSelect>>", show_selected)
        if rows:
            listbox.selection_set(0)
        show_selected()

    def _fetch_selected_product_image(self, product_id):
        try:
            changed = self._fetch_and_promote_web_image(product_id)
            if changed:
                self.after(0, self._refresh_product_image_views)
        except Exception:
            pass

    def _fetch_and_promote_web_image(self, product_id):
        """Fetch one product image and replace generated placeholders on success."""
        record = self.core.products.get(product_id)
        if not record or self.core.products.has_real_image(product_id):
            return False
        page_url = str(record["source_url"] or "").strip()
        if not page_url or not page_url.lower().startswith(("http://", "https://")):
            return False
        image_url = self._find_web_preview_url(page_url)
        if not image_url:
            return False
        saved = self._download_product_image(product_id, image_url)
        self.core.products.add_image(
            product_id, str(saved), source_url=page_url,
            attribution=("Reference preview downloaded automatically from the model source page. "
                         "Internal catalog use only."),
            make_primary=True,
        )
        self.core.products.remove_placeholder_images(product_id, delete_files=True)
        return True

    def _start_auto_image_sync(self):
        """Fetch missing verified product images once per application session."""
        if self._auto_image_sync_started or self._auto_image_sync_running:
            return
        self._auto_image_sync_started = True
        self._auto_image_sync_running = True

        def worker():
            found = 0
            try:
                rows = self.core.products.list(order_by="name")
                for row in rows:
                    if str(row["license_status"] or "") != "verified":
                        continue
                    if self.core.products.has_real_image(row["id"]):
                        continue
                    try:
                        if self._fetch_and_promote_web_image(row["id"]):
                            found += 1
                            self.after(0, self._refresh_product_image_views)
                    except Exception:
                        # Sites may require login, JavaScript, or block automated requests.
                        # Leave the product untouched and continue with the remaining catalog.
                        continue
            finally:
                self._auto_image_sync_running = False
                if found:
                    self.after(0, self._refresh_product_image_views)

        threading.Thread(target=worker, name="FabOSImageSync", daemon=True).start()

    def _refresh_product_image_views(self):
        if self.active_page == "Products" and self.product_table:
            try:
                self._refresh_products()
            except Exception:
                pass

    def _find_web_preview_url(self, page_url):
        request = Request(page_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 Chrome/109 Safari/537.36", "Accept": "text/html,application/xhtml+xml,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"})
        with urlopen(request, timeout=25) as response:
            html = response.read(5_000_000).decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            final_url = response.geturl()
        candidates=[]
        patterns = [
            r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
            r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)',
            r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)',
            r'"(?:image|imageUrl|thumbnailUrl|previewImage|coverImage)"\s*:\s*"([^"\\]+)"',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, html, flags=re.I):
                raw=match.group(1).replace("&amp;", "&").replace('\\u002F','/').replace('\\/','/')
                candidates.append(urljoin(final_url,raw))
        for m in re.finditer(r'(?:srcset|data-srcset)=["\']([^"\']+)',html,re.I):
            parts=[]
            for item in m.group(1).split(','):
                bits=item.strip().split()
                if bits:parts.append(bits[0])
            candidates.extend(urljoin(final_url,x) for x in reversed(parts))
        for m in re.finditer(r'<img[^>]+(?:src|data-src|data-lazy-src)=["\']([^"\']+)',html,re.I):
            candidates.append(urljoin(final_url,m.group(1).replace("&amp;","&")))
        seen=set()
        for url in candidates:
            if not url or url in seen:continue
            seen.add(url);low=url.lower()
            if low.startswith('data:') or any(x in low for x in ('logo','avatar','favicon','pixel','spacer','badge','icon')):continue
            try:
                req=Request(url,headers={"User-Agent":"Mozilla/5.0 (Windows NT 6.1; Win64; x64) Chrome/109 Safari/537.36","Referer":final_url,"Accept":"image/avif,image/webp,image/apng,image/*,*/*;q=0.8"})
                with urlopen(req,timeout=12) as r:
                    ctype=(r.headers.get('Content-Type') or '').lower();sample=r.read(64)
                if ctype.startswith('image/') and sample:return url
            except Exception:continue
        return None

    def _download_product_image(self, product_id, image_url):
        request = Request(image_url, headers={"User-Agent": "Mozilla/5.0 FabOS/0.4.2", "Referer": image_url})
        with urlopen(request, timeout=25) as response:
            content = response.read(15_000_000)
            ctype = (response.headers.get("Content-Type") or "").split(";")[0].lower()
        if not content:
            raise ValueError("The image download returned no data.")
        ext_map = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp", "image/bmp": ".bmp"}
        ext = ext_map.get(ctype) or Path(urlparse(image_url).path).suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
            ext = ".img"
        root = Path(__file__).resolve().parents[1]
        dest_dir = root / "data" / "product_images" / product_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / ("web_" + str(uuid.uuid4())[:10] + ext)
        dest.write_bytes(content)
        return dest

    def _simple_records(self, parent, rows, columns):
        table = ttk.Treeview(parent, columns=[c[0] for c in columns], show="headings", style="Dark.Treeview")
        table.tag_configure("body", foreground=COLORS["text"], background=COLORS["surface"])
        for key, label in columns:
            table.heading(key, text=label)
            table.column(key, width=180, anchor="w")
        for row in rows:
            table.insert("", "end", values=[row[key] or "" for key, _ in columns], tags=("body",))
        table.pack(fill="both", expand=True, padx=12, pady=12)

    def _product_preview(self):
        product_id = self._selected_product_id()
        if not product_id:
            return
        record = self.core.products.get(product_id)
        image_row = self._preferred_product_image(product_id)
        if image_row and self._is_placeholder_image(image_row) and not self._auto_image_sync_running:
            threading.Thread(target=lambda: self._fetch_selected_product_image(product_id), daemon=True).start()
        if not image_row:
            messagebox.showinfo("Preview", "No image is attached to this product yet.")
            return
        win = tk.Toplevel(self)
        win.title("Preview — " + record["name"])
        win.geometry("920x720")
        win.configure(bg=COLORS["bg"])
        viewer = tk.Frame(win, bg=COLORS["surface"])
        viewer.pack(fill="both", expand=True, padx=14, pady=14)
        self._render_image_panel(viewer, image_row, record["name"], max_size=(850, 610))
        tk.Label(win, text=image_row["attribution"] or "Internal reference image", bg=COLORS["bg"],
                 fg=COLORS["muted"], font=("Segoe UI", 8)).pack(pady=(0, 4))
        tk.Button(win, text="Manage Images", command=lambda: self._product_image_manager(product_id, record["name"], win),
                  bg=COLORS["purple"], fg="white", bd=0, padx=16, pady=9).pack(pady=(2, 12))

    def _product_image_manager(self, product_id, product_name, parent_window=None):
        win = tk.Toplevel(parent_window or self)
        win.title("Product Images — " + product_name)
        win.geometry("980x680")
        win.configure(bg=COLORS["bg"])
        container = tk.Frame(win, bg=COLORS["surface"])
        container.pack(fill="both", expand=True, padx=14, pady=14)
        self._build_product_images_tab(container, product_id, product_name, parent_window)

    def _open_product_source(self):
        product_id = self._selected_product_id()
        if not product_id: return
        url = self.core.products.get(product_id)["source_url"]
        if not url:
            messagebox.showinfo("Model source", "This product does not have a source URL."); return
        webbrowser.open(url)

    def _delete_product(self):
        product_id = self._selected_product_id()
        if not product_id: return
        record = self.core.products.get(product_id)
        if messagebox.askyesno("Delete product", "Delete '%s'?\n\nAttached product records will also be removed." % record["name"]):
            self.core.products.delete(product_id); self._refresh_products()

    def publish_test_event(self, module_name: str) -> None:
        self.core.event_bus.publish(Event("ui.module.action", payload={"module": module_name}))
        messagebox.showinfo("FabOS", "Action recorded through the FabOS event bus.")

    def global_search(self) -> None:
        query=self.search_var.get().strip()
        if query.lower().startswith("print "):
            target=query[6:].strip()
            results=[r for r in self.core.global_search.search(target) if r["kind"]=="Product"]
            if results:
                self.show_page("Products")
                pid=results[0]["id"]
                self.after(100,lambda:self._select_and_print_product(pid))
                return
        if query.lower() in ("print next","next print"):
            return self._dashboard_print_next()
        if query.lower() in ("system health","health"):
            return self.show_page("Backup & Health")
        if query.lower() in ("unpaid invoices","invoices unpaid"):
            return self.show_page("Invoices")
        if not query:
            messagebox.showinfo("Search","Enter a product, customer, quote, order, invoice, printer, print job or filament.")
            return
        try:results=self.core.global_search.search(query)
        except Exception as exc:
            return messagebox.showerror("FabOS Search",str(exc))
        win=tk.Toplevel(self);win.title("FabOS Search — "+query);win.geometry("900x570")
        win.minsize(700,420);win.configure(bg=COLORS["bg"]);win.transient(self)
        head=tk.Frame(win,bg=COLORS["bg"]);head.pack(fill="x",padx=18,pady=(18,10))
        tk.Label(head,text='Search results for "%s"'%query,bg=COLORS["bg"],fg=COLORS["text"],
                 font=("Segoe UI",16,"bold")).pack(side="left")
        tk.Label(head,text="%d result%s"%(len(results),"" if len(results)==1 else "s"),
                 bg=COLORS["bg"],fg=COLORS["muted"]).pack(side="right")
        card=self._card(win);card.pack(fill="both",expand=True,padx=18,pady=(0,18))
        cols=("type","title","detail","status")
        table=ttk.Treeview(card,columns=cols,show="headings",style="Dark.Treeview",selectmode="browse")
        for c,label,w in (("type","Type",105),("title","Result",220),("detail","Details",390),("status","Status",100)):
            table.heading(c,text=label);table.column(c,width=w,anchor="w",stretch=(c=="detail"))
        self._search_result_map={}
        for i,r in enumerate(results):
            iid="search_%d"%i;self._search_result_map[iid]=r
            table.insert("","end",iid=iid,values=(r["kind"],r["title"],r["detail"],str(r["status"]).replace("_"," ").title()),tags=("body",))
        table.pack(fill="both",expand=True,padx=12,pady=12)
        def open_result(_event=None):
            sel=table.selection()
            if not sel:return
            result=self._search_result_map.get(sel[0])
            if not result:return
            win.destroy();self.show_page(result["page"])
            self.after(120,lambda:self._select_entity_with_fallback(result["page"],result["id"]))
        table.bind("<Double-1>",open_result)
        table.bind("<Return>",open_result)
        if results:
            table.selection_set("search_0")
        if not results:
            table.insert("","end",values=("","No matches found","Try a name, SKU, order number, invoice number, printer, color, or material.",""),tags=("body",))
        def open_selected(_event=None):
            sel=table.selection()
            if not sel:return
            result=self._search_result_map.get(sel[0])
            if not result:return
            win.destroy();self.show_page(result["page"])
            self.after(100,lambda:self._focus_search_result(result))
        table.bind("<Double-1>",open_selected)
        buttons=tk.Frame(win,bg=COLORS["bg"]);buttons.pack(fill="x",padx=18,pady=(0,18))
        self._button(buttons,"Open Selected",open_selected,True).pack(side="right")
        self._button(buttons,"Close",win.destroy).pack(side="right",padx=7)

    def _focus_search_result(self,result):
        rid=result.get("id");page=result.get("page")
        mapping={
            "Products":"product_table","Customers":"customer_table","Quotes":"quote_table",
            "Orders":"order_table","Invoices":"invoice_table","Production":"production_table",
            "Printers":"printer_table","Filament":"filament_table"
        }
        table=getattr(self,mapping.get(page,""),None)
        if table:
            try:
                if table.exists(rid):
                    table.selection_set(rid);table.focus(rid);table.see(rid)
                    if page=="Products":self._embedded_product_details(rid)
                    elif page=="Orders":self._order_dossier()
            except Exception:
                pass

    def _select_and_print_product(self,pid):
        try:
            if self.product_table.exists(pid):
                self.product_table.selection_set(pid);self.product_table.see(pid)
                self._embedded_product_details(pid)
                self._print_selected_product(product_id=pid)
        except Exception as exc:messagebox.showerror("Print Product",str(exc))

    def quick_add(self) -> None:
        menu=tk.Menu(self,tearoff=0,bg=COLORS["surface_alt"],fg=COLORS["text"],
                     activebackground=COLORS["purple_dark"],activeforeground="white")
        menu.add_command(label="New Quote",command=lambda:(self.show_page("Quotes"),self.after(80,lambda:self._quote_editor(None))))
        menu.add_command(label="New Customer",command=lambda:(self.show_page("Customers"),self.after(80,self._add_customer)))
        menu.add_command(label="Add Product",command=lambda:self.show_page("Products"))
        menu.add_command(label="Add Filament",command=lambda:self.show_page("Filament"))
        menu.add_separator()
        menu.add_command(label="Schedule / View Production",command=lambda:self.show_page("Production"))
        menu.add_command(label="View Printers",command=lambda:self.show_page("Printers"))
        try:
            x=self.winfo_pointerx();y=self.winfo_pointery();menu.tk_popup(x,y)
        finally:
            try:menu.grab_release()
            except Exception:pass

    def create_backup(self) -> None:
        try:
            backup_path = self.core.backups.create()
        except Exception as exc:
            messagebox.showerror("Backup failed", str(exc))
            return
        messagebox.showinfo("Backup complete", str(backup_path))

    def close_app(self) -> None:
        try:
            if str(self.core.shop_settings.get("auto_backup_on_shutdown","1"))=="1":
                path=self.core.backups.create("shutdown")
                result=self.core.backups.validate_backup(path)
                if not result.get("valid"):
                    self.core.error_log.warning("Shutdown backup validation failed",result.get("detail",""))
            self.core.backups.prune(int(float(self.core.shop_settings.get("backup_retention","30") or 30)))
        except Exception as exc:
            try:self.core.error_log.error("Shutdown backup failed",exc)
            except Exception:pass
        finally:
            try:self.core.recovery.clean_shutdown()
            except Exception:pass
            self.destroy()


def main() -> None:
    FabOSDesktop().mainloop()


if __name__ == "__main__":
    main()
