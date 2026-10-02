from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import RLock, get_ident


class SeenStorage:
    def __init__(self, file_path: Path) -> None:
        self._lock = RLock()
        self.file_path = file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.file_path.touch()
        self._entries: list[tuple[str, int]] = []
        self._seen: set[str] = set()
        self._load()

    def _load(self) -> None:
        self._entries.clear()
        self._seen.clear()
        now = int(time.time())
        try:
            with self.file_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    if "|" in line:
                        key, timestamp_text = line.split("|", 1)
                        try:
                            timestamp = int(timestamp_text)
                        except ValueError:
                            timestamp = now
                    else:
                        key, timestamp = line, now
                    if key not in self._seen:
                        self._seen.add(key)
                        self._entries.append((key, timestamp))
        except OSError:
            return

    @staticmethod
    def _key(source: str, job_id: str) -> str:
        return f"{source}:{job_id}"

    def is_seen(self, source: str, job_id: str) -> bool:
        with self._lock:
            return self._key(source, job_id) in self._seen

    def is_seen_any(self, source: str, job_ids: list[str] | tuple[str, ...]) -> bool:
        """Check canonical and historical identifiers without rewriting seen data."""
        return any(self.is_seen(source, job_id) for job_id in job_ids if job_id)

    def add(self, source: str, job_id: str, timestamp: int | None = None) -> None:
        with self._lock:
            key = self._key(source, job_id)
            if key in self._seen:
                return
            timestamp = timestamp if timestamp is not None else int(time.time())
            self._seen.add(key)
            self._entries.append((key, timestamp))
            with self.file_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{key}|{timestamp}\n")

    def count(self) -> int:
        with self._lock:
            return len(self._seen)

    def purge_older_than_days(self, max_days: int = 2) -> int:
        with self._lock:
            cutoff = int(time.time()) - max_days * 86400
            kept = [entry for entry in self._entries if entry[1] >= cutoff]
            removed = len(self._entries) - len(kept)
            if removed:
                self._entries = kept
                self._seen = {entry[0] for entry in kept}
                with self.file_path.open("w", encoding="utf-8") as handle:
                    for key, timestamp in self._entries:
                        handle.write(f"{key}|{timestamp}\n")
            return removed

    def keep_last(self, max_items: int) -> int:
        with self._lock:
            max_items = max(max_items, 0)
            if len(self._entries) <= max_items:
                return 0
            kept = self._entries[-max_items:] if max_items else []
            removed = len(self._entries) - len(kept)
            self._entries = kept
            self._seen = {entry[0] for entry in kept}
            with self.file_path.open("w", encoding="utf-8") as handle:
                for key, timestamp in self._entries:
                    handle.write(f"{key}|{timestamp}\n")
            return removed


class RelevanceDecisionCache:
    """Bounded cache for unchanged rejected and review decisions."""

    def __init__(
        self,
        file_path: Path,
        max_items: int = 4000,
        retention_days: int = 7,
    ) -> None:
        self._lock = RLock()
        self.file_path = file_path
        self.max_items = max(1, max_items)
        self.retention_days = max(1, retention_days)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, dict[str, object]] = {}
        try:
            raw = json.loads(self.file_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._entries = {
                    str(key): value
                    for key, value in raw.items()
                    if isinstance(value, dict)
                }
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        self.purge()

    @staticmethod
    def _key(source: str, job_id: str) -> str:
        return f"{source}:{job_id}"

    def get(
        self, source: str, job_id: str, fingerprint: str
    ) -> dict[str, object] | None:
        with self._lock:
            entry = self._entries.get(self._key(source, job_id))
            if not entry or entry.get("fingerprint") != fingerprint:
                return None
            if self._timestamp(entry) < int(time.time()) - self.retention_days * 86400:
                self._entries.pop(self._key(source, job_id), None)
                self._save_locked()
                return None
            return entry

    def put(
        self, source: str, job_id: str, fingerprint: str, decision: dict[str, object]
    ) -> None:
        with self._lock:
            self._entries[self._key(source, job_id)] = {
                "fingerprint": fingerprint,
                "decision": decision,
                "timestamp": int(time.time()),
            }
            self._purge_locked()

    def purge(self, max_days: int | None = None) -> int:
        with self._lock:
            return self._purge_locked(max_days)

    def _purge_locked(self, max_days: int | None = None) -> int:
        effective_days = self.retention_days if max_days is None else max(1, max_days)
        cutoff = int(time.time()) - effective_days * 86400
        kept = [
            (key, value)
            for key, value in self._entries.items()
            if self._timestamp(value) >= cutoff
        ]
        kept.sort(key=lambda pair: self._timestamp(pair[1]))
        if len(kept) > self.max_items:
            kept = kept[-self.max_items :]
        removed = len(self._entries) - len(kept)
        self._entries = dict(kept)
        self._save_locked()
        return removed

    @staticmethod
    def _timestamp(value: dict[str, object]) -> int:
        raw_timestamp = value.get("timestamp", 0)
        if not isinstance(raw_timestamp, (int, str, bytes, bytearray)):
            return 0
        try:
            return int(raw_timestamp)
        except (TypeError, ValueError):
            return 0

    def _save_locked(self) -> None:
        # A unique temporary name also protects this file if two bot processes overlap.
        temporary = self.file_path.with_name(
            f".{self.file_path.name}.{os.getpid()}.{get_ident()}.tmp"
        )
        temporary.write_text(
            json.dumps(self._entries, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.file_path)
