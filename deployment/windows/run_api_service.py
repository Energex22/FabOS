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

from fabos_api.server import _parse_args, run


if __name__ == "__main__":
    args = _parse_args()
    run(host=args.host, port=args.port, threads=args.threads, data_dir=args.data_dir)
