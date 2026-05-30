"""The patch engine: resolve, apply, revert.

Discipline: resolve everything up front (detect -> locate -> verify are hard
gates), then write once to a temp file and atomically swap. Never leave the
binary half-patched; auto-rollback if the smoke test fails.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import backup, effect, sign, verify
from .anchors import OpResolution, OpState, ResolvedEdit, resolve_op
from .detect import Target
from .manifest import Manifest, b64, unb64
from .patchdef import PatchDef
from .region import enumerate_modules


class PatchError(RuntimeError):
    pass


@dataclass
class Resolution:
    patch_id: str
    ops: list[OpResolution]
    edits: list[ResolvedEdit] = field(default_factory=list)

    @property
    def state(self) -> str:
        states = {o.state for o in self.ops}
        if states == {OpState.APPLIED}:
            return "applied"
        if OpState.AMBIGUOUS in states:
            return "ambiguous"
        if OpState.ABSENT in states and OpState.UNPATCHED not in states:
            return "absent"
        if states <= {OpState.UNPATCHED, OpState.APPLIED}:
            return "partial" if OpState.APPLIED in states else "unpatched"
        return "mixed"

    @property
    def applicable(self) -> bool:
        # at least one op resolvable to an edit, none ambiguous
        return bool(self.edits) and not any(o.state == OpState.AMBIGUOUS for o in self.ops)


def resolve(pd: PatchDef, data: bytes) -> Resolution:
    mods = enumerate_modules(data)
    ops = [resolve_op(op, data, mods) for op in pd.operations]
    edits = [o.edit for o in ops if o.edit is not None]
    return Resolution(patch_id=pd.id, ops=ops, edits=edits)


def _splice(data: bytearray, edits: list[ResolvedEdit]) -> None:
    """Apply each edit at its exact offset (single-site, NOT replace-all)."""
    for e in edits:
        cur = bytes(data[e.offset:e.offset + len(e.old_bytes)])
        if cur != e.old_bytes:
            raise PatchError(
                f"op {e.op_id}: bytes at offset {e.offset} changed under us "
                f"(expected {e.old_bytes[:24]!r})"
            )
        data[e.offset:e.offset + len(e.old_bytes)] = e.new_bytes


def apply_patch(pd: PatchDef, target: Target, profile: str = "default",
                dry_run: bool = False) -> dict:
    """Apply one patch. Returns a report dict."""
    binary = target.path
    data = binary.read_bytes()
    res = resolve(pd, data)

    if res.state == "applied":
        return {"id": pd.id, "result": "already-applied", "resolution": res}
    if not res.applicable:
        return {"id": pd.id, "result": "not-applicable",
                "resolution": res,
                "reason": "; ".join(f"{o.op_id}:{o.state.value}({o.detail})"
                                    for o in res.ops if o.state != OpState.UNPATCHED)}

    # only apply the ops that are currently UNPATCHED (idempotent partial)
    edits = [o.edit for o in res.ops if o.state == OpState.UNPATCHED and o.edit]
    plan = {
        "id": pd.id, "name": pd.name, "group": pd.group, "level": pd.level,
        "provenance": pd.provenance,
        "edits": [{"op_id": e.op_id, "offset": e.offset,
                   "len": len(e.old_bytes), "same_length": e.same_length,
                   "module": e.module_index} for e in edits],
        "resign": sign.needs_signing(target.container),
    }
    if dry_run:
        return {"id": pd.id, "result": "dry-run", "plan": plan, "resolution": res}

    # ---- mutate (resolve done; now write once) ----
    backup.ensure_pristine(binary, target.version)
    rollback = backup.make_rollback(binary)
    expected_trailer = verify.trailer_offset(data)
    try:
        buf = bytearray(data)
        _splice(buf, edits)
        tmp = binary.with_name(binary.name + ".ccx-tmp")
        tmp.write_bytes(buf)
        tmp.chmod(binary.stat().st_mode)
        resign_meta = sign.resign(tmp, target.container)
        os.replace(tmp, binary)  # atomic swap

        vr = verify.verify_patched(
            binary, target.container,
            expected_patched=[e.new_bytes for e in edits],
            expected_trailer=expected_trailer,
        )
        if not vr.ok:
            backup.restore(rollback, binary)
            sign.resign(binary, target.container)
            raise PatchError(f"verification failed, rolled back: {vr.detail} "
                             f"checks={vr.checks}")
    finally:
        backup.drop_rollback(rollback)

    # ---- record manifest ----
    mf = Manifest.open(profile)
    mf.set_target({
        "path": str(binary), "version": target.version,
        "container": target.container, "signed": target.signed,
    })
    eff_status, eff_detail = effect.classify(binary, edits, pd.data.get("effect_probe"))
    mf.upsert({
        "id": pd.id, "name": pd.name, "group": pd.group, "level": pd.level,
        "source": pd.provenance,
        "edits": [{"op_id": e.op_id, "offset": e.offset,
                   "original_b64": b64(e.old_bytes), "patched_b64": b64(e.new_bytes),
                   "same_length": e.same_length} for e in edits],
        "resign": resign_meta, "effect": eff_status,
    })
    mf.save()
    return {"id": pd.id, "result": "applied", "plan": plan,
            "verify": vr.checks, "edits": len(edits),
            "effect": eff_status, "effect_detail": eff_detail}


def validate_on_copy(pd: PatchDef, target: Target) -> dict:
    """Apply a patch to a TEMP COPY, smoke-test launch, discard. Used by
    `ccx validate-all` and release-watch CI — never touches the real binary or
    manifest."""
    import shutil
    import tempfile

    data = target.path.read_bytes()
    res = resolve(pd, data)
    if res.state == "applied":
        return {"id": pd.id, "applies": True, "launch_ok": None, "state": "already-applied"}
    if not res.applicable:
        reason = "; ".join(f"{o.op_id}:{o.state.value}" for o in res.ops
                           if o.state in (OpState.ABSENT, OpState.AMBIGUOUS))
        return {"id": pd.id, "applies": False, "launch_ok": False, "reason": reason or "not applicable"}

    edits = [o.edit for o in res.ops if o.state == OpState.UNPATCHED and o.edit]
    with tempfile.TemporaryDirectory() as td:
        copy = Path(td) / "claude"
        shutil.copy2(target.path, copy)
        copy.chmod(0o755)
        buf = bytearray(data)
        try:
            _splice(buf, edits)
        except PatchError as e:
            return {"id": pd.id, "applies": False, "launch_ok": False, "reason": str(e)}
        copy.write_bytes(buf)
        try:
            sign.resign(copy, target.container)
        except sign.SignError as e:
            return {"id": pd.id, "applies": True, "launch_ok": False, "reason": f"resign: {e}"}
        launch_ok, detail = verify.smoke_launch(copy)
        return {"id": pd.id, "applies": True, "launch_ok": launch_ok, "edits": len(edits),
                "detail": "ok" if launch_ok else detail}


def verify_effect(pd: PatchDef, target: Target) -> dict:
    """Classify the runtime effect of an applied patch (M2)."""
    data = target.path.read_bytes()
    res = resolve(pd, data)
    edits = [o.edit for o in res.ops if o.edit] or []
    # if applied, edits resolve to patched form; reconstruct from anchors regardless
    status, detail = effect.classify(target.path, edits, pd.data.get("effect_probe"))
    return {"id": pd.id, "state": res.state, "effect": status, "detail": detail}


def revert_patch(patch_id: str, target: Target, profile: str = "default") -> dict:
    """Surgical inverse from the manifest: re-locate each patched byte sequence
    and restore the original. Survives re-signing (offsets in the JS region are
    stable) and falls back to a search-by-bytes relocate if offsets drifted."""
    binary = target.path
    mf = Manifest.open(profile)
    entry = mf.get(patch_id)
    if entry is None:
        return {"id": patch_id, "result": "not-in-manifest"}

    data = bytearray(binary.read_bytes())
    expected_trailer = verify.trailer_offset(bytes(data))
    restored = 0
    for ed in entry["edits"]:
        orig = unb64(ed["original_b64"])
        patched = unb64(ed["patched_b64"])
        off = ed.get("offset")
        if off is not None and bytes(data[off:off + len(patched)]) == patched:
            data[off:off + len(patched)] = orig
            restored += 1
            continue
        # relocate by unique patched bytes
        idx = bytes(data).find(patched)
        if idx < 0 or bytes(data).find(patched, idx + 1) != -1:
            return {"id": patch_id, "result": "revert-failed",
                    "reason": f"op {ed['op_id']}: patched bytes not uniquely locatable"}
        data[idx:idx + len(patched)] = orig
        restored += 1

    tmp = binary.with_name(binary.name + ".ccx-tmp")
    tmp.write_bytes(bytes(data))
    tmp.chmod(binary.stat().st_mode)
    sign.resign(tmp, target.container)
    os.replace(tmp, binary)

    vr = verify.verify_patched(binary, target.container, expected_patched=[],
                               expected_trailer=expected_trailer)
    mf.remove(patch_id)
    mf.save()
    return {"id": patch_id, "result": "reverted", "ops": restored,
            "launch_ok": vr.checks.get("launch_ok")}
