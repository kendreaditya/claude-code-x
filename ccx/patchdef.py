"""Load patch definitions from the registry (and user customs).

A patch definition is pure data; the engine is generic. Definitions live in
registry/<group>/<id>.ccxpatch.json (built-ins) and ~/.claudius-code/registry/
(user customs). Patches that don't apply to the latest version live under
registry/_archived/.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .manifest import STATE_DIR

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILTIN_REGISTRY = REPO_ROOT / "registry"
ARCHIVE_DIR = BUILTIN_REGISTRY / "_archived"
USER_REGISTRY = STATE_DIR / "registry"


@dataclass
class PatchDef:
    path: Path
    data: dict
    archived: bool = False

    @property
    def id(self) -> str: return self.data["id"]
    @property
    def name(self) -> str: return self.data.get("name", self.id)
    @property
    def group(self) -> str: return self.data.get("group", "misc")
    @property
    def description(self) -> str: return self.data.get("description", "")
    @property
    def provenance(self) -> dict: return self.data.get("provenance", {})
    @property
    def operations(self) -> list[dict]: return self.data.get("operations", [])
    @property
    def applies_to(self) -> dict: return self.data.get("applies_to", {})
    @property
    def level(self) -> str:
        # intervention level badge; default binary
        return self.data.get("level") or (
            self.operations[0].get("kind", "binary") if self.operations else "binary"
        )


def _semver(v: str) -> tuple[int, int, int]:
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", v or "0.0.0")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def _in_range(version: str | None, rng: str | None) -> bool:
    """Tiny semver range check supporting '>=A <B' and exact 'A'."""
    if not version or not rng:
        return True
    v = _semver(version)
    ok = True
    for tok in rng.split():
        if tok.startswith(">="):
            ok &= v >= _semver(tok[2:])
        elif tok.startswith("<="):
            ok &= v <= _semver(tok[2:])
        elif tok.startswith("<"):
            ok &= v < _semver(tok[1:])
        elif tok.startswith(">"):
            ok &= v > _semver(tok[1:])
        else:
            ok &= v == _semver(tok)
    return ok


def version_compatible(pd: PatchDef, version: str | None) -> bool:
    return _in_range(version, pd.applies_to.get("version_range"))


def container_compatible(pd: PatchDef, container: str) -> bool:
    cs = pd.applies_to.get("containers")
    if not cs:
        return True
    return any(container.startswith(c.split("-bun")[0].rsplit("-", 0)[0]) or c.startswith(container)
               or container == c for c in cs) or container in cs


def load_all(include_archived: bool = False) -> list[PatchDef]:
    defs: list[PatchDef] = []
    roots = [(BUILTIN_REGISTRY, False)]
    if USER_REGISTRY.exists():
        roots.append((USER_REGISTRY, False))
    if include_archived and ARCHIVE_DIR.exists():
        roots.append((ARCHIVE_DIR, True))
    seen = set()
    for root, archived in roots:
        for p in sorted(root.rglob("*.ccxpatch.json")):
            if "_archived" in p.parts and not archived:
                continue
            try:
                data = json.loads(p.read_text())
            except Exception:
                continue
            if data.get("id") in seen:
                continue
            seen.add(data.get("id"))
            defs.append(PatchDef(path=p, data=data, archived=archived))
    return defs


def load_one(patch_id: str, include_archived: bool = True) -> PatchDef | None:
    for pd in load_all(include_archived=include_archived):
        if pd.id == patch_id:
            return pd
    return None
