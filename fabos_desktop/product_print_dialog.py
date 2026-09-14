"""Reusable Product Print selection UI foundation."""
import tkinter as tk
from tkinter import ttk

class ProductPrintDialog(ttk.Frame):
    def __init__(self, master, products, printers=None, orders=None,
                 on_start=None, **kwargs):
        super().__init__(master, **kwargs)
        self.products = products or []
        self.printers = printers or []
        self.orders = orders or []
        self.on_start = on_start
        self.product_var = tk.StringVar()
        self.printer_var = tk.StringVar()
        self.order_var = tk.StringVar()
        self.quantity_var = tk.IntVar(value=1)
        self.status_var = tk.StringVar(value="Select a product")

        ttk.Label(self, text="Start Print", font=("", 14, "bold")).pack(
            anchor="w", padx=10, pady=(10, 8))
        ttk.Label(self, text="Product").pack(anchor="w", padx=10)
        self.product_box = ttk.Combobox(
            self, textvariable=self.product_var,
            values=[str(x) for x in self.products], state="readonly")
        self.product_box.pack(fill="x", padx=10, pady=(2, 8))

        ttk.Label(self, text="Printer").pack(anchor="w", padx=10)
        self.printer_box = ttk.Combobox(
            self, textvariable=self.printer_var,
            values=[str(x) for x in self.printers], state="readonly")
        self.printer_box.pack(fill="x", padx=10, pady=(2, 8))

        ttk.Label(self, text="Attach to Order (optional)").pack(
            anchor="w", padx=10)
        self.order_box = ttk.Combobox(
            self, textvariable=self.order_var,
            values=[str(x) for x in self.orders], state="readonly")
        self.order_box.pack(fill="x", padx=10, pady=(2, 8))

        ttk.Label(self, text="Quantity").pack(anchor="w", padx=10)
        ttk.Spinbox(self, from_=1, to=999,
                    textvariable=self.quantity_var).pack(
            fill="x", padx=10, pady=(2, 8))

        ttk.Label(self, textvariable=self.status_var).pack(
            anchor="w", padx=10, pady=8)

        self.start_button = ttk.Button(
            self, text="Check & Print", command=self._start, state="disabled")
        self.start_button.pack(anchor="e", padx=10, pady=(0, 10))
        self.product_box.bind("<<ComboboxSelected>>", self._selection_changed)
        self.printer_box.bind("<<ComboboxSelected>>", self._selection_changed)

    def _selection_changed(self, _event=None):
        ready = bool(self.product_var.get() and self.printer_var.get())
        self.status_var.set(
            "Product and printer selected — ready for preflight"
            if ready else "Select a product and printer")
        self.start_button.configure(
            state="normal" if ready else "disabled")

    def _start(self):
        if self.on_start:
            self.on_start({
                "product": self.product_var.get(),
                "printer": self.printer_var.get(),
                "order": self.order_var.get(),
                "quantity": self.quantity_var.get(),
            })
