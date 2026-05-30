"""Code signing. Any byte change invalidates the signature; on Apple Silicon an
invalid/missing signature is an immediate SIGKILL, so re-signing is mandatory.

We preserve entitlements (the binary needs allow-jit / allow-unsigned-executable-
memory or JSC crashes at launch). We deliberately match the verified-working flag
set (entitlements only) rather than the broader untested set.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class SignError(RuntimeError):
    pass


def needs_signing(container: str) -> bool:
    return container.startswith("macho")


def resign(binary: Path, container: str) -> dict:
    """Re-sign in place. Returns metadata about what was done."""
    if not needs_signing(container):
        return {"tool": None, "skipped": "non-macho container needs no signing"}

    if shutil.which("codesign") is None:
        raise SignError("codesign not found (required on macOS)")

    cmd = ["codesign", "--force", "--sign", "-",
           "--preserve-metadata=entitlements", str(binary)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise SignError(f"codesign failed: {out.stderr.strip()}")
    return {"tool": "codesign", "preserved": ["entitlements"]}


def verify_signature(binary: Path, container: str) -> tuple[bool, str]:
    if not needs_signing(container):
        return True, "no signature required"
    if shutil.which("codesign") is None:
        return True, "codesign unavailable; skipped"
    out = subprocess.run(["codesign", "--verify", "--strict", str(binary)],
                         capture_output=True, text=True)
    ok = out.returncode == 0
    return ok, (out.stderr.strip() or "valid")
