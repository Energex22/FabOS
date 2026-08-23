from dataclasses import dataclass
from pathlib import Path
import os
@dataclass(frozen=True)
class Settings:
    data_dir:Path; database_path:Path; backup_dir:Path; plugin_dir:Path; log_dir:Path
def load_settings():
    base=Path(os.environ.get('FABOS_DATA_DIR',Path.home()/'WireVault FabOS Data'))
    return Settings(base,base/'fabos.sqlite3',base/'Backups',base/'Plugins',base/'Logs')
def ensure_directories(s):
    for p in (s.data_dir,s.backup_dir,s.plugin_dir,s.log_dir): p.mkdir(parents=True,exist_ok=True)
