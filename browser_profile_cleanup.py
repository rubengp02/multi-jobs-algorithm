"""Safely bound disk use from disposable browser data.

Browser profiles also contain cookies and local storage that keep provider
sessions alive.  This module intentionally removes only Chromium cache
directories and clearly named, expired session backups; it never removes a
live profile directory or ``seen_jobs.txt``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path

CACHE_DIRECTORY_NAMES = frozenset(
    {
        "Cache",
        "Code Cache",
        "GPUCache",
        "DawnCache",
        "GrShaderCache",
        "ShaderCache",
        "Crashpad",
        "Crash Reports",
    }
)
SESSION_BACKUP_PATTERN = re.compile(r".+_session_backup_\d{8}_\d{6}$")


def _is_within(root: Path, candidate: Path) -> bool:
    """Return whether a resolved candidate remains inside its expected root."""
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _remove_directory(root: Path, candidate: Path) -> bool:
    """Remove a known disposable directory without following symlinks outside root."""
    if not _is_within(root, candidate):
        return False
    if candidate.is_symlink():
        candidate.unlink(missing_ok=True)
    elif candidate.is_dir():
        shutil.rmtree(candidate)
    else:
        return False
    return True


def cleanup_profile_caches(profile_dir: Path) -> int:
    """Clear regenerable cache directories while preserving browser session data."""
    if not profile_dir.is_dir():
        return 0

    removed = 0
    for current_root, directories, _ in os.walk(
        profile_dir, topdown=True, followlinks=False
    ):
        current = Path(current_root)
        for name in list(directories):
            if name not in CACHE_DIRECTORY_NAMES:
                continue
            candidate = current / name
            if _remove_directory(profile_dir, candidate):
                removed += 1
            directories.remove(name)
    return removed


def cleanup_session_backups(
    data_dir: Path, retention_days: int, *, now: datetime | None = None
) -> int:
    """Remove only old timestamped backup folders created by this project."""
    if not data_dir.is_dir():
        return 0
    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - timedelta(days=max(1, retention_days))
    removed = 0
    for candidate in data_dir.iterdir():
        if not candidate.is_dir() or not SESSION_BACKUP_PATTERN.fullmatch(
            candidate.name
        ):
            continue
        modified = datetime.fromtimestamp(candidate.stat().st_mtime, tz=timezone.utc)
        if modified < cutoff and _remove_directory(data_dir, candidate):
            removed += 1
    return removed


def cleanup_extension_runtimes(
    runtime_root: Path,
    retention_days: int,
    keep_names: Iterable[str] = (),
    *,
    now: datetime | None = None,
) -> int:
    """Prune superseded unpacked extension copies before Chromium starts."""
    if not runtime_root.is_dir():
        return 0
    protected = {name for name in keep_names if name}
    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - timedelta(days=max(1, retention_days))
    removed = 0
    for candidate in runtime_root.iterdir():
        if not candidate.is_dir() or candidate.name in protected:
            continue
        modified = datetime.fromtimestamp(candidate.stat().st_mtime, tz=timezone.utc)
        if modified < cutoff and _remove_directory(runtime_root, candidate):
            removed += 1
    return removed


def cleanup_browser_storage(
    data_dir: Path,
    profile_dirs: Iterable[Path],
    backup_retention_days: int,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Run the safe cleanup used by the bot after a completed provider cycle."""
    return {
        "browser_cache_directories": sum(
            cleanup_profile_caches(profile_dir) for profile_dir in profile_dirs
        ),
        "expired_session_backups": cleanup_session_backups(
            data_dir, backup_retention_days, now=now
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prune disposable browser data safely")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path, action="append", default=[])
    parser.add_argument("--backup-retention-days", type=int, default=14)
    parser.add_argument("--extension-runtime-root", type=Path)
    parser.add_argument("--extension-runtime-retention-days", type=int, default=30)
    parser.add_argument("--keep-extension-runtime", action="append", default=[])
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = cleanup_browser_storage(
        args.data_dir, args.profile, args.backup_retention_days
    )
    if args.extension_runtime_root is not None:
        result["expired_extension_runtimes"] = cleanup_extension_runtimes(
            args.extension_runtime_root,
            args.extension_runtime_retention_days,
            args.keep_extension_runtime,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
