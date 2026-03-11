"""Webhook URL validation and outbound delivery helpers."""

import ipaddress
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

# Blocked IP ranges: loopback, private, link-local, metadata endpoints
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # loopback
    ipaddress.ip_network("10.0.0.0/8"),         # RFC-1918
    ipaddress.ip_network("172.16.0.0/12"),      # RFC-1918
    ipaddress.ip_network("192.168.0.0/16"),     # RFC-1918
    ipaddress.ip_network("169.254.0.0/16"),     # link-local / cloud metadata
    ipaddress.ip_network("0.0.0.0/8"),          # "this" network
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 unique-local
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
]


def _is_private_host(hostname: str) -> bool:
    """Resolve hostname and check if it points to a blocked private/reserved IP."""
    try:
        addr_infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve webhook hostname: {hostname}") from exc

    for _, _, _, _, sockaddr in addr_infos:
        ip = ipaddress.ip_address(sockaddr[0])
        for network in _BLOCKED_NETWORKS:
            if ip in network:
                return True
    return False


def validate_webhook_url(webhook_url: str) -> str:
    """Validate scheme/host and block private-address destinations."""
    normalized_url = webhook_url.strip()
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Webhook URL must include http:// or https://")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Webhook URL has no valid hostname")

    if _is_private_host(hostname):
        raise ValueError("Webhook URL must not point to a private or reserved IP address")

    return normalized_url


def deliver_webhook(webhook_url: str, job_id: str, result: dict) -> None:
    """Send a completion payload to a validated webhook endpoint."""
    safe_webhook_url = validate_webhook_url(webhook_url)
    payload = {
        "job_id": job_id,
        "status": "COMPLETE",
        "result": result,
        "delivered_at": datetime.now(timezone.utc).isoformat(),
    }
    with httpx.Client(timeout=10.0) as client:
        response = client.post(safe_webhook_url, json=payload)
        response.raise_for_status()
