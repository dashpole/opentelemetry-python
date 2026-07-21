---
name: spec-compliance-review
description: Review a PR or diff for OpenTelemetry specification compliance. Use when a maintainer asks for a spec review, or as first-pass triage on changes that implement or alter spec-defined behavior (SDK processors, exporters, propagators, API semantics, environment-variable handling).
---

# OpenTelemetry Specification Compliance Review

Check a change against the normative requirements of the OpenTelemetry
specification and produce a reviewer-facing report. This skill produces a
report for the human reviewer — never post its output as PR comments or
reviews. Discussions on OpenTelemetry repositories are for humans only
(`AGENTS.md`, community GenAI policy).

## Ground rules

- The spec defines **behavior**; this repo deliberately does not mirror the
  spec's structure ("Focus on Capabilities, Not Structure Compliance" —
  `CONTRIBUTING.md`). Never flag idiomatic-Python divergence from the spec's
  object model as a violation. Do flag the opposite failure: unidiomatic
  Python that exists only to transcribe spec structure.
- Deliberate deviation is legitimate in this project but must be **recorded**.
  The finding for an unmet requirement is never "violation, must fix" — it is
  "requirement not met; needs either a fix or an explicit recorded decision
  (issue discussion + compliance matrix update)."
- Cite the spec for every finding. A finding without a section link and
  quoted normative sentence is an opinion; drop it.

## Procedure

1. **Collect requirements.** Read the linked issue's "Specification
   references" section — those anchors are the primary requirement set. If
   the issue has none, locate the relevant sections yourself in
   <https://github.com/open-telemetry/opentelemetry-specification> (search
   the `specification/` tree for the feature; use the spec version pinned by
   the issue, or the latest release tag). Extract every MUST / MUST NOT /
   SHOULD / MAY sentence the changed code could affect, including nearby ones
   the issue did not quote.
2. **Check each requirement against the diff.** Classify:
   - **Complies** — cite the code that satisfies it and the test that proves it.
   - **Does not comply** — concrete mismatch (wrong default, wrong unit,
     missing fallback, wrong precedence...). Quote spec and code.
   - **Not addressed** — in scope for the change but untouched.
   - **Deliberate deviation** — deviation with a recorded decision; check the
     record actually exists and is linked.
3. **Sweat the configuration details.** Defaults, units, and environment-
   variable semantics are where silent noncompliance lives (a known
   multi-year bug in another SIG was a seconds-vs-milliseconds mismatch). For
   every configurable value the diff touches, compare name, default, unit,
   and precedence order character-by-character against the spec's tables.
   OpenTelemetry Python environment variables must be `OTEL_PYTHON_`-prefixed
   and declared in an `environment_variables` module (`CONTRIBUTING.md`);
   check both the value semantics and that placement.
4. **Check tests, not just code.** Each MUST the change implements should
   have a test asserting it. Existing behavior is often pinned with
   `assertLogs` / `assertWarns` for expected log and warning output
   (`CONTRIBUTING.md`) — note requirements whose implementation is plausible
   but unproven.

## Report format

Order findings by severity: non-compliance first, unproven-by-tests second,
unrecorded deviations third, then confirmations (one line each). For each:
the requirement (quoted, linked), the code location (`file:line`), what to
do. End with a one-paragraph verdict: safe to merge from a spec standpoint,
or blocked on which findings. If every requirement complies and is tested,
say exactly that in one line — do not pad.
