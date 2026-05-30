"""Target detection: locate the Claude Code binary, sniff container/version/signing.

The engine never hardcodes offsets; everything downstream resolves against the
bytes of whatever binary `detect()` returns.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

BUN_TRAILER = b"\n---- Bun! ----\n"
# Plaintext CJS module header Bun emits for each bundled module.
MODULE_HEADER = b"// @bun @bytecode @bun-cjs\n"

# Default install layout: ~/.local/bin/claude -> ~/.local/share/claude/versions/<ver>
DEFAULT_LAUNCHER = Path.home() / ".local" / "bin" / "claude"


@dataclass
class Target:
    path: Path                       # the real versioned binary (symlinks resolved)
    launcher: Path | None            # ~/.local/bin/claude symlink, if that's how we found it
    version: str | None              # Claude Code version, e.g. "2.1.158"
    container: str                   # macho-arm64 | macho-x64 | elf-x64 | pe | unknown
    is_bun: bool                     # Bun standalone graph present
    bun_trailer_offset: int | None
    signed: str | None               # codesign identity summary, or None
    size: int
    format_class: str                # native-bun-binary | legacy-cli-js | unknown
    notes: list[str] = field(default_factory=list)

    def short(self) -> str:
        sig = self.signed or "unsigned"
        return f"{self.version or '?'}  {self.container}  {sig}  ({self.size:,} bytes)"


def _resolve_launcher(p: Path) -> Path:
    """Follow a launcher symlink to the real versioned binary."""
    return p.resolve()


def _sniff_container(head: bytes) -> str:
    if head[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
        # Mach-O 64; arch byte at 4..8 (cputype). 0x0100000c = arm64, 0x01000007 = x86_64
        cputype = int.from_bytes(head[4:8], "little")
        if cputype == 0x0100000C:
            return "macho-arm64"
        if cputype == 0x01000007:
            return "macho-x64"
        return "macho"
    if head[:4] == b"\x7fELF":
        return "elf-x64"
    if head[:2] == b"MZ":
        return "pe"
    return "unknown"


def _read_version(path: Path) -> str | None:
    """Try to read the CC version cheaply. Prefer launching --version; fall back
    to scanning for a version string near package metadata."""
    try:
        out = subprocess.run(
            [str(path), "--version"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "CLAUDIUS_INFLIGHT": "1"},
        )
        m = re.search(r"(\d+\.\d+\.\d+)", out.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    # Fallback: many builds embed the version path component.
    name = path.name
    m = re.match(r"(\d+\.\d+\.\d+)", name)
    return m.group(1) if m else None


def _codesign_info(path: Path) -> str | None:
    try:
        out = subprocess.run(
            ["codesign", "-dvv", str(path)],
            capture_output=True, text=True, timeout=20,
        )
        blob = (out.stderr or "") + (out.stdout or "")
        m = re.search(r"Identifier=(\S+)", blob)
        ad_hoc = "Signature=adhoc" in blob
        if m or ad_hoc:
            ident = m.group(1) if m else ""
            return ("adhoc-" if ad_hoc else "") + (ident or "signed")
        return None
    except Exception:
        return None


def detect(target: str | os.PathLike | None = None) -> Target:
    """Resolve and characterize the Claude Code binary.

    If `target` is given, use it; otherwise follow the default launcher symlink.
    """
    if target:
        p = Path(target)
        if p.is_symlink():
            p = _resolve_launcher(p)
        launcher = None
    else:
        if not DEFAULT_LAUNCHER.exists():
            raise FileNotFoundError(
                f"no --target given and default launcher {DEFAULT_LAUNCHER} not found"
            )
        launcher = DEFAULT_LAUNCHER
        p = _resolve_launcher(DEFAULT_LAUNCHER)

    if not p.is_file():
        raise FileNotFoundError(f"target binary not found: {p}")

    with open(p, "rb") as f:
        head = f.read(64)
        f.seek(0, os.SEEK_END)
        size = f.tell()
        # read the tail to find the Bun trailer (search last 4 MiB)
        tail_window = min(size, 4 * 1024 * 1024)
        f.seek(size - tail_window)
        tail = f.read(tail_window)

    container = _sniff_container(head)
    ti = tail.rfind(BUN_TRAILER)
    bun_trailer_offset = (size - tail_window + ti) if ti >= 0 else None
    is_bun = bun_trailer_offset is not None

    if is_bun and container.startswith("macho"):
        format_class = "native-bun-binary"
    elif p.suffix == ".js" or p.name == "cli.js":
        format_class = "legacy-cli-js"
    elif is_bun:
        format_class = "native-bun-binary"
    else:
        format_class = "unknown"

    signed = _codesign_info(p) if container.startswith("macho") else None
    version = _read_version(p)

    return Target(
        path=p, launcher=launcher, version=version, container=container,
        is_bun=is_bun, bun_trailer_offset=bun_trailer_offset, signed=signed,
        size=size, format_class=format_class,
    )
