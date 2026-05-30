# M2 finding: does editing the plaintext JS actually take effect?

**Question (raised in the design review).** The Bun binary's CJS module headers
carry an `@bytecode` tag. If a compiled JSC bytecode blob executes instead of the
embedded plaintext source, then byte-patching the plaintext JS would have *no
runtime effect* and `claude --version` could not detect it.

**Experiment.** On a fresh copy of pristine 2.1.158:

1. The user-facing string `Claude Code - starts an interactive session by default`
   occurs **twice**:
   - `132,104,512` — inside a binary/bytecode blob (preceded by NUL bytes, not in
     any CJS module region).
   - `208,568,016` — plaintext JS source, the `.description("…")` call, inside the
     main CJS module (`[193,186,504, 208,706,548)`).
2. We replaced **only the plaintext occurrence** (same length, padded), re-signed
   ad-hoc, and ran `claude --help`.

**Result.**

```
$ claude --help
...
PLAINTEXT-JS-EXECUTES                                 , use -p/--print for
```

The output changed. **The plaintext JS source is the executed path.** The
`@bytecode` blob is not authoritative for this string (Bun falls back to / runs
the embedded source). The other occurrence at 132M is outside every CJS module
region, so `ccx`'s region gating would never touch it anyway.

**Consequence for patches.** All three `fifo-steering-queue` edits land in the
same module (`193M–208M`) that this experiment proved executes. Byte edits to
plaintext JS in a CJS module region therefore have real runtime effect.

**Verification policy.** `ccx` records a patch's post-apply runtime status as:

- `effect-verified` — the patch declares an `effect_probe` (e.g. a CLI-output
  check) and it passed against the patched binary.
- `module-execution-confirmed` — no headless probe exists (e.g. FIFO's behavior
  is interactive-only), but every edit lands in a module proven to execute
  plaintext via the canary above.
- `unverified` — edits land in a module with no execution evidence.

The canary itself is reproducible: `tests/test_m2_canary.py` performs exactly the
experiment above on a sandbox copy and asserts the help output changes.
