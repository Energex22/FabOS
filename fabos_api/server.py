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
import os
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


def run(host=None, port=None):
    host = host or os.environ.get("FABOS_API_HOST", "127.0.0.1")
    port = int(port or os.environ.get("FABOS_API_PORT", "8000"))
    core = FabOSApplication()
    application = _application_with_cors(core)
    core.production_automation.start_worker()
    print("FabOS API production server (Waitress): http://%s:%d" % (host, port))
    print("Health check: http://%s:%d/api/v1/health" % (host, port))
    print("CORS origins: %s" % (", ".join(_cors_origins()) or "(same-origin / none configured)"))
    if serve is None:
        raise RuntimeError("Waitress is required to run the FabOS API server. Install the project dependencies first.")
    threads = int(os.environ.get("FABOS_API_THREADS", "8"))
    try:
        serve(application, host=host, port=port, threads=max(1, threads), ident="FabOS")
    except KeyboardInterrupt:
        pass
    finally:
        core.production_automation.stop_worker()


if __name__ == "__main__":
    run()
