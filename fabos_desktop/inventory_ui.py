import tkinter as tk
from tkinter import ttk,messagebox,simpledialog

class InventoryProfitMixin:
 def _build_filament_page(self):
  bar=tk.Frame(self.content,bg=self._c('bg'));bar.pack(fill='x',pady=(4,10))
  self._button(bar,'+ Add Spool',self._filament_add,True).pack(side='left')
  self._button(bar,'Adjust Remaining',self._filament_adjust).pack(side='left',padx=7)
  self._button(bar,'Cost Settings',self._cost_settings).pack(side='left')
  self._button(bar,'Packaging & Supplies',self._supplies_manager).pack(side='left',padx=7)
  filters=self._card(self.content);filters.pack(fill='x',pady=(0,10))
  row=tk.Frame(filters,bg=self._c('surface'));row.pack(fill='x',padx=14,pady=10)
  tk.Label(row,text='Search',bg=self._c('surface'),fg=self._c('muted')).pack(side='left')
  self.filament_query=tk.StringVar()
  e=self._entry(row,self.filament_query,30);e.pack(side='left',padx=8,ipady=6)
  e.bind('<KeyRelease>',lambda _e:self._filament_refresh())
  self.filament_summary=tk.Label(row,text='',bg=self._c('surface'),fg=self._c('muted'));self.filament_summary.pack(side='right')

  recs=self._card(self.content,'Inventory Recommendations');recs.pack(fill='x',pady=(0,10))
  self.filament_recs=tk.Frame(recs,bg=self._c('surface'));self.filament_recs.pack(fill='x',padx=14,pady=(0,12))

  card=self._card(self.content,'Filament Spools');card.pack(fill='both',expand=True)
  cols=('material','brand','color','remaining','percent','cost','costg','used','location')
  self.filament_table=ttk.Treeview(card,columns=cols,show='headings',style='Dark.Treeview')
  labels={'material':'Material','brand':'Brand','color':'Color','remaining':'Remaining','percent':'Left',
          'cost':'Spool Cost','costg':'Cost/g','used':'Used 30d','location':'Location'}
  widths={'material':90,'brand':130,'color':120,'remaining':95,'percent':70,'cost':90,'costg':75,'used':85,'location':130}
  for c in cols:self.filament_table.heading(c,text=labels[c],command=lambda x=c:self._sort_filament(x));self.filament_table.column(c,width=widths[c],anchor='w')
  self.filament_table.tag_configure('low',foreground='#f87171',background=self._c('surface'))
  self.filament_table.tag_configure('warn',foreground='#fb923c',background=self._c('surface'))
  self.filament_table.tag_configure('ok',foreground=self._c('text'),background=self._c('surface'))
  self.filament_table.pack(fill='both',expand=True,padx=12,pady=(0,12))
  self._filament_sort='material';self._filament_desc=False
  self._filament_refresh()

 def _sort_filament(self,col):
  if self._filament_sort==col:self._filament_desc=not self._filament_desc
  else:self._filament_sort=col;self._filament_desc=False
  self._filament_refresh()

 def _filament_refresh(self):
  if not getattr(self,'filament_table',None):return
  rows=list(self.core.inventory_profit.spools(self.filament_query.get()))
  keymap={'material':lambda r:(r['material'] or '').lower(),'brand':lambda r:(r['brand'] or '').lower(),
   'color':lambda r:(r['color'] or '').lower(),'remaining':lambda r:r['remaining_g'] or 0,
   'percent':lambda r:r['pct_remaining'] or 0,'cost':lambda r:r['cost_cents'] or 0,
   'costg':lambda r:r['cost_per_g_cents'] or 0,'used':lambda r:r['used_30d'] or 0,
   'location':lambda r:(r['location'] or '').lower()}
  rows.sort(key=keymap.get(self._filament_sort,keymap['material']),reverse=self._filament_desc)
  self.filament_table.delete(*self.filament_table.get_children())
  low=float(self.core.inventory_profit.setting('filament_low_threshold_g','250') or 250)
  total=sum(float(r['remaining_g'] or 0) for r in rows)
  for r in rows:
   rem=float(r['remaining_g'] or 0);pct=float(r['pct_remaining'] or 0)
   tag='low' if rem<=low else ('warn' if pct<=30 else 'ok')
   self.filament_table.insert('','end',iid=r['id'],values=(r['material'],r['brand'] or '—',r['color'] or '—',
    '%.0fg'%rem,'%.0f%%'%pct,'$%.2f'%((r['cost_cents'] or 0)/100.0),
    '$%.4f'%((r['cost_per_g_cents'] or 0)/100.0),'%.0fg'%(r['used_30d'] or 0),r['location'] or '—'),tags=(tag,))
  self.filament_summary.config(text='%d spool%s • %.2f kg remaining'%(len(rows),'' if len(rows)==1 else 's',total/1000.0))
  for c in self.filament_recs.winfo_children():c.destroy()
  recs=self.core.inventory_profit.recommendations()
  if not recs:
   tk.Label(self.filament_recs,text='✓ No filament shortages predicted from current usage.',
            bg=self._c('surface'),fg=self._c('green')).pack(anchor='w')
  else:
   for r in recs:
    color='#f87171' if r['severity']=='high' else '#fb923c'
    tk.Label(self.filament_recs,text='●  '+r['text'],bg=self._c('surface'),fg=color,
             wraplength=900,justify='left').pack(anchor='w',pady=2)

 def _selected_spool(self):
  s=self.filament_table.selection() if getattr(self,'filament_table',None) else ()
  if not s:messagebox.showinfo('Filament','Select a spool first.');return None
  return s[0]

 def _filament_add(self):
  win=tk.Toplevel(self);win.title('Add Filament Spool');win.geometry('540x580');win.minsize(500,500)
  win.configure(bg=self._c('bg'));win.transient(self);win.grab_set()
  body=self._card(win,'New Spool');body.pack(fill='both',expand=True,padx=16,pady=16)
  fields={};defaults={'Material':'PLA','Brand':'','Color':'Black','Initial Weight (g)':'1000','Cost ($)':'20.00','Location':'','Lot / Batch':''}
  for lab,val in defaults.items():
   tk.Label(body,text=lab,bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(8,2))
   v=tk.StringVar(value=val);self._entry(body,v,40).pack(fill='x',padx=16,ipady=5);fields[lab]=v
  def save():
   try:
    self.core.inventory_profit.add_spool(fields['Material'].get().strip(),fields['Brand'].get().strip(),
     fields['Color'].get().strip(),float(fields['Initial Weight (g)'].get()),
     int(round(float(fields['Cost ($)'].get())*100)),fields['Location'].get().strip(),fields['Lot / Batch'].get().strip())
    win.destroy();self._filament_refresh()
   except Exception as e:messagebox.showerror('Add Spool',str(e))
  self._button(body,'Add Spool',save,True).pack(anchor='e',padx=16,pady=16)

 def _filament_adjust(self):
  sid=self._selected_spool()
  if not sid:return
  row=next(x for x in self.core.inventory_profit.spools("",False) if x['id']==sid)
  win=tk.Toplevel(self);win.title('Adjust Filament');win.geometry('480x300');win.configure(bg=self._c('bg'));win.transient(self);win.grab_set()
  body=self._card(win,'%s %s'%(row['material'],row['color'] or ''));body.pack(fill='both',expand=True,padx=16,pady=16)
  rem=tk.StringVar(value='%.0f'%row['remaining_g']);note=tk.StringVar(value='Manual spool adjustment')
  tk.Label(body,text='Remaining weight (g)',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(10,2))
  self._entry(body,rem,30).pack(fill='x',padx=16,ipady=5)
  tk.Label(body,text='Reason / note',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(10,2))
  self._entry(body,note,30).pack(fill='x',padx=16,ipady=5)
  def save():
   try:self.core.inventory_profit.adjust_spool(sid,float(rem.get()),note.get());win.destroy();self._filament_refresh()
   except Exception as e:messagebox.showerror('Adjust',str(e))
  self._button(body,'Save Adjustment',save,True).pack(anchor='e',padx=16,pady=15)

 def _cost_settings(self):
  win=tk.Toplevel(self);win.title('Production Cost Settings');win.geometry('520x450');win.configure(bg=self._c('bg'));win.transient(self);win.grab_set()
  body=self._card(win,'Cost & Stock Settings');body.pack(fill='both',expand=True,padx=16,pady=16)
  specs=[('Machine cost per hour ($)','machine_hourly_cost'),('Default packaging per job ($)','default_packaging_cost'),
         ('Target margin (%)','target_margin_percent'),('Low filament threshold (g)','filament_low_threshold_g'),
         ('Forecast reorder window (days)','filament_reorder_days')]
  vals={}
  for label,key in specs:
   tk.Label(body,text=label,bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(8,2))
   v=tk.StringVar(value=self.core.inventory_profit.setting(key,''));self._entry(body,v,30).pack(fill='x',padx=16,ipady=5);vals[key]=v
  def save():
   for k,v in vals.items():self.core.inventory_profit.set_setting(k,v.get())
   win.destroy();self._filament_refresh()
  self._button(body,'Save Settings',save,True).pack(anchor='e',padx=16,pady=16)

 def _supplies_manager(self):
  win=tk.Toplevel(self);win.title('Packaging & Supplies');win.geometry('900x590')
  win.minsize(720,480);win.configure(bg=self._c('bg'));win.transient(self);win.grab_set()
  bar=tk.Frame(win,bg=self._c('bg'));bar.pack(fill='x',padx=14,pady=(14,8))

  card=self._card(win,'Supply Inventory');card.pack(fill='both',expand=True,padx=14,pady=(0,14))
  cols=('name','category','quantity','unit','cost','value','threshold')
  table=ttk.Treeview(card,columns=cols,show='headings',style='Dark.Treeview',selectmode='browse')
  specs=[('name','Item',210),('category','Category',120),('quantity','Qty',75),('unit','Unit',65),
         ('cost','Unit Cost',90),('value','Value',90),('threshold','Low At',75)]
  for c,label,w in specs:table.heading(c,text=label);table.column(c,width=w,anchor='w',stretch=(c=='name'))
  sy=ttk.Scrollbar(card,orient='vertical',command=table.yview);table.configure(yscrollcommand=sy.set)
  table.pack(side='left',fill='both',expand=True,padx=(12,0),pady=(0,12));sy.pack(side='right',fill='y',padx=(0,12),pady=(0,12))
  table.tag_configure('low',foreground=self._c('orange'));table.tag_configure('ok',foreground=self._c('text'))

  def refresh():
   table.delete(*table.get_children())
   for row in self.core.supplies.list(False):
    value=float(row['quantity'] or 0)*int(row['unit_cost_cents'] or 0)
    tag='low' if row['active'] and float(row['low_threshold'] or 0)>0 and float(row['quantity'] or 0)<=float(row['low_threshold'] or 0) else 'ok'
    table.insert('','end',iid=row['id'],values=(
     row['name'],row['category'],'%g'%row['quantity'],row['unit'],
     '$%.2f'%(row['unit_cost_cents']/100.0),'$%.2f'%(value/100.0),'%g'%row['low_threshold']),tags=(tag,))

  def add():
   d=tk.Toplevel(win);d.title('Add Supply');d.geometry('430x470');d.configure(bg=self._c('bg'));d.transient(win);d.grab_set()
   vars={k:tk.StringVar(value=v) for k,v in {
    'name':'','category':'Packaging','unit':'ea','quantity':'0','cost':'0.00','threshold':'0','notes':''}.items()}
   box=self._card(d,'Supply Item');box.pack(fill='both',expand=True,padx=14,pady=14)
   for label,key in [('Name','name'),('Category','category'),('Unit','unit'),('Starting Quantity','quantity'),
                     ('Unit Cost ($)','cost'),('Low Threshold','threshold'),('Notes','notes')]:
    tk.Label(box,text=label,bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=14,pady=(7,2))
    self._entry(box,vars[key],38).pack(fill='x',padx=14,ipady=5)
   def save():
    try:
     if not vars['name'].get().strip():raise ValueError('Name is required.')
     self.core.supplies.create(vars['name'].get().strip(),vars['category'].get().strip() or 'Packaging',
      vars['unit'].get().strip() or 'ea',float(vars['quantity'].get() or 0),
      int(round(float(vars['cost'].get() or 0)*100)),float(vars['threshold'].get() or 0),vars['notes'].get())
     d.destroy();refresh()
    except Exception as exc:messagebox.showerror('Supply',str(exc),parent=d)
   self._button(box,'Save Supply',save,True).pack(side='right',padx=14,pady=14)
   self._button(box,'Cancel',d.destroy).pack(side='right',pady=14)

  def adjust():
   sel=table.selection()
   if not sel:return messagebox.showinfo('Supplies','Select an item first.',parent=win)
   amount=simpledialog.askfloat('Adjust Supply','Enter quantity to add (negative removes):',parent=win)
   if amount is None:return
   self.core.supplies.adjust(sel[0],amount,'manual','','Manual inventory adjustment');refresh()

  self._button(bar,'+ Add Supply',add,True).pack(side='left')
  self._button(bar,'Adjust Quantity',adjust).pack(side='left',padx=7)
  tk.Label(bar,text='Tracked value: $%.2f'%(self.core.supplies.total_value_cents()/100.0),
           bg=self._c('bg'),fg=self._c('muted')).pack(side='right')
  refresh()

 def _build_analytics_page(self):
  period=getattr(self,'_analytics_range','All Time')
  days={'Today':1,'7 Days':7,'30 Days':30,'1 Year':365}.get(period)
  rows=list(self.core.inventory_profit.profitability())
  finance=self.core.invoices.finance_summary(days)
  business=self.core.inventory_profit.business_profit_summary(days)
  payments=list(self.core.invoices.payment_history(100,days))
  filterbar=tk.Frame(self.content,bg=self._c('bg'));filterbar.pack(fill='x',pady=(4,8))
  tk.Label(filterbar,text='Analytics Period',bg=self._c('bg'),fg=self._c('muted')).pack(side='left')
  period_var=tk.StringVar(value=period)
  combo=ttk.Combobox(filterbar,textvariable=period_var,values=['Today','7 Days','30 Days','1 Year','All Time'],state='readonly',width=14)
  combo.pack(side='left',padx=8)
  def change_period(_event=None):
   self._analytics_range=period_var.get();self.show_page('Analytics')
  combo.bind('<<ComboboxSelected>>',change_period)
  totals={'jobs':sum(int(r['completed'] or 0) for r in rows),
          'cost':sum(int(r['costs_cents'] or 0) for r in rows),
          'profit':sum(int(r['profit_cents'] or 0) for r in rows)}

  metrics=tk.Frame(self.content,bg=self._c('bg'));metrics.pack(fill='x',pady=(0,10))
  supply_value=self.core.supplies.total_value_cents()
  low_supplies=len(self.core.supplies.low())
  cards=[
   ('Paid Revenue','$%.2f'%(finance['paid_revenue_cents']/100.0),self._c('green'),'Cash recorded in selected period'),
   ('Net Tracked Profit','$%.2f'%(business['net_profit_cents']/100.0),self._c('purple'),'Revenue minus manufacturing, shipping + used supplies'),
   ('Margin','%.1f%%'%business['margin_percent'],self._c('blue'),'Tracked net margin'),
   ('Outstanding','$%.2f'%(finance['outstanding_cents']/100.0),self._c('orange'),'Current open + partial balance'),
   ('Failure Rate','%.1f%%'%business['failure_rate_percent'],self._c('red'),'%d failed / %d jobs'%(business['failed_jobs'],business['jobs'])),
   ('Print Hours','%.1f h'%business['print_hours'],self._c('purple'),'Tracked print time'),
   ('Packaging Used','$%.2f'%(business['supply_cost_cents']/100.0),self._c('orange'),'Recorded supply consumption'),
   ('Supply Inventory','$%.2f'%(supply_value/100.0),self._c('blue'),'%d low item%s'%(low_supplies,'' if low_supplies==1 else 's')),
  ]
  for i,(title,value,color,detail) in enumerate(cards):
   row=i//4;col=i%4
   card=self._metric_card(metrics,title,value,color,detail)
   card.grid(row=row,column=col,sticky='nsew',padx=(0 if col==0 else 7,0),pady=(0 if row==0 else 7,0))
   metrics.columnconfigure(col,weight=1)

  nb=ttk.Notebook(self.content);nb.pack(fill='both',expand=True)

  finance_tab=tk.Frame(nb,bg=self._c('bg'))
  product_tab=tk.Frame(nb,bg=self._c('bg'))
  nb.add(finance_tab,text='Revenue & Payments')
  nb.add(product_tab,text='Product Profitability')

  paid_card=self._card(finance_tab,'Payment Ledger');paid_card.pack(fill='both',expand=True,pady=(8,0))
  cols=('date','invoice','order','customer','method','amount')
  pt=ttk.Treeview(paid_card,columns=cols,show='headings',style='Dark.Treeview')
  labels={'date':'Paid','invoice':'Invoice','order':'Order','customer':'Customer','method':'Method','amount':'Amount'}
  widths={'date':135,'invoice':140,'order':105,'customer':220,'method':120,'amount':95}
  for c in cols:pt.heading(c,text=labels[c]);pt.column(c,width=widths[c],anchor='w')
  for p in payments:
   pt.insert('','end',values=(str(p['paid_at'])[:16],p['invoice_number'],p['order_number'] or '—',
    p['customer_name'],p['method'] or 'Payment','$%.2f'%(p['amount_cents']/100.0)),tags=('body',))
  pt.pack(fill='both',expand=True,padx=12,pady=(0,12))
  if not payments:
   tk.Label(paid_card,text='No payments have been recorded yet.',
    bg=self._c('surface'),fg=self._c('muted')).place(relx=.5,rely=.5,anchor='center')

  card=self._card(product_tab,'Manufacturing Profitability');card.pack(fill='both',expand=True,pady=(8,0))
  cols=('product','sku','jobs','completed','cost','profit','avg')
  table=ttk.Treeview(card,columns=cols,show='headings',style='Dark.Treeview')
  for c,title,width in [('product','Product',260),('sku','SKU',100),('jobs','Jobs',60),('completed','Completed',80),
                ('cost','Tracked Cost',100),('profit','Tracked Profit',100),('avg','Avg Print',90)]:
   table.heading(c,text=title);table.column(c,width=width,anchor='w')
  for r in rows:
   mins=int(r['avg_minutes'] or 0)
   table.insert('','end',values=(r['name'],r['sku'] or '—',r['jobs'],r['completed'],
    '$%.2f'%(r['costs_cents']/100.0),'$%.2f'%(r['profit_cents']/100.0),
    ('%dh %02dm'%(mins//60,mins%60)) if mins else '—'),tags=('body',))
  table.pack(fill='both',expand=True,padx=12,pady=(0,12))

