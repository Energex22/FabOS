import tkinter as tk, os
from tkinter import ttk,messagebox
from pathlib import Path

class SystemReliabilityMixin:
    def _build_backup_health_page(self):
        bar=tk.Frame(self.content,bg=self._c('bg'));bar.pack(fill='x',pady=(4,10))
        self._button(bar,'Create Backup',self._system_create_backup,True).pack(side='left')
        self._button(bar,'Restore Selected',self._system_restore_backup).pack(side='left',padx=7)
        self._button(bar,'Open Backup Folder',self._system_open_backup_folder).pack(side='left')
        self._button(bar,'Run Health Check',self._system_refresh_health).pack(side='left',padx=7)
        self._button(bar,'Setup Wizard',self._run_setup_wizard).pack(side='left')

        metrics=tk.Frame(self.content,bg=self._c('bg'));metrics.pack(fill='x',pady=(0,10))
        backups=self.core.backups.list()
        checks=self.core.operations.system_ready()
        pass_count=sum(1 for x in checks if x['status']=='pass')
        warn_count=sum(1 for x in checks if x['status']=='warn')
        fail_count=sum(1 for x in checks if x['status']=='fail')
        cards=[
            ('Backups',len(backups),self._c('purple'),'Automatic + manual restore points'),
            ('Health Passed',pass_count,self._c('green'),'Checks currently passing'),
            ('Warnings',warn_count,self._c('orange'),'Items worth reviewing'),
            ('Failures',fail_count,self._c('red'),'Items needing attention'),
        ]
        for i,(title,value,color,detail) in enumerate(cards):
            card=self._metric_card(metrics,title,value,color,detail)
            card.grid(row=0,column=i,sticky='nsew',padx=(0 if i==0 else 7,0));metrics.columnconfigure(i,weight=1)

        split=tk.PanedWindow(self.content,orient='horizontal',bg=self._c('bg'),sashwidth=6,bd=0)
        split.pack(fill='both',expand=True)
        left=self._card(split,'Backup History');right=self._card(split,'System Health')
        split.add(left,minsize=470,stretch='always');split.add(right,minsize=420,stretch='always')

        self.backup_table=ttk.Treeview(left,columns=('name','created','size'),show='headings',style='Dark.Treeview',selectmode='browse')
        for c,title,w in [('name','Backup',265),('created','Created',145),('size','Size',85)]:
            self.backup_table.heading(c,text=title);self.backup_table.column(c,width=w,anchor='w')
        sy=ttk.Scrollbar(left,orient='vertical',command=self.backup_table.yview)
        self.backup_table.configure(yscrollcommand=sy.set)
        self.backup_table.pack(side='left',fill='both',expand=True,padx=(12,0),pady=(0,12))
        sy.pack(side='right',fill='y',padx=(0,12),pady=(0,12))

        self.health_table=ttk.Treeview(right,columns=('check','status','detail'),show='headings',style='Dark.Treeview')
        for c,title,w in [('check','Check',150),('status','Status',75),('detail','Details',280)]:
            self.health_table.heading(c,text=title);self.health_table.column(c,width=w,anchor='w',stretch=(c=='detail'))
        self.health_table.tag_configure('pass',foreground=self._c('green'),background=self._c('surface'))
        self.health_table.tag_configure('warn',foreground=self._c('orange'),background=self._c('surface'))
        self.health_table.tag_configure('fail',foreground=self._c('red'),background=self._c('surface'))
        health_shell=tk.Frame(right,bg=self._c('surface'));health_shell.pack(fill='both',expand=True,padx=12,pady=(0,12))
        health_v=ttk.Scrollbar(health_shell,orient='vertical',command=self.health_table.yview)
        health_h=ttk.Scrollbar(health_shell,orient='horizontal',command=self.health_table.xview)
        self.health_table.configure(yscrollcommand=health_v.set,xscrollcommand=health_h.set)
        self.health_table.grid(row=0,column=0,sticky='nsew')
        health_v.grid(row=0,column=1,sticky='ns');health_h.grid(row=1,column=0,sticky='ew')
        health_shell.rowconfigure(0,weight=1);health_shell.columnconfigure(0,weight=1)

        self._system_refresh_backups()
        self._system_refresh_health()

    @staticmethod
    def _system_human_bytes(value):
        value=float(value or 0)
        for unit in ('B','KB','MB','GB'):
            if value<1024:return ('%.1f %s'%(value,unit)) if unit!='B' else ('%d B'%value)
            value/=1024
        return '%.1f TB'%value

    def _system_refresh_backups(self):
        if not getattr(self,'backup_table',None):return
        self.backup_table.delete(*self.backup_table.get_children())
        self._backup_paths={}
        for i,b in enumerate(self.core.backups.list()):
            iid='backup_%d'%i;self._backup_paths[iid]=b['path']
            self.backup_table.insert('','end',iid=iid,values=(
                b['name'],b['modified'].strftime('%Y-%m-%d %H:%M:%S'),
                self._system_human_bytes(b['bytes'])),tags=('body',))

    def _system_refresh_health(self):
        if not getattr(self,'health_table',None):return
        self.health_table.delete(*self.health_table.get_children())
        for i,row in enumerate(self.core.reliability.health()):
            self.health_table.insert('','end',iid='health_%d'%i,values=(
                row['name'],row['status'].upper(),row['detail']),tags=(row['status'],))

    def _system_create_backup(self):
        try:
            path=self.core.backups.create('manual')
            self.core.backups.prune(int(float(self.core.shop_settings.get('backup_retention','30'))))
            self._system_refresh_backups();self._system_refresh_health()
            messagebox.showinfo('Backup Created','FabOS backup created:\n\n%s'%path)
        except Exception as exc:messagebox.showerror('Backup',str(exc))

    def _system_restore_backup(self):
        sel=self.backup_table.selection() if getattr(self,'backup_table',None) else ()
        if not sel:return messagebox.showinfo('Restore Backup','Select a backup first.')
        path=self._backup_paths.get(sel[0])
        if not path:return
        if not messagebox.askyesno('Restore FabOS Backup',
            'Restore this backup?\n\n%s\n\nFabOS will automatically create a safety backup of the current database first. '
            'After restore, restart FabOS so every screen reloads the restored data.'%Path(path).name):
            return
        try:
            safety=self.core.backups.restore(path)
            messagebox.showinfo('Restore Complete',
                'The database was restored successfully.\n\nA pre-restore safety backup was created:\n%s\n\nClose and reopen FabOS now.'%safety)
            self._system_refresh_backups();self._system_refresh_health()
        except Exception as exc:messagebox.showerror('Restore Failed',str(exc))

    def _system_open_backup_folder(self):
        try:
            folder=Path(self.core.settings.backup_dir);folder.mkdir(parents=True,exist_ok=True)
            os.startfile(str(folder))
        except Exception as exc:messagebox.showerror('Backups',str(exc))

    def _build_settings_page(self):
        settings=self.core.shop_settings.snapshot()

        bar=tk.Frame(self.content,bg=self._c('bg'));bar.pack(fill='x',pady=(4,10))
        self._button(bar,'Save Settings',self._settings_save_all,True).pack(side='left')
        self._button(bar,'Backup Before Changes',self._system_create_backup).pack(side='left',padx=7)
        self._button(bar,'Open Data Folder',self._settings_open_data_folder).pack(side='left')
        self._button(bar,'Run Setup Wizard',self._run_setup_wizard).pack(side='left',padx=7)

        self._settings_vars={}
        nb=ttk.Notebook(self.content);nb.pack(fill='both',expand=True)
        business=tk.Frame(nb,bg=self._c('bg'));pricing=tk.Frame(nb,bg=self._c('bg'))
        production=tk.Frame(nb,bg=self._c('bg'));system=tk.Frame(nb,bg=self._c('bg'))
        nb.add(business,text='Business');nb.add(pricing,text='Pricing & Billing')
        nb.add(production,text='Production');nb.add(system,text='System')

        def add_entry(parent,label,key,help_text='',browse=None):
            card=self._card(parent)
            card.pack(fill='x',pady=(0,8))
            row=tk.Frame(card,bg=self._c('surface'));row.pack(fill='x',padx=14,pady=10)
            left=tk.Frame(row,bg=self._c('surface'));left.pack(side='left',fill='x',expand=True)
            tk.Label(left,text=label,bg=self._c('surface'),fg=self._c('text'),
                     font=('Segoe UI',9,'bold')).pack(anchor='w')
            if help_text:
                tk.Label(left,text=help_text,bg=self._c('surface'),fg=self._c('muted'),
                         font=('Segoe UI',8),wraplength=360,justify='left').pack(anchor='w',pady=(2,0))
            var=tk.StringVar(value=settings.get(key,''))
            self._settings_vars[key]=var
            right=tk.Frame(row,bg=self._c('surface'));right.pack(side='right',fill='x')
            ent=self._entry(right,var,30);ent.pack(side='left',ipady=5)
            if browse:self._button(right,'Browse',lambda:browse(var)).pack(side='left',padx=(6,0))
            return var

        # Business identity
        add_entry(business,'Shop / Business Name','shop_name','Printed at the top of exported invoices.')
        add_entry(business,'Owner / Contact Name','shop_owner_name','Internal business contact.')
        add_entry(business,'Business Email','shop_email','Used on invoices and future customer communications.')
        add_entry(business,'Business Phone','shop_phone','Displayed on invoice exports.')
        add_entry(business,'Business Address','shop_address','Single-line address displayed on invoice exports.')
        add_entry(business,'Customer Update Signature','customer_update_signature',
                  'Optional ending automatically appended to generated customer messages.')

        # Pricing and billing
        add_entry(pricing,'Invoice Prefix','invoice_prefix','Example: INV creates INV-YYYYMM-0001.')
        add_entry(pricing,'Invoice Due Days','invoice_due_days','Default number of days before a new invoice is due.')
        add_entry(pricing,'Default Sales Tax (%)','default_tax_percent',
                  'Automatically applied to newly created invoices. Enter 0 if tax is handled manually.')
        add_entry(pricing,'Quote Valid Days','quote_valid_days','Default quote-expiration window.')
        add_entry(pricing,'Machine Cost / Hour ($)','machine_hourly_cost',
                  'Used in manufacturing cost and profitability calculations.')
        add_entry(pricing,'Default Packaging / Job ($)','default_packaging_cost',
                  'Added to tracked manufacturing cost.')
        add_entry(pricing,'Target Margin (%)','target_margin_percent',
                  'Business target used for pricing/profit guidance.')

        # Production
        slicer_card=self._card(production)
        slicer_card.pack(fill='x',pady=(0,8))
        row=tk.Frame(slicer_card,bg=self._c('surface'));row.pack(fill='x',padx=14,pady=10)
        tk.Label(row,text='Default Slicer',bg=self._c('surface'),fg=self._c('text'),
                 font=('Segoe UI',9,'bold')).pack(side='left')
        slicer=tk.StringVar(value=settings.get('default_slicer','Cura'))
        self._settings_vars['default_slicer']=slicer
        ttk.Combobox(row,textvariable=slicer,values=['Cura','PrusaSlicer'],state='readonly',width=20).pack(side='right')

        add_entry(production,'CuraEngine.exe','cura_engine_path',
                  'FabOS uses CuraEngine for automated slicing.',
                  lambda v:self._settings_browse_file(v,[('CuraEngine','CuraEngine.exe'),('EXE files','*.exe'),('All files','*.*')]))
        add_entry(production,'PETG Cura Profile','cura_petg_profile_path',
                  'Default PETG .curaprofile for the Vyper.',
                  lambda v:self._settings_browse_file(v,[('Cura profile','*.curaprofile'),('All files','*.*')]))
        add_entry(production,'Cura Base Printer Definition','cura_fdmprinter_path',
                  'Optional fallback: select fdmprinter.def.json if FabOS cannot find Cura resources automatically.',
                  lambda v:self._settings_browse_file(v,[('Cura definition','fdmprinter.def.json'),('JSON files','*.json'),('All files','*.*')]))
        add_entry(production,'Cura Base Extruder Definition','cura_fdmextruder_path',
                  'Optional fallback: select fdmextruder.def.json if FabOS cannot find Cura resources automatically.',
                  lambda v:self._settings_browse_file(v,[('Cura definition','fdmextruder.def.json'),('JSON files','*.json'),('All files','*.*')]))
        add_entry(production,'Low Filament Threshold (g)','filament_low_threshold_g',
                  'Spools below this weight are flagged low.')
        add_entry(production,'Reorder Forecast Window (days)','filament_reorder_days',
                  'Predict shortages inside this many days.')

        # System
        add_entry(system,'Backup Retention','backup_retention',
                  'Number of newest automatic/manual backups FabOS should keep.')
        info=self._card(system,'FabOS Data Location');info.pack(fill='x',pady=(0,8))
        tk.Label(info,text=str(self.core.settings.data_dir),bg=self._c('surface'),fg=self._c('text'),
                 wraplength=720,justify='left').pack(anchor='w',padx=16,pady=(0,5))
        tk.Label(info,text='Database: %s\nBackups: %s'%(self.core.settings.database_path,self.core.settings.backup_dir),
                 bg=self._c('surface'),fg=self._c('muted'),wraplength=720,justify='left').pack(anchor='w',padx=16,pady=(0,14))

    def _run_setup_wizard(self):
        win=tk.Toplevel(self);win.title("FabOS Setup Wizard");win.geometry("760x620")
        win.minsize(680,520);win.configure(bg=self._c('bg'));win.transient(self);win.grab_set()
        body=self._card(win,"FabOS Production Setup");body.pack(fill='both',expand=True,padx=16,pady=16)
        tk.Label(body,text="Configure the shop from top to bottom. Each step links to the part of FabOS that owns that setting.",
                 bg=self._c('surface'),fg=self._c('muted'),wraplength=680,justify='left').pack(anchor='w',padx=16,pady=(6,12))
        rows=tk.Frame(body,bg=self._c('surface'));rows.pack(fill='both',expand=True,padx=16)

        def add_step(num,title,detail,status,page):
            row=tk.Frame(rows,bg=self._c('surface_alt'));row.pack(fill='x',pady=4)
            color=self._c('green') if status else self._c('orange')
            tk.Label(row,text=str(num),bg=self._c('purple_dark'),fg='white',width=3,pady=8,font=('Segoe UI',9,'bold')).pack(side='left')
            text=tk.Frame(row,bg=self._c('surface_alt'));text.pack(side='left',fill='x',expand=True,padx=10,pady=6)
            tk.Label(text,text=title,bg=self._c('surface_alt'),fg=self._c('text'),font=('Segoe UI',9,'bold'),anchor='w').pack(fill='x')
            tk.Label(text,text=detail,bg=self._c('surface_alt'),fg=self._c('muted'),font=('Segoe UI',8),anchor='w',wraplength=470,justify='left').pack(fill='x')
            tk.Label(row,text='✓ Ready' if status else 'Needs setup',bg=self._c('surface_alt'),fg=color,font=('Segoe UI',8,'bold')).pack(side='right',padx=8)
            tk.Button(row,text='Open',bg=self._c('surface'),fg=self._c('text'),bd=0,
                      command=lambda p=page:(win.destroy(),self.show_page(p))).pack(side='right',padx=5)

        s=self.core.shop_settings.snapshot()
        printers=list(self.core.printer_automation.list())
        octo=any(p['connection_mode']=='octoprint' and p['octoprint_url'] and p['api_key_ref'] for p in printers)
        cura=bool(s.get('cura_engine_path') or self.core.inventory_profit.setting('cura_engine_path',''))
        profile=bool(s.get('cura_petg_profile_path') or self.core.inventory_profit.setting('cura_petg_profile_path',''))
        spools=list(self.core.inventory_profit.spools())
        try:ready_catalog=sum(1 for v in self.core.design_vault.product_print_status_map([p['id'] for p in self.core.products.list()]).values() if v['ready'])
        except Exception:ready_catalog=0
        add_step(1,'Business','Shop name, contact details, billing and tax.',bool(s.get('shop_name')),'Settings')
        add_step(2,'Printer','At least one physical printer configured.',bool(printers),'Printers')
        add_step(3,'OctoPrint','Server URL/API key and live printer connection.',octo,'Printers')
        add_step(4,'Cura','CuraEngine and base definitions/profile available for experimental automatic slicing.',cura and profile,'Settings')
        add_step(5,'Materials','At least one active filament spool.',bool(spools),'Filament')
        add_step(6,'Catalog','At least one product has an STL or saved G-code.',ready_catalog>0,'Products')
        checks=self.core.operations.system_ready()
        failed=[x for x in checks if x['status']=='fail']
        tk.Label(body,text=('✓ FabOS is ready for production.' if not failed else '⚠ %d system health failure%s remain.'%(len(failed),'' if len(failed)==1 else 's')),
                 bg=self._c('surface'),fg=self._c('green') if not failed else self._c('red'),font=('Segoe UI',10,'bold')).pack(anchor='w',padx=16,pady=12)
        self._button(body,'Open System Health',lambda:(win.destroy(),self.show_page('Backup & Health')),True).pack(side='right',padx=16,pady=(0,12))
        self._button(body,'Close',win.destroy).pack(side='right',pady=(0,12))

    def _settings_browse_file(self,var,filetypes):
        from tkinter import filedialog
        path=filedialog.askopenfilename(filetypes=filetypes)
        if path:var.set(path)

    def _settings_save_all(self):
        if not getattr(self,'_settings_vars',None):return
        values={k:v.get().strip() for k,v in self._settings_vars.items()}
        numeric={
            'invoice_due_days':(1,365),'default_tax_percent':(0,100),'quote_valid_days':(1,365),
            'machine_hourly_cost':(0,1000),'default_packaging_cost':(0,1000),
            'target_margin_percent':(0,1000),'filament_low_threshold_g':(0,100000),
            'filament_reorder_days':(1,3650),'backup_retention':(1,3650)
        }
        try:
            for key,(minimum,maximum) in numeric.items():
                value=float(values.get(key,0))
                if value<minimum or value>maximum:
                    raise ValueError('%s must be between %s and %s.'%(key,minimum,maximum))
            if not values.get('invoice_prefix'):
                raise ValueError('Invoice Prefix cannot be blank.')
            self.core.shop_settings.update(values)
            # Keep legacy setting consumers synchronized.
            for key in ('machine_hourly_cost','default_packaging_cost','target_margin_percent',
                        'filament_low_threshold_g','filament_reorder_days','default_slicer',
                        'cura_engine_path','cura_petg_profile_path'):
                self.core.inventory_profit.set_setting(key,values.get(key,''))
            keep=int(float(values.get('backup_retention','30')))
            self.core.backups.prune(keep)
            messagebox.showinfo('Settings Saved','FabOS settings were saved successfully.')
        except Exception as exc:
            messagebox.showerror('Settings',str(exc))

    def _settings_open_data_folder(self):
        try:os.startfile(str(self.core.settings.data_dir))
        except Exception as exc:messagebox.showerror('Data Folder',str(exc))

