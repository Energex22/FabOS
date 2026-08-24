from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urljoin,urlparse
from urllib.error import HTTPError,URLError
import html as htmlmod,re,json,uuid,subprocess,shutil,os

class ProductPrintService:
 def __init__(self,db,products,vault,manufacturing,data_dir):
  self.db=db;self.products=products;self.vault=vault;self.m=manufacturing
  self.data_dir=Path(data_dir)
  self.root=self.data_dir/'Product Downloads';self.root.mkdir(parents=True,exist_ok=True)

 @staticmethod
 def _request(url,referer=None,limit=20_000_000):
  headers={'User-Agent':'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 Chrome/109 Safari/537.36',
           'Accept':'text/html,application/xhtml+xml,application/json,image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
           'Accept-Language':'en-US,en;q=0.9'}
  if referer:headers['Referer']=referer
  req=Request(url,headers=headers)
  with urlopen(req,timeout=25) as r:return r.read(limit),dict(r.headers),r.geturl()

 def discover_model_url(self,page_url):
  try:
   data,headers,final=self._request(page_url)
  except HTTPError as exc:
   if exc.code==403:
    raise RuntimeError('MODEL WEBSITE 403 FORBIDDEN: the source website blocked FabOS from reading the model page. This is not an OctoPrint error. Open the source page in your browser, download the STL normally once, then import it into Design Vault; future prints will use the cached local model.')
   raise RuntimeError('MODEL WEBSITE HTTP %s while reading %s'%(exc.code,page_url))
  except URLError as exc:
   raise RuntimeError('MODEL WEBSITE CONNECTION ERROR: %s'%getattr(exc,'reason',exc))
  ctype=(headers.get('Content-Type') or headers.get('content-type') or '').lower()
  if any(x in ctype for x in ('model/stl','application/octet-stream','application/zip')):
   return final
  txt=data.decode('utf-8','replace')
  candidates=[]
  # Structured metadata and direct links.
  for pat in [
   r'"(?:contentUrl|downloadUrl|fileUrl|download_url|url)"\s*:\s*"([^"\\]+\.(?:stl|3mf|zip)(?:\?[^"\\]*)?)"',
   r"href=[\"']([^\"']+\.(?:stl|3mf|zip)(?:\?[^\"']*)?)[\"']",
   r"(?:data-url|data-download-url)=[\"']([^\"']+)[\"']",
  ]:
   for m in re.finditer(pat,txt,re.I):
    u=htmlmod.unescape(m.group(1)).replace('\\u002F','/').replace('\\/','/')
    u=urljoin(final,u)
    if re.search(r'\.(?:stl|3mf|zip)(?:\?|$)',u,re.I):candidates.append(u)
  # Thingiverse pages often link to /download:<file_id> or /thing:<id>/files.
  for m in re.finditer(r'href=[\"\']([^\"\']*(?:/download:\d+|/download/[^\"\']+))',txt,re.I):
   candidates.append(urljoin(final,htmlmod.unescape(m.group(1))))
  # De-duplicate while preferring STL then 3MF then ZIP.
  seen=[]
  for u in candidates:
   if u not in seen:seen.append(u)
  seen.sort(key=lambda u:(0 if '.stl' in u.lower() else 1 if '.3mf' in u.lower() else 2,len(u)))
  return seen[0] if seen else None

 def download_model(self,product_id):
  p=self.products.get(product_id)
  if not p:raise KeyError('Product not found.')
  if str(p['license_status'] or '')!='verified':
   raise ValueError('Automatic model download is blocked until the commercial-use license is verified.')
  did=self.vault.ensure_product(product_id)
  existing=self.vault.primary_model_asset(did)
  if existing and Path(existing['stored_path']).exists() and existing['kind']=='STL':
   return Path(existing['stored_path']),'existing'
  with self.db.connect() as c:
   stl=c.execute("""SELECT * FROM design_assets WHERE design_id=? AND kind='STL'
      ORDER BY is_primary DESC,created_at DESC LIMIT 1""",(did,)).fetchone()
  if stl and Path(stl['stored_path']).exists():return Path(stl['stored_path']),'existing'
  source=str(p['source_url'] or '').strip()
  if not source:raise ValueError('This product has no source URL.')
  direct=self.discover_model_url(source)
  if not direct:
   raise ValueError('The source page did not expose a public STL/3MF download. Open the source page, download the model normally, then import it into Design Vault. FabOS will use it automatically after that.')
  try:
   raw,headers,final=self._request(direct,referer=source,limit=100_000_000)
  except HTTPError as exc:
   if exc.code==403:
    raise RuntimeError('MODEL DOWNLOAD 403 FORBIDDEN: FabOS found a model download link, but the website requires a browser/login/session to download it. Open the source page, download the STL manually once, and import it into Design Vault. FabOS will use the local copy automatically after that.')
   raise RuntimeError('MODEL DOWNLOAD HTTP %s from %s'%(exc.code,direct))
  except URLError as exc:
   raise RuntimeError('MODEL DOWNLOAD CONNECTION ERROR: %s'%getattr(exc,'reason',exc))
  ctype=(headers.get('Content-Type') or headers.get('content-type') or '').lower()
  path=urlparse(final).path;ext=Path(path).suffix.lower()
  if ext not in ('.stl','.3mf','.zip'):
   if raw[:2]==b'PK':ext='.zip'
   elif raw[:5].lower()==b'solid' or len(raw)>84:ext='.stl'
   else:raise ValueError('The discovered download did not return a recognized model file.')
  folder=self.root/product_id;folder.mkdir(parents=True,exist_ok=True)
  target=folder/('source_model'+ext);target.write_bytes(raw)
  if ext=='.zip':
   import zipfile
   with zipfile.ZipFile(target) as z:
    members=[x for x in z.namelist() if Path(x).suffix.lower() in ('.stl','.3mf') and not x.endswith('/')]
    if not members:raise ValueError('Downloaded ZIP did not contain an STL or 3MF file.')
    member=members[0];out=folder/Path(member).name
    out.write_bytes(z.read(member));target=out
  self.vault.import_file(did,target)
  asset=self.vault.primary_model_asset(did)
  return Path(asset['stored_path']),'downloaded'

 def find_prusaslicer(self,configured=''):
  candidates=[]
  if configured:candidates.append(Path(configured))
  env=os.environ.get('PRUSASLICER_PATH');
  if env:candidates.append(Path(env))
  candidates += [
   Path(r'C:\\Program Files\\Prusa3D\\PrusaSlicer\\prusa-slicer-console.exe'),
   Path(r'C:\\Program Files\\Prusa3D\\PrusaSlicer\\prusa-slicer.exe'),
   Path(r'C:\\Program Files\\PrusaSlicer\\prusa-slicer-console.exe'),
  ]
  for c in candidates:
   if c.exists():return c
  which=shutil.which('prusa-slicer-console') or shutil.which('prusa-slicer-console.exe') or shutil.which('prusa-slicer')
  return Path(which) if which else None

 def slice_model(self,model_path,output_path,exe_path='',profile_path=''):
  exe=self.find_prusaslicer(exe_path)
  if not exe:raise ValueError('PrusaSlicer console executable was not found. Set its path in the Print Product window.')
  output=Path(output_path);output.parent.mkdir(parents=True,exist_ok=True)
  cmd=[str(exe)]
  if profile_path:
   if not Path(profile_path).exists():raise ValueError('The saved PrusaSlicer profile file does not exist: '+profile_path)
   cmd += ['--load',str(profile_path)]
  cmd += ['--export-gcode','--output',str(output),str(model_path)]
  run=subprocess.run(cmd,capture_output=True,text=True,timeout=900)
  if run.returncode!=0 or not output.exists():
   detail=(run.stderr or run.stdout or '').strip()
   raise RuntimeError('PrusaSlicer could not create G-code.' + ('\n\n'+detail[-1500:] if detail else ''))
  return output

 def cura_assisted_models(self,pid):
  """
  Prepare the exact individual STL pieces Cura GUI should open.
  Duplicate quantities are copied to unique filenames so Cura imports every requested copy.
  """
  product=self.products.get(pid)
  if not product:raise KeyError("Product not found.")
  did=self.vault.ensure_product(pid)
  status=self.vault.product_model_status(pid)
  session=self.data_dir/"Cura Assisted"/str(pid)
  session.mkdir(parents=True,exist_ok=True)

  # Clear only old temporary STL copies for this product.
  for old in session.glob("*.stl"):
   try:old.unlink()
   except Exception:pass

  paths=[]
  if status.get("model_mode")=="part_set":
   for part in self.vault.model_parts(did):
    if not part["include_in_complete_set"]:continue
    source=Path(part["stored_path"])
    if source.suffix.lower()!=".stl" or not source.exists():continue
    qty=int(part["quantity"] or 1)
    safe=re.sub(r"[^A-Za-z0-9._-]+","_",part["part_name"] or source.stem).strip("_") or "part"
    for copy_index in range(1,qty+1):
     target=session/("%02d_%s_%02d.stl"%(len(paths)+1,safe,copy_index))
     shutil.copy2(str(source),str(target))
     paths.append(target)
  else:
   source,origin=self.download_model(pid)
   source=Path(source)
   if source.suffix.lower()!=".stl":
    raise ValueError("Cura-assisted printing currently requires an STL.")
   target=session/("01_"+source.name)
   shutil.copy2(str(source),str(target));paths.append(target)

  if not paths:
   raise ValueError("No local STL files are available for Cura-assisted printing.")
  return paths


 def upload_gcode(self,printer,gcode_path,start=False):
  # Multipart upload accepted by OctoPrint. print=true will select and start if operational.
  boundary='----FabOS'+uuid.uuid4().hex
  name=Path(gcode_path).name
  pieces=[]
  def fld(k,v):pieces.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'%(boundary,k,v)).encode())
  fld('select','true');fld('print','true' if start else 'false')
  pieces.append(('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\nContent-Type: application/octet-stream\r\n\r\n'%(boundary,name)).encode())
  pieces.append(Path(gcode_path).read_bytes());pieces.append(('\r\n--%s--\r\n'%boundary).encode())
  data=b''.join(pieces)
  req=Request(str(printer['octoprint_url']).rstrip('/')+'/api/files/local',data=data,method='POST',headers={
   'X-Api-Key':printer['api_key_ref'],'Content-Type':'multipart/form-data; boundary='+boundary,'Content-Length':str(len(data)),'Accept':'application/json'})
  try:
   with urlopen(req,timeout=60) as r:
    raw=r.read();return json.loads(raw.decode()) if raw else {}
  except HTTPError as exc:
   if exc.code==403:
    raise RuntimeError('OCTOPRINT 403 FORBIDDEN DURING G-CODE UPLOAD: the configured API key is invalid or does not have FILES_UPLOAD permission. Generate/use a user API key in OctoPrint with file upload/select and print permissions, then save that key in FabOS.')
   raise RuntimeError('OCTOPRINT HTTP %s DURING G-CODE UPLOAD'%exc.code)
  except URLError as exc:
   raise RuntimeError('OCTOPRINT CONNECTION ERROR DURING G-CODE UPLOAD: %s'%getattr(exc,'reason',exc))
