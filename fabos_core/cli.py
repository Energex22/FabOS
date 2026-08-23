import argparse,json
from pathlib import Path
from fabos_core.application import FabOSApplication
def main():
    p=argparse.ArgumentParser(); s=p.add_subparsers(dest='cmd',required=True)
    for x in ['init','summary','backup']: s.add_parser(x)
    i=s.add_parser('import-data'); i.add_argument('path')
    a=p.parse_args(); app=FabOSApplication()
    if a.cmd=='init': print(app.settings.database_path)
    elif a.cmd=='summary': print(json.dumps(app.summary(),indent=2))
    elif a.cmd=='backup': print(app.backups.create())
    else:
        src=Path(a.path); report={'source':str(src),'files':[str(x) for x in src.rglob('*') if x.is_file()] if src.exists() else [],'status':'inspection_required'}; out=app.settings.data_dir/'import_report.json'; out.write_text(json.dumps(report,indent=2),encoding='utf-8'); print(out)
if __name__=='__main__': main()
