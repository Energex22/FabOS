import tkinter as tk
from tkinter import ttk,messagebox,filedialog
from pathlib import Path
import threading
import time,webbrowser,json,uuid

class ProductPrintMixin:
    def _choose_file(self,var,filetypes):
        path=filedialog.askopenfilename(filetypes=filetypes)
        if path:var.set(path)

    def _filament_check_for_print(self,spool,grams,parent=None):
        if not grams or not spool:return True
        need=float(grams);have=float(spool["remaining_g"] or 0);after=have-need
        if have+0.01<need:
            messagebox.showerror(
                "Insufficient Filament",
                "This print needs about %.0f g, but the selected %s %s spool has only %.0f g remaining.\n\n"
                "Choose a different spool before starting."%
                (need,spool["material"],spool["color"] or "",have),parent=parent or self)
            return False
        if after<max(25.0,need*0.08):
            return messagebox.askyesno(
                "Low Filament After Print",
                "Estimated filament required: %.0f g\n"
                "Selected spool remaining: %.0f g\n"
                "Estimated after print: %.0f g\n\n"
                "That leaves very little reserve. Continue?"%(need,have,after),parent=parent or self)
        return True

    def _import_cura_gcode_print(self, product_id, printer, spool, existing_job_id=None,
                                order_id=None, parent=None, model_status=None, gcode_path=None):
        """Import G-code already sliced in Cura, then verify/upload/start it."""
        parent=parent or self
        product=self.core.products.get(product_id)
        if not product:return
        model_status=model_status or self.core.design_vault.product_model_status(product_id)

        if gcode_path:
            gcode=Path(gcode_path)
            if not gcode.exists():
                return messagebox.showerror("Saved G-code","The saved G-code file no longer exists:\n\n"+str(gcode),parent=parent)
        else:
            gcode=filedialog.askopenfilename(
                parent=parent,
                title="Select Cura G-code — "+product["name"],
                filetypes=[("G-code files","*.gcode *.gco *.gc"),("All files","*.*")]
            )
            if not gcode:return
            gcode=Path(gcode)

        try:
            validation=self.core.cura.validate_print_gcode(gcode)
            if not validation["valid"]:
                return messagebox.showerror(
                    "Cura G-code Safety Check",
                    "FabOS will not send this G-code to the printer:\n\n"+
                    "\n".join("• "+p for p in validation["problems"]),parent=parent)

            bounds=validation.get("bounds") or {}
            gmeta=self.core.cura.gcode_metadata(gcode,spool["material"])
            targets=self.core.cura.gcode_heater_targets(gcode)
            if not self._filament_check_for_print(spool,gmeta.get("filament_g"),parent):
                return

            # Any manually imported Cura G-code becomes reusable for this Catalog
            # product automatically. Existing Design Vault files de-duplicate by SHA-256.
            if not gcode_path:
                try:self.core.design_vault.import_product_print_files(product_id,[gcode])
                except Exception:pass

            preflight=self.core.octoprint_print.preflight(printer)
            uploaded=self.core.octoprint_print.upload_and_select(printer,gcode)
            octo_path=uploaded["path"]

            attached_job=None
            if not existing_job_id and order_id:
                attached_job=self.core.production.find_attachable_job(order_id,product_id)
            job_id=existing_job_id or (attached_job["id"] if attached_job else None)

            order_text="Personal / no order"
            if order_id:
                with self.core.database.connect() as c:
                    row=c.execute("SELECT order_number FROM orders WHERE id=?",(order_id,)).fetchone()
                if row:order_text=row["order_number"]

            summary=[
                "Cura G-code: "+gcode.name,
                "Order: "+order_text,
                "OctoPrint file: "+octo_path,
                "XY range: X %.2f–%.2f mm, Y %.2f–%.2f mm"%(
                    bounds.get("min_x",0),bounds.get("max_x",0),
                    bounds.get("min_y",0),bounds.get("max_y",0))
            ]
            if targets.get("bed") or targets.get("hotend"):
                summary.append("Preheat together: bed %s°C / hotend %s°C"%(
                    "—" if targets.get("bed") is None else ("%g"%targets["bed"]),
                    "—" if targets.get("hotend") is None else ("%g"%targets["hotend"])))
            if gmeta.get("estimated_minutes"):
                summary.append("Estimated print time: %.1f hr"%(gmeta["estimated_minutes"]/60.0))
            if gmeta.get("filament_g"):
                summary.append("Estimated filament: %.0f g"%gmeta["filament_g"])

            if not messagebox.askyesno(
                "Start Cura-Sliced Print",
                "FabOS verified the G-code:\n\n"+"\n".join("• "+x for x in summary)+
                "\n\nConfirm the build plate is clear and the selected %s spool is loaded.\n\nStart printing now?"%
                spool["material"],parent=parent):
                return

            # Non-waiting M140 + M104 are sent together first. The Cura G-code's
            # normal M190/M109 waits can then finish both heaters as needed.
            self.core.octoprint_print.preheat_together(
                printer,targets.get("hotend"),targets.get("bed"))

            started=self.core.octoprint_print.start_selected(
                printer,octo_path,timeout=20,verify_heaters=True,
                initial_temps=preflight.get("temperatures"))
            state=started["state"]

            metadata=json.dumps({
                "slicer":"Cura GUI / Imported G-code",
                "profile":"User sliced in Cura desktop",
                "octoprint_verified_state":state,
                "model_mode":model_status.get("model_mode","single"),
                "part_set_pieces":model_status.get("piece_count",1),
                "imported_cura_gcode":True
            })

            with self.core.database.connect() as c:
                if job_id:
                    c.execute("""UPDATE print_jobs SET order_id=COALESCE(?,order_id),product_id=?,
                      printer_id=?,spool_id=?,status='printing',gcode_path=?,octoprint_file=?,
                      estimated_minutes=?,estimated_filament_g=?,
                      started_at=COALESCE(started_at,CURRENT_TIMESTAMP),slicer_metadata_json=?
                      WHERE id=?""",
                      (order_id,product_id,printer["id"],spool["id"],str(gcode),octo_path,
                       gmeta.get("estimated_minutes") or product["estimated_minutes"],
                       gmeta.get("filament_g") or product["estimated_filament_g"],
                       metadata,job_id))
                else:
                    job_id=str(uuid.uuid4())
                    c.execute("""INSERT INTO print_jobs(
                      id,order_id,product_id,printer_id,spool_id,status,gcode_path,octoprint_file,
                      estimated_minutes,estimated_filament_g,started_at,slicer_metadata_json
                      ) VALUES(?,?,?,?,?,'printing',?,?,?,?,CURRENT_TIMESTAMP,?)""",
                      (job_id,order_id,product_id,printer["id"],spool["id"],str(gcode),octo_path,
                       gmeta.get("estimated_minutes") or product["estimated_minutes"],
                       gmeta.get("filament_g") or product["estimated_filament_g"],metadata))
                if order_id:
                    c.execute("""UPDATE orders SET status=CASE
                      WHEN status IN ('new','production') THEN 'production' ELSE status END WHERE id=?""",
                      (order_id,))
                c.execute("""UPDATE printers SET status='printing',octoprint_current_file=?,
                  octoprint_state_text=? WHERE id=?""",(octo_path,state,printer["id"]))
                c.commit()
            try:self.core.operations.log('print.started','Print started',
                '%s • %s • %s'%(product['name'],printer['name'],order_text),'Production',job_id)
            except Exception:pass

            messagebox.showinfo(
                "Print Started",
                "OctoPrint now reports %s.\n\nFabOS is tracking this Cura-sliced job%s."%
                (state,(" on order "+order_text) if order_id else ""),parent=parent)
            try:parent.destroy()
            except Exception:pass
            self.show_page("Printers")
        except Exception as exc:
            messagebox.showerror("Import Cura G-code",str(exc),parent=parent)

    # Compatibility alias for any older UI callback.
    def _cura_assisted_print(self,*args,**kwargs):
        return self._import_cura_gcode_print(*args,**kwargs)

    def _print_selected_product(self, product_id=None, printer_id=None, spool_id=None, existing_job_id=None, preferred_gcode=None):
        product_id=product_id or self._selected_product_id()
        if not product_id:return
        product=self.core.products.get(product_id)
        try:
            model_status=self.core.design_vault.product_model_status(product_id)
        except Exception:
            model_status={'model_mode':'single','ready':False,'part_count':0,'piece_count':0}
        try:
            print_status=self.core.design_vault.product_print_status(product_id)
        except Exception:
            print_status={'ready':False,'has_stl':False,'has_gcode':False,'preferred_gcode':None,'reason':'Needs STL or G-code'}
        printers=[p for p in self.core.printer_automation.list() if p['connection_mode']=='octoprint']
        if not printers:
            return messagebox.showinfo('Print Product','Configure at least one printer for OctoPrint first.')
        spools=list(self.core.inventory_profit.spools())
        if not spools:
            return messagebox.showinfo('Print Product','Add the filament spool loaded in the printer first.')

        win=tk.Toplevel(self);win.title('Print — '+product['name']);win.geometry('700x720');win.minsize(640,610)
        win.configure(bg=self._c('bg'));win.transient(self);win.grab_set()
        outer=tk.Frame(win,bg=self._c('bg'));outer.pack(fill='both',expand=True)
        canvas=tk.Canvas(outer,bg=self._c('bg'),highlightthickness=0)
        scroll=ttk.Scrollbar(outer,orient='vertical',command=canvas.yview)
        body=self._card(canvas,'One-Click Product Print')
        body.bind('<Configure>',lambda _e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0,0),window=body,anchor='nw',width=645);canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side='left',fill='both',expand=True,padx=(14,0),pady=14);scroll.pack(side='right',fill='y',padx=(0,14),pady=14)

        tk.Label(body,text=product['name'],bg=self._c('surface'),fg=self._c('text'),
                 font=('Segoe UI',15,'bold'),wraplength=585,justify='left').pack(anchor='w',padx=16,pady=(5,2))
        if print_status.get('has_gcode') and not print_status.get('has_stl'):
            print_description='Saved G-code is ready for this product. Select the printer/spool/order below and use Print Saved G-code.'
        elif model_status.get('model_mode')=='part_set':
            print_description=('Part Set: slice the individual parts in your normal Cura setup and use Import Cura G-code, '
                               'or use Automatic Slice (Experimental). Saved G-code can also be reused when available.')
        else:
            print_description=('Single Model: slice normally in Cura and use Import Cura G-code, or use Automatic Slice (Experimental). '
                               'Saved G-code can be reused when available.')
        tk.Label(body,
            text=print_description,
            bg=self._c('surface'),fg=self._c('muted'),wraplength=585,justify='left'
        ).pack(anchor='w',padx=16,pady=(0,14))

        printer_map={('%s — %s'%(p['name'],p['status'].title())):p for p in printers}
        spool_map={('%s %s %s — %.0fg'%(s['brand'] or '',s['material'],s['color'] or '',s['remaining_g'])).strip():s for s in spools}
        orders=list(self.core.production.attachable_orders(product_id))
        order_map={'No Order / Personal Print':None}
        for o in orders:
            suffix=(' • queued job ready' if int(o['matching_waiting_jobs'] or 0)>0 else '')
            order_map['%s — %s — %s%s'%(o['order_number'],o['customer_name'],o['status'].title(),suffix)]=o['id']
        existing_order_id=None
        if existing_job_id:
            try:existing_order_id=self.core.production.get(existing_job_id)['order_id']
            except Exception:existing_order_id=None
        printer_choice=next((label for label,p in printer_map.items() if printer_id and p['id']==printer_id),next(iter(printer_map)))
        spool_choice=next((label for label,s in spool_map.items() if spool_id and s['id']==spool_id),next(iter(spool_map)))
        pvar=tk.StringVar(value=printer_choice)
        svar=tk.StringVar(value=spool_choice)
        order_choice=next((label for label,oid in order_map.items() if existing_order_id and oid==existing_order_id),
                          'No Order / Personal Print')
        ovar=tk.StringVar(value=order_choice)
        slicervar=tk.StringVar(value=self.core.inventory_profit.setting('default_slicer','Cura') or 'Cura')

        saved_cura=(self.core.inventory_profit.setting('cura_engine_path','') or
                    self.core.shop_settings.get('cura_engine_path','') or '')
        curaexe=tk.StringVar(value=saved_cura)
        curaprofile=tk.StringVar()
        curafdmprinter=tk.StringVar(value=self.core.shop_settings.get('cura_fdmprinter_path','') or '')
        curafdmextruder=tk.StringVar(value=self.core.shop_settings.get('cura_fdmextruder_path','') or '')
        curaresources=tk.StringVar(value='Checked only when Automatic Slice is used.')
        prusaexe=tk.StringVar(value=self.core.inventory_profit.setting('prusaslicer_path','') or '')
        prusaprofile=tk.StringVar(value=self.core.inventory_profit.setting('prusaslicer_profile_path','') or '')

        def selected_spool():
            return spool_map.get(svar.get())

        def material_key(material):
            return 'cura_profile_%s_path'%str(material or '').strip().upper().replace(' ','_')

        def load_material_profile(*_):
            spool=selected_spool()
            material=(spool['material'] if spool else 'PETG')
            saved=self.core.inventory_profit.setting(material_key(material),'') or ''
            if not saved and str(material).upper()=='PETG':
                saved=self.core.inventory_profit.setting('cura_petg_profile_path','') or ''
            curaprofile.set(saved)

        gcode_rows=list(self.core.design_vault.gcode_library(product_id)) if print_status.get('has_gcode') else []
        gcode_map={}
        gcode_hints={}
        for row in gcode_rows:
            path=Path(row['stored_path'])
            try:hints=self.core.cura.gcode_profile_hints(path)
            except Exception:hints={}
            gcode_hints[str(path)]=hints
            bits=[row['original_name']]
            if hints.get('material'):bits.append(hints['material'])
            if hints.get('hotend') or hints.get('bed'):
                bits.append('%s/%s°C'%(
                    '—' if hints.get('hotend') is None else '%g'%hints['hotend'],
                    '—' if hints.get('bed') is None else '%g'%hints['bed']))
            if hints.get('estimated_minutes'):
                mins=int(hints['estimated_minutes'])
                bits.append('%dh %02dm'%(mins//60,mins%60))
            label=' • '.join(bits)
            # Keep labels unique if filenames repeat.
            if label in gcode_map:label+=' • '+str(row['created_at'] or '')[:10]
            gcode_map[label]=str(path)
        preferred_label=next((label for label,path in gcode_map.items()
                              if preferred_gcode and str(path)==str(preferred_gcode)),None)
        gvar=tk.StringVar(value=preferred_label or next(iter(gcode_map),''))
        gcode_compat=tk.StringVar(value='')

        def field(label,var,combo=None,browse=None):
            tk.Label(body,text=label,bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(9,3))
            row=tk.Frame(body,bg=self._c('surface'));row.pack(fill='x',padx=16)
            if combo is not None:
                widget=ttk.Combobox(row,textvariable=var,values=list(combo),state='readonly')
                widget.pack(side='left',fill='x',expand=True)
            else:
                widget=self._entry(row,var,44);widget.pack(side='left',fill='x',expand=True,ipady=5)
            if browse:self._button(row,'Browse',browse).pack(side='left',padx=(7,0))
            return widget

        field('OctoPrint Printer',pvar,printer_map)
        spool_combo=field('Filament Spool Loaded in Printer',svar,spool_map)

        def update_gcode_compat(*_):
            if not gcode_map:
                gcode_compat.set('');return
            path=gcode_map.get(gvar.get())
            hints=gcode_hints.get(str(path),{}) if path else {}
            spool=selected_spool()
            hinted=str(hints.get('material') or '').upper().strip()
            loaded=str(spool['material'] if spool else '').upper().strip()
            if hinted and loaded and hinted!=loaded:
                gcode_compat.set('⚠ Saved G-code says %s, but selected spool is %s.'%(hinted,loaded))
            elif hinted:
                gcode_compat.set('✓ Material match: %s'%hinted if loaded==hinted else 'Saved material: '+hinted)
            else:
                gcode_compat.set('Material was not identified in this G-code; verify the selected spool.')

        def spool_changed(*_):
            load_material_profile()
            update_gcode_compat()

        spool_combo.bind('<<ComboboxSelected>>',spool_changed)
        if gcode_map:
            gcode_combo=field('Saved G-code',gvar,gcode_map)
            gcode_combo.bind('<<ComboboxSelected>>',update_gcode_compat)
            tk.Label(body,textvariable=gcode_compat,bg=self._c('surface'),fg=self._c('muted'),
                     wraplength=560,justify='left').pack(anchor='w',padx=16,pady=(4,0))
            update_gcode_compat()
        order_combo=field('Attach Print to Order',ovar,order_map)
        if existing_order_id:
            order_combo.configure(state='disabled')
        slicer_combo=field('Slicer',slicervar,['Cura','PrusaSlicer'])

        cura_frame=tk.Frame(body,bg=self._c('surface'))
        tk.Label(cura_frame,text='CuraEngine.exe — Cura 4.13.1',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(9,3))
        row=tk.Frame(cura_frame,bg=self._c('surface'));row.pack(fill='x',padx=16)
        self._entry(row,curaexe,44).pack(side='left',fill='x',expand=True,ipady=5)
        def choose_cura_engine():
            self._choose_file(curaexe,[('CuraEngine','CuraEngine.exe'),('EXE files','*.exe'),('All files','*.*')])
            if curaexe.get().strip():
                diag=self.core.cura.installation_diagnostic(curaexe.get().strip(),configured_fdmprinter=curafdmprinter.get().strip(),configured_fdmextruder=curafdmextruder.get().strip())
                curaresources.set(diag.get('resources') or ('Not found — '+diag.get('message','')))
        self._button(row,'Browse',choose_cura_engine).pack(side='left',padx=(7,0))
        tk.Label(cura_frame,text='Cura resources detected',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(8,2))
        tk.Label(cura_frame,textvariable=curaresources,bg=self._c('surface_alt'),fg=self._c('text'),
                 anchor='w',justify='left',wraplength=560,padx=8,pady=6).pack(fill='x',padx=16)
        tk.Label(cura_frame,text='Fallback base definitions (only if resources are not found)',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(9,3))
        row=tk.Frame(cura_frame,bg=self._c('surface'));row.pack(fill='x',padx=16)
        self._entry(row,curafdmprinter,44).pack(side='left',fill='x',expand=True,ipady=5)
        self._button(row,'fdmprinter',lambda:self._choose_file(curafdmprinter,[('Cura definition','fdmprinter.def.json'),('JSON files','*.json'),('All files','*.*')])).pack(side='left',padx=(7,0))
        row=tk.Frame(cura_frame,bg=self._c('surface'));row.pack(fill='x',padx=16,pady=(5,0))
        self._entry(row,curafdmextruder,44).pack(side='left',fill='x',expand=True,ipady=5)
        self._button(row,'fdmextruder',lambda:self._choose_file(curafdmextruder,[('Cura definition','fdmextruder.def.json'),('JSON files','*.json'),('All files','*.*')])).pack(side='left',padx=(7,0))
        tk.Label(cura_frame,text='Cura .curaprofile for selected material',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(9,3))
        row2=tk.Frame(cura_frame,bg=self._c('surface'));row2.pack(fill='x',padx=16)
        self._entry(row2,curaprofile,44).pack(side='left',fill='x',expand=True,ipady=5)
        self._button(row2,'Browse',lambda:self._choose_file(curaprofile,[('Cura profile','*.curaprofile'),('All files','*.*')])).pack(side='left',padx=(7,0))

        prusa_frame=tk.Frame(body,bg=self._c('surface'))
        tk.Label(prusa_frame,text='PrusaSlicer console executable',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(9,3))
        row3=tk.Frame(prusa_frame,bg=self._c('surface'));row3.pack(fill='x',padx=16)
        self._entry(row3,prusaexe,44).pack(side='left',fill='x',expand=True,ipady=5)
        self._button(row3,'Browse',lambda:self._choose_file(prusaexe,[('PrusaSlicer','*.exe'),('All files','*.*')])).pack(side='left',padx=(7,0))
        tk.Label(prusa_frame,text='PrusaSlicer INI profile',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(9,3))
        row4=tk.Frame(prusa_frame,bg=self._c('surface'));row4.pack(fill='x',padx=16)
        self._entry(row4,prusaprofile,44).pack(side='left',fill='x',expand=True,ipady=5)
        self._button(row4,'Browse',lambda:self._choose_file(prusaprofile,[('INI profile','*.ini'),('All files','*.*')])).pack(side='left',padx=(7,0))

        def show_slicer_fields(*_):
            if slicervar.get()=='Cura':
                prusa_frame.pack_forget()
                if not cura_frame.winfo_manager():cura_frame.pack(fill='x')
            else:
                cura_frame.pack_forget()
                if not prusa_frame.winfo_manager():prusa_frame.pack(fill='x')
        slicer_combo.bind('<<ComboboxSelected>>',show_slicer_fields)
        load_material_profile()
        show_slicer_fields()

        status=tk.Label(body,text='Ready.',bg=self._c('surface_alt'),fg=self._c('text'),
                        anchor='w',justify='left',wraplength=570,padx=12,pady=10)
        status.pack(fill='x',padx=16,pady=15)
        progress=ttk.Progressbar(body,maximum=100,value=0);progress.pack(fill='x',padx=16,pady=(0,4))
        slice_detail=tk.Label(body,text='',bg=self._c('surface'),fg=self._c('muted'),
                              anchor='w',justify='left',padx=16)
        slice_detail.pack(fill='x',pady=(0,8))
        button_row=tk.Frame(body,bg=self._c('surface'));button_row.pack(fill='x',padx=16,pady=(4,16))

        def ui(msg,pct=None):
            def update():
                if win.winfo_exists():
                    status.config(text=msg)
                    if pct is not None:progress['value']=pct
                    if pct is not None and pct>=58 and not str(msg).lower().startswith('slicing'):
                        slice_detail.config(text='')
            self.after(0,update)

        def _fmt_duration(seconds):
            if seconds is None:return 'calculating…'
            seconds=max(0,int(round(seconds)))
            if seconds<60:return '%ds'%seconds
            minutes,sec=divmod(seconds,60)
            if minutes<60:return '%dm %02ds'%(minutes,sec)
            hours,minutes=divmod(minutes,60)
            return '%dh %02dm'%(hours,minutes)

        def slicing_ui(fraction,stage,elapsed,eta):
            pct=max(1,min(99,int(round(float(fraction)*100))))
            total=(elapsed+eta) if eta is not None else None
            def update():
                if win.winfo_exists():
                    progress['value']=pct
                    status.config(text='Slicing with Cura 4.13.1 — %d%% — %s'%(pct,stage))
                    slice_detail.config(text='Elapsed: %s    Estimated slicing total: %s    Estimated remaining: %s'%
                        (_fmt_duration(elapsed),_fmt_duration(total),_fmt_duration(eta)))
            self.after(0,update)

        def print_saved_gcode():
            printer=printer_map.get(pvar.get());spool=selected_spool()
            if not printer:
                return messagebox.showerror('Print Product','Select an OctoPrint printer.',parent=win)
            if printer['status'].lower() in ('printing','paused'):
                return messagebox.showwarning('Printer Busy','The selected printer is currently busy.',parent=win)
            if not spool:
                return messagebox.showerror('Print Product','Select the filament spool loaded in the printer.',parent=win)
            saved=gcode_map.get(gvar.get()) if gcode_map else print_status.get('preferred_gcode')
            if not saved:
                return messagebox.showinfo('Saved G-code','No saved G-code is available for this product.',parent=win)
            hints=gcode_hints.get(str(saved),{})
            hinted=str(hints.get('material') or '').upper().strip()
            loaded=str(spool['material'] or '').upper().strip()
            if hinted and loaded and hinted!=loaded:
                if not messagebox.askyesno(
                    'Material Mismatch',
                    'This saved G-code appears to be for %s, but the selected spool is %s.\n\n'
                    'Using G-code with the wrong material can use incorrect temperatures. Continue anyway?'%
                    (hinted,loaded),parent=win):
                    return
            self._import_cura_gcode_print(
                product_id,printer,spool,existing_job_id=existing_job_id,
                order_id=order_map.get(ovar.get()),parent=win,model_status=model_status,
                gcode_path=saved
            )

        def import_gcode():
            printer=printer_map.get(pvar.get());spool=selected_spool()
            if not printer:
                return messagebox.showerror('Print Product','Select an OctoPrint printer.',parent=win)
            if printer['status'].lower() in ('printing','paused'):
                return messagebox.showwarning('Printer Busy','The selected printer is currently busy.',parent=win)
            if not spool:
                return messagebox.showerror('Print Product','Select the filament spool loaded in the printer.',parent=win)
            self._import_cura_gcode_print(
                product_id,printer,spool,existing_job_id=existing_job_id,
                order_id=order_map.get(ovar.get()),parent=win,model_status=model_status
            )

        def prepare():
            if not print_status.get('has_stl'):
                return messagebox.showwarning(
                    'Automatic Slice',
                    'Automatic slicing needs a local STL. This product currently has %s.'%
                    ('saved G-code only' if print_status.get('has_gcode') else 'no printable file'),
                    parent=win)
            printer=printer_map.get(pvar.get());spool=selected_spool()
            if not printer:return messagebox.showerror('Print Product','Select an OctoPrint printer.',parent=win)
            if printer['status'].lower() in ('printing','paused'):
                return messagebox.showwarning('Printer Busy','The selected printer is currently busy.',parent=win)
            if not spool:return messagebox.showerror('Print Product','Select the filament spool loaded in the printer.',parent=win)

            slicer=slicervar.get()
            self.core.inventory_profit.set_setting('default_slicer',slicer)
            if slicer=='Cura':
                if not curaexe.get().strip():
                    found=self.core.cura.find_cura('')
                    if found:curaexe.set(str(found))
                if not curaexe.get().strip():
                    return messagebox.showerror('Cura','CuraEngine.exe was not found. Browse to your Cura 4.13.1 CuraEngine.exe.',parent=win)
                diag=self.core.cura.installation_diagnostic(curaexe.get().strip(),configured_fdmprinter=curafdmprinter.get().strip(),configured_fdmextruder=curafdmextruder.get().strip())
                curaresources.set(diag.get('resources') or ('Not found — '+diag.get('message','')))
                if not diag.get('ok'):
                    return messagebox.showerror('Cura Resources',diag.get('message','Cura resources were not found.'),parent=win)
                if not curaprofile.get().strip() or not Path(curaprofile.get().strip()).exists():
                    return messagebox.showerror('Cura','Select a Cura .curaprofile for %s.'%spool['material'],parent=win)
                self.core.inventory_profit.set_setting('cura_engine_path',curaexe.get().strip())
                self.core.shop_settings.set('cura_engine_path',curaexe.get().strip())
                self.core.shop_settings.set('cura_fdmprinter_path',curafdmprinter.get().strip())
                self.core.shop_settings.set('cura_fdmextruder_path',curafdmextruder.get().strip())
                self.core.inventory_profit.set_setting(material_key(spool['material']),curaprofile.get().strip())
                if str(spool['material']).upper()=='PETG':
                    self.core.inventory_profit.set_setting('cura_petg_profile_path',curaprofile.get().strip())
            else:
                self.core.inventory_profit.set_setting('prusaslicer_path',prusaexe.get().strip())
                self.core.inventory_profit.set_setting('prusaslicer_profile_path',prusaprofile.get().strip())

            start_btn.config(state='disabled')

            def worker():
                try:
                    if model_status.get('model_mode')=='part_set':
                        ui('1/5  Arranging the complete part set on the Vyper plate…',10)
                        plate=self.core.model_plate.build_complete_set(product_id,245.0,245.0,5.0,4.0)
                        model=plate['path']
                        origin='complete set — %d pieces'%plate['pieces']
                        ui('2/5  Complete set fits %.1f × %.1f mm. Preparing slicer…'%(plate['used_w'],plate['used_d']),22)
                    else:
                        ui('1/5  Finding the saved model…',10)
                        model,origin=self.core.product_print.download_model(product_id)
                    out_dir=Path(self.core.settings.data_dir)/'G-code'/product_id
                    out_dir.mkdir(parents=True,exist_ok=True)
                    output=out_dir/(Path(model).stem+'_FabOS.gcode')

                    if slicer=='Cura':
                        ui('3/6  Model ready (%s). Slicing with Cura 4.13.1…'%origin,35)
                        self.core.cura.slice(model,output,curaprofile.get().strip(),curaexe.get().strip(),fdmprinter_path=curafdmprinter.get().strip(),fdmextruder_path=curafdmextruder.get().strip(),progress_callback=slicing_ui)
                        gmeta=self.core.cura.gcode_metadata(output,spool['material'])
                    else:
                        ui('3/6  Model ready (%s). Slicing with PrusaSlicer…'%origin,35)
                        self.core.product_print.slice_model(model,output,prusaexe.get().strip(),prusaprofile.get().strip())
                        gmeta=self.core.manufacturing.parse_gcode_file(output)

                    validation=self.core.cura.validate_print_gcode(output)
                    bounds=validation.get('bounds') or {}
                    if validation['valid'] and bounds:
                        warnings=bounds.get('warnings') or []
                        if warnings:
                            worst=max(
                                max(abs(float(w.get('x',0))-245.0) if float(w.get('x',0))>245 else abs(float(w.get('x',0))) if float(w.get('x',0))<0 else 0,
                                    abs(float(w.get('y',0))-245.0) if float(w.get('y',0))>245 else abs(float(w.get('y',0))) if float(w.get('y',0))<0 else 0)
                                for w in warnings
                            )
                            ui('G-code safety passed with Cura edge-rounding tolerance — X %.2f to %.2f, Y %.2f to %.2f mm (max nominal overshoot %.3f mm).'%
                               (bounds.get('min_x',0),bounds.get('max_x',0),
                                bounds.get('min_y',0),bounds.get('max_y',0),worst),55)
                        else:
                            ui('G-code safety passed — X %.2f to %.2f mm, Y %.2f to %.2f mm.'%
                               (bounds.get('min_x',0),bounds.get('max_x',0),
                                bounds.get('min_y',0),bounds.get('max_y',0)),55)
                    if not validation['valid']:
                        raise RuntimeError('Generated G-code failed FabOS safety validation: '+', '.join(validation['problems'])+
                            '. Open the file in Cura and confirm the printer/material profile before trying again.')

                    ui('4/6  Checking OctoPrint printer readiness…',58)
                    preflight=self.core.octoprint_print.preflight(printer)
                    ui('5/6  Printer is %s. Uploading and selecting G-code…'%preflight['state'],72)
                    uploaded=self.core.octoprint_print.upload_and_select(printer,output)
                    octo_path=uploaded['path']
                    detail=[]
                    if gmeta.get('estimated_minutes'):detail.append('%.1f hr'%(gmeta['estimated_minutes']/60.0))
                    if gmeta.get('filament_g'):detail.append('%.0f g'%gmeta['filament_g'])
                    detail.append('heater commands verified')
                    ui('6/6  OctoPrint selected %s%s. Waiting for final start confirmation.'%
                       (octo_path,((' — '+', '.join(detail)) if detail else '')),100)

                    def confirm():
                        if not win.winfo_exists():return
                        if not self._filament_check_for_print(spool,gmeta.get('filament_g'),win):
                            start_btn.config(state='normal');return
                        if not messagebox.askyesno(
                            'Start Physical Print',
                            'FabOS verified all of these steps:\n\n'
                            '• Cura generated printable G-code\n'
                            '• nozzle and bed heater commands are present\n'
                            '• OctoPrint says the printer is operational\n'
                            '• OctoPrint selected: %s\n\n'
                            'Confirm the build plate is clear and the correct %s filament is loaded.\n\n'
                            'Start the printer now?'%(octo_path,spool['material']),
                            parent=win
                        ):
                            start_btn.config(state='normal');return

                        status.config(text='Sending START to OctoPrint and waiting for physical print state…')
                        progress['value']=95
                        def start_worker():
                            try:
                                targets=self.core.cura.gcode_heater_targets(output)
                                self.core.octoprint_print.preheat_together(
                                    printer,targets.get('hotend'),targets.get('bed'))
                                started=self.core.octoprint_print.start_selected(
                                    printer,octo_path,timeout=20,verify_heaters=True,
                                    initial_temps=preflight.get('temperatures'))
                                state=started['state']
                                temps=started.get('temperatures') or {}
                                tool=temps.get('tool0') or {}
                                bed=temps.get('bed') or {}
                                attached_order_id=order_map.get(ovar.get())
                                attachable=(None if existing_job_id else self.core.production.find_attachable_job(attached_order_id,product_id))
                                job_to_update=existing_job_id or (attachable['id'] if attachable else None)
                                metadata=json.dumps({'slicer':slicer,
                                  'profile':curaprofile.get() if slicer=='Cura' else prusaprofile.get(),
                                  'octoprint_verified_state':state,'model_mode':model_status.get('model_mode','single'),'part_set_pieces':model_status.get('piece_count',1)})
                                with self.core.database.connect() as c:
                                    if job_to_update:
                                        c.execute("""UPDATE print_jobs SET product_id=?,printer_id=?,spool_id=?,status='printing',
                                          gcode_path=?,octoprint_file=?,estimated_minutes=?,estimated_filament_g=?,
                                          started_at=COALESCE(started_at,CURRENT_TIMESTAMP),slicer_metadata_json=?
                                          WHERE id=?""",
                                          (product_id,printer['id'],spool['id'],str(output),octo_path,
                                           gmeta.get('estimated_minutes') or product['estimated_minutes'],
                                           gmeta.get('filament_g') or product['estimated_filament_g'],
                                           metadata,job_to_update))
                                    else:
                                        jid=str(uuid.uuid4())
                                        c.execute("""INSERT INTO print_jobs(
                                          id,order_id,product_id,printer_id,spool_id,status,gcode_path,octoprint_file,
                                          estimated_minutes,estimated_filament_g,started_at,slicer_metadata_json
                                          ) VALUES(?,?,?,?,?,'printing',?,?,?,?,CURRENT_TIMESTAMP,?)""",
                                          (jid,attached_order_id,product_id,printer['id'],spool['id'],str(output),octo_path,
                                           gmeta.get('estimated_minutes') or product['estimated_minutes'],
                                           gmeta.get('filament_g') or product['estimated_filament_g'],metadata))
                                    if attached_order_id:
                                        c.execute("""UPDATE orders SET status=CASE WHEN status IN ('new','production')
                                          THEN 'production' ELSE status END WHERE id=?""",(attached_order_id,))
                                    c.execute("UPDATE printers SET status='printing',octoprint_current_file=?,octoprint_state_text=? WHERE id=?",
                                              (octo_path,state,printer['id']))
                                    c.commit()
                                try:self.core.operations.log('print.started','Print started',
                                    '%s • %s'%(product['name'],printer['name']),'Production',job_to_update or jid)
                                except Exception:pass
                                def success():
                                    if not win.winfo_exists():return
                                    nozzle_target=tool.get('target')
                                    bed_target=bed.get('target')
                                    temp_text=''
                                    if nozzle_target or bed_target:
                                        temp_text='\n\nTargets reported by OctoPrint: nozzle %s°C, bed %s°C.'%(
                                            '—' if nozzle_target is None else nozzle_target,
                                            '—' if bed_target is None else bed_target)
                                    heater_text='\n\nFabOS also confirmed heater response from the physical printer.' if started.get('heater_confirmed') else ''
                                    messagebox.showinfo(
                                        'Physical Print Started',
                                        'OctoPrint now reports %s for %s.%s%s\n\nFabOS will track the live job on the Printers page.'%
                                        (state,octo_path,temp_text,heater_text),parent=win)
                                    win.destroy();self.show_page('Printers')
                                self.after(0,success)
                            except Exception as exc:
                                def failed():
                                    if not win.winfo_exists():return
                                    status.config(text='START FAILED — '+str(exc));progress['value']=0
                                    messagebox.showerror('Printer did not start',str(exc),parent=win)
                                    start_btn.config(state='normal')
                                self.after(0,failed)
                        threading.Thread(target=start_worker,name='FabOS-OctoPrintStart',daemon=True).start()
                    self.after(0,confirm)
                except Exception as exc:
                    ui('Could not prepare print: '+str(exc),0)
                    self.after(0,lambda:start_btn.config(state='normal') if win.winfo_exists() else None)

            threading.Thread(target=worker,name='FabOS-OneClickPrint',daemon=True).start()

        start_btn=self._button(button_row,'Automatic Slice (Experimental)',prepare)
        if print_status.get('has_stl'):
            start_btn.pack(side='right')
        if print_status.get('has_gcode'):
            self._button(button_row,'Print Saved G-code',print_saved_gcode,True).pack(side='right',padx=7)
            self._button(button_row,'Import Different G-code',import_gcode).pack(side='right',padx=7)
        else:
            self._button(button_row,'Import Cura G-code',import_gcode,True).pack(side='right',padx=7)
        self._button(button_row,'Open Source Page',lambda:webbrowser.open(product['source_url'] or '')).pack(side='right',padx=7)
