"""Maintain public refresh metadata without changing portfolio content data."""

from datetime import datetime, timezone
from pathlib import Path

try:
    from .news_batch_pipeline import read_json, write_json_atomic
except ImportError:
    from news_batch_pipeline import read_json, write_json_atomic


def legacy_content_timestamp(data_root):
    values = []
    for relative, key in (
        ("earnings/index.json", "generatedAt"),
        ("disclosures/index.json", "generatedAt"),
        ("news/index.json", "generated_at"),
    ):
        value = (read_json(Path(data_root) / relative, {}) or {}).get(key)
        if value:
            values.append(value)
    return max(values, default=None)


def update_refresh_status(data_root, completed_at=None, content_changed=False):
    data_root = Path(data_root)
    path = data_root / "state" / "refresh-status.json"
    status = read_json(path, {}) or {}
    completed_at = completed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    status["lastSuccessfulRefreshAt"] = completed_at
    if content_changed:
        status["lastContentChangedAt"] = completed_at
    elif not status.get("lastContentChangedAt"):
        status["lastContentChangedAt"] = legacy_content_timestamp(data_root)
    write_json_atomic(path, status)
    return status
