"""Windows service entry point for the production FabOS API.

This file keeps the Windows service process as Python itself while explicitly
adding the FabOS checkout to sys.path. That avoids relying on the service
manager's working directory or on a separately installed FabOS package.
"""
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import os

from fabos_core.application import FabOSApplication
from fabos_core.api import create_app
from fabos_api.server import _load_env_file


def _parse_args(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Run the FabOS FastAPI production service on Windows.")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--env-file", default=None)
    return parser.parse_args(argv)


def run(host=None, port=None, threads=None, data_dir=None, env_file=None):
    _load_env_file(env_file)
    if data_dir:
        os.environ["FABOS_DATA_DIR"] = data_dir
    host = host or os.environ.get("FABOS_API_HOST", "127.0.0.1")
    port = int(port or os.environ.get("FABOS_API_PORT", "8000"))
    threads = int(threads or os.environ.get("FABOS_API_THREADS", "8"))
    trusted_proxies = os.environ.get("FABOS_TRUSTED_PROXIES", "127.0.0.1").strip() or "127.0.0.1"
    import uvicorn
    core = FabOSApplication()
    uvicorn.run(
        create_app(core),
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips=trusted_proxies,
        workers=1,
    )


if __name__ == "__main__":
    args = _parse_args()
    run(host=args.host, port=args.port, threads=args.threads, data_dir=args.data_dir, env_file=args.env_file)
