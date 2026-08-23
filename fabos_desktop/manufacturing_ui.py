import tkinter as tk,os,math,json
from tkinter import ttk,messagebox,filedialog
from pathlib import Path

class ManufacturingMixin:
 def _build_design_vault_page(self):
  self.core.design_vault.ensure_all()
  bar=tk.Frame(self.content,bg=self._c('bg'));bar.pack(fill='x',pady=(4,10))
  self._button(bar,'Import File',self._vault_import,True).pack(side='left')
  self._button(bar,'New Version',self._vault_version).pack(side='left',padx=7)
  self._button(bar,'Print Profile',self._vault_profile).pack(side='left')
  self._button(bar,'Open Selected File',self._vault_open_asset).pack(side='left',padx=7)

  filters=self._card(self.content);filters.pack(fill='x',pady=(0,10))
  row=tk.Frame(filters,bg=self._c('surface'));row.pack(fill='x',padx=14,pady=10)
  tk.Label(row,text='Search',bg=self._c('surface'),fg=self._c('muted')).pack(side='left')
  self.vault_query=tk.StringVar()
  e=self._entry(row,self.vault_query,30);e.pack(side='left',padx=8,ipady=6)
  e.bind('<KeyRelease>',lambda _e:self._vault_refresh())
  self.vault_count=tk.Label(row,text='',bg=self._c('surface'),fg=self._c('muted'))
  self.vault_count.pack(side='right')

  split=tk.PanedWindow(self.content,orient='horizontal',bg=self._c('bg'),sashwidth=6,bd=0)
  split.pack(fill='both',expand=True)
  left=self._card(split,'Design Vault');right=self._card(split,'Design Workspace')
  split.add(left,minsize=500);split.add(right,minsize=520)

  self.vault_table=ttk.Treeview(left,columns=('name','sku','cat','ver','files'),show='headings',style='Dark.Treeview')
  for c,t,w in [('name','Design',225),('sku','SKU',90),('cat','Category',120),('ver','Version',70),('files','Files',55)]:
   self.vault_table.heading(c,text=t);self.vault_table.column(c,width=w,anchor='w')
  sy=ttk.Scrollbar(left,orient='vertical',command=self.vault_table.yview)
  self.vault_table.configure(yscrollcommand=sy.set)
  self.vault_table.pack(side='left',fill='both',expand=True,padx=(12,0),pady=(0,12))
  sy.pack(side='right',fill='y',padx=(0,12),pady=(0,12))
  self.vault_table.bind('<<TreeviewSelect>>',lambda _e:self._vault_detail())

  self.vault_panel=tk.Frame(right,bg=self._c('surface'))
  self.vault_panel.pack(fill='both',expand=True,padx=14,pady=(0,14))
  self._vault_refresh()

 def _vault_refresh(self):
  self.vault_table.delete(*self.vault_table.get_children())
  rows=self.core.design_vault.list(self.vault_query.get() if getattr(self,'vault_query',None) else '')
  for r in rows:
   self.vault_table.insert('','end',iid=r['id'],
      values=(r['name'],r['sku'],r['category'],'v%d'%r['current_version'],r['asset_count']),tags=('body',))
  if getattr(self,'vault_count',None):self.vault_count.config(text='%d design%s'%(len(rows),'' if len(rows)==1 else 's'))
  if rows:
   self.vault_table.selection_set(rows[0]['id']);self.vault_detail_select(rows[0]['id'])
  else:self._vault_detail()

 def vault_detail_select(self,did):
  try:self.vault_table.selection_set(did);self.vault_table.see(did)
  except Exception:return
  self._vault_detail()

 def _vdid(self):
  s=self.vault_table.selection() if getattr(self,'vault_table',None) else ()
  return s[0] if s else None

 def _vault_detail(self):
  for x in self.vault_panel.winfo_children():x.destroy()
  did=self._vdid()
  if not did:
   tk.Label(self.vault_panel,text='Select a design to inspect files, versions and print history.',
            bg=self._c('surface'),fg=self._c('muted'),wraplength=450,justify='left').pack(anchor='w',pady=15)
   return
  d=self.core.design_vault.get(did);assets=self.core.design_vault.assets(did)
  versions=self.core.design_vault.versions(did);history=self.core.design_vault.production_history(did)
  model=self.core.design_vault.primary_model_asset(did)

  head=tk.Frame(self.vault_panel,bg=self._c('surface'));head.pack(fill='x')
  tk.Label(head,text=d['name'],bg=self._c('surface'),fg=self._c('text'),
           font=('Segoe UI',16,'bold'),wraplength=380,justify='left').pack(side='left',anchor='w')
  tk.Label(head,text='v%d'%d['current_version'],bg=self._c('purple'),fg='white',
           font=('Segoe UI',9,'bold'),padx=9,pady=4).pack(side='right')

  nb=ttk.Notebook(self.vault_panel);nb.pack(fill='both',expand=True,pady=(10,0))
  overview=tk.Frame(nb,bg=self._c('surface'));files=tk.Frame(nb,bg=self._c('surface'))
  versions_tab=tk.Frame(nb,bg=self._c('surface'));profile_tab=tk.Frame(nb,bg=self._c('surface'))
  history_tab=tk.Frame(nb,bg=self._c('surface'))
  nb.add(overview,text='Overview');nb.add(files,text='Files');nb.add(versions_tab,text='Versions')
  nb.add(profile_tab,text='Print Profile');nb.add(history_tab,text='History')

  # Overview with actual STL wireframe when possible.
  self.vault_preview=tk.Canvas(overview,height=285,bg=self._c('surface_alt'),highlightthickness=0)
  self.vault_preview.pack(fill='x',padx=8,pady=8)
  if model and model['kind']=='STL':
   self._draw_stl_preview(self.vault_preview,model['stored_path'])
   fit=(model['width_mm'] is not None and model['width_mm']<=245 and model['depth_mm']<=245 and model['height_mm']<=260)
   details='%.1f × %.1f × %.1f mm   •   %s triangles   •   %s Vyper'%(
       model['width_mm'] or 0,model['depth_mm'] or 0,model['height_mm'] or 0,
       model['triangle_count'] or '—','Fits' if fit else 'EXCEEDS')
  elif model:
   self.vault_preview.create_text(250,130,text='%s MODEL\n%s'%(model['kind'],model['original_name']),
                                  fill=self._c('text'),font=('Segoe UI',12,'bold'),justify='center')
   details='Metadata preview is currently strongest for STL files.'
  else:
   self.vault_preview.create_text(250,130,text='No 3D model file imported yet.',
                                  fill=self._c('muted'),font=('Segoe UI',11))
   details='Import STL, 3MF or STEP files into the current design version.'
  tk.Label(overview,text=details,bg=self._c('surface'),fg=self._c('muted'),
           wraplength=470,justify='left').pack(anchor='w',padx=8,pady=(0,10))

  # Files tab.
  self.vault_assets=ttk.Treeview(files,columns=('type','file','ver','size'),show='headings',style='Dark.Treeview')
  for c,t,w in [('type','Type',65),('file','File',245),('ver','Ver.',55),('size','Size',80)]:
   self.vault_assets.heading(c,text=t);self.vault_assets.column(c,width=w,anchor='w')
  for a in assets:
   self.vault_assets.insert('','end',iid=a['id'],
      values=(a['kind'],a['original_name'],'v%s'%(a['version'] or '?'),self._human_bytes(a['bytes'])),tags=('body',))
  self.vault_assets.pack(fill='both',expand=True,padx=8,pady=8)
  self.vault_assets.bind('<Double-1>',lambda _e:self._vault_open_asset())

  # Versions tab.
  vt=ttk.Treeview(versions_tab,columns=('version','label','created'),show='headings',style='Dark.Treeview')
  for c,t,w in [('version','Version',80),('label','Label',230),('created','Created',145)]:
   vt.heading(c,text=t);vt.column(c,width=w,anchor='w')
  for v in versions:vt.insert('','end',values=('v%d'%v['version'],v['label'] or '—',str(v['created_at'])[:16]),tags=('body',))
  vt.pack(fill='both',expand=True,padx=8,pady=8)

  # Profile tab.
  prof=self.core.design_vault.profile(did)
  if prof:
   rows=[('Profile',prof['name']),('Material',prof['material'] or '—'),
         ('Nozzle','%.2f mm'%prof['nozzle_mm']),('Layer Height','%.2f mm'%prof['layer_height_mm']),
         ('Infill','%.0f%%'%prof['infill_percent']),('Supports',prof['supports'] or '—'),
         ('PrusaSlicer Profile',prof['slicer_profile_path'] or '—')]
   for label,value in rows:
    line=tk.Frame(profile_tab,bg=self._c('surface'));line.pack(fill='x',padx=12,pady=5)
    tk.Label(line,text=label,bg=self._c('surface'),fg=self._c('muted'),width=18,anchor='w').pack(side='left')
    tk.Label(line,text=str(value),bg=self._c('surface'),fg=self._c('text'),anchor='w',wraplength=290,justify='left').pack(side='left',fill='x',expand=True)
  else:
   tk.Label(profile_tab,text='No manufacturing profile saved for this design.',
            bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=12,pady=15)
  self._button(profile_tab,'Edit Print Profile',self._vault_profile,True).pack(anchor='w',padx=12,pady=12)

  # History tab.
  ht=ttk.Treeview(history_tab,columns=('order','printer','status','est','actual','created'),show='headings',style='Dark.Treeview')
  for c,t,w in [('order','Order',95),('printer','Printer',130),('status','Status',85),
                ('est','Est.',70),('actual','Actual',70),('created','Created',125)]:
   ht.heading(c,text=t);ht.column(c,width=w,anchor='w')
  for h in history:
   ht.insert('','end',values=(h['order_number'],h['printer_name'],h['status'].title(),
       self._fmt_minutes(h['estimated_minutes']),self._fmt_minutes(h['actual_minutes']),str(h['created_at'])[:16]),tags=('body',))
  ht.pack(fill='both',expand=True,padx=8,pady=8)

 def _draw_stl_preview(self,canvas,path):
  try:
   meta=self.core.design_vault.stl_meta(path);verts=meta[4]
  except Exception:verts=[]
  canvas.delete('all');w=max(canvas.winfo_width(),500);h=285
  # build plate
  canvas.create_rectangle(55,35,w-55,h-35,outline=self._c('purple'),width=2)
  canvas.create_text(70,h-45,text='245 × 245 mm Vyper plate',fill=self._c('muted'),anchor='w',font=('Segoe UI',8))
  if not verts:
   canvas.create_text(w//2,h//2,text='STL geometry loaded, but no preview vertices were available.',
                      fill=self._c('muted'),font=('Segoe UI',10));return
  xs=[v[0] for v in verts];ys=[v[1] for v in verts];zs=[v[2] for v in verts]
  cx=(min(xs)+max(xs))/2;cy=(min(ys)+max(ys))/2;cz=(min(zs)+max(zs))/2
  # isometric projection
  pts=[]
  for x,y,z in verts:
   x-=cx;y-=cy;z-=cz
   px=(x-y)*0.866
   py=(x+y)*0.5-z
   pts.append((px,py))
  max_abs=max(max(abs(x) for x,y in pts),max(abs(y) for x,y in pts),1)
  scale=min((w-150)/(2*max_abs),(h-100)/(2*max_abs))*0.9
  ox=w/2;oy=h/2
  limit=min(len(pts)//3,1500)
  for i in range(limit):
   tri=pts[i*3:i*3+3]
   coords=[]
   for x,y in tri:coords.extend((ox+x*scale,oy-y*scale))
   coords.extend(coords[:2])
   canvas.create_line(*coords,fill='#a78bfa',width=1)

 def _vault_import(self):
  did=self._vdid()
  if not did:return
  fs=filedialog.askopenfilenames(filetypes=[
    ('Manufacturing files','*.stl *.3mf *.step *.stp *.gcode *.png *.jpg *.jpeg *.webp'),('All','*.*')])
  added=0
  for f in fs:
   try:added+=1 if self.core.design_vault.import_file(did,f) else 0
   except Exception as e:messagebox.showerror('Import',str(e))
  if fs:
   messagebox.showinfo('Design Vault','Imported %d new file(s). Duplicates were skipped.'%added)
   self._vault_refresh()

 def _vault_version(self):
  if self._vdid():self.core.design_vault.new_version(self._vdid());self._vault_refresh()

 def _vault_open_asset(self):
  if not getattr(self,'vault_assets',None) or not self.vault_assets.selection():return
  aid=self.vault_assets.selection()[0]
  a=next((x for x in self.core.design_vault.assets(self._vdid()) if x['id']==aid),None)
  if not a:return
  try:os.startfile(a['stored_path'])
  except Exception as e:messagebox.showerror('Open File',str(e))

 def _vault_profile(self):
  did=self._vdid()
  if not did:return
  current=self.core.design_vault.profile(did)
  win=tk.Toplevel(self);win.title('Print Profile');win.geometry('520x560');win.minsize(500,480)
  win.configure(bg=self._c('bg'));win.transient(self);win.grab_set()
  outer=tk.Frame(win,bg=self._c('bg'));outer.pack(fill='both',expand=True)
  canvas=tk.Canvas(outer,bg=self._c('bg'),highlightthickness=0);sb=ttk.Scrollbar(outer,orient='vertical',command=canvas.yview)
  body=self._card(canvas,'Anycubic Vyper / PrusaSlicer Profile')
  body.bind('<Configure>',lambda _e:canvas.configure(scrollregion=canvas.bbox('all')))
  canvas.create_window((0,0),window=body,anchor='nw',width=475);canvas.configure(yscrollcommand=sb.set)
  canvas.pack(side='left',fill='both',expand=True,padx=(12,0),pady=12);sb.pack(side='right',fill='y',padx=(0,12),pady=12)
  defaults={'Name':'Vyper Standard','Material':'PLA','Nozzle mm':'0.4','Layer height mm':'0.20','Infill %':'15','Supports':'As needed','PrusaSlicer profile path':''}
  if current:
   defaults.update({'Name':current['name'],'Material':current['material'] or '',
     'Nozzle mm':str(current['nozzle_mm']),'Layer height mm':str(current['layer_height_mm']),
     'Infill %':str(current['infill_percent']),'Supports':current['supports'] or '',
     'PrusaSlicer profile path':current['slicer_profile_path'] or ''})
  vals={}
  for lab,default in defaults.items():
   tk.Label(body,text=lab,bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(8,2))
   v=tk.StringVar(value=default);self._entry(body,v,40).pack(fill='x',padx=16,ipady=5);vals[lab]=v
  def save():
   try:
    self.core.design_vault.save_profile(did,vals['Name'].get(),vals['Material'].get(),vals['Nozzle mm'].get(),
       vals['Layer height mm'].get(),vals['Infill %'].get(),vals['Supports'].get(),vals['PrusaSlicer profile path'].get())
    win.destroy();self._vault_detail()
   except Exception as e:messagebox.showerror('Profile',str(e))
  self._button(body,'Save Profile',save,True).pack(anchor='e',padx=16,pady=16)

 @staticmethod
 def _human_bytes(value):
  value=float(value or 0)
  for unit in ('B','KB','MB','GB'):
   if value<1024:return ('%.1f %s'%(value,unit)) if unit!='B' else ('%d B'%value)
   value/=1024
  return '%.1f TB'%value

 @staticmethod
 def _fmt_minutes(value):
  if not value:return '—'
  value=int(value);return '%dh %02dm'%(value//60,value%60)

 def _build_qc_page(self):
  try:self.core.manufacturing.reconcile_qc()
  except Exception:pass
  bar=tk.Frame(self.content,bg=self._c('bg'));bar.pack(fill='x',pady=(4,10))
  self._button(bar,'Inspect / Edit',self._qc_inspect,True).pack(side='left')
  self._button(bar,'Mark Rework',lambda:self._qc_quick_status('rework')).pack(side='left',padx=7)
  self._button(bar,'Refresh',self._qc_refresh).pack(side='left')

  filters=self._card(self.content);filters.pack(fill='x',pady=(0,10))
  row=tk.Frame(filters,bg=self._c('surface'));row.pack(fill='x',padx=14,pady=10)
  tk.Label(row,text='Search',bg=self._c('surface'),fg=self._c('muted')).pack(side='left')
  self.qc_query=tk.StringVar()
  e=self._entry(row,self.qc_query,28);e.pack(side='left',padx=(7,16),ipady=6)
  e.bind('<KeyRelease>',lambda _e:self._qc_refresh())
  tk.Label(row,text='Status',bg=self._c('surface'),fg=self._c('muted')).pack(side='left')
  self.qc_status=tk.StringVar(value='All')
  cb=ttk.Combobox(row,textvariable=self.qc_status,values=['All','pending','rework','passed'],state='readonly',width=14)
  cb.pack(side='left',padx=7);cb.bind('<<ComboboxSelected>>',lambda _e:self._qc_refresh())
  self.qc_count=tk.Label(row,text='',bg=self._c('surface'),fg=self._c('muted'));self.qc_count.pack(side='right')

  card=self._card(self.content,'Quality Control Queue');card.pack(fill='both',expand=True)
  cols=('order','customer','product','status','created')
  self.qc_table=ttk.Treeview(card,columns=cols,show='headings',style='Dark.Treeview',selectmode='browse')
  labels={'order':'Order','customer':'Customer','product':'Product','status':'Status','created':'Created'}
  widths={'order':115,'customer':190,'product':260,'status':95,'created':135}
  for c in cols:
   self.qc_table.heading(c,text=labels[c],command=lambda x=c:self._qc_sort(x))
   self.qc_table.column(c,width=widths[c],anchor='w',stretch=(c in ('customer','product')))
  self.qc_table.tag_configure('pending',foreground=self._c('orange'),background=self._c('surface'))
  self.qc_table.tag_configure('rework',foreground=self._c('red'),background=self._c('surface'))
  self.qc_table.tag_configure('passed',foreground=self._c('green'),background=self._c('surface'))
  sy=ttk.Scrollbar(card,orient='vertical',command=self.qc_table.yview)
  self.qc_table.configure(yscrollcommand=sy.set)
  self.qc_table.pack(side='left',fill='both',expand=True,padx=(12,0),pady=(0,12))
  tk.Label(card,text='QC inspections are created automatically from completed order prints.',bg=self._c('surface'),fg=self._c('muted')).pack(side='bottom',anchor='w',padx=12,pady=(0,6))
  sy.pack(side='right',fill='y',padx=(0,12),pady=(0,12))
  self.qc_table.bind('<Double-1>',lambda _e:self._qc_inspect())
  self.qc_sort_column='created';self.qc_sort_desc=True
  self._qc_refresh()

 def _qc_sort(self,column):
  if self.qc_sort_column==column:self.qc_sort_desc=not self.qc_sort_desc
  else:self.qc_sort_column=column;self.qc_sort_desc=False
  self._qc_refresh()

 def _qc_rows(self):
  rows=list(self.core.manufacturing.qc_list())
  query=(self.qc_query.get().strip().lower() if getattr(self,'qc_query',None) else '')
  status=(self.qc_status.get() if getattr(self,'qc_status',None) else 'All')
  if query:
   rows=[r for r in rows if query in str(r['order_number'] or '').lower()
         or query in str(r['customer_name'] or '').lower()
         or query in str(r['product_name'] or '').lower()]
  if status!='All':rows=[r for r in rows if r['status']==status]
  keymap={
   'order':lambda r:str(r['order_number'] or '').lower(),
   'customer':lambda r:str(r['customer_name'] or '').lower(),
   'product':lambda r:str(r['product_name'] or '').lower(),
   'status':lambda r:str(r['status'] or '').lower(),
   'created':lambda r:str(r['created_at'] or '')
  }
  rows.sort(key=keymap.get(self.qc_sort_column,keymap['created']),reverse=self.qc_sort_desc)
  return rows

 def _qc_refresh(self):
  if not getattr(self,'qc_table',None):return
  try:self.core.manufacturing.reconcile_qc()
  except Exception:pass
  self.qc_table.delete(*self.qc_table.get_children())
  rows=self._qc_rows()
  for r in rows:
   self.qc_table.insert('','end',iid=r['id'],values=(
    r['order_number'],r['customer_name'],r['product_name'] or '—',
    r['status'].title(),str(r['created_at'])[:16]),tags=(r['status'],))
  arrow=' ▼' if self.qc_sort_desc else ' ▲'
  labels={'order':'Order','customer':'Customer','product':'Product','status':'Status','created':'Created'}
  for c,label in labels.items():
   self.qc_table.heading(c,text=label+(arrow if c==self.qc_sort_column else ''),command=lambda x=c:self._qc_sort(x))
  if getattr(self,'qc_count',None):self.qc_count.config(text='%d inspection%s'%(len(rows),'' if len(rows)==1 else 's'))

 def _selected_qc(self):
  s=self.qc_table.selection() if getattr(self,'qc_table',None) else ()
  if not s:messagebox.showinfo('QC','Select an inspection first.');return None
  return s[0]

 def _qc_quick_status(self,status):
  qid=self._selected_qc()
  if not qid:return
  r=next((x for x in self.core.manufacturing.qc_list() if x['id']==qid),None)
  if not r:return
  items=json.loads(r['checklist_json'] or '[]')
  self.core.manufacturing.qc_update(qid,items,r['notes'] or '',status)
  self._qc_refresh()

 def _qc_inspect(self):
  qid=self._selected_qc()
  if not qid:return
  r=next((x for x in self.core.manufacturing.qc_list() if x['id']==qid),None)
  if not r:return
  items=json.loads(r['checklist_json'] or '[]')

  win=tk.Toplevel(self);win.title('QC '+str(r['order_number']));win.geometry('720x700');win.minsize(620,560)
  win.configure(bg=self._c('bg'));win.transient(self);win.grab_set()
  outer=tk.Frame(win,bg=self._c('bg'));outer.pack(fill='both',expand=True)
  canvas=tk.Canvas(outer,bg=self._c('bg'),highlightthickness=0)
  scroll=ttk.Scrollbar(outer,orient='vertical',command=canvas.yview)
  body=self._card(canvas,'Quality Control — Editable Checklist')
  body.bind('<Configure>',lambda _e:canvas.configure(scrollregion=canvas.bbox('all')))
  canvas.create_window((0,0),window=body,anchor='nw',width=660)
  canvas.configure(yscrollcommand=scroll.set)
  canvas.pack(side='left',fill='both',expand=True,padx=(14,0),pady=14)
  scroll.pack(side='right',fill='y',padx=(0,14),pady=14)

  tk.Label(body,text='%s • %s'%(r['order_number'],r['product_name'] or 'Product'),
           bg=self._c('surface'),fg=self._c('text'),font=('Segoe UI',13,'bold')).pack(anchor='w',padx=16,pady=(4,2))
  tk.Label(body,text='Edit the checklist wording, add/remove checks, or save the inspection for later.',
           bg=self._c('surface'),fg=self._c('muted'),wraplength=600,justify='left').pack(anchor='w',padx=16,pady=(0,12))

  list_frame=tk.Frame(body,bg=self._c('surface'));list_frame.pack(fill='x',padx=16)
  rows=[]

  def rebuild():
   for child in list_frame.winfo_children():child.destroy()
   for index,rowdata in enumerate(rows):
    line=tk.Frame(list_frame,bg=self._c('surface'));line.pack(fill='x',pady=4)
    chk=tk.Checkbutton(line,variable=rowdata['checked'],bg=self._c('surface'),fg=self._c('text'),
       selectcolor=self._c('surface_alt'),activebackground=self._c('surface'),activeforeground=self._c('text'))
    chk.pack(side='left')
    ent=self._entry(line,rowdata['text'],45);ent.pack(side='left',fill='x',expand=True,ipady=5,padx=(4,6))
    self._button(line,'Remove',lambda i=index:remove_row(i)).pack(side='right')

  def remove_row(index):
   if 0<=index<len(rows):rows.pop(index);rebuild()

  def add_row(text='New inspection step',checked=False):
   rows.append({'text':tk.StringVar(value=text),'checked':tk.BooleanVar(value=checked)})
   rebuild()

  for item in items:
   add_row(item.get('text','Inspection step'),bool(item.get('checked',False)))

  self._button(body,'+ Add Inspection Step',lambda:add_row()).pack(anchor='w',padx=16,pady=(10,5))

  tk.Label(body,text='Notes',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(12,3))
  notes=tk.Text(body,height=7,bg=self._c('surface_alt'),fg=self._c('text'),insertbackground='white',bd=0)
  notes.insert('1.0',r['notes'] or '')
  notes.pack(fill='x',padx=16)

  status_var=tk.StringVar(value=r['status'] if r['status'] in ('pending','rework','passed') else 'pending')
  tk.Label(body,text='Inspection Status',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(12,3))
  ttk.Combobox(body,textvariable=status_var,values=['pending','rework','passed'],state='readonly').pack(fill='x',padx=16)

  def collect():
   result=[]
   for rowdata in rows:
    text=rowdata['text'].get().strip()
    if text:result.append({'text':text,'checked':bool(rowdata['checked'].get())})
   return result

  def save(status=None):
   updated=collect()
   chosen=status or status_var.get()
   if chosen=='passed' and (not updated or not all(x['checked'] for x in updated)):
    return messagebox.showwarning('QC','Every remaining checklist item must be checked before passing QC.',parent=win)
   try:
    self.core.manufacturing.qc_update(qid,updated,notes.get('1.0','end').strip(),chosen)
    win.destroy();self._qc_refresh()
   except Exception as exc:messagebox.showerror('QC',str(exc),parent=win)

  buttons=tk.Frame(body,bg=self._c('surface'));buttons.pack(fill='x',padx=16,pady=16)
  self._button(buttons,'Pass QC',lambda:save('passed'),True).pack(side='right')
  self._button(buttons,'Save',lambda:save()).pack(side='right',padx=7)
  self._button(buttons,'Needs Rework',lambda:save('rework')).pack(side='right')
