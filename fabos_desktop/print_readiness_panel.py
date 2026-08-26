import tkinter as tk
from tkinter import ttk

class PrintReadinessPanel(ttk.Frame):
    def __init__(self, master, evaluator, on_print=None, on_fix=None, **kwargs):
        super().__init__(master, **kwargs)
        self.evaluator, self.on_print, self.on_fix = evaluator, on_print, on_fix
        self.result = None
        self.status_var = tk.StringVar(value="Select a product")
        ttk.Label(self, text="Print Readiness", font=("",14,"bold")).pack(
            anchor="w", padx=10, pady=(10,2))
        ttk.Label(self, textvariable=self.status_var, font=("",12,"bold")).pack(
            anchor="w", padx=10)
        self.list = ttk.Frame(self); self.list.pack(fill="both", expand=True, padx=10, pady=8)
        buttons = ttk.Frame(self); buttons.pack(fill="x", padx=10, pady=(0,10))
        self.print_button = ttk.Button(buttons, text="PRINT", command=self._print, state="disabled")
        self.print_button.pack(side="right")
        self.fix_button = ttk.Button(buttons, text="Fix Issue", command=self._fix, state="disabled")
        self.fix_button.pack(side="right", padx=(0,8))

    def load(self, product_id, product_name, **kwargs):
        self.result = self.evaluator(product_id, product_name, **kwargs)
        for child in self.list.winfo_children(): child.destroy()
        for item in self.result.items:
            marker = "✓" if item.ok else ("⚠" if item.severity == "warning" else "✕")
            row = ttk.Frame(self.list); row.pack(fill="x", pady=2)
            ttk.Label(row, text=f"{marker} {item.label}").pack(side="left")
            if not item.ok and item.detail:
                ttk.Label(row, text=item.detail).pack(side="right")
        self.status_var.set(self.result.summary())
        self.print_button.configure(state="normal" if self.result.ready else "disabled")
        self.fix_button.configure(state="normal" if (self.result.errors or self.result.warnings) else "disabled")

    def _print(self):
        if self.on_print and self.result and self.result.ready: self.on_print(self.result)

    def _fix(self):
        if self.on_fix and self.result: self.on_fix(self.result)
