---
name: benchmark-review
description: Compare benchmark performance of a PR branch against its base and produce a formatted pytest-benchmark report. Use when a PR claims a performance improvement, touches SDK hot paths (span start/end, metric record, context propagation), or a maintainer asks for a performance check.
---

# Benchmark Comparison Review

Produce a statistically honest before/after benchmark comparison for a change.
The output is a report the contributor can paste into the PR's Evidence
section, or the reviewer can use directly. This repo uses
[`pytest-benchmark`](https://pytest-benchmark.readthedocs.io/); benchmark
tests live under a package's `benchmarks/` folder in files named
`test_benchmark_*.py` (`CONTRIBUTING.md`).

## Non-negotiable method

- **Baseline via a separate worktree — never switch branches in place.**
  `git stash` / `git checkout` dances lose state and invalidate the
  environment:

  ```sh
  git worktree add /tmp/bench-base $(git merge-base HEAD origin/main)
  ```

  (Use the PR's actual base branch if it is not `main`.)

- **Save a named baseline, then compare — don't eyeball two runs.**
  pytest-benchmark persists results and compares them for you:

  ```sh
  # in the baseline worktree:
  tox -e benchmark-opentelemetry-sdk -- --benchmark-save=base
  # in the PR tree:
  tox -e benchmark-opentelemetry-sdk -- --benchmark-compare=base --benchmark-compare-fail=mean:5%
  ```

  Use `tox -f benchmark` to discover the benchmark environments; scope to the
  package the diff touches (plus in-repo dependents). Repo-wide runs are slow
  and drown the signal. `--benchmark-compare-fail=mean:5%` makes a regression
  beyond the threshold a non-zero exit, so it is reproducible in CI/console.

- **Repetition and stability.** Let pytest-benchmark control rounds
  (`--benchmark-min-rounds` if a benchmark is too short to be stable). Report
  `Mean`, `StdDev`, and `OPS` — a delta smaller than the combined standard
  deviation is noise, not a finding. Note the environment: shared or
  virtualized machines are noisy; if results look unstable, raise the round
  count or rerun rather than cherry-picking a clean run. Trust the
  distribution, not a single fast run.

## What to flag

1. **Allocation / object-churn on hot paths.** Span start/end, metric record,
   and context attach/detach are hot. A benchmark that constructs objects per
   operation where the base did not is a finding even if `Mean` looks flat,
   because it shows up as GC pressure under load. Call it out with the
   benchmark name.
2. **Significant time regressions** in touched packages, with the specific
   benchmark names and the compare table.
3. **Claims without coverage:** the PR claims a speedup but no benchmark
   exercises the changed code — say which benchmark is missing and sketch it
   (a `test_benchmark_*` using the `benchmark` fixture, per `CONTRIBUTING.md`).
4. **Benchmark quality:** benchmarks that include fixture/setup cost in the
   measured callable, or measure the wrong unit of work.

## Report format

Start with the verdict in one sentence (improves / regresses / no reliable
change / claims unsubstantiated). Then the raw pytest-benchmark compare table
in a code block, an environment note (machine, round count), and findings. Do
not editorialize beyond what the statistics support. Remove the worktree
(`git worktree remove /tmp/bench-base`) when done.
