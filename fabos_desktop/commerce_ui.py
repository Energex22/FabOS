import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import date, timedelta

# Uses COLORS and helper methods from the main desktop class.
class CommerceMixin:

    def _build_quotes_page(self):
        bar=tk.Frame(self.content,bg=self._c('bg')); bar.pack(fill='x',pady=(4,10))
        self._button(bar,'+ New Quote',lambda:self._quote_editor(None),primary=True).pack(side='left')
        for label,cmd in [('Edit',self._edit_quote),('View',self._view_quote),('Approve & Create Order',self._convert_quote)]:
            self._button(bar,label,cmd).pack(side='left',padx=(7,0))

        self.quote_view=tk.StringVar(value='active')
        tabs=tk.Frame(self.content,bg=self._c('bg')); tabs.pack(fill='x',pady=(0,8))
        self.quote_tab_buttons={}
        for label,value in [('Active Quotes','active'),('Quote History','history')]:
            button=tk.Button(
                tabs,text=label,bd=0,padx=18,pady=9,font=('Segoe UI',9,'bold'),
                command=lambda v=value:self._switch_quote_view(v)
            )
            button.pack(side='left',padx=(0,6))
            self.quote_tab_buttons[value]=button
        self._style_quote_tabs()

        filt=self._card(self.content); filt.pack(fill='x',pady=(0,10))
        row=tk.Frame(filt,bg=self._c('surface')); row.pack(fill='x',padx=14,pady=10)
        tk.Label(row,text='Search',bg=self._c('surface'),fg=self._c('muted')).pack(side='left')
        self.quote_query=tk.StringVar()
        e=self._entry(row,self.quote_query,28); e.pack(side='left',padx=(7,16),ipady=6)
        e.bind('<KeyRelease>',lambda _e:self._refresh_quotes())
        tk.Label(row,text='Status',bg=self._c('surface'),fg=self._c('muted')).pack(side='left')
        self.quote_status=tk.StringVar(value='All')
        self.quote_status_combo=ttk.Combobox(
            row,textvariable=self.quote_status,
            values=['All','draft','sent'],state='readonly',width=16
        )
        self.quote_status_combo.pack(side='left',padx=7)
        self.quote_status_combo.bind('<<ComboboxSelected>>',lambda _e:self._refresh_quotes())
        self.quote_count=tk.Label(row,text='',bg=self._c('surface'),fg=self._c('muted'))
        self.quote_count.pack(side='right')

        card=self._card(self.content,'Quotes'); card.pack(fill='both',expand=True)
        cols=('number','customer','status','items','total','expires','created')
        self.quote_table=ttk.Treeview(card,columns=cols,show='headings',style='Dark.Treeview')
        labels={'number':'Quote','customer':'Customer','status':'Status','items':'Items','total':'Total','expires':'Expires','created':'Created'}
        widths={'number':135,'customer':220,'status':100,'items':70,'total':95,'expires':105,'created':130}
        for c in cols:
            self.quote_table.heading(c,text=labels[c],command=lambda x=c:self._sort_quotes(x))
            self.quote_table.column(c,width=widths[c],anchor='w')
        self.quote_table.tag_configure('approved',foreground=self._c('green'),background=self._c('surface'))
        self.quote_table.tag_configure('declined',foreground=self._c('red'),background=self._c('surface'))
        self.quote_table.tag_configure('expired',foreground=self._c('orange'),background=self._c('surface'))
        self.quote_table.tag_configure('draft',foreground=self._c('text'),background=self._c('surface'))
        self.quote_table.tag_configure('sent',foreground=self._c('blue'),background=self._c('surface'))
        sy=ttk.Scrollbar(card,orient='vertical',command=self.quote_table.yview)
        self.quote_table.configure(yscrollcommand=sy.set)
        self.quote_table.pack(side='left',fill='both',expand=True,padx=(12,0),pady=(0,12))
        sy.pack(side='right',fill='y',padx=(0,12),pady=(0,12))
        self.quote_table.bind('<Double-1>',lambda _e:self._view_quote())
        self._refresh_quotes()

    def _style_quote_tabs(self):
        active=self.quote_view.get()
        for value,button in self.quote_tab_buttons.items():
            selected=value==active
            button.configure(
                bg=self._c('purple') if selected else self._c('surface_alt'),
                fg='white' if selected else self._c('text'),
                activebackground=self._c('purple_dark') if selected else self._c('border'),
                activeforeground='white'
            )

    def _switch_quote_view(self,view):
        self.quote_view.set(view)
        self.quote_status.set('All')
        values=['All','draft','sent'] if view=='active' else ['All','approved','declined','expired']
        self.quote_status_combo.configure(values=values)
        self._style_quote_tabs()
        self._refresh_quotes()

    def _c(self,name):
        from fabos_desktop.main import COLORS
        return COLORS[name]
    def _button(self,parent,text,command,primary=False):
        return tk.Button(parent,text=text,command=command,bg=self._c('purple') if primary else self._c('surface_alt'),fg='white' if primary else self._c('text'),bd=0,padx=14,pady=9,font=('Segoe UI',9,'bold' if primary else 'normal'))
    def _entry(self,parent,var,width=20):
        return tk.Entry(parent,textvariable=var,bg=self._c('surface_alt'),fg=self._c('text'),insertbackground='white',selectbackground=self._c('purple_dark'),selectforeground='white',relief='flat',width=width)
    def _sort_quotes(self,column):
        if self.quote_sort_column==column:self.quote_sort_descending=not self.quote_sort_descending
        else:self.quote_sort_column=column;self.quote_sort_descending=False
        self._refresh_quotes()
    def _refresh_quotes(self):
        if not getattr(self,'quote_table',None):return
        self.quote_table.delete(*self.quote_table.get_children())
        group=self.quote_view.get() if getattr(self,'quote_view',None) else 'all'
        rows=self.core.quotes.list(
            self.quote_query.get().strip(),self.quote_status.get(),
            self.quote_sort_column,self.quote_sort_descending,group=group
        )
        for r in rows:
            self.quote_table.insert(
                '','end',iid=r['id'],
                values=(r['quote_number'],r['customer_name'],r['status'].title(),r['item_count'],
                        '$%.2f'%(r['total_cents']/100.0),r['expires_at'] or '—',str(r['created_at'])[:16]),
                tags=(r['status'],)
            )
        if getattr(self,'quote_count',None):
            label='active quote' if group=='active' else 'history record'
            self.quote_count.configure(text='%d %s%s'%(len(rows),label,'' if len(rows)==1 else 's'))
    def _selected_quote_id(self):
        sel=self.quote_table.selection() if getattr(self,'quote_table',None) else ()
        if not sel:messagebox.showinfo('Quotes','Select a quote first.');return None
        return sel[0]
    def _edit_quote(self):
        qid=self._selected_quote_id()
        if qid:self._quote_editor(qid)
    def _convert_quote(self):
        qid=self._selected_quote_id()
        if not qid:return
        try:self.core.quotes.convert_to_order(qid)
        except Exception as exc:messagebox.showerror('Convert quote',str(exc));return
        self._refresh_quotes()
        messagebox.showinfo(
            'Order created',
            'The quote was approved, moved to Quote History, and converted into an order.'
        )
        self.show_page('Orders')
    def _quote_editor(self,quote_id):
        record=None; old=[]
        if quote_id:record,old=self.core.quotes.get(quote_id)
        customers=self.core.customers.list(); products=self.core.products.list(); cmap={r['name']+((' — '+r['email']) if r['email'] else ''):r['id'] for r in customers}; pmap={r['name']:r for r in products}
        if not cmap:messagebox.showinfo('New quote','Add a customer before creating a quote.');self.show_page('Customers');return
        win=tk.Toplevel(self);win.title('Edit Quote' if record else 'New Quote');win.geometry('940x720');win.minsize(780,600);win.configure(bg=self._c('bg'));win.transient(self);win.grab_set()
        top=tk.Frame(win,bg=self._c('surface'));top.pack(fill='x',padx=14,pady=(14,8));cv=tk.StringVar();sv=tk.StringVar(value=record['status'] if record else 'draft');ev=tk.StringVar(value=record['expires_at'] if record and record['expires_at'] else (date.today()+timedelta(days=14)).isoformat())
        tk.Label(top,text='Customer',bg=self._c('surface'),fg=self._c('muted')).pack(side='left',padx=(12,5));ttk.Combobox(top,textvariable=cv,values=list(cmap),state='readonly',width=34).pack(side='left')
        tk.Label(top,text='Status',bg=self._c('surface'),fg=self._c('muted')).pack(side='left',padx=(14,5));ttk.Combobox(top,textvariable=sv,values=['draft','sent','approved','declined'],state='readonly',width=12).pack(side='left')
        tk.Label(top,text='Expires',bg=self._c('surface'),fg=self._c('muted')).pack(side='left',padx=(14,5));self._entry(top,ev,12).pack(side='left',ipady=5)
        if record:
            for label,cid in cmap.items():
                if cid==record['customer_id']:cv.set(label);break
        items=[{k:i[k] for k in ('product_id','description','quantity','unit_price_cents','material','color','estimated_minutes','estimated_filament_g')} for i in old]
        add=self._card(win);add.pack(fill='x',padx=14,pady=8);r=tk.Frame(add,bg=self._c('surface'));r.pack(fill='x',padx=12,pady=10);pv=tk.StringVar();qv=tk.StringVar(value='1');mv=tk.StringVar(value='PLA');color=tk.StringVar()
        tk.Label(r,text='Product',bg=self._c('surface'),fg=self._c('muted')).pack(side='left');ttk.Combobox(r,textvariable=pv,values=list(pmap),state='readonly',width=30).pack(side='left',padx=6)
        tk.Label(r,text='Qty',bg=self._c('surface'),fg=self._c('muted')).pack(side='left');self._entry(r,qv,5).pack(side='left',padx=6,ipady=5)
        mats=[]
        with self.core.database.connect() as conn:mats=[x[0] for x in conn.execute('SELECT DISTINCT material FROM filament_spools WHERE active=1 ORDER BY material').fetchall()]
        tk.Label(r,text='Material',bg=self._c('surface'),fg=self._c('muted')).pack(side='left');ttk.Combobox(r,textvariable=mv,values=mats or ['PLA','PETG','TPU'],width=10).pack(side='left',padx=6)
        tk.Label(r,text='Color',bg=self._c('surface'),fg=self._c('muted')).pack(side='left');self._entry(r,color,12).pack(side='left',padx=6,ipady=5)
        card=self._card(win,'Quote Items');card.pack(fill='both',expand=True,padx=14,pady=8);table=ttk.Treeview(card,columns=('item','qty','material','time','grams','price'),show='headings',style='Dark.Treeview')
        for c,l,w in [('item','Item',290),('qty','Qty',50),('material','Material / Color',145),('time','Time',75),('grams','Filament',75),('price','Line Total',95)]:table.heading(c,text=l);table.column(c,width=w,anchor='w')
        table.pack(fill='both',expand=True,padx=12,pady=(0,10));total=tk.Label(win,text='Total: $0.00',bg=self._c('bg'),fg=self._c('purple'),font=('Segoe UI',14,'bold'));total.pack(anchor='e',padx=22)
        def refresh():
            table.delete(*table.get_children());amount=0
            for n,i in enumerate(items):amount+=i['quantity']*i['unit_price_cents'];table.insert('','end',iid=str(n),values=(i['description'],i['quantity'],('%s %s'%(i['material'],i['color'])).strip(),'%.1fh'%(i['estimated_minutes']/60.0),'%.0fg'%i['estimated_filament_g'],'$%.2f'%(i['quantity']*i['unit_price_cents']/100.0)),tags=('body',))
            total.configure(text='Total: $%.2f'%(amount/100.0))
        def add_item():
            p=pmap.get(pv.get())
            if not p:messagebox.showinfo('Quote item','Choose a catalog product.');return
            try:q=max(1,int(qv.get()))
            except ValueError:messagebox.showerror('Quote item','Quantity must be a whole number.');return
            items.append({'product_id':p['id'],'description':p['name'],'quantity':q,'unit_price_cents':p['price_cents'],'material':mv.get(),'color':color.get(),'estimated_minutes':p['estimated_minutes'] or 0,'estimated_filament_g':p['estimated_filament_g'] or 0});refresh()
        def remove():
            sel=table.selection()
            if sel:items.pop(int(sel[0]));refresh()
        self._button(r,'Add Item',add_item,True).pack(side='left',padx=6);self._button(r,'Remove',remove).pack(side='left')
        bottom=tk.Frame(win,bg=self._c('bg'));bottom.pack(fill='x',padx=14,pady=(4,14))
        def save():
            try:self.core.quotes.save({'customer_id':cmap.get(cv.get()),'status':sv.get(),'expires_at':ev.get(),'notes':''},items,quote_id)
            except Exception as exc:messagebox.showerror('Save quote',str(exc));return
            win.destroy();self._refresh_quotes();messagebox.showinfo('Quote saved','The quote was saved successfully.')
        self._button(bottom,'Save Quote',save,True).pack(side='right');self._button(bottom,'Cancel',win.destroy).pack(side='right',padx=8);refresh()
    def _view_quote(self):
        qid=self._selected_quote_id()
        if not qid:return
        q,items=self.core.quotes.get(qid);self._document_view('Quote '+q['quote_number'],q['quote_number'],q['customer_name'],q['status'],q['total_cents'],items,q['expires_at'])

    def _build_orders_page(self):
        bar=tk.Frame(self.content,bg=self._c('bg'));bar.pack(fill='x',pady=(4,10))
        self._button(bar,'Open Order',self._view_order,True).pack(side='left')
        self._button(bar,'Next Action',self._order_next_action).pack(side='left',padx=(7,0))
        self._button(bar,'Fulfillment',self._order_fulfillment).pack(side='left',padx=(7,0))
        self._button(bar,'Customer Update',self._order_customer_update).pack(side='left',padx=(7,0))
        more=tk.Menubutton(bar,text='More ▾',bg=self._c('surface_alt'),fg=self._c('text'),
            bd=0,relief='flat',activebackground=self._c('border'),activeforeground='white',font=('Segoe UI',9),padx=13,pady=9)
        menu=tk.Menu(more,tearoff=0,bg=self._c('surface_alt'),fg=self._c('text'),
            activebackground=self._c('purple_dark'),activeforeground='white')
        menu.add_command(label='Create Production Jobs',command=self._order_create_jobs)
        menu.add_command(label='Open Production',command=lambda:self.show_page('Production'))
        menu.add_command(label='Open QC',command=lambda:self.show_page('QC'))
        menu.add_command(label='Create / Open Invoice',command=self._order_create_invoice)
        menu.add_separator()
        for label,status in [('Mark Production','production'),('Mark QC','qc'),('Mark Ready','ready'),
                             ('Mark Shipped','shipped'),('Complete','completed'),('Cancel','cancelled')]:
            menu.add_command(label=label,command=lambda s=status:self._set_order_status(s))
        more.configure(menu=menu);more.pack(side='left',padx=(7,0))

        self.order_view=tk.StringVar(value='active')
        tabs=tk.Frame(self.content,bg=self._c('bg'));tabs.pack(fill='x',pady=(0,8))
        self.order_tab_buttons={}
        for label,value in [('Active Orders','active'),('Order History','history')]:
            button=tk.Button(
                tabs,text=label,bd=0,padx=18,pady=9,font=('Segoe UI',9,'bold'),
                command=lambda v=value:self._switch_order_view(v)
            )
            button.pack(side='left',padx=(0,6))
            self.order_tab_buttons[value]=button
        self._style_order_tabs()

        filt=self._card(self.content);filt.pack(fill='x',pady=(0,10))
        r=tk.Frame(filt,bg=self._c('surface'));r.pack(fill='x',padx=14,pady=10)
        self.order_query=tk.StringVar();self.order_status=tk.StringVar(value='All')
        tk.Label(r,text='Search',bg=self._c('surface'),fg=self._c('muted')).pack(side='left')
        e=self._entry(r,self.order_query,26);e.pack(side='left',padx=(7,16),ipady=6);e.bind('<KeyRelease>',lambda _e:self._refresh_orders())
        tk.Label(r,text='Status',bg=self._c('surface'),fg=self._c('muted')).pack(side='left')
        self.order_status_combo=ttk.Combobox(
            r,textvariable=self.order_status,
            values=['All','new','production','qc','ready'],state='readonly',width=16)
        self.order_status_combo.pack(side='left',padx=7)
        self.order_status_combo.bind('<<ComboboxSelected>>',lambda _e:self._refresh_orders())
        self.order_count=tk.Label(r,text='',bg=self._c('surface'),fg=self._c('muted'))
        self.order_count.pack(side='right')

        split=tk.PanedWindow(self.content,orient='horizontal',bg=self._c('bg'),sashwidth=6,bd=0);split.pack(fill='both',expand=True)
        card=self._card(split,'Orders');detail=self._card(split,'Order Workspace')
        split.add(card,minsize=480,stretch='always');split.add(detail,minsize=390,stretch='always')
        cols=('number','customer','status','due','total')
        self.order_table=ttk.Treeview(card,columns=cols,show='headings',style='Dark.Treeview',selectmode='browse')
        labels={'number':'Order','customer':'Customer','status':'Status','due':'Due','total':'Total'}
        widths={'number':120,'customer':200,'status':90,'due':90,'total':85}
        for c in cols:
            self.order_table.heading(c,text=labels[c],command=lambda x=c:self._sort_orders(x))
            self.order_table.column(c,width=widths[c],anchor='w',stretch=(c=='customer'))
        self.order_table.tag_configure('completed',foreground=self._c('green'))
        self.order_table.tag_configure('shipped',foreground=self._c('blue'))
        self.order_table.tag_configure('delivered',foreground=self._c('green'))
        self.order_table.tag_configure('picked_up',foreground=self._c('green'))
        self.order_table.tag_configure('cancelled',foreground=self._c('red'))
        self.order_table.pack(fill='both',expand=True,padx=12,pady=(0,12))
        self.order_table.bind('<<TreeviewSelect>>',lambda _e:self._order_dossier())
        self.order_table.bind('<Double-1>',lambda _e:self._view_order())
        self.order_table.bind('<Button-3>',self._order_context_menu)
        self.order_detail_panel=tk.Frame(detail,bg=self._c('surface'));self.order_detail_panel.pack(fill='both',expand=True,padx=14,pady=(0,14))
        self._refresh_orders()

    def _order_context_menu(self,event):
        row=self.order_table.identify_row(event.y)
        if row:self.order_table.selection_set(row);self._order_dossier()
        menu=tk.Menu(self,tearoff=0,bg=self._c('surface_alt'),fg=self._c('text'),
                     activebackground=self._c('purple_dark'),activeforeground='white')
        menu.add_command(label='Open Order',command=self._view_order)
        menu.add_command(label='Create / View Production Jobs',command=self._order_create_jobs)
        menu.add_command(label='Fulfillment / Shipping',command=self._order_fulfillment)
        menu.add_command(label='Create Invoice',command=self._order_create_invoice)
        menu.add_separator()
        menu.add_command(label='Mark Ready',command=lambda:self._set_order_status('ready'))
        menu.add_command(label='Mark Shipped',command=lambda:self._set_order_status('shipped'))
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:
            try:menu.grab_release()
            except Exception:pass

    def _sort_orders(self,column):
        if self.order_sort_column==column:self.order_sort_descending=not self.order_sort_descending
        else:self.order_sort_column=column;self.order_sort_descending=False
        self._refresh_orders()

    def _switch_order_view(self,view):
        self.order_view.set(view)
        self.order_status.set('All')
        values=(['All','new','production','qc','ready'] if view=='active'
                else ['All','shipped','delivered','picked_up','completed','cancelled'])
        self.order_status_combo.configure(values=values)
        self._style_order_tabs()
        self._refresh_orders()

    def _style_order_tabs(self):
        active=self.order_view.get()
        for value,button in self.order_tab_buttons.items():
            selected=value==active
            button.configure(
                bg=self._c('purple') if selected else self._c('surface_alt'),
                fg='white' if selected else self._c('text'),
                activebackground=self._c('purple_dark') if selected else self._c('border'),
                activeforeground='white'
            )

    def _refresh_orders(self):
        if not getattr(self,'order_table',None):return
        self.order_table.delete(*self.order_table.get_children())
        group=self.order_view.get() if getattr(self,'order_view',None) else 'all'
        rows=self.core.orders.list(
            self.order_query.get().strip(),self.order_status.get(),
            self.order_sort_column,self.order_sort_descending,group=group)
        for r in rows:
            display=(r['display_status'] or r['status']).replace('_',' ').title()
            tag=(r['display_status'] or r['status'])
            self.order_table.insert(
                '','end',iid=r['id'],
                values=(r['order_number'],r['customer_name'],display,r['due_at'] or '—',
                        '$%.2f'%(r['total_cents']/100.0)),
                tags=(tag,))
        if getattr(self,'order_count',None):
            label='active order' if group=='active' else 'history record'
            self.order_count.configure(text='%d %s%s'%(len(rows),label,'' if len(rows)==1 else 's'))
        if rows:self.order_table.selection_set(rows[0]['id'])
        self._order_dossier()

    def _selected_order_id(self):
        sel=self.order_table.selection() if getattr(self,'order_table',None) else ()
        if not sel:messagebox.showinfo('Orders','Select an order first.');return None
        return sel[0]

    def _order_dossier(self):
        panel=getattr(self,'order_detail_panel',None)
        if not panel:return
        for child in panel.winfo_children():child.destroy()
        oid=self._selected_order_id() if self.order_table.selection() else None
        if not oid:return
        d=self.core.orders.dossier(oid);o=d['order'];f=d['fulfillment']
        tk.Label(panel,text=o['order_number'],bg=self._c('surface'),fg=self._c('text'),font=('Segoe UI',16,'bold')).pack(anchor='w')
        tk.Label(panel,text='%s • %s'%(o['customer_name'],o['status'].title()),bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',pady=(2,8))
        lifecycle=tk.Frame(panel,bg=self._c('surface'));lifecycle.pack(fill='x',pady=(0,10))
        status=str(o['status'] or 'new').lower()
        fstatus=str(f['status'] if f else '').lower()
        steps=[('Accepted',True),
               ('Production',status not in ('new','cancelled')),
               ('QC',status in ('qc','ready','shipped','completed') or d['completed_jobs']>=d['total_jobs']>0),
               ('Packing',status in ('ready','shipped','completed')),
               ('Shipped',status in ('shipped','completed') or fstatus in ('shipped','delivered','picked_up'))]
        for label,done in steps:
            tk.Label(lifecycle,text=('✓ ' if done else '○ ')+label,bg=self._c('surface'),
                     fg=self._c('green') if done else self._c('muted'),font=('Segoe UI',8,'bold')).pack(side='left',padx=(0,9))
        box=tk.Frame(panel,bg=self._c('surface_alt'));box.pack(fill='x',pady=(0,10))
        tk.Label(box,text='NEXT ACTION',bg=self._c('surface_alt'),fg=self._c('muted'),font=('Segoe UI',8,'bold')).pack(anchor='w',padx=10,pady=(8,1))
        tk.Label(box,text=d['next_action'],bg=self._c('surface_alt'),fg=self._c('text'),font=('Segoe UI',11,'bold')).pack(anchor='w',padx=10,pady=(0,8))
        summary='Production %d/%d   •   QC %d/%d   •   Paid $%.2f   •   %s'%(d['completed_jobs'],d['total_jobs'],d['qc_passed'],d['qc_total'],d['paid_cents']/100.0,(f['status'].replace('_',' ').title() if f else 'Fulfillment not set'))
        tk.Label(panel,text=summary,bg=self._c('surface'),fg=self._c('muted'),wraplength=380,justify='left').pack(anchor='w',pady=(0,10))
        nb=ttk.Notebook(panel);nb.pack(fill='both',expand=True)

        items_tab=tk.Frame(nb,bg=self._c('surface'));nb.add(items_tab,text='Items')
        if d['items']:
            for item in d['items']:
                line=tk.Frame(items_tab,bg=self._c('surface_alt'));line.pack(fill='x',padx=8,pady=3)
                name=item['product_name'] or item['description'] or 'Custom item'
                qty=int(item['quantity'] or 1);material=(' %s %s'%(item['material'] or '',item['color'] or '')).strip()
                tk.Label(line,text='%s ×%d'%(name,qty),bg=self._c('surface_alt'),fg=self._c('text'),font=('Segoe UI',8,'bold'),anchor='w').pack(fill='x',padx=8,pady=(5,0))
                tk.Label(line,text='%s  •  $%.2f each'%(material or 'Material not set',(item['unit_price_cents'] or 0)/100.0),bg=self._c('surface_alt'),fg=self._c('muted'),font=('Segoe UI',8),anchor='w').pack(fill='x',padx=8,pady=(0,5))
        else:tk.Label(items_tab,text='No quoted line items.',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=10,pady=10)

        prod_tab=tk.Frame(nb,bg=self._c('surface'));nb.add(prod_tab,text='Production')
        if d['jobs']:
            for job in d['jobs']:
                line=tk.Frame(prod_tab,bg=self._c('surface_alt'));line.pack(fill='x',padx=8,pady=3)
                mins=int(job['actual_minutes'] or job['estimated_minutes'] or 0)
                tk.Label(line,text='%s • %s'%(job['product_name'],job['status'].replace('_',' ').title()),bg=self._c('surface_alt'),fg=self._c('text'),font=('Segoe UI',8,'bold'),anchor='w').pack(fill='x',padx=8,pady=(5,0))
                tk.Label(line,text='%s • %s • %s'%(job['printer_name'],('%dh %02dm'%(mins//60,mins%60)) if mins else 'time unknown',('%.0fg'%(job['actual_filament_g'] or job['estimated_filament_g'])) if (job['actual_filament_g'] or job['estimated_filament_g']) else 'filament unknown'),bg=self._c('surface_alt'),fg=self._c('muted'),font=('Segoe UI',8),anchor='w').pack(fill='x',padx=8,pady=(0,5))
        else:tk.Label(prod_tab,text='No production jobs yet.',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=10,pady=10)

        qc_tab=tk.Frame(nb,bg=self._c('surface'));nb.add(qc_tab,text='QC')
        if d['qc']:
            for q in d['qc']:
                line=tk.Frame(qc_tab,bg=self._c('surface_alt'));line.pack(fill='x',padx=8,pady=3)
                color=self._c('green') if q['status']=='passed' else self._c('orange') if q['status']=='pending' else self._c('red')
                tk.Label(line,text='%s • %s'%(q['product_name'],q['status'].replace('_',' ').title()),bg=self._c('surface_alt'),fg=color,font=('Segoe UI',8,'bold'),anchor='w').pack(fill='x',padx=8,pady=(5,0))
                tk.Label(line,text=q['notes'] or 'No inspection notes.',bg=self._c('surface_alt'),fg=self._c('muted'),font=('Segoe UI',8),anchor='w',wraplength=340,justify='left').pack(fill='x',padx=8,pady=(0,5))
        else:tk.Label(qc_tab,text='QC records will appear after completed prints.',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=10,pady=10)

        bill_tab=tk.Frame(nb,bg=self._c('surface'));nb.add(bill_tab,text='Billing')
        if d['invoices']:
            for inv in d['invoices']:
                line=tk.Frame(bill_tab,bg=self._c('surface_alt'));line.pack(fill='x',padx=8,pady=3)
                tk.Label(line,text='%s • %s'%(inv['invoice_number'],inv['status'].title()),bg=self._c('surface_alt'),fg=self._c('text'),font=('Segoe UI',8,'bold'),anchor='w').pack(fill='x',padx=8,pady=(5,0))
                tk.Label(line,text='Total $%.2f • Paid $%.2f • Balance $%.2f'%(inv['total_cents']/100.0,inv['paid_cents']/100.0,inv['balance_cents']/100.0),bg=self._c('surface_alt'),fg=self._c('muted'),font=('Segoe UI',8),anchor='w').pack(fill='x',padx=8,pady=(0,5))
            if d['payments']:
                tk.Label(bill_tab,text='Recent payments',bg=self._c('surface'),fg=self._c('muted'),font=('Segoe UI',8,'bold')).pack(anchor='w',padx=10,pady=(8,2))
                for pay in d['payments'][:5]:
                    tk.Label(bill_tab,text='%s • $%.2f • %s'%(str(pay['paid_at'])[:16],pay['amount_cents']/100.0,pay['method'] or 'Payment'),bg=self._c('surface'),fg=self._c('text'),font=('Segoe UI',8),anchor='w').pack(fill='x',padx=10,pady=1)
        else:tk.Label(bill_tab,text='No invoice yet.',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=10,pady=10)

        ft=tk.Frame(nb,bg=self._c('surface'));nb.add(ft,text='Fulfillment')
        if f:
            dims=' × '.join('%g'%x for x in (f['package_length_in'],f['package_width_in'],f['package_height_in']) if x is not None)
            text='%s • %s\nCarrier: %s\nTracking: %s\nPackage: %s%s\nDestination: %s'%(
                f['method'].title(),f['status'].replace('_',' ').title(),f['carrier'] or '—',
                f['tracking_number'] or '—',
                ('%.1f oz'%f['package_weight_oz']) if f['package_weight_oz'] is not None else '—',
                (' • '+dims+' in') if dims else '',f['destination'] or '—')
        else:text='No fulfillment method set.'
        tk.Label(ft,text=text,bg=self._c('surface'),fg=self._c('text'),justify='left',wraplength=360).pack(anchor='w',padx=10,pady=12)
        self._button(ft,'Edit Fulfillment',self._order_fulfillment,True).pack(anchor='w',padx=10)

        updates=tk.Frame(nb,bg=self._c('surface'));nb.add(updates,text='Customer Updates')
        history=self.core.customer_updates.history(oid)
        suggested=self.core.customer_updates.generate(oid)
        tk.Label(updates,text='Suggested now: '+suggested['subject'],bg=self._c('surface'),fg=self._c('text'),
                 wraplength=350,justify='left',font=('Segoe UI',9,'bold')).pack(anchor='w',padx=10,pady=(10,3))
        tk.Label(updates,text=suggested['body'],bg=self._c('surface'),fg=self._c('muted'),
                 wraplength=350,justify='left').pack(anchor='w',padx=10)
        self._button(updates,'Create Customer Update',self._order_customer_update,True).pack(anchor='w',padx=10,pady=10)
        if history:
            tk.Label(updates,text='Recent communication',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=10,pady=(4,2))
            for msg in history[:5]:
                line=tk.Frame(updates,bg=self._c('surface_alt'));line.pack(fill='x',padx=10,pady=3)
                tk.Label(line,text=(msg['subject'] or msg['message_type']).strip(),bg=self._c('surface_alt'),
                         fg=self._c('text'),font=('Segoe UI',8,'bold'),wraplength=240,justify='left').pack(anchor='w',padx=8,pady=(5,0))
                tk.Label(line,text='%s • %s'%(msg['status'].title(),str(msg['sent_at'] or msg['created_at'])[:16]),
                         bg=self._c('surface_alt'),fg=self._c('muted'),font=('Segoe UI',8)).pack(anchor='w',padx=8,pady=(0,5))
        else:
            tk.Label(updates,text='No customer updates logged yet.',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=10,pady=6)

    def _order_create_jobs(self):
        oid=self._selected_order_id()
        if not oid:return
        try:
            created=self.core.production.create_jobs_from_order(oid);self._refresh_orders()
            messagebox.showinfo('Production','Created %d production job%s.'%(len(created),'' if len(created)==1 else 's'))
        except Exception as exc:messagebox.showerror('Production',str(exc))

    def _order_next_action(self):
        oid=self._selected_order_id()
        if not oid:return
        action=self.core.orders.dossier(oid)['next_action']
        if action=='Create production jobs':return self._order_create_jobs()
        if action=='Finish production':return self.show_page('Production')
        if action=='Complete QC':return self.show_page('QC')
        if action=='Create invoice':return self._order_create_invoice()
        if action=='Collect payment':return self.show_page('Invoices')
        if action in ('Set fulfillment','Complete fulfillment'):return self._order_fulfillment()
        if action=='Complete order':self.core.orders.set_status(oid,'completed');self._refresh_orders();return
        messagebox.showinfo('Order',action)

    def _order_fulfillment(self):
        oid=self._selected_order_id()
        if not oid:return
        current=self.core.fulfillment.get_for_order(oid)
        win=tk.Toplevel(self);win.title('Fulfillment');win.geometry('620x700');win.configure(bg=self._c('bg'));win.transient(self);win.grab_set()
        body=self._card(win,'Pickup / Shipping');body.pack(fill='both',expand=True,padx=16,pady=16)
        method=tk.StringVar(value=current['method'] if current else 'pickup');status=tk.StringVar(value=current['status'] if current else 'pending')
        carrier=tk.StringVar(value=(current['carrier'] if current else '') or '');tracking=tk.StringVar(value=(current['tracking_number'] if current else '') or '')
        destination=tk.StringVar(value=(current['destination'] if current else '') or '');cost=tk.StringVar(value='%.2f'%((current['shipping_cost_cents'] if current else 0)/100.0))
        weight=tk.StringVar(value='' if not current or current['package_weight_oz'] is None else '%g'%current['package_weight_oz'])
        length=tk.StringVar(value='' if not current or current['package_length_in'] is None else '%g'%current['package_length_in'])
        width=tk.StringVar(value='' if not current or current['package_width_in'] is None else '%g'%current['package_width_in'])
        height=tk.StringVar(value='' if not current or current['package_height_in'] is None else '%g'%current['package_height_in'])
        for label,var,vals in [('Method',method,['pickup','shipping']),('Status',status,['pending','ready_for_pickup','picked_up','packed','shipped','delivered'])]:
            tk.Label(body,text=label,bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(8,2))
            ttk.Combobox(body,textvariable=var,values=vals,state='readonly').pack(fill='x',padx=16)
        def use_packaging_supply():
            items=self.core.supplies.list()
            if not items:return messagebox.showinfo('Packaging','No packaging/supply items exist yet. Add them under Filament → Packaging & Supplies.',parent=win)
            options={('%s — %g %s available'%(r['name'],r['quantity'],r['unit'])):r for r in items}
            pick=tk.Toplevel(win);pick.title('Use Packaging Supply');pick.geometry('480x280');pick.configure(bg=self._c('bg'));pick.transient(win);pick.grab_set()
            box=self._card(pick,'Packaging Usage');box.pack(fill='both',expand=True,padx=14,pady=14)
            choice=tk.StringVar(value=next(iter(options)));qty=tk.StringVar(value='1')
            tk.Label(box,text='Supply',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=14,pady=(10,3))
            ttk.Combobox(box,textvariable=choice,values=list(options),state='readonly').pack(fill='x',padx=14)
            tk.Label(box,text='Quantity Used',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=14,pady=(10,3))
            self._entry(box,qty,20).pack(anchor='w',padx=14,ipady=5)
            def save_usage():
                try:
                    row=options[choice.get()];amount=float(qty.get() or 0)
                    if amount<=0:raise ValueError('Quantity must be greater than zero.')
                    if amount>float(row['quantity'] or 0):raise ValueError('Not enough supply inventory remains.')
                    self.core.supplies.adjust(row['id'],-amount,'order',oid,'Packaging used for order')
                    self.core.operations.log('supply.used','Packaging used',
                        '%s × %g'%(row['name'],amount),'Orders',oid)
                    pick.destroy()
                except Exception as exc:messagebox.showerror('Packaging',str(exc),parent=pick)
            self._button(box,'Use Supply',save_usage,True).pack(side='right',padx=14,pady=14)
            self._button(box,'Cancel',pick.destroy).pack(side='right',pady=14)

        self._button(body,'Use Packaging Supply',use_packaging_supply).pack(anchor='e',padx=14,pady=(4,2))
        for label,var in [('Carrier',carrier),('Tracking Number',tracking),('Destination',destination),
                          ('Package Weight (oz)',weight),('Length (in)',length),('Width (in)',width),('Height (in)',height),
                          ('Shipping Cost ($)',cost)]:
            tk.Label(body,text=label,bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(8,2))
            self._entry(body,var,36).pack(fill='x',padx=16,ipady=5)
        def save():
            try:
                self.core.fulfillment.save(
                    oid,method.get(),status.get(),carrier.get(),tracking.get(),
                    float(weight.get()) if weight.get().strip() else None,
                    int(round(float(cost.get() or 0)*100)),destination.get(),
                    length_in=float(length.get()) if length.get().strip() else None,
                    width_in=float(width.get()) if width.get().strip() else None,
                    height_in=float(height.get()) if height.get().strip() else None)
                try:
                    self.core.operations.log('fulfillment','Fulfillment updated',
                        '%s • %s'%(method.get(),status.get()),'Orders',oid)
                except Exception:
                    pass
                win.destroy();self._refresh_orders()
            except Exception as exc:
                messagebox.showerror('Fulfillment',str(exc),parent=win)
        self._button(body,'Save Fulfillment',save,True).pack(anchor='e',padx=16,pady=16)

    def _order_customer_update(self):
        oid=self._selected_order_id()
        if not oid:return
        try:
            suggested=self.core.customer_updates.generate(oid)
            dossier=self.core.orders.dossier(oid)
        except Exception as exc:
            return messagebox.showerror('Customer Update',str(exc))

        win=tk.Toplevel(self);win.title('Customer Update — '+dossier['order']['order_number'])
        win.geometry('650x650');win.minsize(580,520);win.configure(bg=self._c('bg'));win.transient(self);win.grab_set()
        body=self._card(win,'Customer Communication');body.pack(fill='both',expand=True,padx=16,pady=16)

        kind=tk.StringVar(value=suggested['message_type'])
        subject=tk.StringVar(value=suggested['subject'])
        tk.Label(body,text='Update Type',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(8,2))
        types=['order_received','production','printing','qc_passed','invoice_ready','payment_received',
               'ready_for_pickup','shipped','delivered','picked_up','cancelled']
        cb=ttk.Combobox(body,textvariable=kind,values=types,state='readonly');cb.pack(fill='x',padx=16)

        tk.Label(body,text='Subject',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(10,2))
        self._entry(body,subject,45).pack(fill='x',padx=16,ipady=5)

        tk.Label(body,text='Message',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(10,2))
        message=tk.Text(body,height=14,bg=self._c('surface_alt'),fg=self._c('text'),insertbackground='white',bd=0,wrap='word')
        message.insert('1.0',suggested['body']);message.pack(fill='both',expand=True,padx=16)

        target=tk.Label(body,text='Email: %s    Phone: %s'%(suggested['email'] or '—',suggested['phone'] or '—'),
                        bg=self._c('surface'),fg=self._c('muted'),wraplength=570,justify='left')
        target.pack(anchor='w',padx=16,pady=(8,0))

        def regenerate(*_):
            try:
                data=self.core.customer_updates.generate(oid,kind.get())
                subject.set(data['subject']);message.delete('1.0','end');message.insert('1.0',data['body'])
            except Exception as exc:messagebox.showerror('Customer Update',str(exc),parent=win)
        cb.bind('<<ComboboxSelected>>',regenerate)

        def save(status='draft',channel='manual'):
            try:
                mid=self.core.customer_updates.save(
                    oid,kind.get(),subject.get().strip(),message.get('1.0','end').strip(),channel,status
                )
                return mid
            except Exception as exc:
                messagebox.showerror('Customer Update',str(exc),parent=win);return None

        def copy_message():
            bodytext=message.get('1.0','end').strip()
            self.clipboard_clear();self.clipboard_append(bodytext);self.update()
            mid=save('sent','clipboard')
            if mid:
                messagebox.showinfo('Copied','Message copied and logged as sent via clipboard.',parent=win)
                win.destroy();self._refresh_orders()

        def email_message():
            email=suggested['email']
            if not email:
                return messagebox.showwarning('Email','This customer does not have an email address saved.',parent=win)
            import urllib.parse,webbrowser
            url='mailto:%s?subject=%s&body=%s'%(urllib.parse.quote(email),
                urllib.parse.quote(subject.get().strip()),urllib.parse.quote(message.get('1.0','end').strip()))
            webbrowser.open(url)
            mid=save('sent','email')
            if mid:
                win.destroy();self._refresh_orders()

        buttons=tk.Frame(body,bg=self._c('surface'));buttons.pack(fill='x',padx=16,pady=14)
        self._button(buttons,'Copy & Log Sent',copy_message,True).pack(side='right')
        self._button(buttons,'Email',email_message).pack(side='right',padx=7)
        self._button(buttons,'Save Draft',lambda:(save('draft','manual'),win.destroy(),self._refresh_orders())).pack(side='right')

    def _order_create_invoice(self):
        oid=self._selected_order_id()
        if not oid:return
        try:
            iid,new=self.core.invoices.create_from_order(oid);self.show_page("Invoices")
            if getattr(self,"invoice_table",None):self.invoice_table.selection_set(iid);self.invoice_table.see(iid)
        except Exception as exc:messagebox.showerror("Invoice",str(exc))

    def _set_order_status(self,status):
        oid=self._selected_order_id()
        if not oid:return
        try:
            old=self.core.orders.get(oid)['status']
        except Exception:old=None
        self.core.orders.set_status(oid,status)
        try:self.core.operations.log('order.status','Order status changed','%s → %s'%(old,status),'Orders',oid,'order_status',{'order_id':oid,'old_status':old})
        except Exception:pass
        self._refresh_orders()

    def _view_order(self):
        oid=self._selected_order_id()
        if not oid:return
        o,items=self.core.orders.get(oid);self._document_view('Order '+o['order_number'],o['order_number'],o['customer_name'],o['status'],o['total_cents'],items,o['due_at'])

    def _document_view(self,title,number,customer,status,total_cents,items,date_value):
        win=tk.Toplevel(self);win.title(title);win.geometry('780x560');win.configure(bg=self._c('bg'))
        tk.Label(win,text=number+'  •  '+status.title(),bg=self._c('bg'),fg=self._c('text'),font=('Segoe UI',18,'bold')).pack(anchor='w',padx=18,pady=(18,4))
        tk.Label(win,text=customer+'   Date: '+str(date_value or 'Not set'),bg=self._c('bg'),fg=self._c('muted')).pack(anchor='w',padx=18)
        t=ttk.Treeview(win,columns=('item','qty','material','time','grams','price'),show='headings',style='Dark.Treeview')
        for c,l,w in [('item','Item',285),('qty','Qty',55),('material','Material / Color',150),('time','Time',70),('grams','Filament',70),('price','Line Total',95)]:
            t.heading(c,text=l);t.column(c,width=w,anchor='w')
        for i in items:t.insert('','end',values=(i['description'],i['quantity'],('%s %s'%(i['material'] or '',i['color'] or '')).strip(),'%.1fh'%((i['estimated_minutes'] or 0)/60.0),'%.0fg'%(i['estimated_filament_g'] or 0),'$%.2f'%(i['quantity']*i['unit_price_cents']/100.0)),tags=('body',))
        t.pack(fill='both',expand=True,padx=18,pady=14)
