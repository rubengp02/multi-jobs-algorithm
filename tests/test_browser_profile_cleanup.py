import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from browser_profile_cleanup import (
    cleanup_browser_storage,
    cleanup_extension_runtimes,
)

NOW = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)


def _write(path: Path, value: str = "cache") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


class BrowserProfileCleanupTests(unittest.TestCase):
    def test_removes_only_disposable_cache_and_expired_session_backups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            data_dir = base_dir / "data"
            profile_dir = data_dir / "infojobs_session"
            cookie = profile_dir / "Default" / "Cookies"
            cache = profile_dir / "Default" / "Cache" / "blob"
            code_cache = profile_dir / "Default" / "Code Cache" / "js" / "blob"
            _write(cookie, "session-cookie")
            _write(cache)
            _write(code_cache)
            old_backup = data_dir / "linkedin_session_backup_20260701_010101"
            recent_backup = data_dir / "infojobs_session_backup_20260823_010101"
            _write(old_backup / "Default" / "Cookies")
            _write(recent_backup / "Default" / "Cookies")
            old_timestamp = (NOW - timedelta(days=20)).timestamp()
            os.utime(old_backup, (old_timestamp, old_timestamp))

            result = cleanup_browser_storage(
                data_dir, [profile_dir], backup_retention_days=14, now=NOW
            )

            self.assertEqual(cookie.read_text(encoding="utf-8"), "session-cookie")
            self.assertFalse(cache.parent.exists())
            self.assertFalse(code_cache.parent.exists())
            self.assertFalse(old_backup.exists())
            self.assertTrue(recent_backup.exists())
            self.assertEqual(result["browser_cache_directories"], 2)
            self.assertEqual(result["expired_session_backups"], 1)

    def test_retains_current_extension_and_prunes_only_expired_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            runtime_root = Path(temporary_directory) / "linkedin_extension_runtime"
            current = runtime_root / "current-build"
            old = runtime_root / "old-build"
            recent = runtime_root / "recent-build"
            _write(current / "manifest.json")
            _write(old / "manifest.json")
            _write(recent / "manifest.json")
            old_timestamp = (NOW - timedelta(days=31)).timestamp()
            os.utime(old, (old_timestamp, old_timestamp))

            removed = cleanup_extension_runtimes(
                runtime_root, 30, ["current-build"], now=NOW
            )

            self.assertEqual(removed, 1)
            self.assertTrue(current.exists())
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())
