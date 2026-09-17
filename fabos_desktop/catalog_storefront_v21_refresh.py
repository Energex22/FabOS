"""Small follow-up for Pass 21: rebuild the storefront card on every Catalog visit."""


def install():
    from fabos_desktop.system_ui import SystemReliabilityMixin

    if getattr(SystemReliabilityMixin, "_catalog_v21_refresh_hook", False):
        return
    SystemReliabilityMixin._catalog_v21_refresh_hook = True
    previous = SystemReliabilityMixin.__init_subclass__

    def init_subclass(cls, **kwargs):
        previous.__func__(cls, **kwargs)
        if cls.__name__ != "FabOSDesktop":
            return
        current_show_page = cls.show_page

        def show_page(self, page_name, *args, **inner_kwargs):
            if page_name == "Products":
                self._fabvex_storefront_card_added = False
            return current_show_page(self, page_name, *args, **inner_kwargs)

        cls.show_page = show_page

    SystemReliabilityMixin.__init_subclass__ = classmethod(init_subclass)


install()
