"""Claude Code release feed.

Canonical distribution (from claude.ai/install.sh -> bootstrap.sh):
  latest version : GET {BASE}/latest                      -> "2.1.158"
  manifest       : GET {BASE}/<version>/manifest.json     -> checksums + sizes
  binary         : GET {BASE}/<version>/<platform>/claude

Platforms: darwin-arm64 darwin-x64 linux-arm64 linux-x64
           linux-arm64-musl linux-x64-musl win32-x64 win32-arm64
"""
from __future__ import annotations

import hashlib
import json
import platform
import urllib.request
from pathlib import Path

BASE = "https://downloads.claude.ai/claude-code-releases"


def _get(url: str, binary: bool = False):
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310
        data = r.read()
    return data if binary else data.decode().strip()


def latest_version() -> str:
    return _get(f"{BASE}/latest")


def manifest(version: str) -> dict:
    return json.loads(_get(f"{BASE}/{version}/manifest.json"))


def detect_platform() -> str:
    sysname = platform.system().lower()
    arch = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(arch, arch)
    if sysname == "darwin":
        return f"darwin-{arch}"
    if sysname == "linux":
        return f"linux-{arch}"
    if sysname.startswith("win"):
        return f"win32-{arch}"
    return f"{sysname}-{arch}"


def binary_url(version: str, plat: str | None = None) -> str:
    return f"{BASE}/{version}/{plat or detect_platform()}/claude"


def download_binary(version: str, dest: Path, plat: str | None = None,
                    verify_checksum: bool = True) -> Path:
    plat = plat or detect_platform()
    data = _get(binary_url(version, plat), binary=True)
    if verify_checksum:
        m = manifest(version)
        want = m.get("platforms", {}).get(plat, {}).get("checksum")
        if want:
            got = hashlib.sha256(data).hexdigest()
            if got != want:
                raise RuntimeError(f"checksum mismatch for {plat}: got {got}, want {want}")
    dest.write_bytes(data)
    dest.chmod(0o755)
    return dest
