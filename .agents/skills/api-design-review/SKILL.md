---
name: api-design-review
description: Review a PR or proposed API sketch for Python API design quality against this repo's conventions. Use when a change adds or modifies public (non-underscore) identifiers, or when a maintainer asks for design review of signatures proposed on an issue.
---

# Python API Design Review

Judgment-level review of public API surface. Assume the deterministic checks
(`ruff`, `pyright`, `public-symbols-check`) already ran — do not repeat what
they catch (formatting, type errors, the raw list of added symbols). Your
scope is everything a tool cannot see: whether the API *should* exist and
whether it is shaped right. Output goes to the reviewing maintainer — do not
post PR comments.

## First, the public-symbol gate

Every public symbol (any identifier not starting with a single underscore, in
a non-`_internal` module) is a permanent backwards-compatibility commitment.
`public-symbols-check` fails CI on any add or remove precisely to force this
review; a PR that adds public symbols must carry the `Approve Public API
check` label, meaning a human signed off. So the first question for every
added identifier is: **does it need to be public at all?** The default is a
single leading underscore or an `_internal` package. Public API beyond the
linked issue's approved sketch is a blocking finding. No approved sketch on
the issue + new public API = blocking finding, full stop.

## Checklist

Work through the diff's public surface. For each added or changed identifier,
in order:

1. **Necessity.** Required by the linked issue's approved API design? Anything
   exported beyond the approved sketch is a finding.
2. **Permanent-commitment test.** Would we maintain this exact name and
   signature forever? Flag: stutter, abbreviations, `get_`/`set_` prefixes
   where a property or plain attribute reads better, booleans where an enum
   will need a third value, concrete types in signatures where the caller
   only needs a protocol/ABC.
3. **Extensibility.** Can this grow without breaking? Optional configuration
   should be **keyword-only** (`def __init__(self, *, timeout_millis=...)`)
   so parameters can be added and reordered without breaking callers;
   required arguments precede the `*`. Prefer accepting an abstract base
   class / `Protocol` and returning a concrete type. Spec-defined extension
   points are `abc.ABC` with `@abstractmethod` (see `sdk.trace.sampling`,
   `sdk.trace.export`); adding an abstract method to a released ABC breaks
   external subclasses — treat it as breaking.
4. **Type hints.** Every public signature is fully annotated (parameters and
   return). No `type: ignore` in the diff (`AGENTS.md`); a type error is
   solved properly, not suppressed. `pyright` must be clean.
5. **Consistency.** Does it match the naming and shape of the nearest
   analogous API (trace vs. metrics vs. logs, API package vs. SDK)? The API
   package defines abstract behavior and no-op defaults; the SDK implements.
   New no-op API additions must be safe and allocation-light when telemetry
   is off. Divergence between signal APIs for the same concept is a finding
   even when both designs are individually fine.
6. **Configuration surface.** New environment variables are `OTEL_PYTHON_`-
   prefixed, declared in an `environment_variables` module, and registered
   via the `opentelemetry_environment_variables` entry point
   (`CONTRIBUTING.md`). Env-var reads belong in the SDK, not the API.
7. **Docs.** Public API carries a Google-style docstring (napoleon)
   (`CONTRIBUTING.md`, "Style Guide").

## Report format

Findings ranked by severity, each with: identifier, the problem in one
sentence, and a concrete alternative signature (not just "reconsider"). Then
a short section listing surface that looks right — the maintainer needs to
know what was checked, not only what failed. End with a verdict: approve
surface as-is / approve with renames / needs design round on the issue.
