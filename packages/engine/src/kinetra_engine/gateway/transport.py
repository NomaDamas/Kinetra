"""HTTP transport for the gateway: stdlib only, injectable so tests never touch the network."""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlparse

from .budget import GatewayError

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class TransportError(GatewayError):
    """The request could not be completed (DNS, connect, timeout). No response was received."""


@dataclass(frozen=True)
class HttpRequest:
    url: str
    body: bytes = field(repr=False)
    headers: dict[str, str] = field(repr=False)  # carries Authorization; never printed
    timeout: float = 120.0


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes = field(repr=False)


Transport = Callable[[HttpRequest], HttpResponse]


def check_base_url(url: str) -> str:
    """https only; plain http is allowed for loopback (a local proxy or a test server) so a key never crosses a network in clear."""
    p = urlparse(url)
    if p.scheme == "https" and p.hostname:
        return url.rstrip("/")
    if p.scheme == "http" and p.hostname in LOOPBACK_HOSTS:
        return url.rstrip("/")
    raise GatewayError("base URL must be https (http only for localhost)")


def urllib_transport(req: HttpRequest) -> HttpResponse:
    r = urllib.request.Request(req.url, data=req.body, headers=req.headers, method="POST")
    try:
        with urllib.request.urlopen(r, timeout=req.timeout) as resp:  # noqa: S310 (scheme checked in check_base_url)
            return HttpResponse(resp.status, resp.read())
    except urllib.error.HTTPError as e:  # 4xx/5xx still carry a body with usage and an error message
        return HttpResponse(e.code, e.read())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TransportError(f"request failed: {type(e).__name__}") from None
