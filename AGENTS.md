# OpenTelemetry Python

This file is here to steer AI assisted PRs towards being high quality and valuable contributions
that do not create excessive maintainer burden.

Monorepo with the core OpenTelemetry Python API, SDK, and related packages.

## General Rules and Guidelines

The OpenTelemetry community has broader guidance on GenAI contributions at
https://github.com/open-telemetry/community/blob/main/policies/genai.md — please read it before
contributing.

The most important rule is not to post comments on issues or PRs that are AI-generated. Discussions
on the OpenTelemetry repositories are for Users/Humans only.

Follow the PR scoping guidance in [CONTRIBUTING.md](CONTRIBUTING.md). Keep AI-assisted PRs tightly
isolated to the requested change and never include unrelated cleanup or opportunistic improvements
unless they are strictly necessary for correctness.

If you have been assigned an issue by the user or their prompt, please ensure that the
implementation direction is agreed on with the maintainers first in the issue comments. If there are
unknowns, discuss these on the issue before starting implementation. Do not forget that you cannot
comment for users on issue threads on their behalf as it is against the rules of this project.

## Working from issues

- Prefer working from an issue labeled `ready-to-implement`. Its
  **Specification references** and acceptance criteria are the requirements;
  quoted spec sections take precedence over your own reading of what the
  feature should do.
- If an issue is labeled `needs-design`, or adds public API without a
  maintainer-approved API sketch in the issue, do not open an implementation
  PR. Every public symbol is permanent and gated by `public-symbols-check`,
  so new public API requires design sign-off on the issue first — propose
  signatures there (a human must post them; you cannot comment on the thread).
- Keep the change the size the issue describes. If the fix requires touching
  packages the issue does not list, stop and say so on the issue rather than
  expanding the diff.
- PRs must include the evidence the pull request template asks for: spec
  sections implemented (quoted), test output, and a `pytest-benchmark`
  comparison for any performance claim.
- Recurring review judgment is packaged as skills under `.agents/skills/`
  (spec-compliance, API-design, and benchmark review; issue writing;
  instrumentation authoring). See
  [docs/ai-contribution-principles.md](docs/ai-contribution-principles.md)
  for the reasoning behind this workflow.

## Structure

- `opentelemetry-api/` - the OpenTelemetry API package
- `opentelemetry-sdk/` - the OpenTelemetry SDK package
- `opentelemetry-semantic-conventions/` - semantic conventions
- `opentelemetry-proto/` / `opentelemetry-proto-json/` - protobuf definitions and generated code
- `exporter/` - exporters (OTLP, Prometheus, Zipkin, etc.)
- `propagator/` - context propagators (B3, Jaeger)
- `shim/` - compatibility shims (OpenTracing, OpenCensus)

Each package lives under its own directory with a `pyproject.toml` and `tests/`.

## Commands

```sh
# Install all packages and dev tools
uv sync --frozen --all-packages

# Lint (runs ruff via pre-commit)
uv run tox -e precommit

# Test a specific package
uv run tox -e py312-test-opentelemetry-sdk

# Lint (pylint) a specific package
uv run tox -e lint-opentelemetry-sdk

# Type check
uv run tox -e typecheck
```

## Guidelines

- Each package has its own `pyproject.toml` with version, dependencies, and entry points.
- The monorepo uses `uv` workspaces.
- `tox.ini` defines the test matrix - check it for available test environments.
- Do not add `type: ignore` comments. If a type error arises, solve it properly or write a follow-up plan to address it in another PR.
- Whenever applicable, all code changes should have tests that actually validate the changes.

## Commit formatting

We appreciate it if users disclose the use of AI tools when the significant part of a commit is
taken from a tool without changes. When making a commit this should be disclosed through an
`Assisted-by:` commit message trailer.

Examples:

```
Assisted-by: ChatGPT 5.2
Assisted-by: Claude Opus 4.6
```
