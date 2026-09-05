"""Minimal Squiggle API client.

Squiggle (api.squiggle.com.au) is free and needs no key, but it asks that bots
identify themselves and behave: cache what you fetch, don't hammer it, don't
fire off simultaneous batches. Non-compliant bots get blocked at the edge, so
everything here goes through one throttled entry point.

Stdlib only, deliberately -- this runs in a bare GitHub Actions container with
no pip install step.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.squiggle.com.au/"

# Squiggle asks for a UserAgent identifying the app and carrying a contact address.
USER_AGENT = (
    "Nine-Lives/1.0 "
    "(+https://github.com/cjkirby79/Nine-lives; clark.kirby@proton.me)"
)

MIN_INTERVAL_SECONDS = 1.5
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3

_last_request_at = 0.0


class SquiggleError(RuntimeError):
    """Any failure to get usable data out of Squiggle."""


def _throttle():
    global _last_request_at
    gap = time.monotonic() - _last_request_at
    if gap < MIN_INTERVAL_SECONDS:
        time.sleep(MIN_INTERVAL_SECONDS - gap)
    _last_request_at = time.monotonic()


def query(q, **params):
    """GET ?q=<q>;k=v;k=v and return the decoded payload.

    Squiggle uses semicolon-separated parameters rather than a normal query
    string, so this builds the URL by hand.
    """
    if os.environ.get("NINE_LIVES_FORCE_FAIL"):
        raise SquiggleError("NINE_LIVES_FORCE_FAIL is set (simulated outage)")

    parts = [f"q={q}"] + [f"{k}={v}" for k, v in sorted(params.items()) if v is not None]
    url = BASE + "?" + urllib.parse.quote(";".join(parts), safe="=;&?")

    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _throttle()
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
            payload = json.loads(body)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        except json.JSONDecodeError as exc:
            last_error = f"malformed JSON from {url}: {exc}"
        else:
            if not isinstance(payload, dict) or q not in payload:
                last_error = f"unexpected payload shape from {url}: {body[:200]}"
            else:
                return payload[q]

        if attempt < MAX_ATTEMPTS:
            time.sleep(2 ** attempt)

    raise SquiggleError(f"{q} failed after {MAX_ATTEMPTS} attempts -- {last_error}")


def cached_query(cache_path, q, **params):
    """Query, but read from disk if we already have it.

    Only ever use this for data that cannot change again -- completed past
    seasons. A cache hit costs Squiggle nothing, which is the point.
    """
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (json.JSONDecodeError, OSError):
            pass  # corrupt cache, fall through and refetch

    data = query(q, **params)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, separators=(",", ":"), sort_keys=True)
    os.replace(tmp, cache_path)
    return data
