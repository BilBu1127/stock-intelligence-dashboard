"""Secret loading with GitHub Actions environment variables before local fallback.

Never log returned values. Callers may report only the missing variable names.
"""

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_env_file(path):
    values = {}
    path = Path(path)
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if clean and not clean.startswith("#") and "=" in clean:
            key, value = clean.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def load_values(names, fallback_path=None, session_path=None, session_name="TELEGRAM_SESSION", environ=None):
    environ = os.environ if environ is None else environ
    fallback = read_env_file(fallback_path) if fallback_path else {}
    values = {name: str(environ.get(name) or fallback.get(name) or "").strip() for name in names}
    if session_path and not values.get(session_name):
        path = Path(session_path)
        if path.is_file():
            values[session_name] = path.read_text(encoding="utf-8").strip()
    return values


def missing_names(values):
    return sorted(name for name, value in values.items() if not value)
