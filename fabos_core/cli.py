import argparse,json,os
from pathlib import Path
from fabos_core.application import FabOSApplication

def main():
    p=argparse.ArgumentParser(); s=p.add_subparsers(dest='cmd',required=True)
    for x in ['init','summary','backup','serve']: s.add_parser(x)
    i=s.add_parser('import-data'); i.add_argument('path')
    a=p.parse_args(); app=FabOSApplication()
    if a.cmd=='init': print(app.settings.database_path)
    elif a.cmd=='summary': print(json.dumps(app.summary(),indent=2))
    elif a.cmd=='backup': print(app.backups.create())
    elif a.cmd=='serve':
        import uvicorn
        from fabos_core.api import create_app
        host=os.environ.get('FABOS_API_HOST','127.0.0.1').strip() or '127.0.0.1'
        try:
            port=int(os.environ.get('FABOS_API_PORT','8000'))
        except ValueError as exc:
            raise SystemExit('FABOS_API_PORT must be an integer') from exc
        if not 1 <= port <= 65535:
            raise SystemExit('FABOS_API_PORT must be between 1 and 65535')
        uvicorn.run(create_app(app),host=host,port=port)
    else:
        src=Path(a.path); report={'source':str(src),'files':[str(x) for x in src.rglob('*') if x.is_file()] if src.exists() else [],'status':'inspection_required'}; out=app.settings.data_dir/'import_report.json'; out.write_text(json.dumps(report,indent=2),encoding='utf-8'); print(out)
if __name__=='__main__': main()
