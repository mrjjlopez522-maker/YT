"""A deliberately polite HTTP client for public APIs.

* identifies itself (User-Agent with a contact address, as Wikimedia requires)
* spaces requests to the same host (min_interval)
* retries transient failures with backoff
* honours 429 / Retry-After; if the server asks for a longer pause than we are
  willing to wait, it raises RateLimitedError instead of working around the limit
* distinguishes "blocked by network policy" from provider failures
* never logs secrets (URLs are redacted by the logging filter)
"""
from __future__ import annotations

import email.utils
import os
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests

from . import __version__
from .errors import NetworkBlockedError, ProviderError, RateLimitedError
from .logging_setup import get_logger
from .retry import retry

log = get_logger("studio.api")


def default_user_agent() -> str:
    contact = os.environ.get("STUDIO_CONTACT_EMAIL") or "contact-not-configured"
    return f"ShortsStudio/{__version__} (research tool; {contact}) python-requests"


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        parsed = email.utils.parsedate_to_datetime(value)
        return max(0.0, parsed.timestamp() - time.time()) if parsed else None


class HttpClient:
    def __init__(self, *, user_agent: str | None = None, timeout: float = 20.0, min_interval: float = 1.0,
                 attempts: int = 3, max_retry_after: float = 60.0, session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent or default_user_agent()
        self.timeout = timeout
        self.min_interval = min_interval
        self.attempts = attempts
        self.max_retry_after = max_retry_after
        self.sleep = sleep
        self._last_call: dict[str, float] = {}
        self.request_count = 0

    def _pace(self, host: str) -> None:
        last = self._last_call.get(host)
        if last is not None:
            wait = self.min_interval - (time.monotonic() - last)
            if wait > 0:
                self.sleep(wait)
        self._last_call[host] = time.monotonic()

    def _once(self, method: str, url: str, **kwargs) -> requests.Response:
        host = urlparse(url).netloc
        self._pace(host)
        self.request_count += 1
        try:
            resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.exceptions.ProxyError as exc:
            raise NetworkBlockedError(f"{host} is blocked by the network policy",
                                      hint="allow this host in your environment's network settings") from exc
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            raise ProviderError(f"Network error calling {host}: {exc.__class__.__name__}", retryable=True) from exc
        log.info("%s %s -> %s", method, resp.url if hasattr(resp, "url") else url, resp.status_code)
        if resp.status_code == 429:
            wait = _retry_after_seconds(resp.headers.get("Retry-After")) or 5.0
            if wait > self.max_retry_after:
                raise RateLimitedError(f"{host} asked us to wait {wait:.0f}s (limit {self.max_retry_after:.0f}s)",
                                       hint="try again later; the client will not bypass rate limits")
            log.warning("429 from %s; honouring Retry-After %.1fs", host, wait)
            self.sleep(wait)
            raise ProviderError(f"429 from {host}", retryable=True)
        if resp.status_code >= 500:
            raise ProviderError(f"{host} returned HTTP {resp.status_code}", retryable=True)
        if resp.status_code >= 400:
            raise ProviderError(f"{host} returned HTTP {resp.status_code}: {resp.text[:200]}")
        return resp

    def get(self, url: str, *, params: dict | None = None, headers: dict | None = None, **kwargs) -> requests.Response:
        return retry(lambda: self._once("GET", url, params=params, headers=headers, **kwargs),
                     attempts=self.attempts, what=f"GET {urlparse(url).netloc}", sleep=self.sleep)

    def get_json(self, url: str, *, params: dict | None = None, headers: dict | None = None):
        resp = self.get(url, params=params, headers=headers)
        try:
            return resp.json()
        except ValueError as exc:
            raise ProviderError(f"Non-JSON response from {urlparse(url).netloc}") from exc

    def post_json(self, url: str, *, json_body: dict, headers: dict | None = None) -> requests.Response:
        return retry(lambda: self._once("POST", url, json=json_body, headers=headers),
                     attempts=self.attempts, what=f"POST {urlparse(url).netloc}", sleep=self.sleep)

    def download(self, url: str, dest: Path, *, max_bytes: int = 2_000_000_000) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")

        def _do():
            resp = self._once("GET", url, stream=True)
            total = 0
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ProviderError(f"Download exceeds {max_bytes} bytes: {url}")
                    fh.write(chunk)
            return dest

        retry(_do, attempts=self.attempts, what=f"download {urlparse(url).netloc}", sleep=self.sleep)
        tmp.replace(dest)
        return dest
