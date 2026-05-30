"""Module region model (M1).

The Bun binary embeds multiple plaintext CJS modules, each introduced by a
`// @bun @bytecode @bun-cjs\\n` header. An edit must land inside the module that
actually owns the anchor — not just "somewhere in the file" — so uniqueness and
region gating are computed against the owning module, not a hardcoded window.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .detect import MODULE_HEADER, BUN_TRAILER

# Any `// @bun` header (some are non-CJS); used only to bound the last module.
_ANY_BUN_HEADER = re.compile(rb"// @bun")


@dataclass
class Module:
    index: int
    start: int          # offset of the header
    body_start: int     # offset just after the header
    end: int            # offset of the next module/trailer (exclusive)

    def contains(self, off: int) -> bool:
        return self.body_start <= off < self.end


def enumerate_modules(data: bytes) -> list[Module]:
    """Find all CJS module regions (the `@bytecode @bun-cjs` plaintext modules).

    Each module spans from its header to the next `// @bun` header (of any kind)
    or the Bun trailer, whichever comes first.
    """
    cjs = [m.start() for m in re.finditer(re.escape(MODULE_HEADER), data)]
    all_heads = sorted(m.start() for m in _ANY_BUN_HEADER.finditer(data))
    trailer = data.rfind(BUN_TRAILER)
    bound = trailer if trailer >= 0 else len(data)

    mods: list[Module] = []
    for i, start in enumerate(cjs):
        body = start + len(MODULE_HEADER)
        # next boundary = smallest header strictly after this body, else trailer
        nxt = bound
        for h in all_heads:
            if h > start and h < nxt:
                nxt = h
        mods.append(Module(index=i, start=start, body_start=body, end=nxt))
    return mods


def owning_module(mods: list[Module], off: int) -> Module | None:
    for m in mods:
        if m.contains(off):
            return m
    return None
