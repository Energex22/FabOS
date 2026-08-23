import tkinter as tk
from tkinter import ttk

SALES_TABS = ("Quotes", "Orders", "Invoices", "Customers")

class SalesWorkspace(ttk.Frame):
    def __init__(self, master, page_builder=None, on_change=None, **kwargs):
        super().__init__(master, **kwargs)
        self.page_builder = page_builder
        self.on_change = on_change
        self.search_var = tk.StringVar()
        header = ttk.Frame(self)
        header.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(header, text="Sales", font=("", 15, "bold")).pack(side="left")
        ttk.Label(header, text="Search").pack(side="right")
        ttk.Entry(header, textvariable=self.search_var, width=28).pack(
            side="right", padx=(8, 0))
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=8, pady=8)
        self.frames = {}
        for name in SALES_TABS:
            frame = ttk.Frame(self.tabs)
            self.tabs.add(frame, text=name)
            self.frames[name] = frame
            if page_builder:
                page_builder(name, frame)
        self.tabs.bind("<<NotebookTabChanged>>", self._changed)

    def _changed(self, _event=None):
        if self.on_change:
            self.on_change(self.active_tab())

    def active_tab(self):
        try:
            return self.tabs.tab(self.tabs.select(), "text")
        except tk.TclError:
            return "Quotes"

    def select(self, name):
        if name in self.frames:
            self.tabs.select(self.frames[name])
            return True
        return False

    def search_text(self):
        return self.search_var.get().strip()
