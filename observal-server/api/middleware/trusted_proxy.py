# SPDX-FileCopyrightText: 2026 Yash Gadgil <yashgadgil08@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Trusted proxy middleware (SEC-003).

Replaces Uvicorn's --proxy-headers flag with app-layer proxy handling
that uses the same trust config (security.trusted_proxy_ips) as the
rate limiter.

When the TCP peer is a trusted proxy this middleware:
  1. Resolves the real client IP from X-Forwarded-For (rightmost non-trusted)
     and overwrites request.scope["client"] so that ALL downstream consumers
     (audit, download tracker, rate limiter, etc.) see the correct IP.
  2. Reads X-Forwarded-Proto and sets request.scope["scheme"].

Unlike Uvicorn's --proxy-headers (which takes the leftmost XFF entry and
is trivially spoofable), this walks the header right-to-left and skips
trusted proxy IPs, using the same algorithm as _get_real_ip() in
api/ratelimit.py.

The setting supports both plain IPs and CIDR notation (e.g.
"172.16.0.0/12,10.0.0.0/8") so Docker-internal networks are matched
regardless of the container IP assigned at runtime.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

from loguru import logger as optic
from starlette.middleware.base import BaseHTTPMiddleware

import services.dynamic_settings as ds

if TYPE_CHECKING:
    from starlette.requests import Request


def _parse_trusted(raw: str) -> tuple[set[str], list[ipaddress.IPv4Network | ipaddress.IPv6Network]]:
    """Parse the trusted proxy setting into exact IPs and CIDR networks."""
    exact: set[str] = set()
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "/" in entry:
            try:
                networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError:
                optic.warning("invalid CIDR in security.trusted_proxy_ips: {}", entry)
        else:
            exact.add(entry)
    return exact, networks


def _is_trusted(ip: str, exact: set[str], networks: list) -> bool:
    """Check if an IP is trusted (exact match or within a CIDR range)."""
    if ip in exact:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in networks)


class TrustedProxyMiddleware(BaseHTTPMiddleware):
    """Resolve real client IP and scheme from proxy headers when the TCP peer is trusted."""

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else None
        trusted_str = ds.get_sync("security.trusted_proxy_ips")

        if not trusted_str or not client_ip:
            return await call_next(request)

        exact, networks = _parse_trusted(trusted_str)

        if _is_trusted(client_ip, exact, networks):
            # Resolve real client IP from X-Forwarded-For (rightmost non-trusted)
            forwarded = request.headers.get("x-forwarded-for", "")
            if forwarded:
                ips = [ip.strip() for ip in forwarded.split(",")]
                for ip in reversed(ips):
                    if not _is_trusted(ip, exact, networks):
                        # Overwrite scope so all downstream sees the real IP
                        request.scope["client"] = (ip, request.scope["client"][1])
                        break

            # Set scheme from X-Forwarded-Proto
            proto = request.headers.get("x-forwarded-proto")
            if proto in ("http", "https"):
                request.scope["scheme"] = proto

        return await call_next(request)
