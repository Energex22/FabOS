"""Pass 21: consolidate catalog operations and add Fabvex storefront publishing.

This module is loaded before ``fabos_desktop.main`` creates FabOSDesktop.  It
uses the existing SystemReliabilityMixin subclass hook to extend the desktop
without duplicating the large legacy shell file.
"""

import tkinter as tk
from tkinter import messagebox



def _safe_call(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _storefront_values(state, visibility):
    state = state or {}
    return {
        "visibility": visibility,
        "origin_type": state.get("origin_type") or "catalog_import",
        "source_customer_id": state.get("source_customer_id"),
        "customer_title": state.get("customer_title"),
        "customer_description": state.get("customer_description"),
    }


def _open_fabvex_storefront(self, product_id=None):
    product_id = product_id or _safe_call(self._selected_product_id)
    if not product_id:
        return messagebox.showinfo(
            "Fabvex Storefront",
            "Select a product in Catalog before managing its Fabvex listing.",
            parent=self,
        )

    product = self.core.products.get(product_id)
    if product is not None:
        product = dict(product)
    if not product:
        return messagebox.showerror("Fabvex Storefront", "The selected product no longer exists.", parent=self)

    state = self.core.products.storefront_state(product_id) or {}
    readiness = self.core.products.storefront_publication_readiness(product_id)
    visibility = str(state.get("visibility") or "draft").lower()
    ready = bool(readiness.get("ready"))

    win = tk.Toplevel(self)
    win.title("Fabvex Storefront — " + str(product["name"] or "Product"))
    win.geometry("650x560")
    win.minsize(560, 500)
    win.configure(bg=self._c("bg"))
    win.transient(self)
    win.grab_set()

    body = tk.Frame(win, bg=self._c("bg"))
    body.pack(fill="both", expand=True, padx=22, pady=22)

    tk.Label(
        body, text="Fabvex Storefront", bg=self._c("bg"), fg=self._c("text"),
        font=("Segoe UI", 19, "bold"), anchor="w",
    ).pack(fill="x")
    tk.Label(
        body, text=str(product["name"] or "Product"), bg=self._c("bg"), fg=self._c("muted"),
        font=("Segoe UI", 10), anchor="w", wraplength=580,
    ).pack(fill="x", pady=(4, 18))

    status = tk.Frame(body, bg=self._c("surface"), highlightbackground=self._c("border"), highlightthickness=1)
    status.pack(fill="x", pady=(0, 12))
    status.columnconfigure(1, weight=1)
    tk.Label(status, text="LISTING STATUS", bg=self._c("surface"), fg=self._c("muted"),
             font=("Segoe UI", 8, "bold")).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))
    status_label = tk.Label(status, text=visibility.upper(), bg=self._c("surface"),
                            fg=self._c("green") if visibility == "published" else self._c("orange"),
                            font=("Segoe UI", 10, "bold"))
    status_label.grid(row=0, column=1, sticky="w", padx=10, pady=(14, 4))
    tk.Label(status, text="PUBLICATION READINESS", bg=self._c("surface"), fg=self._c("muted"),
             font=("Segoe UI", 8, "bold")).grid(row=1, column=0, sticky="w", padx=16, pady=(4, 14))
    tk.Label(status, text="READY" if ready else "NOT READY", bg=self._c("surface"),
             fg=self._c("green") if ready else self._c("red"),
             font=("Segoe UI", 10, "bold")).grid(row=1, column=1, sticky="w", padx=10, pady=(4, 14))

    detail = tk.Frame(body, bg=self._c("surface"))
    detail.pack(fill="both", expand=True, pady=(0, 14))
    tk.Label(detail, text="What needs attention", bg=self._c("surface"), fg=self._c("text"),
             font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x", padx=16, pady=(14, 6))
    reasons = list(readiness.get("reasons") or [])
    if ready:
        reasons = ["Model, price, and license checks are ready for customer publication."]
    elif not reasons:
        reasons = ["The product is not ready for customer publication."]
    for reason in reasons:
        tk.Label(detail, text="• " + str(reason), bg=self._c("surface"), fg=self._c("muted"),
                 font=("Segoe UI", 9), anchor="w", justify="left", wraplength=570).pack(fill="x", padx=16, pady=3)

    buttons = tk.Frame(body, bg=self._c("bg"))
    buttons.pack(fill="x")

    def save_visibility(new_visibility):
        try:
            values = _storefront_values(state, new_visibility)
            updated = self.core.products.save_storefront(product_id, values)
            try:
                self.core.operations.log(
                    "storefront.visibility_changed",
                    "Changed Fabvex storefront visibility",
                    "%s → %s" % (visibility, new_visibility),
                    "Products", product_id,
                )
            except Exception:
                pass
            messagebox.showinfo(
                "Fabvex Storefront",
                "%s is now %s in the Fabvex catalog." % (product["name"], str(updated.get("visibility") or new_visibility).upper()),
                parent=win,
            )
            win.destroy()
            self.show_page("Products")
        except Exception as exc:
            messagebox.showerror("Fabvex Storefront", str(exc), parent=win)

    if visibility != "published":
        tk.Button(
            buttons, text="Publish to Fabvex" if ready else "Publish when ready",
            bg=self._c("green") if ready else self._c("surface_alt"),
            fg="white" if ready else self._c("muted"), bd=0,
            activebackground=self._c("green") if ready else self._c("border"),
            activeforeground="white", font=("Segoe UI", 10, "bold"), padx=18, pady=10,
            command=lambda: save_visibility("published"),
            state=tk.NORMAL if ready else tk.DISABLED,
        ).pack(side="left")
    else:
        tk.Button(
            buttons, text="Unpublish", bg=self._c("surface_alt"), fg=self._c("text"), bd=0,
            activebackground=self._c("border"), activeforeground="white",
            font=("Segoe UI", 10, "bold"), padx=18, pady=10,
            command=lambda: save_visibility("draft"),
        ).pack(side="left")
        tk.Button(
            buttons, text="Retire", bg=self._c("surface_alt"), fg=self._c("muted"), bd=0,
            activebackground=self._c("border"), activeforeground="white",
            font=("Segoe UI", 9), padx=14, pady=10,
            command=lambda: save_visibility("retired"),
        ).pack(side="left", padx=8)

    tk.Button(
        buttons, text="Close", bg=self._c("surface_alt"), fg=self._c("muted"), bd=0,
        activebackground=self._c("border"), activeforeground="white",
        font=("Segoe UI", 9), padx=16, pady=10, command=win.destroy,
    ).pack(side="right")


def _add_storefront_card(self):
    if getattr(self, "_fabvex_storefront_card_added", False):
        return
    self._fabvex_storefront_card_added = True

    card = tk.Frame(self.content, bg=self._c("surface"), highlightbackground=self._c("border"), highlightthickness=1)
    children = self.content.winfo_children()
    if children:
        card.pack(fill="x", pady=(0, 10), before=children[0])
    else:
        card.pack(fill="x", pady=(0, 10))

    left = tk.Frame(card, bg=self._c("surface"))
    left.pack(side="left", fill="x", expand=True, padx=16, pady=12)
    tk.Label(left, text="FABVEX STOREFRONT", bg=self._c("surface"), fg=self._c("purple"),
             font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x")
    tk.Label(left, text="Publish the selected Catalog product directly to Fabvex.", bg=self._c("surface"),
             fg=self._c("muted"), font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(3, 0))
    tk.Button(
        card, text="Manage Listing", bg=self._c("purple"), fg="white", bd=0,
        activebackground=self._c("purple_dark"), activeforeground="white",
        font=("Segoe UI", 9, "bold"), padx=16, pady=9,
        command=lambda: _open_fabvex_storefront(self),
    ).pack(side="right", padx=16, pady=12)


def _install_catalog_v21(cls):
    if getattr(cls, "_catalog_v21_installed", False):
        return
    cls._catalog_v21_installed = True

    # Products is the single operator-facing catalog workspace. Design Vault
    # remains an internal storage/pipeline service for custom uploads and model
    # assets, but it is no longer a desktop destination.
    workspaces = dict(getattr(cls, "WORKSPACES", {}))
    workspaces.pop("Design Vault", None)
    if "Products" in workspaces:
        workspaces["Products"] = ("Catalog", ["Products"])
    cls.WORKSPACES = workspaces

    original_show_page = cls.show_page
    def show_page(self, page_name, *args, **kwargs):
        if page_name == "Design Vault":
            page_name = "Products"
        return original_show_page(self, page_name, *args, **kwargs)
    cls.show_page = show_page

    original_build_products = cls._build_products_page
    def build_products(self, *args, **kwargs):
        result = original_build_products(self, *args, **kwargs)
        try:
            _add_storefront_card(self)
        except Exception as exc:
            try:
                self.core.error_log.warning("Fabvex storefront card could not be added", str(exc))
            except Exception:
                pass
        return result
    cls._build_products_page = build_products

    # Any legacy callback that would have opened the old destination now stays
    # inside the product workspace and opens the product dossier instead.
    if hasattr(cls, "_open_selected_product_design"):
        cls._open_selected_product_design = lambda self: _safe_call(
            lambda: self._product_details(), None
        )

    cls._open_fabvex_storefront = _open_fabvex_storefront


def install():
    # The immediate parent of FabOSDesktop is SystemReliabilityMixin. Its
    # subclass hook runs after the class body has been created, which lets this
    # module extend the legacy shell without maintaining a second copy of it.
    from fabos_desktop.system_ui import SystemReliabilityMixin

    if getattr(SystemReliabilityMixin, "_catalog_v21_hook", False):
        return
    SystemReliabilityMixin._catalog_v21_hook = True

    def init_subclass(cls, **kwargs):
        # SystemReliabilityMixin has no custom subclass initialization of its
        # own, so there is no legacy hook to forward to here.
        if cls.__name__ == "FabOSDesktop":
            _install_catalog_v21(cls)

    SystemReliabilityMixin.__init_subclass__ = classmethod(init_subclass)


install()
