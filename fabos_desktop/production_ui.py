import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading

class ProductionMixin:
    STATUS_COLORS = {
        "queued": "#38bdf8", "scheduled": "#8b5cf6", "printing": "#a78bfa",
        "paused": "#fb923c", "qc": "#fb923c", "completed": "#34d399",
        "failed": "#f87171", "cancelled": "#9a9daf",
    }

    def _build_production_page(self):
        toolbar = tk.Frame(self.content, bg=self._c("bg"))
        toolbar.pack(fill="x", pady=(4, 10))
        self._button(toolbar, "Create Jobs from Orders", self._production_generate, True).pack(side="left")
        for label, command in [
            ("Assign", self._production_assign), ("Start", lambda: self._production_status("printing")),
            ("Complete", lambda: self._production_status("completed")),
            ("Failed", self._production_fail),
            ("Retry Failed", self._production_retry_failed),
            ("Reprint", self._production_reprint),
            ("G-code", self._production_gcode), ("Details", self._production_details),
        ]:
            self._button(toolbar, label, command).pack(side="left", padx=(7, 0))

        self.production_view=tk.StringVar(value="active")
        tabs=tk.Frame(self.content,bg=self._c("bg"));tabs.pack(fill="x",pady=(0,8))
        self.production_tab_buttons={}
        for label,value in [("Active Production","active"),("Production History","history")]:
            button=tk.Button(
                tabs,text=label,bd=0,padx=18,pady=9,font=("Segoe UI",9,"bold"),
                command=lambda v=value:self._switch_production_view(v))
            button.pack(side="left",padx=(0,6))
            self.production_tab_buttons[value]=button
        self._style_production_tabs()

        summary = tk.Frame(self.content, bg=self._c("bg"))
        summary.pack(fill="x", pady=(0, 10))
        jobs = self.core.production.list_jobs(group='active')
        counts = {}
        for row in jobs:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        for index, (label, key, color) in enumerate([
            ("Waiting", "queued", self._c("blue")), ("Scheduled", "scheduled", self._c("purple")),
            ("Printing", "printing", "#a78bfa"), ("QC / Completed", "completed", self._c("green")),
            ("Failed", "failed", self._c("red")),
        ]):
            card = self._metric_card(summary, label, counts.get(key, 0), color, "Production jobs")
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 6, 0))
            summary.columnconfigure(index, weight=1)

        controls = self._card(self.content)
        controls.pack(fill="x", pady=(0, 10))
        row = tk.Frame(controls, bg=self._c("surface"))
        row.pack(fill="x", padx=14, pady=10)
        self.production_query = tk.StringVar()
        self.production_status_filter = tk.StringVar(value="All")
        self.production_quick_filter = tk.StringVar(value="All Active")
        tk.Label(row, text="Search", bg=self._c("surface"), fg=self._c("muted")).pack(side="left")
        entry = self._entry(row, self.production_query, 24)
        entry.pack(side="left", padx=(7, 12), ipady=6)
        entry.bind("<KeyRelease>", lambda _e: self._refresh_production())
        tk.Label(row, text="View", bg=self._c("surface"), fg=self._c("muted")).pack(side="left")
        self.production_quick_combo=ttk.Combobox(
            row,textvariable=self.production_quick_filter,
            values=["All Active","Ready","Printing","Needs Attention","Failed"],
            state="readonly",width=16)
        self.production_quick_combo.pack(side="left",padx=7)
        self.production_quick_combo.bind("<<ComboboxSelected>>",lambda _e:self._refresh_production())
        tk.Label(row, text="Status", bg=self._c("surface"), fg=self._c("muted")).pack(side="left",padx=(10,0))
        self.production_status_combo = ttk.Combobox(
            row, textvariable=self.production_status_filter,
            values=["All", "queued", "scheduled", "printing", "paused", "failed"],
            state="readonly", width=13
        )
        self.production_status_combo.pack(side="left", padx=7)
        self.production_status_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_production())
        self.production_count=tk.Label(row,text="",bg=self._c("surface"),fg=self._c("muted"))
        self.production_count.pack(side="right")

        split = tk.PanedWindow(
            self.content, orient="horizontal", bg=self._c("bg"),
            sashwidth=6, sashrelief="flat", bd=0
        )
        split.pack(fill="both", expand=True)

        left = self._card(split, "Production Queue")
        right = self._card(split, "Selected Job")
        split.add(left, minsize=610, stretch="always")
        split.add(right, minsize=350, stretch="always")

        columns = ("job", "order", "product", "printfile", "printer", "status", "estimate", "material")
        self.production_table = ttk.Treeview(
            left, columns=columns, show="headings", style="Dark.Treeview", selectmode="browse"
        )
        labels = {"job": "Job", "order": "Order", "product": "Product", "printfile":"Print File",
                  "printer": "Printer", "status": "Status", "estimate": "Estimate", "material": "Material"}
        widths = {"job": 58, "order": 84, "product": 155, "printfile":100, "printer": 105,
                  "status": 70, "estimate": 72, "material": 90}
        for col in columns:
            self.production_table.heading(col, text=labels[col])
            self.production_table.column(
                col,width=widths[col],anchor="w",
                stretch=(col=="product"))
        for key, color in self.STATUS_COLORS.items():
            self.production_table.tag_configure(key, foreground=color, background=self._c("surface"))
        sy = ttk.Scrollbar(left, orient="vertical", command=self.production_table.yview)
        self.production_table.configure(yscrollcommand=sy.set)
        self.production_table.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=(0, 12))
        sy.pack(side="right", fill="y", padx=(0, 12), pady=(0, 12))
        self.production_table.bind("<<TreeviewSelect>>", lambda _e: self._production_selected_panel())
        self.production_table.bind("<Double-1>", lambda _e: self._production_details())
        self.production_table.bind("<Button-3>", self._production_context_menu)

        self.production_detail_panel = tk.Frame(right, bg=self._c("surface"))
        self.production_detail_panel.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        self._refresh_production()
        self._start_production_live_refresh()

    def _start_production_live_refresh(self):
        token=getattr(self,'_production_live_token',0)+1
        self._production_live_token=token
        self.after(1200,lambda:self._production_live_tick(token))

    def _production_live_tick(self,token):
        if token!=getattr(self,'_production_live_token',None) or getattr(self,'active_page',None)!='Production':
            return
        if getattr(self,'_production_sync_busy',False):
            self.after(2000,lambda:self._production_live_tick(token))
            return
        self._production_sync_busy=True

        def worker():
            try:
                for printer in self.core.printer_automation.list():
                    if printer['connection_mode']=='octoprint' and printer['octoprint_url'] and printer['api_key_ref']:
                        try:self.core.printer_automation.sync_octoprint(printer['id'])
                        except Exception:pass
            finally:
                def apply():
                    self._production_sync_busy=False
                    if token!=getattr(self,'_production_live_token',None) or getattr(self,'active_page',None)!='Production':
                        return
                    try:self._refresh_production()
                    except Exception:pass
                    self.after(3000,lambda:self._production_live_tick(token))
                self.after(0,apply)

        threading.Thread(target=worker,name='FabOS-ProductionLiveSync',daemon=True).start()

    def _production_context_menu(self,event):
        row=self.production_table.identify_row(event.y)
        if row:self.production_table.selection_set(row)
        menu=tk.Menu(self,tearoff=0,bg=self._c('surface_alt'),fg=self._c('text'),
                     activebackground=self._c('purple_dark'),activeforeground='white')
        menu.add_command(label='Start / Print',command=self._production_start_print)
        menu.add_command(label='Open Product',command=lambda:self._open_job_product(self.core.production.get(self._selected_production_id())) if self._selected_production_id() else None)
        menu.add_command(label='Assign Printer / Spool',command=self._production_assign)
        menu.add_separator()
        menu.add_command(label='Mark Completed',command=lambda:self._production_status('completed'))
        menu.add_command(label='Record Failed Print',command=self._production_fail)
        menu.add_command(label='Retry Failed Print',command=self._production_retry_failed)
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:
            try:menu.grab_release()
            except Exception:pass

    def _production_generate(self):
        try:
            count = self.core.production.create_jobs_for_all_new_orders()
        except Exception as exc:
            messagebox.showerror("Production", str(exc))
            return
        self._refresh_production()
        messagebox.showinfo("Production", "%d new print job(s) were created." % count)

    def _selected_production_id(self):
        selected = self.production_table.selection() if getattr(self, "production_table", None) else ()
        if not selected:
            messagebox.showinfo("Production", "Select a print job first.")
            return None
        return selected[0]

    def _switch_production_view(self,view):
        self.production_view.set(view)
        self.production_status_filter.set("All")
        self.production_quick_filter.set("All Active" if view=="active" else "All History")
        if view=="active":
            self.production_quick_combo.configure(values=["All Active","Ready","Printing","Needs Attention","Failed"])
            self.production_status_combo.configure(values=["All","queued","scheduled","printing","paused","failed"])
        else:
            self.production_quick_combo.configure(values=["All History","Completed","Cancelled"])
            self.production_status_combo.configure(values=["All","completed","cancelled"])
        self._style_production_tabs()
        self._refresh_production()

    def _style_production_tabs(self):
        active=self.production_view.get()
        for value,button in self.production_tab_buttons.items():
            selected=value==active
            button.configure(
                bg=self._c("purple") if selected else self._c("surface_alt"),
                fg="white" if selected else self._c("text"),
                activebackground=self._c("purple_dark") if selected else self._c("border"),
                activeforeground="white")

    def _refresh_production(self):
        if not getattr(self, "production_table", None):
            return
        self.production_table.delete(*self.production_table.get_children())
        group=self.production_view.get() if getattr(self,"production_view",None) else "active"
        rows = list(self.core.production.list_jobs(
            self.production_query.get().strip(),
            self.production_status_filter.get(),
            group=group
        ))
        quick=self.production_quick_filter.get() if getattr(self,"production_quick_filter",None) else ""
        display=[]
        for row in rows:
            try:readiness=self.core.production.job_print_readiness(row["id"],self.core.design_vault)
            except Exception:readiness={"ready":False,"state":"attention","reason":"Check print file"}
            status=str(row["status"] or "").lower()
            include=True
            if group=="active":
                if quick=="Printing":include=status in ("printing","paused")
                elif quick=="Failed":include=status=="failed"
                elif quick=="Ready":include=status in ("queued","scheduled") and readiness.get("ready")
                elif quick=="Needs Attention":
                    include=(status in ("queued","scheduled") and not readiness.get("ready")) or status=="failed"
            else:
                if quick=="Completed":include=status=="completed"
                elif quick=="Cancelled":include=status=="cancelled"
            if include:display.append((row,readiness))

        for row,readiness in display:
            minutes = int(row["estimated_minutes"] or 0)
            estimate = "%dh %02dm" % (minutes // 60, minutes % 60) if minutes else "—"
            file_text={"gcode":"G-code Ready","stl":"STL Ready","attention":"Needs Attention"}.get(
                readiness.get("state"),"Check File")
            self.production_table.insert(
                "", "end", iid=row["id"],
                values=(row["id"][:8], row["order_number"], row["product_name"],file_text,
                        row["printer_name"], row["status"].title(), estimate, row["spool_name"]),
                tags=(row["status"],),
            )
        if getattr(self,"production_count",None):
            label="active job" if group=="active" else "history job"
            self.production_count.configure(text="%d %s%s"%(len(display),label,"" if len(display)==1 else "s"))
        self._production_selected_panel()

    def _production_selected_panel(self):
        panel = getattr(self, "production_detail_panel", None)
        if not panel:
            return
        for child in panel.winfo_children():
            child.destroy()
        selected = self.production_table.selection()
        if not selected:
            tk.Label(panel, text="Select a job to see its production dossier.",
                     bg=self._c("surface"), fg=self._c("muted"),
                     font=("Segoe UI", 10), wraplength=280, justify="left").pack(anchor="w", pady=14)
            return
        job = self.core.production.get(selected[0])
        tk.Label(panel, text=job["product_name"], bg=self._c("surface"), fg=self._c("text"),
                 font=("Segoe UI", 16, "bold"), wraplength=290, justify="left").pack(anchor="w", pady=(8, 3))
        tk.Label(panel, text="%s • %s" % (job["order_number"], job["customer_name"]),
                 bg=self._c("surface"), fg=self._c("muted"), font=("Segoe UI", 9)).pack(anchor="w")
        color = self.STATUS_COLORS.get(job["status"], self._c("muted"))
        tk.Label(panel, text=job["status"].upper(), bg=self._c("surface_alt"), fg=color,
                 font=("Segoe UI", 9, "bold"), padx=10, pady=5).pack(anchor="w", pady=12)
        try:readiness=self.core.production.job_print_readiness(job["id"],self.core.design_vault)
        except Exception:readiness={"ready":False,"state":"attention","reason":"Print file needs attention","gcode":None}
        details = [
            ("Print File", readiness.get("reason","—")),
            ("Printer", job["printer_name"]), ("Filament", job["spool_name"]),
            ("Estimated Time", self._minutes(job["estimated_minutes"])),
            ("Estimated Filament", "%.0f g" % (job["estimated_filament_g"] or 0)),
            ("Actual Time", self._minutes(job["actual_minutes"])),
            ("Started", str(job["started_at"] or "—")[:19]),
            ("Finished", str(job["completed_at"] or "—")[:19]),
        ]
        for label, value in details:
            line = tk.Frame(panel, bg=self._c("surface"))
            line.pack(fill="x", pady=3)
            tk.Label(line, text=label, bg=self._c("surface"), fg=self._c("muted"),
                     width=17, anchor="w").pack(side="left")
            tk.Label(line, text=str(value), bg=self._c("surface"), fg=self._c("text"),
                     anchor="w", wraplength=170, justify="left").pack(side="left", fill="x", expand=True)
        if job["product_id"]:
            start_label="▶ Start Print" if readiness.get("ready") else "Fix Print File"
            start_cmd=self._production_start_print if readiness.get("ready") else lambda:self._open_job_product(job)
            self._button(panel,start_label,start_cmd,True).pack(fill="x",pady=(18,6))
            self._button(panel, "Open Product", lambda: self._open_job_product(job)).pack(fill="x", pady=3)
        self._button(panel, "Assign Printer / Spool", self._production_assign).pack(fill="x", pady=3)

    @staticmethod
    def _minutes(value):
        if not value:
            return "—"
        value = int(value)
        return "%dh %02dm" % (value // 60, value % 60)

    def _open_job_product(self, job):
        if not job["product_id"]:
            return
        self.show_page("Products")
        try:
            self.product_table.selection_set(job["product_id"])
            self.product_table.see(job["product_id"])
            self._embedded_product_details(job["product_id"])
        except Exception:
            pass

    def _production_start_print(self):
        job_id=self._selected_production_id()
        if not job_id:return
        job=self.core.production.get(job_id)
        if not job["product_id"]:
            return messagebox.showwarning("Start Print","This production job has no catalog product/model attached.")
        if not job["printer_id"]:
            return messagebox.showwarning("Start Print","Assign a printer to this production job first.")
        if not job["spool_id"]:
            return messagebox.showwarning("Start Print","Assign the loaded filament spool to this production job first.")
        readiness=self.core.production.job_print_readiness(job_id,self.core.design_vault)
        if not readiness.get("ready"):
            return messagebox.showwarning("Start Print",readiness.get("reason","This job needs a printable file."))
        self._print_selected_product(
            product_id=job["product_id"],
            printer_id=job["printer_id"],
            spool_id=job["spool_id"],
            existing_job_id=job_id,
            preferred_gcode=readiness.get("gcode")
        )

    def _production_assign(self):
        job_id = self._selected_production_id()
        if not job_id:
            return
        win = tk.Toplevel(self)
        win.title("Assign Production Job")
        win.geometry("520x300")
        win.configure(bg=self._c("bg"))
        win.transient(self)
        win.grab_set()
        printers = self.core.production.printers()
        spools = self.core.production.spools()
        printer_map = {"%s — %s" % (p["name"], p["status"].title()): p["id"] for p in printers}
        spool_map = {
            "%s %s — %.0fg" % (s["material"], s["color"] or "", s["remaining_g"]): s["id"]
            for s in spools
        }
        printer_var, spool_var = tk.StringVar(), tk.StringVar()
        body = self._card(win, "Assign Printer and Filament")
        body.pack(fill="both", expand=True, padx=16, pady=16)
        tk.Label(body, text="Printer", bg=self._c("surface"), fg=self._c("muted")).pack(anchor="w", padx=16)
        ttk.Combobox(body, textvariable=printer_var, values=list(printer_map), state="readonly").pack(fill="x", padx=16, pady=(4, 12))
        tk.Label(body, text="Filament Spool", bg=self._c("surface"), fg=self._c("muted")).pack(anchor="w", padx=16)
        ttk.Combobox(body, textvariable=spool_var, values=list(spool_map), state="readonly").pack(fill="x", padx=16, pady=(4, 12))
        def save():
            self.core.production.assign(job_id, printer_map.get(printer_var.get()), spool_map.get(spool_var.get()))
            win.destroy()
            self._refresh_production()
        self._button(body, "Save Assignment", save, True).pack(anchor="e", padx=16, pady=10)

    def _production_status(self, status):
        job_id = self._selected_production_id()
        if not job_id:
            return
        try:
            self.core.production.set_status(job_id, status)
        except Exception as exc:
            messagebox.showerror("Production", str(exc))
            return
        self._refresh_production()


    def _production_gcode(self):
        jid=self._selected_production_id()
        if not jid:return
        path=filedialog.askopenfilename(filetypes=[("G-code","*.gcode"),("All","*.*")])
        if not path:return
        try:
            m=self.core.manufacturing.attach_gcode(jid,path);messagebox.showinfo("PrusaSlicer G-code","Attached. Estimated time: %s; filament: %s g"%(self._minutes(m.get("estimated_minutes")),m.get("filament_g") if m.get("filament_g") is not None else "—"));self._refresh_production()
        except Exception as exc:messagebox.showerror("G-code",str(exc))

    def _production_fail(self):
        job_id = self._selected_production_id()
        if not job_id:
            return
        win=tk.Toplevel(self);win.title("Failed Print");win.geometry("520x310");win.configure(bg=self._c("bg"));win.transient(self);win.grab_set()
        body=self._card(win,"Failure Reason");body.pack(fill="both",expand=True,padx=16,pady=16)
        reason=tk.StringVar(value="Bed adhesion")
        ttk.Combobox(body,textvariable=reason,state="readonly",values=[
            "Bed adhesion","Stringing / blobs","Layer shift","Nozzle clog","Filament problem",
            "Power loss","Dimensional / fit issue","Support failure","Printer error","User cancelled","Other"
        ]).pack(fill="x",padx=16,pady=14)
        def save():
            self.core.manufacturing.fail_job(job_id,reason.get())
            self.core.production.set_status(job_id,"failed")
            try:
                grams=self.core.inventory_profit.record_failed_waste(job_id)
                self.core.operations.log('print.failed','Failed print recorded',
                    '%s • estimated waste %.0fg'%(reason.get(),grams),'Production',job_id)
            except Exception:pass
            win.destroy();self._refresh_production()
        self._button(body,"Record Failed Print",save,True).pack(anchor="e",padx=16,pady=12)

    def _production_retry_failed(self):
        job_id=self._selected_production_id()
        if not job_id:return
        job=self.core.production.get(job_id)
        if str(job["status"]).lower()!="failed":
            return messagebox.showinfo("Retry Print","Select a failed Production job first.")
        if not job["product_id"]:
            return messagebox.showwarning("Retry Print","The failed job has no Catalog product attached.")
        try:
            readiness=self.core.production.job_print_readiness(job_id,self.core.design_vault)
            if not readiness.get("ready"):
                return messagebox.showwarning("Retry Print",readiness.get("reason","The product needs a printable file."))
            self._print_selected_product(
                product_id=job["product_id"],printer_id=job["printer_id"],spool_id=job["spool_id"],
                existing_job_id=job_id,preferred_gcode=readiness.get("gcode"))
        except Exception as exc:
            messagebox.showerror("Retry Print",str(exc))

    def _production_reprint(self):
        job_id=self._selected_production_id()
        if not job_id:return
        try:
            self.core.manufacturing.reprint(job_id)
            self._refresh_production()
            messagebox.showinfo("Reprint","A replacement job was added while the original print remains in history.")
        except Exception as exc:messagebox.showerror("Reprint",str(exc))

    def _production_details(self):
        job_id = self._selected_production_id()
        if not job_id:
            return
        self._production_selected_panel()
