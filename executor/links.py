"""
Resolves the Google redirect links of a grounded call (Hound sources).

A grounded Gemini call returns each source as a Google redirect
(https://vertexaisearch.cloud.google.com/grounding-api-redirect/...) with only the
site name as its title. This module asks that redirect where it leads WITHOUT
following it (one GET per source, the Location header is read, the body never is),
all sources in parallel, so the caller gets the real page address.

Rules (docs/m0 C1 section 4.1):
  - Only an exact https vertexaisearch.cloud.google.com/grounding-api-redirect/ URL is
    ever requested. Any other URL is returned untouched and nothing is fetched, so a
    model-provided URL can never make Kernel call an arbitrary host.
  - 3 s per source, 5 s in total. When time runs out, the sources not yet answered
    keep their redirect.
  - A failure of any kind (timeout, network error, not a redirect, a Location that is
    missing, empty, relative, not http(s), or on Google's own redirect host) leaves that source as it was:
    `url` = the redirect, `resolved` = false. Nothing here ever raises into the call.
  - No model call, no store, no cookies kept past the request, no secret.
Each source is `{title, url, redirect_url, resolved}`: `url` is the real page address
when `resolved` is true (otherwise the redirect), `redirect_url` is always the original.
"""
import asyncio

import httpx

REDIRECT_HOST = "vertexaisearch.cloud.google.com"
REDIRECT_PATH_PREFIX = "/grounding-api-redirect/"
PER_SOURCE_TIMEOUT_S = 3.0
TOTAL_TIMEOUT_S = 5.0
MAX_FETCHES = 30          # distinct redirects requested per call; any beyond stay unresolved
MAX_LOCATION_CHARS = 8192
_REDIRECT_STATUSES = (301, 302, 303, 307, 308)

# Test hook: tests inject an httpx.MockTransport so no live request is ever made.
# None (production) means the real network transport.
_transport = None


def source(title, url):
    """A grounding source as the executor returns it, before any resolution."""
    return {"title": title, "url": url, "redirect_url": url, "resolved": False}


def is_google_redirect(url):
    """True only for an exact https Google grounding redirect URL: the one kind of
    URL Kernel is willing to request."""
    if type(url) is not str or not url:
        return False
    try:
        parsed = httpx.URL(url)
    except Exception:
        return False
    return (parsed.scheme == "https" and parsed.host == REDIRECT_HOST and parsed.port is None
            and not parsed.userinfo and parsed.path.startswith(REDIRECT_PATH_PREFIX))


def _target_of(location):
    """The real page a Location header points to, or None when it is not one: empty,
    oversized, containing whitespace or control characters, relative, not http(s), or
    on Google's own redirect host (which is never a source page). An absolute Location
    is returned exactly as sent."""
    if not location or len(location) > MAX_LOCATION_CHARS:
        return None
    location = location.strip()
    if not location or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in location):
        return None
    try:
        parsed = httpx.URL(location)
    except Exception:
        return None
    if not parsed.is_absolute_url or parsed.scheme not in ("http", "https") or not parsed.host:
        return None
    if parsed.host == REDIRECT_HOST:
        return None
    return location


async def _locate(client, url):
    """Where one redirect leads (a str), or None. Reads the status line and headers
    only: the response is closed without reading its body."""
    async with client.stream("GET", url) as response:
        if response.status_code not in _REDIRECT_STATUSES:
            return None
        return _target_of(response.headers.get("location"))


async def _locate_bounded(client, url):
    try:
        return await asyncio.wait_for(_locate(client, url), timeout=PER_SOURCE_TIMEOUT_S)
    except Exception:  # noqa: BLE001 -- includes timeouts and network errors: the source keeps its redirect
        return None


async def resolve_sources(sources):
    """Returns a new list in the same order with each Google redirect resolved where
    possible. Never raises (cancellation of the request itself is still honoured)."""
    resolved_sources = [dict(s) for s in sources]
    try:
        urls = []
        for s in resolved_sources:
            url = s.get("redirect_url")
            if is_google_redirect(url) and url not in urls and len(urls) < MAX_FETCHES:
                urls.append(url)
        if not urls:
            return resolved_sources
        answers = await _fetch_all(urls)
        for s in resolved_sources:
            target = answers.get(s.get("redirect_url"))
            if target:
                s["url"], s["resolved"] = target, True
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 -- never fail the call over a link
        return [dict(s) for s in sources]
    return resolved_sources


async def _fetch_all(urls):
    """{redirect url: real page address} for the redirects answered within the total cap."""
    kwargs = {"follow_redirects": False, "timeout": httpx.Timeout(PER_SOURCE_TIMEOUT_S), "trust_env": False,
              "headers": {"Accept": "*/*"}}
    if _transport is not None:
        kwargs["transport"] = _transport
    answers = {}
    async with httpx.AsyncClient(**kwargs) as client:
        tasks = {asyncio.ensure_future(_locate_bounded(client, url)): url for url in urls}
        try:
            done, pending = await asyncio.wait(tasks, timeout=TOTAL_TIMEOUT_S)
        finally:
            # whatever happened (total cap, or the request itself was cancelled), no task outlives this call
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        for task in done:
            if not task.cancelled() and task.exception() is None and task.result():
                answers[tasks[task]] = task.result()
    return answers


def summary(sources):
    """(resolved, total) for the log line: counts only, never a URL."""
    return sum(1 for s in sources if s.get("resolved")), len(sources)
