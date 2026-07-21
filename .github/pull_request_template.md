<!--
Keep it factual and short. Reviewers check evidence, not prose: a PR that
shows its work gets reviewed faster. PRs whose review cost exceeds the effort
evidently invested in them may be closed on that basis — see
docs/ai-contribution-principles.md.

This template is a default, not a contract: delete any section that does not
apply to your change (a docs fix or typo needs almost none of it).
-->

# Description

<!--
One or two sentences: what changes and why. Link the issue this implements.
If there is no ready-to-implement issue for this change and it touches public
API, open one first — public API changes without an approved design are not
reviewed (see CONTRIBUTING.md, "Public Symbols").
-->

Fixes # (issue)

## Specification references

<!--
Quote the normative spec sentence(s) this change implements, with pinned
links — usually copied from the issue. Write "n/a" for changes with no spec
surface.
-->

## Evidence

<!--
Show, don't tell. Paste the commands you ran and their relevant output:
- the test run for the new/changed behavior
- for performance claims or hot-path changes: a pytest-benchmark comparison
  (`--benchmark-compare` against a saved baseline)
Do not paste generated summaries of the diff; the diff speaks for itself.
-->

```console
tox -e ruff && tox -e py312-opentelemetry-sdk
```

## Out of scope

<!-- What you intentionally did NOT do, and where that work is tracked. -->

## Does This PR Require a Contrib Repo Change?

<!--
Answer Yes if this changes the public API of `opentelemetry-api/` or
`opentelemetry-sdk/`, the interfaces of `test/util`, or scripts/config files
copied into the Contrib repo (e.g. `pyproject.toml`, CODEOWNERS). See
CONTRIBUTING.md for the cross-repo procedure.
-->

- [ ] Yes. - Link to PR:
- [ ] No.

## Checklist

<!--
No changelog or public-symbols checkbox: CI enforces the changelog fragment
(see CONTRIBUTING.md, "Changelog") and the public-symbols check. A checklist
item a machine can verify is a bug in the checklist —
docs/ai-contribution-principles.md, principle 10.
-->

- [ ] Tests assert the issue's acceptance criteria (not implementation details)
- [ ] No new public symbols beyond the issue's approved API design
- [ ] Documentation updated if user-facing behavior changed
