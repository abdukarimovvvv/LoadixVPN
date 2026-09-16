from __future__ import annotations

import asyncio
import logging
import re

log = logging.getLogger(__name__)

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


async def generate(name: str) -> str:
    """Generate WireGuard client config, add peer to server, return .conf string."""
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
    safe_name = name.replace("'", "").replace("\\", "")
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
