import tkinter as tk
from tkinter import ttk,messagebox
import threading

class PrinterAutomationMixin:
 LIVE_REFRESH_MS=3000

 def _build_printers_page(self):
  self._printer_live_token=getattr(self,'_printer_live_token',0)+1
  self._printer_sync_busy=False
  self._printer_last_error={}
  bar=tk.Frame(self.content,bg=self._c('bg'));bar.pack(fill='x',pady=(4,10))
  self._button(bar,'Configure Selected',self._printer_configure,True).pack(side='left')
  self._button(bar,'Sync Now',self._printer_sync).pack(side='left',padx=7)
  self._button(bar,'Pause / Resume',self._printer_pause_resume).pack(side='left')
  self._button(bar,'Cancel Print',self._printer_cancel).pack(side='left',padx=7)
  self._button(bar,'Open Active Job',self._printer_open_job).pack(side='left')
  self._button(bar,'Start Simulation',self._printer_start_sim).pack(side='left',padx=7)
  self._button(bar,'Advance Simulation +10%',lambda:self._printer_tick(10)).pack(side='left',padx=7)
  self.printer_live_label=tk.Label(bar,text='● Live sync every 3 sec',bg=self._c('bg'),fg=self._c('green'),font=('Segoe UI',9,'bold'))
  self.printer_live_label.pack(side='right',padx=4)
  self.printer_cards=tk.Frame(self.content,bg=self._c('bg'));self.printer_cards.pack(fill='x')
  queue=self._card(self.content,'Printer Activity');queue.pack(fill='both',expand=True,pady=(10,0))
  self.printer_table=ttk.Treeview(queue,columns=('name','mode','status','job','progress','elapsed','remaining','temps','seen'),show='headings',style='Dark.Treeview')
  for c,t,w in [('name','Printer',155),('mode','Connection',90),('status','Status',90),('job','Current Job / File',220),('progress','Progress',75),('elapsed','Elapsed',75),('remaining','Remaining',80),('temps','Nozzle / Bed',110),('seen','Last Seen',140)]:
   self.printer_table.heading(c,text=t);self.printer_table.column(c,width=w,anchor='w')
  self.printer_table.pack(fill='both',expand=True,padx=12,pady=(0,12))
  self._printer_refresh();self._printer_schedule_live_sync(self._printer_live_token,250)

 @staticmethod
 def _seconds(value):
  if value is None:return '—'
  try:value=int(value)
  except:return '—'
  h=value//3600;m=(value%3600)//60;s=value%60
  return '%dh %02dm'%(h,m) if h else ('%dm %02ds'%(m,s))

 def _printer_refresh(self):
  if not getattr(self,'printer_table',None) or not self.printer_table.winfo_exists():return
  selected=self.printer_table.selection();self.printer_table.delete(*self.printer_table.get_children())
  for x in self.printer_cards.winfo_children():x.destroy()
  rows=self.core.printer_automation.list()
  for i,p in enumerate(rows):
   job=self.core.printer_automation.active_job(p['id'])
   status_text=p['octoprint_state_text'] if p['connection_mode']=='octoprint' and p['octoprint_state_text'] else p['status'].title()
   if p['connection_mode']=='octoprint':
    live=str(status_text or '').lower() in ('printing','pausing','paused')
    name=(p['octoprint_current_file'] or (job['product_name'] if job and live else None) or 'Idle') if live else 'Idle'
   else:
    name=(job['product_name'] if job else None) or 'Idle'
   progress=float(p['simulation_progress'] or 0);temps='%s° / %s°'%('—' if p['nozzle_temp'] is None else int(p['nozzle_temp']),'—' if p['bed_temp'] is None else int(p['bed_temp']))
   self.printer_table.insert('','end',iid=p['id'],values=(p['name'],p['connection_mode'].title(),status_text,name,'%.0f%%'%progress,self._seconds(p['print_time_seconds']),self._seconds(p['print_time_left_seconds']),temps,str(p['last_seen_at'] or '—')[:19]),tags=('body',))
   card=self._card(self.printer_cards);card.grid(row=i//3,column=i%3,sticky='nsew',padx=(0 if i%3==0 else 7,0),pady=4);self.printer_cards.columnconfigure(i%3,weight=1)
   tk.Label(card,text=p['name'],bg=self._c('surface'),fg=self._c('text'),font=('Segoe UI',12,'bold')).pack(anchor='w',padx=14,pady=(12,2))
   tk.Label(card,text='%s • %s'%(p['connection_mode'].title(),status_text),bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=14)
   tk.Label(card,text=name,bg=self._c('surface'),fg=self._c('text'),wraplength=250,justify='left').pack(anchor='w',padx=14,pady=(10,4))
   ttk.Progressbar(card,maximum=100,value=progress).pack(fill='x',padx=14,pady=4)
   tk.Label(card,text='%.0f%%   Nozzle %s   Bed %s'%(progress,'—' if p['nozzle_temp'] is None else '%d°'%p['nozzle_temp'],'—' if p['bed_temp'] is None else '%d°'%p['bed_temp']),bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=14,pady=(3,2))
   tk.Label(card,text='Elapsed %s   •   Remaining %s'%(self._seconds(p['print_time_seconds']),self._seconds(p['print_time_left_seconds'])),bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=14,pady=(0,3))
   if job:
    extra='Order %s • %s %s'%(job['order_number'] or 'Personal',job['spool_material'] or 'No spool',job['spool_color'] or '')
    tk.Label(card,text=extra,bg=self._c('surface'),fg=self._c('muted'),wraplength=260,justify='left').pack(anchor='w',padx=14,pady=(0,10))
   controls=tk.Frame(card,bg=self._c('surface'));controls.pack(fill='x',padx=14,pady=(0,10))
   tk.Button(controls,text='Pause/Resume',bg=self._c('surface_alt'),fg=self._c('text'),bd=0,
             command=lambda pid=p['id']:self._printer_action_for(pid,'pause')).pack(side='left')
   tk.Button(controls,text='Cancel',bg=self._c('surface_alt'),fg=self._c('red'),bd=0,
             command=lambda pid=p['id']:self._printer_action_for(pid,'cancel')).pack(side='left',padx=5)
  if selected and selected[0] in self.printer_table.get_children():self.printer_table.selection_set(selected[0])
  elif rows:self.printer_table.selection_set(rows[0]['id'])

 def _printer_schedule_live_sync(self,token,delay=None):
  if token!=getattr(self,'_printer_live_token',None) or getattr(self,'active_page',None)!='Printers':return
  self.after(delay if delay is not None else self.LIVE_REFRESH_MS,lambda:self._printer_live_sync(token))

 def _printer_live_sync(self,token):
  if token!=getattr(self,'_printer_live_token',None) or getattr(self,'active_page',None)!='Printers':return
  if getattr(self,'_printer_sync_busy',False):self._printer_schedule_live_sync(token);return
  self._printer_sync_busy=True
  def worker():
   errors={}
   try:
    for p in self.core.printer_automation.list():
     if p['connection_mode']=='octoprint':
      try:self.core.printer_automation.sync_octoprint(p['id'])
      except Exception as exc:errors[p['id']]=str(exc)
   finally:
    try:self.after(0,lambda:self._printer_live_finished(token,errors))
    except Exception:pass
  threading.Thread(target=worker,name='FabOS-OctoPrint-LiveSync',daemon=True).start()

 def _printer_live_finished(self,token,errors):
  self._printer_sync_busy=False
  if token!=getattr(self,'_printer_live_token',None) or getattr(self,'active_page',None)!='Printers':return
  self._printer_last_error=errors
  if getattr(self,'printer_live_label',None) and self.printer_live_label.winfo_exists():
   self.printer_live_label.config(text='● Live sync • connection issue' if errors else '● Live • updated automatically',fg='#fb923c' if errors else self._c('green'))
  self._printer_refresh();self._printer_schedule_live_sync(token)

 def _selected_printer(self):
  s=self.printer_table.selection() if getattr(self,'printer_table',None) else ()
  if not s:messagebox.showinfo('Printers','Select a printer first.');return None
  return s[0]

 def _printer_by_id(self,pid):
  return next((p for p in self.core.printer_automation.list() if p['id']==pid),None)

 def _printer_action_for(self,pid,action):
  p=self._printer_by_id(pid)
  if not p or p['connection_mode']!='octoprint':
   return messagebox.showinfo('Printer','This action requires an OctoPrint printer.')
  try:
   state=str(p['octoprint_state_text'] or p['status']).lower()
   if action=='cancel':
    if not messagebox.askyesno('Cancel Print','Cancel the current physical print on %s?'%p['name']):return
    self.core.octoprint_print.cancel(p)
    try:
     job=self.core.printer_automation.active_job(pid)
     if job:
      self.core.manufacturing.fail_job(job['id'],'User cancelled')
      self.core.production.set_status(job['id'],'failed')
      try:self.core.inventory_profit.record_failed_waste(job['id'])
      except Exception:pass
      try:self.core.operations.log('print.cancelled','Print cancelled',p['name'],'Production',job['id'])
      except Exception:pass
    except Exception:pass
   elif action=='pause':
    if 'paused' in state:self.core.octoprint_print.resume(p)
    else:self.core.octoprint_print.pause(p)
   self.after(400,self._printer_refresh)
  except Exception as exc:messagebox.showerror('Printer Control',str(exc))

 def _printer_pause_resume(self):
  pid=self._selected_printer()
  if pid:self._printer_action_for(pid,'pause')

 def _printer_cancel(self):
  pid=self._selected_printer()
  if pid:self._printer_action_for(pid,'cancel')

 def _printer_open_job(self):
  pid=self._selected_printer()
  if not pid:return
  job=self.core.printer_automation.active_job(pid)
  if not job:return messagebox.showinfo('Printer','No active FabOS job is attached to this printer.')
  self.show_page('Production')
  self.after(100,lambda:self._select_entity_on_active_page(job['id']))

 def _printer_configure(self):
  pid=self._selected_printer()
  if not pid:return
  with self.core.database.connect() as c:p=c.execute('SELECT * FROM printers WHERE id=?',(pid,)).fetchone()
  win=tk.Toplevel(self);win.title('Printer Setup');win.geometry('560x430');win.configure(bg=self._c('bg'));win.transient(self);win.grab_set()
  body=self._card(win,'Printer Connection');body.pack(fill='both',expand=True,padx=16,pady=16)
  mode=tk.StringVar(value=p['connection_mode'] or 'simulation');url=tk.StringVar(value=p['octoprint_url'] or 'http://octopi.local');key=tk.StringVar(value=p['api_key_ref'] or '')
  tk.Label(body,text='Connection Mode',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(8,3));ttk.Combobox(body,textvariable=mode,values=['simulation','octoprint'],state='readonly').pack(fill='x',padx=16)
  tk.Label(body,text='OctoPrint URL',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(12,3));self._entry(body,url,40).pack(fill='x',padx=16,ipady=5)
  tk.Label(body,text='OctoPrint API Key',bg=self._c('surface'),fg=self._c('muted')).pack(anchor='w',padx=16,pady=(12,3));ent=self._entry(body,key,40);ent.configure(show='•');ent.pack(fill='x',padx=16,ipady=5)
  tk.Label(body,text="For Windows 7, using the OctoPrint computer's local IP address is usually more reliable than octopi.local.",bg=self._c('surface'),fg=self._c('muted'),wraplength=480,justify='left').pack(anchor='w',padx=16,pady=14)
  def save():self.core.printer_automation.configure(pid,mode.get(),url.get().strip(),key.get().strip());win.destroy();self._printer_refresh()
  self._button(body,'Save Printer',save,True).pack(anchor='e',padx=16,pady=10)

 def _printer_sync(self):
  pid=self._selected_printer()
  if not pid:return
  with self.core.database.connect() as c:p=c.execute('SELECT * FROM printers WHERE id=?',(pid,)).fetchone()
  if p['connection_mode']=='simulation':self._printer_refresh();return
  try:self.core.printer_automation.sync_octoprint(pid);self._printer_refresh()
  except Exception as e:messagebox.showerror('OctoPrint',str(e))

 def _printer_start_sim(self):
  pid=self._selected_printer()
  if not pid:return
  job=self.core.printer_automation.active_job(pid)
  if not job:return messagebox.showinfo('Simulation','Assign a scheduled production job to this printer first.')
  try:self.core.printer_automation.start_simulation(pid,job['id']);self._printer_refresh()
  except Exception as e:messagebox.showerror('Simulation',str(e))

 def _printer_tick(self,step):
  pid=self._selected_printer()
  if not pid:return
  try:
   result=self.core.printer_automation.simulation_tick(pid,step);self._printer_refresh()
   if result is None:messagebox.showinfo('Simulation','This printer does not have a simulated print running.')
   elif result>=100:messagebox.showinfo('Simulation','Simulated print completed. FabOS recorded manufacturing data, deducted filament, and created QC.')
  except Exception as e:messagebox.showerror('Simulation',str(e))
