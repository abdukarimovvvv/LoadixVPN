from __future__ import annotations

import secrets
from urllib.parse import quote

SERVER_ADDR = "panel.loadix.cyou"
SERVER_PORT = 38443
# UDP port-hopping range, DNAT'd to SERVER_PORT via iptables on the server
# (PREROUTING -p udp --dport 20000:50000 -j DNAT --to-destination :38443).
# The client picks a random port in this range and can hop between them
# across reconnects, so the ISP can't just rate-limit/block one fixed
# destination port — it would have to block the whole range.
PORT_HOP_RANGE = "20000-50000"

# Salamander UDP obfuscation password (must match /etc/hysteria/config.yaml's
# obfs.salamander.password on the server). Without this, every client's QUIC
# packets carry Hysteria2's plain wire signature — easy for DPI to fingerprint
# and rate-limit/drop even when the auth itself succeeds, which is what was
# happening on Beeline mobile: connections authenticated fine but almost all
# subsequent stream traffic timed out ("no recent network activity"), a
# classic asymmetric-UDP-throttling pattern. Salamander wraps every packet in
# per-connection obfuscation so it no longer matches a plain QUIC/Hysteria2
# signature.
OBFS_PASSWORD = "ii32TuAqMZSzKnWPz3q0AA"


def generate_password() -> str:
    """Hysteria2 auth is HTTP-callback based (see hysteria_auth.py) — each
    node's standalone server has no per-peer config to write, so a device is
    just a random password checked against the shared DB on every connection
    (the node calls back into the one central backend regardless of which
    server the device belongs to)."""
    return secrets.token_urlsafe(24)


def build_uri(password: str, name: str, *, server=None) -> str:
    """Build a Hysteria2 share URI. Uses a specific Server row's own
    host/port when given (multi-location support), else falls back to the
    original hardcoded OVH values. Always includes Salamander obfs params —
    every node's config.yaml must set the matching obfs.salamander.password."""
    host = (server.hysteria_host if server and server.hysteria_host else None) or SERVER_ADDR
    port = (server.hysteria_port if server and server.hysteria_port else None) or SERVER_PORT
    tag = quote(name or "loadix")
    # mport enables client-side port hopping across PORT_HOP_RANGE; the base
    # host:port stays as a fallback for clients that don't support mport.
    return (
        f"hysteria2://{quote(password)}@{host}:{port}/"
        f"?sni={host}&obfs=salamander&obfs-password={quote(OBFS_PASSWORD)}"
        f"&mport={PORT_HOP_RANGE}"
        f"#{tag}"
    )
