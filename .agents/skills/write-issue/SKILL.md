---
name: write-issue
description: Expand a maintainer's rough task idea into a complete spec-implementation issue draft using this repo's issue template. Use when a maintainer describes work to be filed as an issue, or asks to "write this up" / "file an issue for X".
---

# Issue Writer (maintainer-side)

Turn a one-or-two-sentence task idea into a draft issue that an unfamiliar
contributor's coding agent could complete. The template being filled is
`.github/ISSUE_TEMPLATE/spec-implementation.yaml` — produce every field.
**Always output a draft for the maintainer to review; never file the issue or
post it anywhere yourself.** Discussions on OpenTelemetry repositories are for
humans only (`AGENTS.md`).

## Procedure

1. **Find the spec surface.** Search the OpenTelemetry specification
   (<https://github.com/open-telemetry/opentelemetry-specification>, the
   `specification/` tree, latest release tag unless told otherwise) for the
   sections governing this task. Quote every normative sentence
   (MUST/SHOULD/MAY) that applies, with pinned links. If the task has no spec
   surface, state that explicitly in the draft.
2. **Localize.** Search this repository for the package, modules, files,
   classes, and functions the change will touch. List expected touch points
   and, just as important, neighboring code that should NOT change. Note
   whether the change lands in the API package (abstract behavior + no-op
   defaults) or the SDK (implementation) — they have different rules.
3. **Size check — before drafting further.** If the work spans more than one
   package, or several modules with disjoint edits, stop and propose a split
   into multiple issues (with a suggested ordering and which one unblocks the
   others). Completion rates collapse as changes spread across files; small
   issues are a feature, not an inconvenience (`CONTRIBUTING.md` asks the same
   of humans: under 500 lines, one change per PR).
4. **Derive acceptance criteria.** One checklist item per quoted normative
   sentence, plus items for error paths and concurrent use where relevant.
   Each must be objectively checkable.
5. **Draft acceptance tests.** Write the table of test cases (name, setup,
   input, expected outcome) covering the criteria. Where cheap, write the
   actual failing test (parametrized where it fits the pattern).
6. **Draft the API sketch — clearly marked unapproved.** Propose signatures
   following this repo's conventions: keyword-only optional arguments, full
   type hints, `abc.ABC` for spec-defined extension points, and the minimum
   public surface (default to a leading underscore). Put it under a header:
   `PROPOSED — awaiting maintainer sign-off`. Flag any new public symbols
   explicitly — they will trip `public-symbols-check` and need the `Approve
   Public API check` label. If the design is genuinely open, write "DESIGN
   OPEN — do not start implementation" and list the open questions instead.
7. **Write non-goals.** Ask yourself what a capable agent would plausibly also
   do (refactor neighbors, add extra keyword arguments, handle adjacent spec
   sections, "clean up" nearby code) and explicitly exclude what isn't wanted.

## Output

The complete issue body in a single markdown block, ready to paste into the
form, keeping the `needs-design` label, followed by a short note to the
maintainer listing: what needs their judgment (the API sketch, any
spec-interpretation calls made), anything that looked ambiguous in the spec,
and the proposed split if step 3 triggered.
