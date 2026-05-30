"""Terminal rendering: group listings, citation blocks, plan summaries."""
from __future__ import annotations

import sys
from collections import defaultdict

_STATE_GLYPH = {
    "applied": "✓ APPLIED",
    "unpatched": "applicable",
    "partial": "partial",
    "absent": "N/A (anchor absent)",
    "ambiguous": "! ambiguous",
    "mixed": "mixed",
}

_RISKY_LICENSES = {"unknown", "unlicensed", "educational-only", "unlicensed-local", None, ""}


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def fmt_state(state: str) -> str:
    return _STATE_GLYPH.get(state, state)


def group_listing(rows, verbose: bool = False) -> None:
    by_group = defaultdict(list)
    for pd, compat, res in rows:
        by_group[pd.group].append((pd, compat, res))
    for group in sorted(by_group):
        items = by_group[group]
        print(f"{group}  ({len(items)})")
        for pd, compat, res in items:
            if not compat:
                mark, state = "[!]", "N/A (version/container)"
            elif res is None:
                mark, state = "[ ]", "?"
            else:
                st = res.state
                mark = {"applied": "[✓]", "unpatched": "[ ]", "partial": "[~]",
                        "absent": "[!]", "ambiguous": "[!]"}.get(st, "[ ]")
                state = fmt_state(st)
            src = pd.provenance.get("source_repo", "?")
            print(f"  {mark}  {pd.id:<28} {pd.level:<7} {state:<22} {src}")
            if verbose:
                lic = pd.provenance.get("license", "unknown")
                print(f"        {pd.name} — {pd.description[:80]}")
                print(f"        license: {lic}")
        print()


def cite_block(pd) -> None:
    pv = pd.provenance
    lic = pv.get("license", "unknown")
    flag = "  ⚠ review before redistribution" if lic in _RISKY_LICENSES else ""
    print(f"\n  Patch:    {pd.id}  \"{pd.name}\"")
    print(f"  Group:    {pd.group}    Level: {pd.level}")
    print(f"  Source:   {pv.get('source_repo','?')}")
    print(f"  Author:   {pv.get('author','?')}")
    print(f"  License:  {lic}{flag}")


def plan_block(plan: dict) -> None:
    if not plan:
        return
    print(f"  Plan for {plan.get('id')}:")
    for e in plan.get("edits", []):
        sl = "same-length" if e.get("same_length") else "VARIABLE-LENGTH"
        print(f"    - edit {e['op_id']} @ {e['offset']:,} ({e['len']} bytes, {sl}, "
              f"module {e.get('module')})")
    if plan.get("resign"):
        print("    - re-sign required (codesign, entitlement-preserving)")
