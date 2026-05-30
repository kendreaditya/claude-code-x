"""Anchor resolution + per-op three-state idempotency.

Every edit is located by a version-agnostic regex anchor that captures the
churned minified identifier in a group and reuses it in the replacement, so the
patch self-adapts across releases. We resolve to a concrete (offset, old_bytes,
new_bytes) inside the owning CJS module, enforcing uniqueness there.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .region import Module, owning_module

# 16 KiB of slack so a match that begins just before a module boundary still
# counts as "in region" (anchors are short).
_SLACK = 64


class OpState(str, Enum):
    UNPATCHED = "unpatched"      # anchor present, ready to apply
    APPLIED = "applied"          # patched_anchor present, anchor gone
    ABSENT = "absent"            # neither found — anchor doesn't exist in this build
    AMBIGUOUS = "ambiguous"      # >1 match where 1 expected, or both forms present


@dataclass
class ResolvedEdit:
    op_id: str
    offset: int
    old_bytes: bytes
    new_bytes: bytes
    module_index: int | None

    @property
    def same_length(self) -> bool:
        return len(self.old_bytes) == len(self.new_bytes)


@dataclass
class OpResolution:
    op_id: str
    state: OpState
    edit: ResolvedEdit | None
    detail: str


def _matches_in_region(pattern: re.Pattern, data: bytes, mods: list[Module] | None):
    """Return matches; if mods given, keep only matches whose start is inside a
    CJS module region (M1 region gating)."""
    ms = list(pattern.finditer(data))
    if mods is None:
        return ms, ms
    in_region = []
    for m in ms:
        mod = owning_module(mods, m.start())
        if mod is None:
            # tolerate a match starting within _SLACK before a body_start
            mod = owning_module(mods, m.start() + _SLACK)
        if mod is not None:
            in_region.append((m, mod))
    return ms, in_region


def resolve_op(op: dict, data: bytes, mods: list[Module] | None) -> OpResolution:
    """Resolve a single patch operation against the binary bytes.

    `op` keys: op_id, anchor, replace, patched_anchor, same_length, must_be_unique,
    in_bun_region.
    """
    op_id = op["op_id"]
    gate = mods if op.get("in_bun_region", True) else None
    same_length = op.get("same_length", True)
    must_unique = op.get("must_be_unique", True)

    anchor = re.compile(op["anchor"].encode())
    replace_tmpl = op["replace"].encode()
    patched = re.compile(op["patched_anchor"].encode()) if op.get("patched_anchor") else None

    _, anc_region = _matches_in_region(anchor, data, gate)
    pat_all, pat_region = (([], []) if patched is None
                           else _matches_in_region(patched, data, gate))

    n_anc = len(anc_region)
    n_pat = len(pat_region)

    # Already applied?
    if n_anc == 0 and patched is not None and n_pat >= 1:
        if n_pat > 1 and must_unique:
            return OpResolution(op_id, OpState.AMBIGUOUS, None,
                                 f"patched form found {n_pat}x (expected 1)")
        return OpResolution(op_id, OpState.APPLIED, None,
                             "patched form present; anchor consumed")

    # Anchor absent entirely → cannot apply (detect-but-skip, never guess)
    if n_anc == 0:
        return OpResolution(op_id, OpState.ABSENT, None,
                            "anchor not found in any module region")

    # Anchor present
    if must_unique and n_anc != 1:
        return OpResolution(op_id, OpState.AMBIGUOUS, None,
                            f"anchor matched {n_anc}x in region (expected 1)")

    m, mod = anc_region[0]
    old = m.group(0)
    new = m.expand(replace_tmpl)

    if same_length and len(new) != len(old):
        return OpResolution(op_id, OpState.AMBIGUOUS, None,
                            f"length policy 'same' violated: old={len(old)} new={len(new)}")

    edit = ResolvedEdit(op_id=op_id, offset=m.start(), old_bytes=old,
                        new_bytes=new, module_index=mod.index if mod else None)
    return OpResolution(op_id, OpState.UNPATCHED, edit, "anchor resolved")
