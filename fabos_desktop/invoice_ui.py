import tkinter as tk, os, webbrowser
from tkinter import ttk, messagebox

class InvoiceMixin:
 def _build_invoices_page(self):
  bar=tk.Frame(self.content,bg=self._c('bg'));bar.pack(fill='x',pady=(4,10))
  self._button(bar,'Create from Order',self._invoice_create_from_order,True).pack(side='left')
  self._button(bar,'View',self._invoice_view).pack(side='left',padx=7)
  self._button(bar,'Record Payment',self._invoice_payment).pack(side='left')
  self._button(bar,'Edit Charges',self._invoice_edit_charges).pack(side='left',padx=7)
  self._button(bar,'Print / Export',self._invoice_export).pack(side='left')
  self._button(bar,'Void',self._invoice_void).pack(side='left',padx=7)

  filt=self._card(self.content);filt.pack(fill='x',pady=(0,10))
  row=tk.Frame(filt,bg=self._c('surface'));row.pack(fill='x',padx=14,pady=10)
  self.invoice_query=tk.StringVar();self.invoice_status=tk.StringVar(value='All')
  tk.Label(row,text='Search',bg=self._c('surface'),fg=self._c('muted')).pack(side='left')
  e=self._entry(row,self.invoice_query,28);e.pack(side='left',padx=(7,16),ipady=6);e.bind('<KeyRelease>',lambda _e:self._refresh_invoices())
  tk.Label(row,text='Status',bg=self._c('surface'),fg=self._c('muted')).pack(side='left')
  cb=ttk.Combobox(row,textvariable=self.invoice_status,values=['All','open','partial','paid','void'],state='readonly',width=15)
  cb.pack(side='left',padx=7);cb.bind('<<ComboboxSelected>>',lambda _e:self._refresh_invoices())
  self.invoice_summary=tk.Label(row,text='',bg=self._c('surface'),fg=self._c('muted'));self.invoice_summary.pack(side='right')

  card=self._card(self.content,'Invoices');card.pack(fill='both',expand=True)
  cols=('number','customer','order','status','total','paid','balance','due','created')
  self.invoice_table=ttk.Treeview(card,columns=cols,show='headings',style='Dark.Treeview')
  labels={'number':'Invoice','customer':'Customer','order':'Order','status':'Status','total':'Total','paid':'Paid','balance':'Balance','due':'Due','created':'Created'}
  widths={'number':140,'customer':190,'order':110,'status':90,'total':90,'paid':90,'balance':90,'due':95,'created':125}
  for c in cols:self.invoice_table.heading(c,text=labels[c],command=lambda x=c:self._sort_invoices(x));self.invoice_table.column(c,width=widths[c],anchor='w')
  self.invoice_table.tag_configure('open',foreground=self._c('blue'),background=self._c('surface'))
  self.invoice_table.tag_configure('partial',foreground=self._c('orange'),background=self._c('surface'))
  self.invoice_table.tag_configure('paid',foreground=self._c('green'),background=self._c('surface'))
  self.invoice_table.tag_configure('void',foreground=self._c('muted'),background=self._c('surface'))
  sy=ttk.Scrollbar(card,orient='vertical',command=self.invoice_table.yview);self.invoice_table.configure(yscrollcommand=sy.set)
  self.invoice_table.pack(side='left',fill='both',expand=True,padx=(12,0),pady=(0,12));sy.pack(side='right',fill='y',padx=(0,12),pady=(0,12))
  self.invoice_table.bind('<Double-1>',lambda _e:self._invoice_view())
  ready=self._card(self.content,'Orders Ready to Invoice');ready.pack(fill='x',pady=(10,0))
  self.invoice_ready_table=ttk.Treeview(ready,columns=('order','customer','status','total'),show='headings',height=5,style='Dark.Treeview')
  for c,title,width in [('order','Order',120),('customer','Customer',230),('status','Status',100),('total','Total',100)]:
   self.invoice_ready_table.heading(c,text=title);self.invoice_ready_table.column(c,width=width,anchor='w')
  self.invoice_ready_table.pack(fill='x',padx=12,pady=(0,8))
  self.invoice_ready_table.bind('<Double-1>',lambda _e:self._invoice_create_ready())
  foot=tk.Frame(ready,bg=self._c('surface'));foot.pack(fill='x',padx=12,pady=(0,10))
  self.invoice_ready_hint=tk.Label(foot,text='',bg=self._c('surface'),fg=self._c('muted'));self.invoice_ready_hint.pack(side='left')
  self._button(foot,'Create Selected Invoice',self._invoice_create_ready,True).pack(side='right')
  self.invoice_sort='created';self.invoice_desc=True
  self._refresh_invoices()

 def _sort_invoices(self,col):
  if self.invoice_sort==col:self.invoice_desc=not self.invoice_desc
  else:self.invoice_sort=col;self.invoice_desc=False
  self._refresh_invoices()

 def _refresh_invoices(self):
  if not getattr(self,'invoice_table',None):return
  rows=self.core.invoices.list(self.invoice_query.get().strip(),self.invoice_status.get(),self.invoice_sort,self.invoice_desc)
  self.invoice_table.delete(*self.invoice_table.get_children())
  total=sum(int(r['balance_cents'] or 0) for r in rows if r['status']!='void')
  for r in rows:
   self.invoice_table.insert('','end',iid=r['id'],values=(r['invoice_number'],r['customer_name'],r['order_number'],r['status'].title(),
    '$%.2f'%(r['total_cents']/100.0),'$%.2f'%(r['paid_cents']/100.0),'$%.2f'%(r['balance_cents']/100.0),r['due_at'] or '—',str(r['created_at'])[:16]),tags=(r['status'],))
  self.invoice_summary.config(text='%d invoice%s • $%.2f outstanding'%(len(rows),'' if len(rows)==1 else 's',total/100.0))

  if getattr(self,'invoice_ready_table',None):
   self.invoice_ready_table.delete(*self.invoice_ready_table.get_children())
   with self.core.database.connect() as c:
    ready=c.execute("""SELECT o.id,o.order_number,o.status,o.total_cents,COALESCE(c.name,'No customer') customer_name
      FROM orders o LEFT JOIN customers c ON c.id=o.customer_id
      WHERE o.status<>'cancelled'
        AND NOT EXISTS(SELECT 1 FROM invoices i WHERE i.order_id=o.id AND i.status<>'void')
      ORDER BY CASE o.status WHEN 'ready' THEN 0 WHEN 'completed' THEN 1 ELSE 2 END,o.created_at DESC""").fetchall()
   for o in ready:
    self.invoice_ready_table.insert('','end',iid=o['id'],values=(o['order_number'],o['customer_name'],o['status'].title(),'$%.2f'%(o['total_cents']/100.0)),tags=('body',))
   self.invoice_ready_hint.config(text=('%d uninvoiced order%s.'%(len(ready),'' if len(ready)==1 else 's')) if ready else 'No uninvoiced orders yet.')

 def _selected_invoice(self):
  s=self.invoice_table.selection() if getattr(self,'invoice_table',None) else ()
  if not s:messagebox.showinfo('Invoices','Select an invoice first.');return None
  return s[0]

 def _invoice_create_ready(self):
  s=self.invoice_ready_table.selection() if getattr(self,'invoice_ready_table',None) else ()
  if not s:return messagebox.showinfo('Invoices','Select an order from Orders Ready to Invoice.')
  try:
   iid,_=self.core.invoices.create_from_order(s[0])
   self._refresh_invoices()
   if iid in self.invoice_table.get_children():
    self.invoice_table.selection_set(iid);self.invoice_table.see(iid)
  except Exception as exc:messagebox.showerror('Invoice',str(exc))

 def _invoice_create_from_order(self):
  # dialog of orders without requiring a manual invoice number
  with self.core.database.connect() as c:
   orders=c.execute("""SELECT o.id,o.order_number,o.total_cents,o.status,COALESCE(c.name,'No customer') customer_name
      FROM orders o LEFT JOIN customers c ON c.id=o.customer_id
      ORDER BY o.created_at DESC""").fetchall()
  if not orders:return messagebox.showinfo('Invoices','There are no orders yet.')
  win=tk.Toplevel(self);win.title('Create Invoice from Order');win.geometry('650x470');win.configure(bg=self._c('bg'));win.transient(self);win.grab_set()
  body=self._card(win,'Select Order');body.pack(fill='both',expand=True,padx=16,pady=16)
  table=ttk.Treeview(body,columns=('order','customer','status','total'),show='headings',style='Dark.Treeview')
  for col,title,width in [('order','Order',120),('customer','Customer',230),('status','Status',100),('total','Total',100)]:
   table.heading(col,text=title);table.column(col,width=width,anchor='w')
  for o in orders:table.insert('','end',iid=o['id'],values=(o['order_number'],o['customer_name'],o['status'].title(),'$%.2f'%(o['total_cents']/100.0)),tags=('body',))
  table.pack(fill='both',expand=True,padx=12,pady=(0,10))
  due=tk.StringVar(value=self.core.shop_settings.get('invoice_due_days','14'))
  foot=tk.Frame(body,bg=self._c('surface'));foot.pack(fill='x',padx=12,pady=(0,12))
  tk.Label(foot,text='Payment due in',bg=self._c('surface'),fg=self._c('muted')).pack(side='left')
  self._entry(foot,due,7).pack(side='left',padx=6,ipady=4)
  tk.Label(foot,text='days',bg=self._c('surface'),fg=self._c('muted')).pack(side='left')
  def create():
   s=table.selection()
   if not s:return messagebox.showinfo('Invoice','Select an order.')
   try:
    iid,new=self.core.invoices.create_from_order(s[0],int(due.get() or 14))
    win.destroy();self._refresh_invoices();self.invoice_table.selection_set(iid);self.invoice_table.see(iid)
    if not new:messagebox.showinfo('Invoice','That order already has an active invoice. FabOS selected it.')
   except Exception as e:messagebox.showerror('Invoice',str(e))
  self._button(foot,'Create Invoice',create,True).pack(side='right')

 def _invoice_view(self):
  iid=self._selected_invoice()
  if not iid:return
  inv,items,pays=self.core.invoices.get(iid)
  win=tk.Toplevel(self);win.title(inv['invoice_number']);win.geometry('820x650');win.configure(bg=self._c('bg'))
  tk.Label(win,text=inv['invoice_number'],bg=self._c('bg'),fg=self._c('text'),font=('Segoe UI',18,'bold')).pack(anchor='w',padx=18,pady=(18,3))
  tk.Label(win,text='%s • Order %s • %s'%(inv['customer_name'],inv['order_number'],inv['status'].title()),
           bg=self._c('bg'),fg=self._c('muted')).pack(anchor='w',padx=18)
  table=ttk.Treeview(win,columns=('item','qty','material','price'),show='headings',height=8,style='Dark.Treeview')
  for c,t,w in [('item','Item',350),('qty','Qty',60),('material','Material',180),('price','Line Total',110)]:
   table.heading(c,text=t);table.column(c,width=w,anchor='w')
  for x in items:
   mat=('%s %s'%(x['material'] or '',x['color'] or '')).strip()
   table.insert('','end',values=(x['description'],x['quantity'],mat,'$%.2f'%(x['quantity']*x['unit_price_cents']/100.0)),tags=('body',))
  table.pack(fill='x',padx=18,pady=14)
  summary=self._card(win,'Invoice Summary');summary.pack(fill='x',padx=18)
  for label,value in [('Subtotal',inv['subtotal_cents']),('Tax',inv['tax_cents']),('Shipping',inv['shipping_cents']),
                      ('Discount',-inv['discount_cents']),('Total',inv['total_cents']),('Paid',inv['paid_cents']),('Balance',inv['balance_cents'])]:
   line=tk.Frame(summary,bg=self._c('surface'));line.pack(fill='x',padx=14,pady=3)
   tk.Label(line,text=label,bg=self._c('surface'),fg=self._c('muted')).pack(side='left')
   tk.Label(line,text='$%.2f'%(value/100.0),bg=self._c('surface'),fg=self._c('text') if label!='Balance' else self._c('purple'),
            font=('Segoe UI',10,'bold' if label in ('Total','Balance') else 'normal')).pack(side='right')
  pays_card=self._card(win,'Payments');pays_card.pack(fill='both',expand=True,padx=18,pady=14)
  pt=ttk.Treeview(pays_card,columns=('date','method','reference','amount'),show='headings',height=6,style='Dark.Treeview')
  for c,t,w in [('date','Date',145),('method','Method',120),('reference','Reference',220),('amount','Amount',100)]:
   pt.heading(c,text=t);pt.column(c,width=w,anchor='w')
  for p in pays:pt.insert('','end',values=(str(p['paid_at'])[:16],p['method'] or 'Payment',p['reference'] or '—','$%.2f'%(p['amount_cents']/100.0)),tags=('body',))
  pt.pack(fill='both',expand=True,padx=12,pady=(0,12))

 def _invoice_payment(self):
  iid=self._selected_invoice()
  if not iid:return
  inv,_,_=self.core.invoices.get(iid)
  if inv['status']=='void':return messagebox.showwarning('Payment','This invoice is void.')
  win=tk.Toplevel(self);win.title('Record Payment');win.geometry('510x430');win.configure(bg=self._c('bg'));win.transient(self);win.grab_set()
  body=self._card(win,'%s — Balance $%.2f'%(inv['invoice_number'],inv['balance_cents']/100.0));body.pack(fill='both',expand=True,padx=16,pady=16)
  vals={}
  for label,default in [('Amount ($)','%.2f'%(inv['balance_cents']/100.0)),('Method','Cash'),('Reference',''),('Notes','')]:
   tk.Label(body,text=label,bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(8,2))
   v=tk.StringVar(value=default);self._entry(body,v,35).pack(fill='x',padx=16,ipady=5);vals[label]=v
  def save():
   try:
    self.core.invoices.record_payment(iid,int(round(float(vals['Amount ($)'].get())*100)),vals['Method'].get(),vals['Reference'].get(),vals['Notes'].get())
    win.destroy();self._refresh_invoices()
   except Exception as e:messagebox.showerror('Payment',str(e))
  self._button(body,'Record Payment',save,True).pack(anchor='e',padx=16,pady=16)

 def _invoice_edit_charges(self):
  iid=self._selected_invoice()
  if not iid:return
  inv,_,_=self.core.invoices.get(iid)
  win=tk.Toplevel(self);win.title('Invoice Charges');win.geometry('520x500');win.configure(bg=self._c('bg'));win.transient(self);win.grab_set()
  body=self._card(win,inv['invoice_number']);body.pack(fill='both',expand=True,padx=16,pady=16)
  vals={}
  for label,cents in [('Tax ($)',inv['tax_cents']),('Shipping ($)',inv['shipping_cents']),('Discount ($)',inv['discount_cents'])]:
   tk.Label(body,text=label,bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(8,2))
   v=tk.StringVar(value='%.2f'%(cents/100.0));self._entry(body,v,30).pack(fill='x',padx=16,ipady=5);vals[label]=v
  tk.Label(body,text='Notes',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(10,2))
  notes=tk.Text(body,height=6,bg=self._c('surface_alt'),fg=self._c('text'),insertbackground='white',bd=0)
  notes.insert('1.0',inv['notes'] or '');notes.pack(fill='x',padx=16)
  def save():
   try:
    self.core.invoices.update_charges(iid,int(round(float(vals['Tax ($)'].get())*100)),int(round(float(vals['Shipping ($)'].get())*100)),
     int(round(float(vals['Discount ($)'].get())*100)),notes.get('1.0','end').strip())
    win.destroy();self._refresh_invoices()
   except Exception as e:messagebox.showerror('Invoice',str(e))
  self._button(body,'Save Charges',save,True).pack(anchor='e',padx=16,pady=16)

 def _invoice_export(self):
  iid=self._selected_invoice()
  if not iid:return
  try:
   path=self.core.invoices.export_html(iid)
   webbrowser.open(path.as_uri())
  except Exception as e:messagebox.showerror('Invoice Export',str(e))

 def _invoice_void(self):
  iid=self._selected_invoice()
  if not iid:return
  try:
   inv,_,payments=self.core.invoices.get(iid)
  except Exception as exc:
   return messagebox.showerror('Void Invoice',str(exc))
  paid=sum(int(p['amount_cents'] or 0) for p in payments)
  if paid>0 or inv['status'] in ('paid','partial'):
   return messagebox.showwarning(
    'Cannot Void Paid Invoice',
    '%s has $%.2f in recorded payments.\n\n'
    'A paid or partially paid invoice should not be voided until its payment is reversed or refunded.'
    %(inv['invoice_number'],paid/100.0)
   )
  if not messagebox.askyesno(
    'Void Invoice',
    'Void %s?\n\nThis invoice has no recorded payments.'%inv['invoice_number']
  ):return
  try:self.core.invoices.void(iid);self._refresh_invoices()
  except Exception as e:messagebox.showerror('Void Invoice',str(e))

