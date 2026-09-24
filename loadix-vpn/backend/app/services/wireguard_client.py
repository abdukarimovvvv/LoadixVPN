from __future__ import annotations

import asyncio
import logging
import re

log = logging.getLogger(__name__)

_CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _safe_wg_name(name: str, fallback: str = "device") -> str:
    """Sanitize a device name for use in the WireGuard [Interface] comment.
    Some WireGuard client apps (Android/iOS) derive the tunnel's displayed
    name from this first comment line when importing a .conf — anything
    outside plain ASCII letters/digits/spaces/hyphen (Cyrillic, emoji,
    other punctuation) can make the app reject the file as having an
    "invalid name" on import, even though the file itself is otherwise
    valid WireGuard syntax."""
    if not name:
        return fallback
    lowered = name.lower()
    translit = "".join(_CYRILLIC_TO_LATIN.get(ch, ch) for ch in lowered)
    safe = re.sub(r"[^a-zA-Z0-9 _-]+", "", translit).strip()
    return safe or fallback


WG_CONTAINER = "amnezia-wireguard"
WG_CONF = "/opt/amnezia/wireguard/wg0.conf"
WG_PSK_FILE = "/opt/amnezia/wireguard/wireguard_psk.key"
WG_SRV_PUB_FILE = "/opt/amnezia/wireguard/wireguard_server_public_key.key"
SERVER_IP = "57.131.153.153"
SERVER_PORT = 44327
DNS = "1.1.1.1, 8.8.8.8"


async def _exec(container: str, *cmd: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", container, *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"docker exec {' '.join(cmd)}: {err.decode().strip()}")
    return out.decode().strip()


async def _exec_stdin(container: str, data: str, *cmd: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", "-i", container, *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(data.encode())
    if proc.returncode != 0:
        raise RuntimeError(f"docker exec_stdin {' '.join(cmd)}: {err.decode().strip()}")
    return out.decode().strip()


async def generate(name: str, *, server=None) -> str:
    """Generate WireGuard client config, add peer to server, return .conf string.

    When `server` is given and isn't the local node, delegates to that
    node's node-agent over HTTP instead (see node_agent_client.py) — the
    local docker socket can only ever manage containers on this same host.
    """
    if server is not None and not server.is_local:
        from app.services.node_agent_client import remote_generate

        return await remote_generate(server, "wireguard", name)

    # 1. Generate client keys inside container
    priv = await _exec(WG_CONTAINER, "wg", "genkey")
    pub = await _exec_stdin(WG_CONTAINER, priv + "\n", "wg", "pubkey")

    # 2. Get server public key and PSK
    srv_pub = await _exec(WG_CONTAINER, "cat", WG_SRV_PUB_FILE)
    psk = await _exec(WG_CONTAINER, "cat", WG_PSK_FILE)

    # 3. Find next available client IP
    conf_text = await _exec(WG_CONTAINER, "cat", WG_CONF)
    used = {int(m) for m in re.findall(r"AllowedIPs\s*=\s*10\.8\.1\.(\d+)/32", conf_text)}
    used.add(1)  # 10.8.1.1 is the server's own wg0 address, never assign it to a client
    n = 2
    while n in used:
        n += 1
    client_ip = f"10.8.1.{n}"

    # 4. Add peer in-memory (instant, no restart needed)
    await _exec(WG_CONTAINER, "wg", "set", "wg0",
                "peer", pub,
                "preshared-key", WG_PSK_FILE,
                "allowed-ips", f"{client_ip}/32")

    # 5. Persist peer to config file for survive restarts
    safe_name = _safe_wg_name(name)
    peer_block = (
        f"\\n[Peer]\\n"
        f"# {safe_name}\\n"
        f"PublicKey = {pub}\\n"
        f"PresharedKey = {psk}\\n"
        f"AllowedIPs = {client_ip}/32\\n"
    )
    await _exec(WG_CONTAINER, "sh", "-c", f"printf '{peer_block}' >> {WG_CONF}")

    # 6. Return client config string
    return (
        f"[Interface]\n"
        f"# {safe_name}\n"
        f"PrivateKey = {priv}\n"
        f"Address = {client_ip}/32\n"
        f"DNS = {DNS}\n\n"
        f"[Peer]\n"
        f"PublicKey = {srv_pub}\n"
        f"PresharedKey = {psk}\n"
        f"Endpoint = {SERVER_IP}:{SERVER_PORT}\n"
        f"AllowedIPs = 0.0.0.0/0\n"
        f"PersistentKeepalive = 25\n"
    )
