"""Backups: pristine snapshot + per-apply rollback snapshot.

Two notions:
  * pristine `<binary>.unpatched` — created once, the first time we ever patch a
    given binary. Used by `revert --all`. Never overwritten.
  * rollback snapshot — copy of the exact pre-apply state, used to auto-restore
    if the smoke test fails. Deleted on success.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pristine_path(binary: Path) -> Path:
    return binary.with_name(binary.name + ".unpatched")


def ensure_pristine(binary: Path, version: str | None) -> Path:
    """Save pristine bytes once, with a sidecar stamp. Never overwrite."""
    bak = pristine_path(binary)
    if bak.exists():
        return bak
    shutil.copy2(binary, bak)
    stamp = {"version": version, "sha256": sha256(bak), "size": bak.stat().st_size}
    bak.with_suffix(bak.suffix + ".json").write_text(json.dumps(stamp, indent=2))
    return bak


def make_rollback(binary: Path) -> Path:
    snap = binary.with_name(binary.name + ".ccx-rollback")
    shutil.copy2(binary, snap)
    return snap


def restore(snapshot: Path, binary: Path) -> None:
    shutil.copy2(snapshot, binary)


def drop_rollback(snapshot: Path) -> None:
    try:
        snapshot.unlink()
    except FileNotFoundError:
        pass
