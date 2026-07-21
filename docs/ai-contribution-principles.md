# Principles for High-Quality Contributions in the Agent Era

Most incoming pull requests are now written wholly or partly by AI coding
agents. That is not a problem to filter out — it is a change in economics to
design for: generating a PR is nearly free, while reviewing one still costs
real maintainer time. Projects that ignore this asymmetry drown their
maintainers; projects that ban AI outright forfeit contributions and can't
enforce the ban anyway. This document takes a third position: **make the
repository itself the expert**, so that an unfamiliar contributor pointing an
agent at one of our issues produces a mergeable PR — and so that maintainer
time concentrates where human judgment is irreplaceable.

These principles are written for opentelemetry-python but are intended to
generalize across OpenTelemetry SIGs. Concrete artifacts implementing them in
this repository: the "Working from issues" section of `AGENTS.md`, the
`spec-implementation` issue template, the pull request template, and the
skills under `.agents/skills/` — building on the guidance
(`AGENTS.md`, the OpenTelemetry community
[GenAI policy](https://github.com/open-telemetry/community/blob/main/policies/genai.md))
and conventions (`CONTRIBUTING.md`) the repository already has.

The skills use the [Agent Skills](https://github.com/agentskills/agentskills)
open format (a directory containing a `SKILL.md` with YAML front matter),
which is read by multiple coding agents, not just one vendor's. Canonical
copies live in the vendor-neutral `.agents/skills/` directory (the
project-level location the format's ecosystem converged on, alongside
`AGENTS.md`); `.claude/skills/` holds relative symlinks for tools that only
discover their vendor-specific path.

## The principles

### 1. The issue is the prompt

Assume every issue will be pasted verbatim into a coding agent by someone
with zero project context. Anything not stated in the issue — or linked with
a specific section anchor — effectively does not exist. A well-specified
issue contains: the requirements (for spec work, the quoted normative
sentences with pinned links), the affected packages and modules, the
non-goals, an API sketch or an explicit "design open" marker, and acceptance
criteria. Under-specified issues are the root cause of low-quality agent PRs:
the agent fills every gap with a plausible-looking guess.

### 2. Separate design from implementation — and only advertise the latter

Spec interpretation and API design are the two most expensive things to
review, and the worst place to review them is a finished PR. Issues are born
`needs-design`; a maintainer settles the API sketch and spec reading *on the
issue*, then relabels it `ready-to-implement` (optionally `help wanted`).
Reviewing a sketch costs minutes; reviewing a PR that embodies a wrong design
costs hours and usually ends in abandonment. This matters more in Python than
in most languages: every public symbol is a permanent backwards-compatibility
commitment (`CONTRIBUTING.md`, "Public Symbols"), and the
`public-symbols-check` deliberately fails CI on any public API change to
force that conversation. Having it on the issue instead of the PR is strictly
cheaper.

### 3. Keep tasks small

The strongest empirical predictor of agent task failure is the size and
spread of the required change — completion rates collapse as edits span more
files and more disjoint hunks. Decomposition is part of issue authoring: a
`ready-to-implement` issue should be confined to one package and ideally a
handful of files. This is the same discipline `CONTRIBUTING.md` already asks
of humans ("Aim for fewer than 500 lines", "One change per PR"); the agent
era raises the stakes. A perfectly specified 500-line issue is still a bad
issue; split it.

### 4. The definition of done must be executable

Phrase acceptance criteria as things a machine or a reviewing agent can
check: "default is 512 per spec §X (quoted)", "no significant regression in
`pytest-benchmark` compare", "test T fails before, passes after". The
strongest form is a failing acceptance test included in the issue itself.
Vague criteria produce vague PRs.

### 5. Evidence, not assertions

Agents are excellent at producing evidence when the template demands it and
excellent at producing confident prose when it doesn't. PRs must show their
work: spec sections quoted, test output pasted, a `pytest-benchmark`
comparison for any performance claim, and an explicit "out of scope"
statement. This converts review from "re-derive whether this is correct" into
"check the evidence." The enforcement rule, borrowed from FastAPI's
contributor policy: **if the effort invested in a PR is evidently less than
the effort required to review it, the PR may be closed on that basis alone.**
This rule needs no AI detection and no debate about tooling — it prices the
externality directly.

### 6. Push every rule down the enforcement ladder

Anything a maintainer says twice in review should move as far down this
ladder as it can:

1. **Deterministic CI check** — ruff, pyright, the changelog-fragment check,
   the public-symbols check, spec-default assertions. Cheapest, zero noise
   budget.
2. **Written rule an agent can cite** — `CONTRIBUTING.md`, `AGENTS.md`. Free
   to apply, requires the reader to comply.
3. **Review skill** — packaged judgment for recurring review types (spec
   compliance, API design, benchmarks). For what tools can't check.
4. **Human attention** — reserved for what's left: taste, tradeoffs, spec
   interpretation calls.

A good maintenance habit: periodically skim your own review comments and ask
which rung each should have been caught on.

### 7. Gate by blast radius, not contributor identity

Anyone with an agent is now a contributor; vetting people doesn't scale, but
gating change types does. Additions to the public API of a released package
require a design-approved issue — no exceptions, and the
`public-symbols-check` already makes them impossible to merge silently.
Internal changes (anything under a `_internal` package or a single-underscore
name), tests, and docs flow freely. Maintainer attention concentrates where
mistakes are permanent.

### 8. Agent guidance files are written by hand and kept minimal

`AGENTS.md` earns its place line by line: every line must state something an
agent cannot infer from the codebase (commands, hard rules, workflow gates).
Auto-generated context files are actively harmful — evaluations have found
they increase inference cost without improving success rates. This
repository's existing `AGENTS.md` already follows this principle: hand-written
and convention-dense, and read by Copilot, Cursor, Codex, and others through
the shared `AGENTS.md` convention (`CLAUDE.md` is just a pointer to it). Keep
it that way. Corollaries: state rules affirmatively ("use keyword-only
arguments for optional configuration") rather than as negations, which keep
the forbidden pattern salient; and if a linter can enforce a rule, the
guidance file says only "run the linter" (this is why `AGENTS.md` says to run
`tox -e ruff`, not how to format).

### 9. Review automation serves the reviewer, not the thread

Automated review comments are a known failure mode — projects that let AI
reviewers post directly have found the noise costs maintainers more than the
bad PRs did. OpenTelemetry's own community
[GenAI policy](https://github.com/open-telemetry/community/blob/main/policies/genai.md)
and this repo's `AGENTS.md` already draw the hard line: **do not post
AI-generated comments on issues or PRs — discussions are for humans.** The
review skills here honor that by producing reports *to the reviewing
maintainer*, who decides what reaches the PR in their own words. Pilot any
review automation privately and tune before trusting it, and never run it
with write access to secrets on fork PRs.

### 10. Agent-friendliness must not tax humans

Most of what helps agents — specified issues, small scope, explicit
non-goals, executable definitions of done — helps human contributors
unconditionally, because a new human is in the same position as an agent: no
context, gaps filled with guesses. The part that can hurt humans is
ceremony: templates, checklists, and gates that agents fill happily but
humans experience as bureaucracy. So put a budget on ceremony and spend the
length elsewhere:

- **Agent-facing content may be long; human-facing surfaces must be short.**
  Detail belongs in `AGENTS.md`, skills, and linked docs — files a human
  never has to scroll past. Anything a human must physically move through
  (templates, checklists) stays minimal.
- **Templates are defaults, not contracts.** Sections that don't apply may
  be deleted, and reviewers never bounce a PR for template noncompliance
  when the substance is present. A ritually enforced form breeds ritual
  compliance — boxes checked without meaning, then ignored by reviewers,
  costing everyone and informing no one.
- **Every checklist item that could be a CI check is a bug in the
  checklist.** A checkbox taxes every contributor forever; a CI check has
  zero marginal human cost and never rots. The changelog fragment and the
  public-symbols check are already enforced by CI, so the PR template points
  at them rather than asking for a self-report. This is the enforcement
  ladder (principle 6) argued from the human side.
- **Gates key on change risk, never on tooling** (principle 7) — risk-keyed
  gates feel fair; tool-keyed gates feel insulting and are unenforceable.
- **Watch the drop-off signals.** Friction is invisible from the
  maintainer's seat. Declining drive-by contributions (docs fixes, small
  cleanups), template sections deleted wholesale or filled with "n/a"
  noise, and rising time-to-first-contribution all say the balance has
  tipped — loosen the forms, not the specifications.

## The deterministic floor (roadmap)

The ladder's first rung. This repository already has an unusually strong
floor — a `public-symbols-check` that fails CI on any public API change, a
towncrier changelog-fragment check, `ruff`, `pyright`, and `pytest-benchmark`
— so the items below close *specific remaining gaps*, and each removes a
class of review comment permanently:

1. **Public-API review ergonomics.** The `public-symbols-check` already
   forces a human to look at every added or removed public symbol (via the
   `Approve Public API check` label). The gap is upstream: surface the
   symbol diff in the PR so the reviewer — and the contributing agent —
   sees it before requesting review, not after CI fails. This is
   presentation, not a new gate.
2. **Differential linting.** Enable ruff's baseline/new-code modes so strict
   new rules can apply to new code without a repo-wide legacy cleanup,
   letting the ruleset tighten over time without a flag day.
3. **Project-idiom rules.** A small, hand-written bundle of custom checks
   (ruff or pylint plugins) encoding `CONTRIBUTING.md`'s conventions —
   `OTEL_PYTHON_`-prefixed environment variables declared in an
   `environment_variables` module, no new public symbols without the
   approval label, Google-style docstrings on public API — so the recurring
   review comments become CI output.
4. **Spec-default assertions.** The specification's environment-variable and
   default-value tables are semi-structured; a small check asserting our
   defaults, names, and units against them catches the silent-noncompliance
   class (wrong unit, wrong default) that has produced multi-year bugs in
   other SIGs.

## Adopting this beyond opentelemetry-python

The language-agnostic pieces — this document, the issue lifecycle and
template, the PR evidence template, the spec-compliance review skill, and
the spec-default checker — could live in a community repository and be
adopted per-SIG. The API-design skill and idiom rules are inherently
per-language and need each SIG's maintainers to encode their own
conventions. The spec-compliance surface is the best build-once candidate:
the specification and its compliance matrix are shared by every SIG, and
today every SIG verifies compliance by hand.

## References

All sources below were verified against primary material; claims that could
not be verified were excluded from this document.

**Policies referenced by principle 5 (evidence, not assertions):**

- FastAPI contributing guidelines, "Automated Code and AI":
  <https://tiangolo.com/open-source/contributing/#automated-code-and-ai> —
  "If the human effort put in a PR, e.g. writing LLM prompts, is less than
  the effort we would need to put to review it, please don't submit the PR."
- curl's experience with unstructured AI submissions — bug bounty ended
  January 2026 after a flood of fabricated AI reports:
  <https://daniel.haxx.se/blog/2026/01/26/the-end-of-the-curl-bug-bounty/>

**Policy referenced by principle 9 (reviewer-facing automation):**

- Django, "Submitting contributions":
  <https://docs.djangoproject.com/en/dev/internals/contributing/writing-code/submitting-patches/>
  — requires disclosure of AI tool use and prohibits requesting automated
  AI reviews on Django PRs because they "do not replace human review and
  often generate noise."
- OpenTelemetry community GenAI policy:
  <https://github.com/open-telemetry/community/blob/main/policies/genai.md>
  — the SIG-wide rule this repo's `AGENTS.md` enforces: no AI-generated
  comments on issues or PRs.

**Evidence for principle 3 (keep tasks small):**

- OpenAI, "Introducing SWE-bench Verified":
  <https://openai.com/index/introducing-swe-bench-verified/> — difficulty
  annotations: 38.8% of tasks ≤15 min, 52.2% 15 min–1 hr, 9% ≥1 hr.
- Analyses of success by difficulty and file spread (J. Ganhotra):
  <https://jatinganhotra.dev/blog/swe-agents/2025/06/05/swe-bench-verified-discriminative-subsets.html>
  — top agents resolve 84–86% of easy tasks but ~42% of hard tasks and
  ~10% of multi-file problems.

**Evidence for principle 1's localization guidance:**

- Liang, Garg, Zilouchian Moghaddam, "The SWE-Bench Illusion: When
  State-of-the-Art LLMs Remember Instead of Reason":
  <https://arxiv.org/abs/2506.12286> — models identify buggy file paths
  from issue text alone at up to 76% on SWE-bench repositories vs. ~53% on
  repositories outside the benchmark, i.e. agents cannot be assumed to
  "know" a codebase's layout; issues must localize.

**Evidence for principle 8 (hand-written, minimal guidance files):**

- Gloaguen, Mündler, Müller, Raychev, Vechev (ETH Zurich), "Evaluating
  AGENTS.md: Are Repository-Level Context Files Helpful for Coding
  Agents?": <https://arxiv.org/abs/2602.11988> — context files do not
  generally improve task success while increasing inference cost by over
  20%; LLM-generated files slightly *reduce* resolution rates, while
  minimal developer-written files give a marginal gain.

**The AGENTS.md convention:**

- <https://agents.md/> — donated to the Linux Foundation's Agentic AI
  Foundation (Dec 2025), adopted by 60,000+ projects; read by Copilot,
  Cursor, Codex, Gemini CLI, and others:
  <https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation>

**Tooling for the deterministic floor:**

- Ruff (linter/formatter, baseline/differential modes):
  <https://docs.astral.sh/ruff/>
- towncrier (changelog fragments): <https://towncrier.readthedocs.io/>
- pytest-benchmark: <https://pytest-benchmark.readthedocs.io/>
- OpenTelemetry spec compliance matrix:
  <https://github.com/open-telemetry/opentelemetry-specification/blob/main/spec-compliance-matrix.md>
