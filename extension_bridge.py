"""Local receiver for complete, auditable LinkedIn extension batches."""

from __future__ import annotations

import json
import logging
import queue
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from config import BotConfig
from models import JobItem
from providers.linkedin_common import (
    exact_search_url,
    expanded_search_urls,
    merge_linkedin_jobs,
    normalise_job,
)


@dataclass(frozen=True)
class ExtensionSearchBatch:
    search_url: str
    state: str
    jobs: tuple[JobItem, ...]
    diagnostics: dict[str, Any]
    error: str = ""
    reference_jobs: tuple[JobItem, ...] = ()

    @property
    def complete(self) -> bool:
        reached_target = bool(self.diagnostics.get("firstPageTargetReached"))
        scroll_stabilised = (
            bool(self.diagnostics.get("reachedEnd"))
            and int(self.diagnostics.get("stableRounds", 0) or 0) >= 3
        )
        return (
            self.state in {"complete", "empty"}
            and (reached_target or scroll_stabilised)
            and bool(self.diagnostics.get("firstPageTargetComplete", True))
            and not bool(self.diagnostics.get("challengeDetected"))
        )


@dataclass(frozen=True)
class ExtensionBatch:
    run_id: str
    searches: tuple[ExtensionSearchBatch, ...]
    reason: str = ""


IngestCallback = Callable[[ExtensionBatch], dict[str, Any]]


def _job_from_payload(raw: object, search_url: str = "") -> JobItem | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    url = str(raw.get("url") or "").strip()
    job_id = str(raw.get("id") or "").strip()
    if not title or not url:
        return None
    posted_text = str(
        raw.get("posted") or raw.get("postedAt") or raw.get("posted_text") or ""
    ).strip()
    published_at = str(raw.get("published_at") or raw.get("publishedAt") or "").strip()
    metadata = raw.get("metadata")
    extension_card = dict(metadata) if isinstance(metadata, dict) else {}
    if search_url:
        extension_card["searchUrl"] = exact_search_url(search_url)
    features: dict[str, object] = {"extension_card": extension_card}
    if search_url:
        scope = exact_search_url(search_url)
        features.update(
            {
                "linkedin_search_urls": [scope],
                "linkedin_recency_evidence": [
                    {
                        "search_url": scope,
                        "posted_text": posted_text,
                        "published_at": published_at,
                    }
                ],
                "linkedin_posted_text": posted_text,
                "linkedin_published_at_raw": published_at,
            }
        )
    company = str(raw.get("company") or "Empresa no indicada").strip()
    location = str(raw.get("location") or "Ubicación no indicada").strip()

    # Generic safeguard against Extension CSS scraping bugs
    if company.lower() == title.lower() or title.lower() in company.lower():
        if len(company) > 25:
            company = "Empresa no indicada"
    if location.lower() == title.lower() or title.lower() in location.lower():
        if len(location) > 25:
            location = "Ubicación no indicada"

    return normalise_job(
        JobItem(
            id=job_id,
            title=title,
            company=company,
            location=location,
            url=url,
            source="linkedin",
            posted_within_1h=bool(raw.get("posted_within_1h"))
            or any(
                marker in posted_text.lower()
                for marker in ("just now", "min", "minute", "hora", "hour", "hace 1 h")
            ),
            published_at=published_at,
            features=features,
        )
    )


def _search_from_payload(raw: object) -> ExtensionSearchBatch | None:
    if not isinstance(raw, dict):
        return None
    url = str(raw.get("url") or raw.get("searchUrl") or "").strip()
    if not url:
        return None
    payload_jobs = raw.get("jobs")
    if not isinstance(payload_jobs, list):
        payload_jobs = []
    search_url = exact_search_url(url)

    def parse_jobs(value: object) -> dict[str, JobItem]:
        parsed: dict[str, JobItem] = {}
        for raw_job in value if isinstance(value, list) else ():
            job = _job_from_payload(raw_job, search_url)
            if job:
                # The card can omit location, so retain the exact listing scope
                # that produced it for the central geographic decision.
                extension_card = dict(job.features.get("extension_card") or {})
                extension_card["searchUrl"] = search_url
                job.features["extension_card"] = extension_card
                parsed[job.id] = (
                    merge_linkedin_jobs(parsed[job.id], job)
                    if job.id in parsed
                    else job
                )
        return parsed

    jobs_by_id = parse_jobs(payload_jobs)
    reference_by_id = parse_jobs(raw.get("referenceJobs") or raw.get("reference_jobs"))
    raw_diagnostics = raw.get("diagnostics")
    diagnostics = (
        {str(key): value for key, value in raw_diagnostics.items()}
        if isinstance(raw_diagnostics, dict)
        else {}
    )
    state = str(raw.get("state") or "partial").lower()
    if state not in {
        "complete",
        "partial",
        "failed",
        "blocked",
        "empty",
        "rate_limited",
    }:
        state = "partial"
    return ExtensionSearchBatch(
        search_url=search_url,
        state=state,
        jobs=tuple(jobs_by_id.values()),
        diagnostics=diagnostics,
        error=str(raw.get("error") or ""),
        reference_jobs=tuple(reference_by_id.values()),
    )


def batch_from_payload(payload: dict[str, Any]) -> ExtensionBatch | None:
    """Accept the v2 batch protocol and a traceable legacy single-search batch."""
    raw_searches = payload.get("searches")
    if not isinstance(raw_searches, list):
        legacy_url = str(payload.get("searchUrl") or payload.get("url") or "")
        raw_jobs = payload.get("jobs")
        if not legacy_url or not isinstance(raw_jobs, list):
            return None
        raw_searches = [
            {
                "url": legacy_url,
                "jobs": raw_jobs,
                "state": "partial",
                "diagnostics": {"legacyPayload": True},
            }
        ]
    searches = tuple(
        search
        for raw in raw_searches
        if (search := _search_from_payload(raw)) is not None
    )
    if not searches:
        return None
    run_id = str(payload.get("run_id") or payload.get("runId") or uuid.uuid4().hex)[
        :128
    ]
    return ExtensionBatch(
        run_id=run_id, searches=searches, reason=str(payload.get("reason") or "")
    )


@dataclass
class ExtensionBridge:
    config: BotConfig
    logger: logging.Logger
    ingest_callback: IngestCallback
    _server: ThreadingHTTPServer | None = None
    _thread: threading.Thread | None = None
    _ingest_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _run_ids_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _accepted_run_ids: OrderedDict[str, None] = field(
        default_factory=OrderedDict, repr=False
    )
    _queue: queue.Queue = field(default_factory=queue.Queue, repr=False)
    _worker_started: bool = field(default=False, repr=False)
    _worker_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def submit(self, batch: ExtensionBatch) -> bool:
        """Accept a browser batch immediately and reconcile it exactly once."""
        with self._run_ids_lock:
            if batch.run_id in self._accepted_run_ids:
                return False
            self._accepted_run_ids[batch.run_id] = None
            # UUID run IDs are short-lived. Keep duplicate protection bounded
            # without making the bridge's lifetime depend on past batches.
            while len(self._accepted_run_ids) > 512:
                self._accepted_run_ids.popitem(last=False)

        received = sum(len(search.jobs) for search in batch.searches)

        with self._worker_lock:
            if not self._worker_started:
                threading.Thread(
                    target=self._worker_loop,
                    name="LinkedInIngest-Worker",
                    daemon=True,
                ).start()
                self._worker_started = True

        self._queue.put((batch, received))
        return True

    def _worker_loop(self) -> None:
        while True:
            try:
                batch, received = self._queue.get()
                self._process(batch, received)
            except Exception as e:
                self.logger.error("Error in bridge worker loop: %s", e)
            finally:
                self._queue.task_done()

    def _process(self, batch: ExtensionBatch, received: int) -> None:
        try:
            # Processing and auditing can take longer than an MV3 worker lives.
            # Never keep the browser POST open while the application handles it.
            with self._ingest_lock:
                stats = self.ingest_callback(batch)
            self.logger.info(
                "Extension ingest | run_id=%s searches=%d received=%d stats=%s",
                batch.run_id,
                len(batch.searches),
                received,
                stats,
            )
        except Exception:
            self.logger.exception(
                "Extension ingest failed | run_id=%s searches=%d received=%d",
                batch.run_id,
                len(batch.searches),
                received,
            )

    @property
    def port(self) -> int:
        return (
            self.config.linkedin_extension_port
            if self._server is None
            else int(self._server.server_address[1])
        )

    def start(self) -> None:
        if self._server is not None:
            return
        if self.config.linkedin_extension_host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError(
                "El receptor de LinkedIn sólo puede escuchar en localhost."
            )
        bridge = self

        class RequestHandler(BaseHTTPRequestHandler):
            server_version = "LinkedInExtensionBridge/2.0"

            def log_message(self, fmt: str, *args: object) -> None:
                bridge.logger.info("Extension bridge | " + fmt, *args)

            def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                except BrokenPipeError:
                    # A browser shutdown must not turn a completed batch into
                    # a noisy bridge traceback or cause a duplicate retry.
                    bridge.logger.info(
                        "Extension bridge client disconnected before response"
                    )

            def _payload(self) -> dict[str, Any] | None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return None
                if length <= 0 or length > 2_000_000:
                    return None
                try:
                    decoded = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return None
                return decoded if isinstance(decoded, dict) else None

            def do_GET(self) -> None:
                path = urlsplit(self.path).path
                if path == "/health":
                    self._json(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "service": "linkedin-extension-bridge",
                            "protocol": 2,
                        },
                    )
                elif path == "/settings":
                    search_urls = expanded_search_urls(
                        [
                            *getattr(bridge.config, "linkedin_urls", ()),
                            getattr(bridge.config, "linkedin_url", ""),
                        ],
                        getattr(
                            bridge.config, "linkedin_time_windows_seconds", (1200, 3600)
                        ),
                    )
                    delay_min = max(
                        0.0,
                        float(
                            getattr(
                                bridge.config, "linkedin_inter_search_min_seconds", 3.0
                            )
                        ),
                    )
                    delay_max = max(
                        delay_min,
                        float(
                            getattr(
                                bridge.config, "linkedin_inter_search_max_seconds", 6.0
                            )
                        ),
                    )
                    self._json(
                        HTTPStatus.OK,
                        {
                            "enabled": bridge.config.linkedin_extension_enabled,
                            "searchUrls": search_urls,
                            "refreshSeconds": bridge.config.linkedin_extension_refresh_seconds,
                            "interSearchDelayMinSeconds": delay_min,
                            "interSearchDelayMaxSeconds": delay_max,
                            # The useful scope is the first results page, ordered by
                            # recency. Accept legacy zero as the same 25-card cap.
                            "maxJobs": min(
                                25,
                                max(1, int(bridge.config.linkedin_max_jobs or 25)),
                            ),
                            "firstPageOnly": True,
                            "protocol": 2,
                        },
                    )
                else:
                    self._json(
                        HTTPStatus.NOT_FOUND, {"ok": False, "error": "unknown endpoint"}
                    )

            def do_POST(self) -> None:
                path = urlsplit(self.path).path
                payload = self._payload()
                if payload is None:
                    self._json(
                        HTTPStatus.BAD_REQUEST,
                        {"ok": False, "error": "invalid JSON payload"},
                    )
                    return
                if path == "/status":
                    bridge.logger.info(
                        "Extension status | state=%s detail=%s",
                        str(payload.get("state") or "unknown")[:80],
                        payload.get("detail") or {},
                    )
                    self._json(HTTPStatus.OK, {"ok": True})
                    return
                if path != "/ingest":
                    self._json(
                        HTTPStatus.NOT_FOUND, {"ok": False, "error": "unknown endpoint"}
                    )
                    return
                batch = batch_from_payload(payload)
                if batch is None:
                    self._json(
                        HTTPStatus.BAD_REQUEST,
                        {"ok": False, "error": "searches must contain URL and jobs"},
                    )
                    return
                received = sum(len(search.jobs) for search in batch.searches)
                accepted = bridge.submit(batch)
                self._json(
                    HTTPStatus.ACCEPTED if accepted else HTTPStatus.OK,
                    {
                        "ok": True,
                        "accepted": accepted,
                        "duplicate": not accepted,
                        "run_id": batch.run_id,
                        "received": received,
                    },
                )

        self._server = ThreadingHTTPServer(
            (self.config.linkedin_extension_host, self.config.linkedin_extension_port),
            RequestHandler,
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="LinkedInExtensionBridge",
            daemon=True,
        )
        self._thread.start()
        self.logger.info(
            "LinkedIn extension bridge listening on http://%s:%d",
            self.config.linkedin_extension_host,
            self.port,
        )

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None
