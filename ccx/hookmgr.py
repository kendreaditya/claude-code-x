"""SessionStart repair-hook management (M3).

`ccx hook install` copies the repair hook into ~/.claude-code-x/hooks/ and adds a
SessionStart entry to ~/.claude/settings.json (backing it up first). `ccx hook
remove` reverses it. Settings edits are minimal and idempotent.
"""
from __future__ import annotations

import json
import shutil
import stat
from pathlib import Path

from .manifest import STATE_DIR
from .patchdef import REPO_ROOT

SETTINGS = Path.home() / ".claude" / "settings.json"
HOOK_SRC = REPO_ROOT / "hooks" / "sessionstart-repair.sh"
HOOK_DST = STATE_DIR / "hooks" / "sessionstart-repair.sh"
MARKER = "ccx-sessionstart-repair"


def _load_settings() -> dict:
    if SETTINGS.exists():
        try:
            return json.loads(SETTINGS.read_text())
        except Exception:
            return {}
    return {}


def _save_settings(doc: dict) -> None:
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    if SETTINGS.exists():
        shutil.copy2(SETTINGS, SETTINGS.with_suffix(".json.ccx-bak"))
    SETTINGS.write_text(json.dumps(doc, indent=2))


def install(repo_root: Path = REPO_ROOT) -> dict:
    HOOK_DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HOOK_SRC, HOOK_DST)
    HOOK_DST.chmod(HOOK_DST.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP)

    doc = _load_settings()
    hooks = doc.setdefault("hooks", {})
    ss = hooks.setdefault("SessionStart", [])
    # idempotent: skip if our command is already present
    cmd = f'CCX_REPO="{repo_root}" "{HOOK_DST}"'
    for entry in ss:
        for h in entry.get("hooks", []):
            if MARKER in h.get("command", "") or str(HOOK_DST) in h.get("command", ""):
                return {"result": "already-installed", "hook": str(HOOK_DST)}
    ss.append({
        "matcher": "startup",
        "hooks": [{"type": "command",
                   "command": f'{cmd}  # {MARKER}'}],
    })
    _save_settings(doc)
    return {"result": "installed", "hook": str(HOOK_DST), "settings": str(SETTINGS)}


def remove() -> dict:
    doc = _load_settings()
    ss = doc.get("hooks", {}).get("SessionStart", [])
    new_ss = []
    removed = 0
    for entry in ss:
        kept = [h for h in entry.get("hooks", [])
                if MARKER not in h.get("command", "") and str(HOOK_DST) not in h.get("command", "")]
        removed += len(entry.get("hooks", [])) - len(kept)
        if kept:
            entry["hooks"] = kept
            new_ss.append(entry)
    if removed:
        doc["hooks"]["SessionStart"] = new_ss
        _save_settings(doc)
    return {"result": "removed" if removed else "not-installed", "removed": removed}
