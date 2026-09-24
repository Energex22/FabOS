import argparse,json,os,getpass
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from fabos_core.application import FabOSApplication

DEFAULT_ENV_FILE=Path("deployment/windows/server.env")

def _env_file_path():
    return Path(os.environ.get("FABOS_ENV_FILE", str(DEFAULT_ENV_FILE))).expanduser()

def _write_env(values):
    path=_env_file_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    existing={}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped=line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key,value=stripped.split("=",1)
                existing[key.strip()]=value.strip().strip('"').strip("'")
    existing.update(values)
    lines=[
        "# FabVex private production environment.",
        "# Keep this file private. Do not commit it to source control.",
        "",
    ]
    lines.extend(f"{key}={value}" for key,value in sorted(existing.items()))
    path.write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(f"Saved production settings to: {path.resolve()}")
    return path

def _setup_dns():
    print("\nDuckDNS setup")
    domain=(input("DuckDNS hostname [fabvex.duckdns.org]: ").strip() or "fabvex.duckdns.org").lower()
    if domain.endswith(".duckdns.org"):
        subdomain=domain[:-len(".duckdns.org")]
    else:
        raise SystemExit("Enter a DuckDNS hostname ending in .duckdns.org.")
    if not subdomain or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in subdomain):
        raise SystemExit("Invalid DuckDNS hostname.")
    token=getpass.getpass("DuckDNS token (hidden): ").strip()
    if not token:
        raise SystemExit("DuckDNS token is required.")
    query=urlencode({"domains":subdomain,"token":token,"verbose":"true"})
    try:
        with urlopen(f"https://www.duckdns.org/update?{query}",timeout=15) as response:
            result=response.read().decode("utf-8","replace").strip()
    except Exception as exc:
        raise SystemExit(f"DuckDNS update failed: {exc}") from exc
    if not result.lower().startswith("ok"):
        raise SystemExit(f"DuckDNS rejected the update: {result}")
    _write_env({"DUCKDNS_DOMAIN":subdomain,"DUCKDNS_TOKEN":token})
    print(f"DuckDNS is configured for {domain}.")
    print("Keep TCP 80 and 443 forwarded to this server; do not expose port 8000.")

def _setup_stripe():
    print("\nStripe setup")
    mode=(input("Stripe mode [test/live]: ").strip().lower() or "test")
    if mode not in {"test","live"}:
        raise SystemExit("Stripe mode must be test or live.")
    publishable=getpass.getpass("Stripe publishable key (hidden): ").strip()
    secret=getpass.getpass("Stripe secret key (hidden): ").strip()
    expected_prefix="pk_test_" if mode=="test" else "pk_live_"
    secret_prefix="sk_test_" if mode=="test" else "sk_live_"
    if not publishable.startswith(expected_prefix) or not secret.startswith(secret_prefix):
        raise SystemExit(f"The keys do not match Stripe {mode} mode.")
    _write_env({
        "STRIPE_MODE":mode,
        "STRIPE_PUBLISHABLE_KEY":publishable,
        "STRIPE_SECRET_KEY":secret,
        "STRIPE_SUCCESS_URL":"https://fabvex.duckdns.org/orders.html",
        "STRIPE_CANCEL_URL":"https://fabvex.duckdns.org/checkout.html",
    })
    print(f"Stripe {mode} mode is configured.")
    print("Use Stripe test cards first; switch to live only after the end-to-end checkout is verified.")

def _setup_owner():
    app=FabOSApplication()
    with app.database.connect() as connection:
        owner=connection.execute(
            "SELECT id,username FROM users WHERE lower(COALESCE(role,''))='owner' "
            "AND lower(COALESCE(account_type,''))='administrator' AND active=1 LIMIT 1"
        ).fetchone()
    if owner is None:
        raise SystemExit("No active owner account exists. Run the normal initialization first.")
    username=(input("Owner username [owner]: ").strip() or "owner")
    if username != owner["username"]:
        with app.database.connect() as connection:
            taken=connection.execute(
                "SELECT 1 FROM users WHERE lower(username)=lower(?) AND id<>? LIMIT 1",
                (username,owner["id"]),
            ).fetchone()
            if taken:
                raise SystemExit("That username is already in use.")
            connection.execute(
                "UPDATE users SET username=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (username,owner["id"]),
            )
            connection.commit()
    while True:
        password=getpass.getpass("New owner password (minimum 12 characters): ")
        confirmation=getpass.getpass("Confirm owner password: ")
        if len(password)<12:
            print("Password must be at least 12 characters.")
            continue
        if password!=confirmation:
            print("Passwords do not match.")
            continue
        break
    app.auth.set_password(owner["id"],password)
    print("Owner setup complete. The default owner credential is no longer usable.")

def main():
    p=argparse.ArgumentParser(); s=p.add_subparsers(dest='cmd',required=True)
    for x in ['init','summary','backup','serve','setup-owner','setup-dns','setup-stripe','setup-production']: s.add_parser(x)
    i=s.add_parser('import-data'); i.add_argument('path')
    a=p.parse_args()
    if a.cmd=='setup-owner':
        _setup_owner()
        return
    if a.cmd=='setup-dns':
        _setup_dns()
        return
    if a.cmd=='setup-stripe':
        _setup_stripe()
        return
    if a.cmd=='setup-production':
        print("\nFABVEX Production Setup")
        print("1. Owner account")
        print("2. DuckDNS")
        print("3. Stripe")
        print("4. All of the above")
        print("5. Back")
        choice=input("Select an option: ").strip()
        if choice in {"1","4"}: _setup_owner()
        if choice in {"2","4"}: _setup_dns()
        if choice in {"3","4"}: _setup_stripe()
        if choice not in {"1","2","3","4","5"}: raise SystemExit("Invalid selection.")
        return
    app=FabOSApplication()
    if a.cmd=='init': print(app.settings.database_path)
    elif a.cmd=='summary': print(json.dumps(app.summary(),indent=2))
    elif a.cmd=='backup': print(app.backups.create())
    elif a.cmd=='serve':
        import uvicorn
        from fabos_core.api import create_app
        host=os.environ.get('FABOS_API_HOST','127.0.0.1').strip() or '127.0.0.1'
        try: port=int(os.environ.get('FABOS_API_PORT','8000'))
        except ValueError as exc: raise SystemExit('FABOS_API_PORT must be an integer') from exc
        if not 1<=port<=65535: raise SystemExit('FABOS_API_PORT must be between 1 and 65535')
        trusted_proxies=os.environ.get('FABOS_TRUSTED_PROXIES','127.0.0.1').strip() or '127.0.0.1'
        uvicorn.run(create_app(app),host=host,port=port,proxy_headers=True,forwarded_allow_ips=trusted_proxies)
    else:
        src=Path(a.path); report={'source':str(src),'files':[str(x) for x in src.rglob('*') if x.is_file()] if src.exists() else [],'status':'inspection_required'}; out=app.settings.data_dir/'import_report.json'; out.write_text(json.dumps(report,indent=2),encoding='utf-8'); print(out)
if __name__=='__main__': main()
