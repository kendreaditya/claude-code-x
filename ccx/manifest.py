"""Applied-patch manifest (single source of truth for status/revert/doctor).

Stored at ~/.claude-code-x/manifests/<profile>.json. Each entry records provenance
and, per edit, the original/patched bytes (base64) so revert is a surgical inverse
that survives re-signing. We deliberately do NOT store file-size as a verification
field (see verify.py).
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path

STATE_DIR = Path.home() / ".claude-code-x"
MANIFEST_DIR = STATE_DIR / "manifests"


def manifest_file(profile: str = "default") -> Path:
    return MANIFEST_DIR / f"{profile}.json"


def _load(profile: str) -> dict:
    f = manifest_file(profile)
    if f.exists():
        return json.loads(f.read_text())
    return {"schema": 1, "profile": profile, "target": None, "applied": []}


def _save(profile: str, doc: dict) -> None:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    manifest_file(profile).write_text(json.dumps(doc, indent=2))


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def unb64(s: str) -> bytes:
    return base64.b64decode(s)


@dataclass
class Manifest:
    profile: str = "default"
    doc: dict = field(default_factory=dict)

    @classmethod
    def open(cls, profile: str = "default") -> "Manifest":
        return cls(profile=profile, doc=_load(profile))

    def save(self) -> None:
        _save(self.profile, self.doc)

    def set_target(self, target_meta: dict) -> None:
        self.doc["target"] = target_meta

    def applied_ids(self) -> list[str]:
        return [e["id"] for e in self.doc.get("applied", [])]

    def get(self, patch_id: str) -> dict | None:
        for e in self.doc.get("applied", []):
            if e["id"] == patch_id:
                return e
        return None

    def upsert(self, entry: dict) -> None:
        applied = self.doc.setdefault("applied", [])
        for i, e in enumerate(applied):
            if e["id"] == entry["id"]:
                applied[i] = entry
                return
        applied.append(entry)

    def remove(self, patch_id: str) -> None:
        self.doc["applied"] = [e for e in self.doc.get("applied", [])
                               if e["id"] != patch_id]
