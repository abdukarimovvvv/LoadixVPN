from __future__ import annotations

import asyncio
import logging
import uuid

log = logging.getLogger(__name__)

OVN_CONTAINER = "amnezia-openvpn"
PKI_DIR = "/etc/openvpn"
SERVER_IP = "57.131.153.153"
SERVER_PORT = 34949


async def _exec(container: str, *cmd: str, cwd: str | None = None) -> str:
    full_cmd = ["docker", "exec"]
    if cwd:
        full_cmd += ["-w", cwd]
    full_cmd += [container, *cmd]
    proc = await asyncio.create_subprocess_exec(
        *full_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"docker exec {' '.join(cmd)}: {err.decode().strip()}")
    return out.decode().strip()


def _clean_pem(pem: str) -> str:
    """Extract only the certificate block from PEM output."""
    lines = pem.splitlines()
    result, inside = [], False
    for line in lines:
        if "-----BEGIN" in line:
            inside = True
        if inside:
            result.append(line)
        if "-----END" in line:
            inside = False
    return "\n".join(result)


async def generate(name: str) -> str:
    """Generate OpenVPN client config (.ovpn) and return as string."""
    client_id = f"lx_{uuid.uuid4().hex[:12]}"

    # 1. Generate client certificate request
    await _exec(OVN_CONTAINER,
                "easyrsa", "--batch", f"--pki-dir={PKI_DIR}/pki",
                "gen-req", client_id, "nopass",
                cwd=PKI_DIR)

    # 2. Sign the request
    await _exec(OVN_CONTAINER,
                "easyrsa", "--batch", f"--pki-dir={PKI_DIR}/pki",
                "sign-req", "client", client_id,
                cwd=PKI_DIR)

    # 3. Read components
    ca = await _exec(OVN_CONTAINER, "cat", f"{PKI_DIR}/ca.crt")
    cert_raw = await _exec(OVN_CONTAINER, "cat", f"{PKI_DIR}/pki/issued/{client_id}.crt")
    cert = _clean_pem(cert_raw)
    key = await _exec(OVN_CONTAINER, "cat", f"{PKI_DIR}/pki/private/{client_id}.key")
    ta = await _exec(OVN_CONTAINER, "cat", f"{PKI_DIR}/ta.key")

    # 4. Assemble .ovpn
    return (
        f"# LoadixVPN — {name}\n"
        f"client\n"
        f"dev tun\n"
        f"proto udp\n"
        f"remote {SERVER_IP} {SERVER_PORT}\n"
        f"resolv-retry infinite\n"
        f"nobind\n"
        f"persist-key\n"
        f"persist-tun\n"
        f"cipher AES-256-GCM\n"
        f"data-ciphers AES-256-GCM\n"
        f"auth SHA512\n"
        f"verb 3\n"
        f"<ca>\n{ca}\n</ca>\n"
        f"<cert>\n{cert}\n</cert>\n"
        f"<key>\n{key}\n</key>\n"
        f"key-direction 1\n"
        f"<tls-auth>\n{ta}\n</tls-auth>\n"
    )
