"""ccx command-line surface (M0-M3 subset): detect, list, status, apply, revert.

Interactive TUI, doctor, credits, custom land in later milestones; the engine
they call is already here.
"""
from __future__ import annotations

import argparse
import sys

from . import __version__, engine
from .anchors import OpState
from .detect import detect
from .manifest import Manifest
from .patchdef import (PatchDef, container_compatible, load_all, load_one,
                       version_compatible)
from .render import (cite_block, fmt_state, group_listing, plan_block, warn)


def _resolve_target(args):
    return detect(getattr(args, "target", None))


def cmd_detect(args) -> int:
    t = _resolve_target(args)
    print(f"path:       {t.path}")
    print(f"version:    {t.version}")
    print(f"container:  {t.container}")
    print(f"format:     {t.format_class}")
    print(f"bun:        trailer @ {t.bun_trailer_offset:,}" if t.bun_trailer_offset
          else "bun:        (no Bun trailer)")
    print(f"signed:     {t.signed}")
    print(f"size:       {t.size:,} bytes")
    return 0


def cmd_list(args) -> int:
    t = _resolve_target(args)
    data = t.path.read_bytes()
    defs = load_all(include_archived=args.archived)
    if args.group:
        defs = [d for d in defs if d.group == args.group]
    rows = []
    for pd in defs:
        compat = (version_compatible(pd, t.version)
                  and container_compatible(pd, t.container))
        res = engine.resolve(pd, data) if compat else None
        rows.append((pd, compat, res))
    print(f"Target: Claude Code {t.version}  ({t.container}, {t.signed})\n")
    group_listing(rows, verbose=args.verbose)
    return 0


def cmd_status(args) -> int:
    t = _resolve_target(args)
    data = t.path.read_bytes()
    mf = Manifest.open(args.profile)
    print(f"Target:   {t.path}")
    print(f"          {t.short()}")
    print(f"Profile:  {args.profile}\n")
    applied = mf.doc.get("applied", [])
    if not applied:
        print("No patches recorded as applied.")
        return 0
    print(f"Applied patches (manifest: {args.profile}):")
    for e in applied:
        pd = load_one(e["id"])
        if pd is None:
            print(f"  {e['id']:<28} (definition missing) — manifest only")
            continue
        res = engine.resolve(pd, data)
        print(f"  {e['id']:<28} {pd.level:<7} {fmt_state(res.state)}")
    return 0


def _select(args, defs: list[PatchDef]) -> list[PatchDef]:
    if getattr(args, "from_manifest", False):
        ids = Manifest.open(args.profile).applied_ids()
        return [d for d in defs if d.id in ids]
    if args.group:
        return [d for d in defs if d.group == args.group]
    if args.all_applicable:
        return defs
    if args.ids:
        chosen = []
        for pid in args.ids:
            pd = load_one(pid)
            if pd is None:
                warn(f"unknown patch id: {pid}")
            else:
                chosen.append(pd)
        return chosen
    return []


def cmd_apply(args) -> int:
    t = _resolve_target(args)
    data = t.path.read_bytes()
    defs = load_all()
    chosen = _select(args, defs)
    if not chosen:
        warn("nothing selected. Give patch ids, --group <g>, or --all-applicable.")
        return 2

    # filter to compatible + applicable
    plan_items = []
    for pd in chosen:
        if not (version_compatible(pd, t.version) and container_compatible(pd, t.container)):
            print(f"  skip {pd.id}: not compatible with {t.version}/{t.container}")
            continue
        res = engine.resolve(pd, data)
        if res.state == "applied":
            print(f"  skip {pd.id}: already applied")
            continue
        if not res.applicable:
            bad = "; ".join(f"{o.op_id}:{o.state.value}" for o in res.ops
                            if o.state in (OpState.ABSENT, OpState.AMBIGUOUS))
            print(f"  skip {pd.id}: not applicable ({bad})")
            continue
        plan_items.append(pd)

    if not plan_items:
        print("Nothing to apply.")
        return 0

    # conflict detection: drop later patches whose edits overlap an earlier one
    conflicts = engine.detect_conflicts(plan_items, data)
    if conflicts:
        drop = set()
        for a, b, span in conflicts:
            print(f"  ! conflict: {a} and {b} edit overlapping bytes {span} — keeping {a}, skipping {b}")
            drop.add(b)
        plan_items = [pd for pd in plan_items if pd.id not in drop]
        if not plan_items:
            print("Nothing to apply after conflict resolution.")
            return 0

    for pd in plan_items:
        cite_block(pd)
    if args.dry_run:
        for pd in plan_items:
            rep = engine.apply_patch(pd, t, profile=args.profile, dry_run=True)
            plan_block(rep.get("plan", {}))
        print("\n(dry-run: nothing was modified)")
        return 0

    if not args.yes:
        ans = input(f"\nApply {len(plan_items)} patch(es) to {t.version}? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("aborted.")
            return 1

    rc = 0
    for pd in plan_items:
        try:
            rep = engine.apply_patch(pd, t, profile=args.profile)
            r = rep["result"]
            if r == "applied":
                print(f"  ✓ {pd.id}: applied {rep['edits']} edit(s); "
                      f"launch={rep['verify'].get('launch_ok')}")
            else:
                print(f"  • {pd.id}: {r} {rep.get('reason','')}")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {pd.id}: {e}")
            rc = 1
    return rc


def cmd_latest(args) -> int:
    from . import release
    try:
        v = release.latest_version()
    except Exception as e:  # noqa: BLE001
        warn(f"could not reach release feed: {e}")
        return 2
    print(f"latest published: {v}")
    try:
        t = detect(getattr(args, "target", None))
        print(f"installed:        {t.version}")
        print(f"  -> {'up to date' if t.version == v else f'newer version {v} available'}")
    except FileNotFoundError:
        pass
    return 0


def cmd_validate_all(args) -> int:
    import json as _json
    t = _resolve_target(args)
    defs = load_all(include_archived=args.archived)
    if args.group:
        defs = [d for d in defs if d.group == args.group]
    results = []
    for pd in defs:
        if not (version_compatible(pd, t.version) and container_compatible(pd, t.container)):
            results.append({"id": pd.id, "applies": False, "launch_ok": None,
                            "reason": "version/container incompatible"})
            continue
        results.append(engine.validate_on_copy(pd, t))
    ok = sum(1 for r in results if r.get("applies") and r.get("launch_ok") in (True, None))
    if args.json:
        print(_json.dumps({"version": t.version, "container": t.container,
                           "results": results}, indent=2))
    else:
        print(f"Validating {len(results)} patch(es) against {t.version} ({t.container}):\n")
        for r in results:
            glyph = "✓" if (r.get("applies") and r.get("launch_ok") in (True, None)) else "✗"
            print(f"  {glyph} {r['id']:<28} applies={r.get('applies')} "
                  f"launch={r.get('launch_ok')} {r.get('reason') or r.get('detail') or ''}")
        print(f"\n{ok}/{len(results)} patches valid on {t.version}")
    return 0 if ok == len(results) else 1


def cmd_hook(args) -> int:
    from . import hookmgr
    if args.action == "install":
        rep = hookmgr.install()
    else:
        rep = hookmgr.remove()
    print(f"  hook {args.action}: {rep}")
    return 0


def cmd_verify_effect(args) -> int:
    t = _resolve_target(args)
    rc = 0
    for pid in args.ids:
        pd = load_one(pid)
        if pd is None:
            warn(f"unknown patch id: {pid}")
            rc = 2
            continue
        rep = engine.verify_effect(pd, t)
        print(f"  {pid:<28} state={rep['state']:<10} effect={rep['effect']}")
        print(f"        {rep['detail']}")
        if rep["effect"] == "effect-FAILED":
            rc = 1
    return rc


def cmd_revert(args) -> int:
    t = _resolve_target(args)
    mf = Manifest.open(args.profile)
    if args.all:
        ids = mf.applied_ids()
    elif args.group:
        ids = [e["id"] for e in mf.doc.get("applied", []) if e.get("group") == args.group]
    else:
        ids = args.ids
    if not ids:
        warn("nothing to revert (give ids, --group, or --all)")
        return 2
    rc = 0
    for pid in ids:
        rep = engine.revert_patch(pid, t, profile=args.profile)
        print(f"  {pid}: {rep['result']} {rep.get('reason','')}")
        if rep["result"] not in ("reverted", "not-in-manifest"):
            rc = 1
    return rc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ccx", description="claude-code-x universal patcher")
    p.add_argument("--version", action="version", version=f"ccx {__version__}")
    p.add_argument("--target", help="path to the Claude Code binary/launcher")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_profile(sp):
        sp.add_argument("--profile", default="default", help="manifest profile")

    sp = sub.add_parser("detect", help="print version/container/signing facts")
    sp.set_defaults(func=cmd_detect)

    sp = sub.add_parser("list", help="list the patch catalog")
    sp.add_argument("--group")
    sp.add_argument("--archived", action="store_true")
    sp.add_argument("--verbose", "-v", action="store_true")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("status", help="what's applied to the current binary")
    add_profile(sp)
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("apply", help="apply patches")
    sp.add_argument("ids", nargs="*")
    sp.add_argument("--group")
    sp.add_argument("--all-applicable", action="store_true")
    sp.add_argument("--from-manifest", action="store_true",
                    help="re-apply every patch recorded in the manifest (idempotent; used by the repair hook)")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--yes", "-y", action="store_true")
    add_profile(sp)
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser("latest", help="show latest published vs installed version")
    sp.set_defaults(func=cmd_latest)

    sp = sub.add_parser("validate-all", help="validate every patch against the target on a temp copy")
    sp.add_argument("--group")
    sp.add_argument("--archived", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_validate_all)

    sp = sub.add_parser("hook", help="manage the SessionStart auto-repair hook")
    sp.add_argument("action", choices=["install", "remove"])
    sp.set_defaults(func=cmd_hook)

    sp = sub.add_parser("verify-effect", help="classify a patch's runtime effect (M2)")
    sp.add_argument("ids", nargs="+")
    sp.set_defaults(func=cmd_verify_effect)

    sp = sub.add_parser("revert", help="revert patches")
    sp.add_argument("ids", nargs="*")
    sp.add_argument("--group")
    sp.add_argument("--all", action="store_true")
    add_profile(sp)
    sp.set_defaults(func=cmd_revert)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        warn(str(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
