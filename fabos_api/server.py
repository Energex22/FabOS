"""WSGI server for the FabOS API boundary.

Serves the existing FabOSApplication and API boundary over Waitress. This is
also the entry point used by the Windows production launcher
(``Start-FabVex-Production.ps1`` in FabOS-Web), where it binds to 127.0.0.1 and
sits behind Caddy, which terminates TLS and is the only public entry point.

Do not bind this directly to a public interface. Note that it reads
``FABOS_CORS_ORIGINS`` (with ``FABOS_API_ALLOW_ORIGIN`` as a legacy fallback) and does not
implement ``FABOS_ALLOWED_HOSTS`` or ``FABOS_API_DOCS``; those belong to the
FastAPI app in ``fabos_core/api.py``. Host filtering on this path comes from
Caddy.
"""
import argparse
import os
from pathlib import Path
try:
    from waitress import serve
except ImportError:  # Keep source checkout usable before optional production deps are installed.
    serve = None

from fabos_api.app import create_wsgi_app
from fabos_core.application import FabOSApplication


def _cors_origins():
    configured = os.environ.get("FABOS_CORS_ORIGINS", "").strip()
    if not configured:
        # Backward compatibility for existing Windows deployments. New
        # deployments should use the same variable as the FastAPI server.
        configured = os.environ.get("FABOS_API_ALLOW_ORIGIN", "").strip()
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def _application_with_cors(core):
    application = create_wsgi_app(core)
    allowed_origins = set(_cors_origins())

    def wrapped(environ, start_response):
        origin = str(environ.get("HTTP_ORIGIN", "")).strip()
        if origin and origin not in allowed_origins:
            if environ.get("REQUEST_METHOD", "GET").upper() == "OPTIONS":
                start_response("403 Forbidden", [("Content-Type", "text/plain; charset=utf-8")])
                return [b"CORS origin not allowed"]
        cors_headers = []
        if origin and origin in allowed_origins:
            cors_headers = [
                ("Access-Control-Allow-Origin", origin),
                ("Access-Control-Allow-Headers", "Authorization, Content-Type"),
                ("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, OPTIONS"),
                ("Access-Control-Max-Age", "600"),
                ("Vary", "Origin"),
            ]
        if environ.get("REQUEST_METHOD", "GET").upper() == "OPTIONS":
            start_response("204 No Content", cors_headers)
            return [b""]

        def cors_start(status, headers):
            headers = list(headers)
            headers.extend(cors_headers)
            start_response(status, headers)

        return application(environ, cors_start)

    return wrapped


def _load_env_file(env_file):
    if not env_file:
        return
    path = Path(env_file).expanduser()
    if not path.is_file():
        raise FileNotFoundError("FabOS environment file was not found: %s" % path)
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or any(ch.isspace() for ch in key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def run(host=None, port=None, threads=None, data_dir=None, env_file=None):
    _load_env_file(env_file)
    if data_dir:
        os.environ["FABOS_DATA_DIR"] = data_dir
    host = host or os.environ.get("FABOS_API_HOST", "127.0.0.1")
    port = int(port or os.environ.get("FABOS_API_PORT", "8000"))
    if serve is None:
        raise RuntimeError("Waitress is required to run the FabOS API server. Install the project dependencies first.")
    core = FabOSApplication()
    application = _application_with_cors(core)
    core.production_automation.start_worker()
    print("FabOS API production server (Waitress): http://%s:%d" % (host, port))
    print("Health check: http://%s:%d/api/v1/health" % (host, port))
    print("CORS origins: %s" % (", ".join(_cors_origins()) or "(same-origin / none configured)"))
    threads = int(threads or os.environ.get("FABOS_API_THREADS", "8"))
    try:
        serve(application, host=host, port=port, threads=max(1, threads), ident="FabOS")
    except KeyboardInterrupt:
        pass
    finally:
        core.production_automation.stop_worker()


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run the FabOS production API server.")
    parser.add_argument("--host", default=None, help="Bind address (default: FABOS_API_HOST or 127.0.0.1).")
    parser.add_argument("--port", type=int, default=None, help="Listen port (default: FABOS_API_PORT or 8000).")
    parser.add_argument("--threads", type=int, default=None, help="Waitress worker threads (default: FABOS_API_THREADS or 8).")
    parser.add_argument("--data-dir", default=None, help="FabOS data directory (overrides FABOS_DATA_DIR).")
    parser.add_argument("--env-file", default=None, help="Optional KEY=VALUE environment file loaded before application startup.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    run(host=args.host, port=args.port, threads=args.threads, data_dir=args.data_dir, env_file=args.env_file)
