# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import grpc
import pytest

from opentelemetry._logs import LogRecord, SeverityNumber
from opentelemetry.context import _SUPPRESS_INSTRUMENTATION_KEY, get_value
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
    ExportLogsServiceResponse,
)
from opentelemetry.proto.collector.logs.v1.logs_service_pb2_grpc import (
    LogsServiceServicer,
    add_LogsServiceServicer_to_server,
)
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
    ExportMetricsServiceResponse,
)
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2_grpc import (
    MetricsServiceServicer,
    add_MetricsServiceServicer_to_server,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2_grpc import (
    TraceServiceServicer,
    add_TraceServiceServicer_to_server,
)
from opentelemetry.sdk._logs import ReadWriteLogRecord
from opentelemetry.sdk._logs.export import LogRecordExportResult
from opentelemetry.sdk._auth import (
    AuthenticationError,
    Authenticator,
    OAuth2Authenticator,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    MetricExportResult,
    MetricsData,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExportResult,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.sdk.util.instrumentation import InstrumentationScope


def _make_sample_spans() -> list[ReadableSpan]:
    mem_exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "auth-grpc-e2e"}))
    provider.add_span_processor(SimpleSpanProcessor(mem_exporter))
    tracer = provider.get_tracer("auth-grpc-tracer")
    with tracer.start_as_current_span("authenticated-grpc-span") as span:
        span.set_attribute("rpc.auth", "oauth2")
    spans = list(mem_exporter.get_finished_spans())
    provider.shutdown()
    return spans


def _make_sample_metrics() -> MetricsData:
    reader = InMemoryMetricReader()
    provider = MeterProvider(
        resource=Resource.create({"service.name": "auth-grpc-e2e"}),
        metric_readers=[reader],
    )
    meter = provider.get_meter("auth-grpc-meter")
    counter = meter.create_counter("authenticated.grpc.counter")
    counter.add(7, {"env": "grpc-test"})
    data = reader.get_metrics_data()
    provider.shutdown()
    assert data is not None
    return data


def _make_sample_logs() -> list[ReadWriteLogRecord]:
    return [
        ReadWriteLogRecord(
            LogRecord(
                timestamp=1700000000000000000,
                severity_text="INFO",
                severity_number=SeverityNumber.INFO,
                body="authenticated grpc log message",
                attributes={"log.auth": "oauth2-grpc"},
            ),
            resource=Resource.create({"service.name": "auth-grpc-e2e"}),
            instrumentation_scope=InstrumentationScope("auth-grpc-logger", "1.0"),
        )
    ]


class _LocalOAuth2AndOTLPGRPCServers(
    TraceServiceServicer,
    MetricsServiceServicer,
    LogsServiceServicer,
):
    """Runs a local HTTP OAuth 2.0 Token Server and a local gRPC OTLP Collector Server."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.expected_client_id = "otlp-grpc-client"
        self.expected_client_secret = "otlp-grpc-secret"
        self.token_counter = 0
        self.current_valid_token: str | None = None
        self.expires_in = 3600
        self.token_requests = 0
        self.fail_token_endpoint = False

        self.received_traces: list[ExportTraceServiceRequest] = []
        self.received_metrics: list[ExportMetricsServiceRequest] = []
        self.received_logs: list[ExportLogsServiceRequest] = []
        self.received_metadata: list[dict[str, str]] = []
        self.fail_next_grpc_unavailable = 0

        self.token_server = ThreadingHTTPServer(("127.0.0.1", 0), self._make_token_handler())
        self._token_thread = threading.Thread(target=self.token_server.serve_forever, daemon=True)

        self.grpc_server = grpc.server(ThreadPoolExecutor(max_workers=4))
        add_TraceServiceServicer_to_server(self, self.grpc_server)
        add_MetricsServiceServicer_to_server(self, self.grpc_server)
        add_LogsServiceServicer_to_server(self, self.grpc_server)
        self.grpc_port = self.grpc_server.add_insecure_port("127.0.0.1:0")

    def start(self) -> None:
        self._token_thread.start()
        self.grpc_server.start()

    def stop(self) -> None:
        self.grpc_server.stop(grace=None)
        self.token_server.shutdown()
        self.token_server.server_close()

    @property
    def token_url(self) -> str:
        host, port = self.token_server.server_address[:2]
        return f"http://{host}:{port}/oauth/token"

    @property
    def grpc_endpoint(self) -> str:
        return f"http://127.0.0.1:{self.grpc_port}"

    def _make_token_handler(self) -> type[BaseHTTPRequestHandler]:
        parent = self

        class TokenHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # pylint: disable=invalid-name
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length).decode("utf-8")
                form = urllib.parse.parse_qs(raw_body)

                with parent.lock:
                    parent.token_requests += 1
                    if parent.fail_token_endpoint:
                        self.send_response(401)
                        self.end_headers()
                        self.wfile.write(b'{"error":"invalid_client"}')
                        return

                    if (
                        form.get("grant_type") != ["client_credentials"]
                        or form.get("client_id") != [parent.expected_client_id]
                        or form.get("client_secret") != [parent.expected_client_secret]
                    ):
                        self.send_response(401)
                        self.end_headers()
                        self.wfile.write(b'{"error":"unauthorized_client"}')
                        return

                    parent.token_counter += 1
                    token = f"valid-grpc-bearer-token-{parent.token_counter}"
                    parent.current_valid_token = token
                    payload = json.dumps(
                        {
                            "access_token": token,
                            "token_type": "Bearer",
                            "expires_in": parent.expires_in,
                        }
                    ).encode("utf-8")

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: Any) -> None:  # pylint: disable=redefined-builtin
                pass

        return TokenHandler

    def _verify_auth(self, context: grpc.ServicerContext) -> bool:
        meta = {k.lower(): v for k, v in context.invocation_metadata()}
        with self.lock:
            self.received_metadata.append(meta)
            if self.fail_next_grpc_unavailable > 0:
                self.fail_next_grpc_unavailable -= 1
                context.abort(grpc.StatusCode.UNAVAILABLE, "simulated transient unavailable")
            expected = (
                f"Bearer {self.current_valid_token}"
                if self.current_valid_token
                else None
            )
            if expected is None or meta.get("authorization") != expected:
                context.abort(grpc.StatusCode.UNAUTHENTICATED, "missing or invalid bearer token")
        return True

    def Export(self, request: Any, context: grpc.ServicerContext) -> Any:  # pylint: disable=invalid-name
        self._verify_auth(context)
        with self.lock:
            if isinstance(request, ExportTraceServiceRequest):
                self.received_traces.append(request)
                return ExportTraceServiceResponse()
            if isinstance(request, ExportMetricsServiceRequest):
                self.received_metrics.append(request)
                return ExportMetricsServiceResponse()
            if isinstance(request, ExportLogsServiceRequest):
                self.received_logs.append(request)
                return ExportLogsServiceResponse()
        context.abort(grpc.StatusCode.INVALID_ARGUMENT, "unknown request type")


class TestOTLPGRPCAuthEndToEnd:
    def test_all_three_grpc_exporters_authenticate_and_export_e2e(self) -> None:
        harness = _LocalOAuth2AndOTLPGRPCServers()
        harness.start()
        try:
            authenticator = OAuth2Authenticator(
                token_url=harness.token_url,
                client_id=harness.expected_client_id,
                client_secret=harness.expected_client_secret,
                scopes=["otel:write"],
            )
            static_headers = {
                "Authorization": "Bearer stale-static-grpc-token",
                "x-custom-meta": "preserve-grpc-meta",
            }

            span_exporter = OTLPSpanExporter(
                endpoint=harness.grpc_endpoint,
                insecure=True,
                headers=static_headers,
                compression=grpc.Compression.Gzip,
                _authenticator=authenticator,
            )
            metric_exporter = OTLPMetricExporter(
                endpoint=harness.grpc_endpoint,
                insecure=True,
                headers=static_headers,
                compression=grpc.Compression.Gzip,
                _authenticator=authenticator,
            )
            log_exporter = OTLPLogExporter(
                endpoint=harness.grpc_endpoint,
                insecure=True,
                headers=static_headers,
                compression=grpc.Compression.Gzip,
                _authenticator=authenticator,
            )

            assert span_exporter.export(_make_sample_spans()) is SpanExportResult.SUCCESS
            assert metric_exporter.export(_make_sample_metrics()) is MetricExportResult.SUCCESS
            assert log_exporter.export(_make_sample_logs()) is LogRecordExportResult.SUCCESS

            # Token fetched once and reused across all 3 gRPC exporters
            assert harness.token_requests == 1
            assert len(harness.received_traces) == 1
            assert len(harness.received_metrics) == 1
            assert len(harness.received_logs) == 1

            # Verify static_headers was not mutated and non-colliding metadata was preserved
            assert static_headers == {
                "Authorization": "Bearer stale-static-grpc-token",
                "x-custom-meta": "preserve-grpc-meta",
            }
            for meta in harness.received_metadata:
                assert meta["authorization"] == "Bearer valid-grpc-bearer-token-1"
                assert meta["x-custom-meta"] == "preserve-grpc-meta"

            span_exporter.shutdown()
            metric_exporter.shutdown()
            log_exporter.shutdown()
        finally:
            harness.stop()

    def test_grpc_token_expiry_triggers_refresh_and_succeeds(self) -> None:
        harness = _LocalOAuth2AndOTLPGRPCServers()
        harness.expires_in = 1
        harness.start()
        try:
            authenticator = OAuth2Authenticator(
                token_url=harness.token_url,
                client_id=harness.expected_client_id,
                client_secret=harness.expected_client_secret,
                expiry_margin_seconds=0.8,
            )
            span_exporter = OTLPSpanExporter(
                endpoint=harness.grpc_endpoint,
                insecure=True,
                _authenticator=authenticator,
            )

            assert span_exporter.export(_make_sample_spans()) is SpanExportResult.SUCCESS
            assert harness.token_requests == 1
            assert harness.received_metadata[-1]["authorization"] == "Bearer valid-grpc-bearer-token-1"

            time.sleep(0.3)
            assert span_exporter.export(_make_sample_spans()) is SpanExportResult.SUCCESS
            assert harness.token_requests == 2
            assert harness.received_metadata[-1]["authorization"] == "Bearer valid-grpc-bearer-token-2"

            span_exporter.shutdown()
        finally:
            harness.stop()

    def test_grpc_retry_reinvokes_authenticator(self) -> None:
        harness = _LocalOAuth2AndOTLPGRPCServers()
        harness.fail_next_grpc_unavailable = 1
        harness.start()
        try:
            tokens = ["Bearer valid-grpc-token-try1", "Bearer valid-grpc-token-try2"]
            call_count = 0

            class RotatingAuthenticator(Authenticator):
                def get_headers(self) -> Mapping[str, str]:
                    nonlocal call_count
                    tok = tokens[min(call_count, len(tokens) - 1)]
                    call_count += 1
                    with harness.lock:
                        harness.current_valid_token = tok.removeprefix("Bearer ")
                    return {"Authorization": tok}

            span_exporter = OTLPSpanExporter(
                endpoint=harness.grpc_endpoint,
                insecure=True,
                _authenticator=RotatingAuthenticator(),
            )

            assert span_exporter.export(_make_sample_spans()) is SpanExportResult.SUCCESS
            assert call_count == 2
            assert len(harness.received_metadata) == 2
            assert harness.received_metadata[0]["authorization"] == "Bearer valid-grpc-token-try1"
            assert harness.received_metadata[1]["authorization"] == "Bearer valid-grpc-token-try2"

            span_exporter.shutdown()
        finally:
            harness.stop()

    def test_grpc_auth_failure_redaction_and_type_validation(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        for cls in (OTLPSpanExporter, OTLPMetricExporter, OTLPLogExporter):
            with pytest.raises(TypeError, match="Authenticator"):
                cls(insecure=True, _authenticator="invalid")  # type: ignore[arg-type]

        class FailingAuthenticator(Authenticator):
            def __init__(self) -> None:
                self.shut_down = False

            def get_headers(self) -> Mapping[str, str]:
                raise AuthenticationError("failed with Bearer secret-grpc-jwt-999")

            def shutdown(self) -> None:
                self.shut_down = True

        auth = FailingAuthenticator()
        span_exporter = OTLPSpanExporter(
            endpoint="http://127.0.0.1:4317",
            insecure=True,
            _authenticator=auth,
        )
        with caplog.at_level(logging.ERROR):
            res = span_exporter.export(_make_sample_spans())
        assert res is SpanExportResult.FAILURE
        assert "secret-grpc-jwt-999" not in caplog.text
        assert "[REDACTED]" in caplog.text

        span_exporter.shutdown()
        assert auth.shut_down is True

    def test_grpc_suppress_instrumentation(self) -> None:
        harness = _LocalOAuth2AndOTLPGRPCServers()
        harness.start()
        try:
            observed_suppress: list[object] = []

            class ContextCheckingAuthenticator(Authenticator):
                def get_headers(self) -> Mapping[str, str]:
                    observed_suppress.append(get_value(_SUPPRESS_INSTRUMENTATION_KEY))
                    with harness.lock:
                        harness.current_valid_token = "ctx-grpc-tok"
                    return {"Authorization": "Bearer ctx-grpc-tok"}

            span_exporter = OTLPSpanExporter(
                endpoint=harness.grpc_endpoint,
                insecure=True,
                _authenticator=ContextCheckingAuthenticator(),
            )
            assert get_value(_SUPPRESS_INSTRUMENTATION_KEY) is None
            assert span_exporter.export(_make_sample_spans()) is SpanExportResult.SUCCESS
            assert observed_suppress == [True]
            assert get_value(_SUPPRESS_INSTRUMENTATION_KEY) is None
            span_exporter.shutdown()
        finally:
            harness.stop()
