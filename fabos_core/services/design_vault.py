from pathlib import Path
import hashlib,shutil,uuid,struct,re
class DesignVaultService:
 def __init__(self,db,data_dir):self.db=db;self.root=Path(data_dir)/'Design Vault';self.root.mkdir(parents=True,exist_ok=True)
 def ensure_product(self,pid):
  with self.db.connect() as c:
   r=c.execute('SELECT * FROM designs WHERE product_id=?',(pid,)).fetchone()
   if r:return r['id']
   p=c.execute('SELECT name FROM products WHERE id=?',(pid,)).fetchone();did=str(uuid.uuid4());vid=str(uuid.uuid4())
   c.execute('INSERT INTO designs(id,product_id,name) VALUES(?,?,?)',(did,pid,p['name']))
   c.execute("INSERT INTO design_versions(id,design_id,version,label) VALUES(?,?,1,'Initial')",(vid,did));c.commit();return did
 def ensure_all(self):
  with self.db.connect() as c:ids=[r[0] for r in c.execute('SELECT id FROM products')]
  for x in ids:self.ensure_product(x)
 def list(self,q=''):
  n='%%%s%%'%q.strip()
  with self.db.connect() as c:return c.execute("""SELECT d.*,COALESCE(p.sku,'—') sku,COALESCE(p.category,'—') category,(SELECT COUNT(*) FROM design_assets a WHERE a.design_id=d.id) asset_count FROM designs d LEFT JOIN products p ON p.id=d.product_id WHERE ?='' OR d.name LIKE ? OR COALESCE(p.sku,'') LIKE ? ORDER BY d.name COLLATE NOCASE""",(q.strip(),n,n)).fetchall()
 def get(self,did):
  with self.db.connect() as c:return c.execute('SELECT * FROM designs WHERE id=?',(did,)).fetchone()
 def assets(self,did):
  with self.db.connect() as c:return c.execute('SELECT a.*,v.version FROM design_assets a LEFT JOIN design_versions v ON v.id=a.version_id WHERE a.design_id=? ORDER BY a.created_at DESC',(did,)).fetchall()
 def new_version(self,did):
  with self.db.connect() as c:
   d=c.execute('SELECT current_version FROM designs WHERE id=?',(did,)).fetchone();v=int(d[0])+1;vid=str(uuid.uuid4());c.execute('INSERT INTO design_versions(id,design_id,version,label) VALUES(?,?,?,?)',(vid,did,v,'Version %d'%v));c.execute('UPDATE designs SET current_version=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(v,did));c.commit()
 def import_file(self,did,path,make_primary=False):
  src=Path(path)
  if not src.exists():raise FileNotFoundError(src)
  raw=src.read_bytes();sha=hashlib.sha256(raw).hexdigest()
  with self.db.connect() as c:
   old=c.execute('SELECT id,kind FROM design_assets WHERE design_id=? AND sha256=?',(did,sha)).fetchone()
   if old:
    if make_primary and old['kind'] in ('STL','3MF','STEP'):
     c.execute("UPDATE design_assets SET is_primary=CASE WHEN id=? THEN 1 ELSE 0 END WHERE design_id=?",(old['id'],did));c.commit()
    return False
   d=c.execute('SELECT * FROM designs WHERE id=?',(did,)).fetchone();v=c.execute('SELECT * FROM design_versions WHERE design_id=? AND version=?',(did,d['current_version'])).fetchone()
  kind={'.stl':'STL','.3mf':'3MF','.step':'STEP','.stp':'STEP','.gcode':'GCODE','.gco':'GCODE','.gc':'GCODE','.png':'IMAGE','.jpg':'IMAGE','.jpeg':'IMAGE'}.get(src.suffix.lower(),'OTHER')
  safe=re.sub(r'[^A-Za-z0-9._-]+','_',d['name'])[:70];folder=self.root/safe/('v%03d'%d['current_version'])/kind;folder.mkdir(parents=True,exist_ok=True);target=folder/src.name
  if target.exists():target=folder/(src.stem+'_'+sha[:8]+src.suffix)
  shutil.copy2(str(src),str(target));meta=self.stl_meta(target) if kind=='STL' else (None,None,None,None,[])
  aid=str(uuid.uuid4())
  with self.db.connect() as c:
   if make_primary and kind in ('STL','3MF','STEP'):
    c.execute('UPDATE design_assets SET is_primary=0 WHERE design_id=?',(did,))
   c.execute('INSERT INTO design_assets(id,design_id,version_id,kind,original_name,stored_path,sha256,bytes,width_mm,depth_mm,height_mm,triangle_count,is_primary) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
    (aid,did,v['id'],kind,src.name,str(target),sha,target.stat().st_size,meta[0],meta[1],meta[2],meta[3],
     1 if make_primary and kind in ('STL','3MF','STEP') else 0))
   if kind in ('STL','3MF','STEP'):
    primary=c.execute('SELECT id FROM design_assets WHERE design_id=? AND is_primary=1',(did,)).fetchone()
    if not primary:c.execute('UPDATE design_assets SET is_primary=1 WHERE id=?',(aid,))
   c.commit()
  return True
 @staticmethod
 def stl_meta(path):
  data=Path(path).read_bytes();verts=[];tri=0
  if len(data)>=84:
   n=struct.unpack('<I',data[80:84])[0]
   if 84+n*50==len(data):
    tri=n
    for i in range(n):
     o=84+i*50+12
     for j in range(3):verts.append(struct.unpack('<fff',data[o+j*12:o+j*12+12]))
  if not verts:
   txt=data.decode('utf-8','ignore')
   for m in re.finditer(r'vertex\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)',txt):
    try:verts.append(tuple(map(float,m.groups())))
    except:pass
   tri=len(verts)//3
  if not verts:return None,None,None,tri or None,[]
  xs=[x[0] for x in verts];ys=[x[1] for x in verts];zs=[x[2] for x in verts]
  return max(xs)-min(xs),max(ys)-min(ys),max(zs)-min(zs),tri,verts[:6000]

 def versions(self,did):
  with self.db.connect() as c:
   return c.execute('SELECT * FROM design_versions WHERE design_id=? ORDER BY version DESC',(did,)).fetchall()

 def production_history(self,did):
  with self.db.connect() as c:
   d=c.execute('SELECT product_id FROM designs WHERE id=?',(did,)).fetchone()
   if not d or not d['product_id']:return []
   return c.execute("""SELECT j.*,COALESCE(o.order_number,'—') order_number,
      COALESCE(pr.name,'Unassigned') printer_name
      FROM print_jobs j
      LEFT JOIN orders o ON o.id=j.order_id
      LEFT JOIN printers pr ON pr.id=j.printer_id
      WHERE j.product_id=?
      ORDER BY j.created_at DESC LIMIT 100""",(d['product_id'],)).fetchall()

 def _ensure_model_part_rows(self,did):
  with self.db.connect() as c:
   assets=c.execute("""SELECT id,original_name FROM design_assets
     WHERE design_id=? AND kind='STL' ORDER BY created_at""",(did,)).fetchall()
   existing={r['asset_id'] for r in c.execute("SELECT asset_id FROM design_model_parts WHERE design_id=?",(did,)).fetchall()}
   order=c.execute("SELECT COALESCE(MAX(sort_order),-1) FROM design_model_parts WHERE design_id=?",(did,)).fetchone()[0]+1
   for a in assets:
    if a['id'] in existing:continue
    stem=Path(a['original_name']).stem.replace('_',' ').replace('-',' ').strip()
    name=' '.join(word.capitalize() for word in stem.split()) or 'Part'
    c.execute("""INSERT INTO design_model_parts(id,design_id,asset_id,part_name,quantity,include_in_complete_set,sort_order)
      VALUES(?,?,?,?,1,1,?)""",(str(uuid.uuid4()),did,a['id'],name,order));order+=1
   c.commit()

 def model_mode(self,did):
  with self.db.connect() as c:
   row=c.execute("SELECT model_mode FROM designs WHERE id=?",(did,)).fetchone()
  return (row['model_mode'] if row else 'single') or 'single'

 def set_model_mode(self,did,mode):
  if mode not in ('single','part_set'):raise ValueError('Model type must be Single Model or Part Set.')
  self._ensure_model_part_rows(did)
  with self.db.connect() as c:
   c.execute("UPDATE designs SET model_mode=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(mode,did));c.commit()

 def model_parts(self,did):
  self._ensure_model_part_rows(did)
  with self.db.connect() as c:
   return c.execute("""SELECT mp.*,a.original_name,a.stored_path,a.kind,a.width_mm,a.depth_mm,a.height_mm,a.is_primary
     FROM design_model_parts mp JOIN design_assets a ON a.id=mp.asset_id
     WHERE mp.design_id=? AND a.kind='STL' ORDER BY mp.sort_order,mp.created_at""",(did,)).fetchall()

 def update_model_part(self,part_id,name,quantity,include=True):
  quantity=int(quantity)
  if quantity<1 or quantity>100:raise ValueError('Part quantity must be between 1 and 100.')
  name=(name or '').strip()
  if not name:raise ValueError('Part name cannot be blank.')
  with self.db.connect() as c:
   c.execute("""UPDATE design_model_parts SET part_name=?,quantity=?,include_in_complete_set=?,
     updated_at=CURRENT_TIMESTAMP WHERE id=?""",(name,quantity,1 if include else 0,part_id));c.commit()

 def model_set_summary(self,did):
  mode=self.model_mode(did);parts=list(self.model_parts(did))
  included=[p for p in parts if p['include_in_complete_set']]
  return {
   'mode':mode,'part_count':len(included),
   'piece_count':sum(int(p['quantity'] or 1) for p in included),
   'parts':parts
  }

 def primary_model_asset(self,did):
  with self.db.connect() as c:
   return c.execute("""SELECT a.*,v.version FROM design_assets a
      LEFT JOIN design_versions v ON v.id=a.version_id
      WHERE a.design_id=? AND a.kind IN ('STL','3MF','STEP')
      ORDER BY a.is_primary DESC,
               CASE a.kind WHEN 'STL' THEN 0 WHEN '3MF' THEN 1 ELSE 2 END,
               v.version DESC,a.created_at DESC LIMIT 1""",(did,)).fetchone()

 def product_print_status_map(self,product_ids):
  ids=list(product_ids or [])
  result={pid:{'ready':False,'has_stl':False,'has_gcode':False,
               'stl_count':0,'gcode_count':0,'reason':'Needs STL or G-code'} for pid in ids}
  if not ids:return result
  marks=','.join('?' for _ in ids)
  with self.db.connect() as c:
   assets=c.execute("""SELECT d.product_id,a.kind,a.stored_path
      FROM designs d JOIN design_assets a ON a.design_id=d.id
      WHERE d.product_id IN (%s) AND a.kind IN ('STL','GCODE')"""%marks,ids).fetchall()
   legacy=c.execute("""SELECT product_id,kind,path FROM product_files
      WHERE product_id IN (%s)"""%marks,ids).fetchall()
  seen={pid:{'stl':set(),'gcode':set()} for pid in ids}
  for pid,kind,path in [(r['product_id'],r['kind'],r['stored_path']) for r in assets]+[
      (r['product_id'],str(r['kind'] or '').upper(),r['path']) for r in legacy]:
   p=Path(path or '')
   if not p.exists():continue
   suffix=p.suffix.lower()
   if kind=='STL' or suffix=='.stl':seen[pid]['stl'].add(str(p))
   elif kind in ('GCODE','G-CODE') or suffix in ('.gcode','.gco','.gc'):
    seen[pid]['gcode'].add(str(p))
  for pid in ids:
   stls=seen[pid]['stl'];gcodes=seen[pid]['gcode']
   if stls and gcodes:reason='STL + G-code ready'
   elif stls:reason='STL ready'
   elif gcodes:reason='Saved G-code ready'
   else:reason='Needs STL or G-code'
   result[pid]={'ready':bool(stls or gcodes),'has_stl':bool(stls),'has_gcode':bool(gcodes),
                'stl_count':len(stls),'gcode_count':len(gcodes),'reason':reason}
  return result

 def gcode_library(self,pid):
  with self.db.connect() as c:
   design=c.execute("SELECT id FROM designs WHERE product_id=?",(pid,)).fetchone()
   rows=[]
   if design:
    rows=c.execute("""SELECT id,original_name,stored_path,bytes,created_at
      FROM design_assets WHERE design_id=? AND kind='GCODE'
      ORDER BY created_at DESC""",(design['id'],)).fetchall()
  return [r for r in rows if Path(r['stored_path']).exists()]

 def best_gcode_for(self,pid,material=None,printer_name=None):
  """Choose the best saved G-code using material/printer hints instead of file age alone."""
  rows=self.gcode_library(pid)
  if not rows:return None
  wanted_material=str(material or '').upper().strip()
  wanted_printer=str(printer_name or '').lower().strip()
  ranked=[]
  for index,row in enumerate(rows):
   path=Path(row['stored_path'])
   text=path.read_text(encoding='utf-8',errors='ignore')
   def find(pattern):
    m=re.search(pattern,text,re.I|re.M)
    return m.group(1).strip() if m else ''
   hinted_material=(find(r"^;\s*MATERIAL(?:_TYPE)?\s*[:=]\s*([A-Za-z0-9 _+\-]+)$") or
                    find(r"^;\s*FILAMENT_TYPE\s*[:=]\s*([A-Za-z0-9 _+\-]+)$")).upper()
   hinted_machine=(find(r"^;\s*MACHINE(?:_NAME)?\s*[:=]\s*(.+)$") or
                   find(r"^;\s*PRINTER(?:_MODEL)?\s*[:=]\s*(.+)$")).lower()
   score=0
   if wanted_material and hinted_material:
    score+=100 if wanted_material==hinted_material else -100
   elif wanted_material:
    score-=5
   if wanted_printer and hinted_machine:
    if wanted_printer in hinted_machine or hinted_machine in wanted_printer:score+=25
    else:score-=20
   ranked.append((score,-index,row))
  ranked.sort(key=lambda item:(item[0],item[1]),reverse=True)
  best=ranked[0]
  if wanted_material and best[0]<0:return None
  return best[2]

 def delete_product_gcode(self,pid,asset_id):
  with self.db.connect() as c:
   row=c.execute("""SELECT a.* FROM design_assets a JOIN designs d ON d.id=a.design_id
      WHERE a.id=? AND d.product_id=? AND a.kind='GCODE'""",(asset_id,pid)).fetchone()
   if not row:return False
   path=Path(row['stored_path'])
   c.execute("DELETE FROM design_assets WHERE id=?",(asset_id,));c.commit()
  try:
   if path.exists():path.unlink()
  except OSError:pass
  return True

 def product_print_status(self,pid):
  """Return whether a Catalog product has a usable local STL and/or G-code."""
  with self.db.connect() as c:
   design=c.execute("SELECT id FROM designs WHERE product_id=?",(pid,)).fetchone()
   assets=[]
   if design:
    assets=c.execute("""SELECT * FROM design_assets
      WHERE design_id=? AND kind IN ('STL','GCODE')
      ORDER BY CASE kind WHEN 'GCODE' THEN 0 ELSE 1 END,created_at DESC""",
      (design['id'],)).fetchall()
   legacy=c.execute("""SELECT * FROM product_files WHERE product_id=?
      ORDER BY version DESC,created_at DESC""",(pid,)).fetchall()

  stls=[];gcodes=[]
  for row in assets:
   path=Path(row['stored_path'])
   if not path.exists():continue
   if row['kind']=='STL':stls.append(path)
   elif row['kind']=='GCODE':gcodes.append(path)
  for row in legacy:
   path=Path(row['path'])
   if not path.exists():continue
   kind=str(row['kind'] or '').upper()
   suffix=path.suffix.lower()
   if (kind=='STL' or suffix=='.stl') and path not in stls:stls.append(path)
   elif (kind in ('GCODE','G-CODE') or suffix in ('.gcode','.gco','.gc')) and path not in gcodes:
    gcodes.append(path)

  reason='Ready'
  if not stls and not gcodes:reason='Needs STL or G-code'
  elif gcodes and not stls:reason='Saved G-code ready'
  elif stls and not gcodes:reason='STL ready'
  else:reason='STL + G-code ready'
  return {
   'ready':bool(stls or gcodes),'has_stl':bool(stls),'has_gcode':bool(gcodes),
   'stl_count':len(stls),'gcode_count':len(gcodes),
   'stl_paths':stls,'gcode_paths':gcodes,
   'preferred_gcode':gcodes[0] if gcodes else None,
   'reason':reason
  }

 def import_product_print_files(self,pid,paths):
  did=self.ensure_product(pid)
  clean=[Path(p) for p in paths if Path(p).suffix.lower() in ('.stl','.3mf','.step','.stp','.gcode','.gco','.gc')]
  if not clean:raise ValueError('Choose an STL, 3MF, STEP, or G-code file.')
  model_paths=[p for p in clean if p.suffix.lower() in ('.stl','.3mf','.step','.stp')]
  gcode_paths=[p for p in clean if p.suffix.lower() in ('.gcode','.gco','.gc')]
  if model_paths:self.import_product_models(pid,model_paths)
  for path in gcode_paths:self.import_file(did,path)
  return self.product_print_status(pid)

 def product_model_status(self,pid):
  did=self.ensure_product(pid)
  with self.db.connect() as c:
   rows=c.execute("""SELECT * FROM design_assets
      WHERE design_id=? AND kind IN ('STL','3MF','STEP')
      ORDER BY is_primary DESC,created_at DESC""",(did,)).fetchall()
  existing=[r for r in rows if Path(r['stored_path']).exists()]
  primary=next((r for r in existing if r['is_primary']),existing[0] if existing else None)
  stls=[r for r in existing if r['kind']=='STL']
  summary=self.model_set_summary(did)
  return {'design_id':did,'count':len(existing),'stl_count':len(stls),'ready':bool(stls),
          'primary':primary,'primary_name':primary['original_name'] if primary else '',
          'primary_kind':primary['kind'] if primary else '',
          'model_mode':summary['mode'],'part_count':summary['part_count'],
          'piece_count':summary['piece_count'],
          'suggest_part_set':len(stls)>1 and summary['mode']=='single'}

 def _asset_for_original(self,did,name):
  with self.db.connect() as c:
   row=c.execute("""SELECT id FROM design_assets WHERE design_id=? AND original_name=?
      ORDER BY created_at DESC LIMIT 1""",(did,name)).fetchone()
  return row['id'] if row else None

 def set_primary_model(self,did,asset_id):
  if not asset_id:return
  with self.db.connect() as c:
   row=c.execute("""SELECT id FROM design_assets WHERE id=? AND design_id=?
      AND kind IN ('STL','3MF','STEP')""",(asset_id,did)).fetchone()
   if not row:raise KeyError('Model asset not found.')
   c.execute('UPDATE design_assets SET is_primary=CASE WHEN id=? THEN 1 ELSE 0 END WHERE design_id=?',(asset_id,did));c.commit()

 def import_product_models(self,pid,paths,primary_path=None):
  did=self.ensure_product(pid)
  clean=[Path(p) for p in paths if Path(p).suffix.lower() in ('.stl','.3mf','.step','.stp')]
  if not clean:raise ValueError('Choose at least one STL, 3MF, STEP, or STP file.')
  requested=str(Path(primary_path).resolve()) if primary_path else ''
  for index,path in enumerate(clean):
   make_primary=(str(path.resolve())==requested) if requested else False
   self.import_file(did,path,make_primary=make_primary)
  if not requested:
   first_stl=next((p for p in clean if p.suffix.lower()=='.stl'),None)
   chosen=first_stl or clean[0]
   aid=self._asset_for_original(did,chosen.name)
   if aid:self.set_primary_model(did,aid)
  self._ensure_model_part_rows(did)
  return self.product_model_status(pid)
 def profile(self,did):
  with self.db.connect() as c:return c.execute('SELECT * FROM print_profiles WHERE design_id=? AND active=1 ORDER BY created_at DESC LIMIT 1',(did,)).fetchone()
 def save_profile(self,did,name,material,nozzle,layer,infill,supports,path=''):
  with self.db.connect() as c:c.execute('UPDATE print_profiles SET active=0 WHERE design_id=?',(did,));c.execute('INSERT INTO print_profiles(id,design_id,name,material,nozzle_mm,layer_height_mm,infill_percent,supports,slicer_profile_path) VALUES(?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),did,name,material,float(nozzle),float(layer),float(infill),supports,path));c.commit()
