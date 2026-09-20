"""Local development server for the FabOS API boundary.

This is intentionally a development convenience, not a production deployment
server. It keeps the existing FabOSApplication and API boundary intact while
making the API reachable by the separate customer frontend during local work.
"""
import os
try:
    from waitress import serve
except ImportError:  # Keep source checkout usable before optional production deps are installed.
    serve = None

from fabos_api.app import create_wsgi_app
from fabos_core.application import FabOSApplication


def _application_with_cors(core):
    application = create_wsgi_app(core)
    allowed_origin = os.environ.get("FABOS_API_ALLOW_ORIGIN", "http://localhost:5173")

    def wrapped(environ, start_response):
        if environ.get("REQUEST_METHOD", "GET").upper() == "OPTIONS":
            start_response("204 No Content", [
                ("Access-Control-Allow-Origin", allowed_origin),
                ("Access-Control-Allow-Headers", "Authorization, Content-Type"),
                ("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, OPTIONS"),
                ("Access-Control-Max-Age", "600"),
            ])
            return [b""]

        def cors_start(status, headers):
            headers = list(headers)
            headers.extend([
                ("Access-Control-Allow-Origin", allowed_origin),
                ("Access-Control-Allow-Headers", "Authorization, Content-Type"),
                ("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, OPTIONS"),
            ])
            start_response(status, headers)

        return application(environ, cors_start)

    return wrapped


def run(host=None, port=None):
    host = host or os.environ.get("FABOS_API_HOST", "127.0.0.1")
    port = int(port or os.environ.get("FABOS_API_PORT", "8000"))
    core = FabOSApplication()
    application = _application_with_cors(core)
    print("FabOS API development server: http://%s:%d" % (host, port))
    print("Health check: http://%s:%d/api/v1/health" % (host, port))
    if serve is None:
        raise RuntimeError("Waitress is required to run the FabOS API server. Install the project dependencies first.")
    threads = int(os.environ.get("FABOS_API_THREADS", "8"))
    try:
        serve(application, host=host, port=port, threads=max(1, threads), ident="FabOS")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
