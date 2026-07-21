---
name: add-instrumentation
description: Add OpenTelemetry traces or metrics to Python code using the OpenTelemetry API. Use when asked to instrument a library, add spans or metrics to an operation, or wire semantic-convention telemetry into code that depends on the otel-python API.
---

# Add Instrumentation

Add tracing or metrics to Python code using this project's own conventions.
The subject is a library (or a component) that instruments its own operations
against the OpenTelemetry **API** — not application setup code that configures
the SDK.

**The API docstrings are canonical for API facts.** This skill cites them and
adds only what has no docstring home: spec-level rules the API docs do not yet
state, and repo procedure. If this skill and a docstring disagree, the
docstring wins — and if you rely on an API fact stated only here, treat that
as a docstring gap worth fixing.

## Ground rules

- **API, never SDK.** Instrumented code imports `opentelemetry.trace`,
  `opentelemetry.metrics`, `opentelemetry.propagate`, and
  `opentelemetry-semantic-conventions` only. It never constructs providers,
  never sets globals (`set_tracer_provider`), and never imports
  `opentelemetry.sdk` outside its tests. Configuration is the application's
  job.
- **Acquire the tracer/meter the standard way.** Call
  `trace.get_tracer(__name__, instrumenting_library_version, schema_url=...)`
  (and `metrics.get_meter(...)` likewise) at module or class scope. Name the
  instrumentation by its own package/module, pass the library version, and
  set `schema_url` to the semconv version in use. When `get_tracer` is called
  before an SDK provider is installed it returns a proxy that starts working
  once configured — so acquiring at import time is safe.
- **Semantic conventions, pinned.** Take attribute keys, span names, metric
  names, and units from `opentelemetry.semconv` at one pinned version. Stable
  conventions live under `opentelemetry.semconv.attributes` /
  `.trace` / `.metrics`; anything under `opentelemetry.semconv._incubating`
  is unstable — pin it deliberately and expect churn. Never hand-write a name
  or unit that semconv already defines.
- **Telemetry must not hurt the host.** No exceptions escaping the
  instrumentation, no blocking, no unbounded growth. If starting a span or
  recording a measurement would fail, the instrumented operation still
  proceeds. A no-op provider (nothing configured) must be a cheap no-op.
- **Bound cardinality** (spec rule). Attribute values come from a small known
  set. Record `error.type` (the exception class), never the exception
  message; never put user-controlled input (URLs with IDs, queries, raw user
  input) into attribute values. Span names are low-cardinality templates — an
  operation name, not a formatted URL.
- **Near-zero cost when disabled.** Guard expensive attribute computation with
  `span.is_recording()`. Don't build attribute dicts or format strings that
  are only needed when recording. For metrics, build the static attribute
  mapping once at construction, not per record.

## Tracing

- Prefer the context manager: `with tracer.start_as_current_span(name) as
  span:` — it starts the span, makes it current, and ends it (and, by
  default, records exceptions and sets `ERROR` status on an uncaught
  exception) even on error. Use `start_span` + `trace.use_span` only when you
  need to hand the span across scopes.
- On a handled failure, call `span.set_status(Status(StatusCode.ERROR))` and
  `span.record_exception(exc)` explicitly — `record_exception` adds an event
  and does **not** change the span status by itself.
- Kind matters: pass `kind=SpanKind.CLIENT/SERVER/PRODUCER/CONSUMER` at span
  start for spans that cross a process boundary; the default is `INTERNAL`.

## Metrics

- Pick the instrument by semantics: `Counter` (monotonic), `UpDownCounter`
  (in-flight / can decrease), `Histogram` (distributions, e.g. durations),
  and the observable/callback variants for values read on collection. Create
  instruments once (at meter-acquisition time), not per operation.
- Units are UCUM codes. Durations are recorded as a `Histogram` in **seconds**
  (unit `s`) — measure with `time.perf_counter()` and record the float
  difference. Instrument names are dot-separated, no plural "count" nouns:
  `http.server.request.duration`, not `requests.count`.
- Attach only bounded attributes on each record; reuse a precomputed mapping
  for the static ones.

## Propagation

Inject/extract only at the process boundaries the library actually owns (an
HTTP client/server, a queue producer/consumer), using
`opentelemetry.propagate.inject` / `.extract` with the global (or a
caller-supplied) propagator. Pure in-process code just lets `contextvars`
carry the current span; do not manually inject in-process.

## Tests and evidence

- Traces: assert against the SDK's in-memory exporter
  (`InMemorySpanExporter` with a `SimpleSpanProcessor`, or a
  `TracerProvider` + reader in a fixture) — span names, attributes, kind,
  status, and parent/child links. Import the SDK only in tests.
- Metrics: drive `sdk.metrics` with an `InMemoryMetricReader` and assert on
  the collected data points — name, unit, attributes, and value.
- No-op path: add a test (or benchmark) showing that with nothing configured
  the instrumented call does no measurable extra work and never raises.
- SPDX header on every new `.py` file and a Google-style docstring on public
  API (`CONTRIBUTING.md`). Add a `.changelog/` fragment if the change is
  user-visible.
