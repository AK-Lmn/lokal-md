"""Process-level guard that refuses outbound connections to non-loopback addresses.

This is defence-in-depth for the "no hidden network requests" requirement: any library
that tries to reach a non-local host from inside the app process fails loudly instead of
silently transmitting data. It does NOT replace OS-level controls (firewall, air gap).
"""
from __future__ import annotations

import ipaddress
import os
import socket
import threading

_installed = False
_lock = threading.Lock()
BLOCKED_LOG: list[str] = []  # host strings only, never payloads


class OfflineViolation(ConnectionError):
    pass


def _is_local(addr) -> bool:
    if not isinstance(addr, tuple) or not addr:
        return True  # AF_UNIX etc.
    host = addr[0]
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    if host in ("localhost", "", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(host.split("%")[0])
        return ip.is_loopback or ip.is_unspecified
    except ValueError:
        return False


def install() -> None:
    """Idempotently patch socket connect calls. Set RHUSCRIBE_ALLOW_NETWORK=1 to disable
    (only the provisioning scripts do this; the operational app never does)."""
    global _installed
    if os.environ.get("RHUSCRIBE_ALLOW_NETWORK") == "1":
        return
    with _lock:
        if _installed:
            return
        orig_connect = socket.socket.connect
        orig_connect_ex = socket.socket.connect_ex

        def _check(address):
            if not _is_local(address):
                BLOCKED_LOG.append(str(address[0]))
                raise OfflineViolation(f"Blocked outbound connection to {address[0]} (offline mode)")

        def connect(self, address):
            _check(address)
            return orig_connect(self, address)

        def connect_ex(self, address):
            _check(address)
            return orig_connect_ex(self, address)

        socket.socket.connect = connect  # type: ignore[assignment]
        socket.socket.connect_ex = connect_ex  # type: ignore[assignment]
        _installed = True


def is_installed() -> bool:
    return _installed
