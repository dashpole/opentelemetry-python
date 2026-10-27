# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import gzip
import json
import threading
import time
import urllib.parse
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
import requests

from opentelemetry._logs import LogRecord, SeverityNumber
from opentelemetry.exporter.otlp.json.http._log_exporter import (
    OTLPLogExporter as JsonOTLPLogExporter,
)
from opentelemetry.exporter.otlp.json.http.metric_exporter import (
    OTLPMetricExporter as JsonOTLPMetricExporter,
)
from opentelemetry.exporter.otlp.json.http.trace_exporter import (
    OTLPSpanExporter as JsonOTLPSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
    ExportLogsServiceResponse,
)
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
    ExportMetricsServiceResponse,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
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
    provider = TracerProvider(resource=Resource.create({"service.name": "auth-http-e2e"}))
    provider.add_span_processor(SimpleSpanProcessor(mem_exporter))
    tracer = provider.get_tracer("auth-http-tracer")
    with tracer.start_as_current_span("authenticated-http-span") as span:
        span.set_attribute("http.auth", "oauth2")
    spans = list(mem_exporter.get_finished_spans())
    provider.shutdown()
    return spans


def _make_sample_metrics() -> MetricsData:
    reader = InMemoryMetricReader()
    provider = MeterProvider(
        resource=Resource.create({"service.name": "auth-http-e2e"}),
        metric_readers=[reader],
    )
    meter = provider.get_meter("auth-http-meter")
    counter = meter.create_counter("authenticated.http.counter")
    counter.add(42, {"env": "test"})
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
                body="authenticated http log message",
                attributes={"log.auth": "oauth2"},
            ),
            resource=Resource.create({"service.name": "auth-http-e2e"}),
            instrumentation_scope=InstrumentationScope("auth-http-logger", "1.0"),
        )
    ]


class _LocalOAuth2AndOTLPHTTPServers:
    """Runs a local OAuth 2.0 Token Server and a local OTLP/HTTP Collector Server."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.expected_client_id = "otlp-http-client"
        self.expected_client_secret = "otlp-http-secret"
        self.token_counter = 0
        self.current_valid_token: str | None = None
        self.expires_in = 3600
        self.token_requests = 0
        self.fail_token_endpoint = False

        self.received_traces: list[ExportTraceServiceRequest | dict[str, Any]] = []
        self.received_metrics: list[ExportMetricsServiceRequest | dict[str, Any]] = []
        self.received_logs: list[ExportLogsServiceRequest | dict[str, Any]] = []
        self.received_headers: list[dict[str, str]] = []
        self.fail_next_otlp_requests = 0
        self.rotate_token_on_otlp_503 = False

        self.token_server = ThreadingHTTPServer(("127.0.0.1", 0), self._make_token_handler())
        self.otlp_server = ThreadingHTTPServer(("127.0.0.1", 0), self._make_otlp_handler())
        self._token_thread = threading.Thread(target=self.token_server.serve_forever, daemon=True)
        self._otlp_thread = threading.Thread(target=self.otlp_server.serve_forever, daemon=True)

    def start(self) -> None:
        self._token_thread.start()
        self._otlp_thread.start()

    def stop(self) -> None:
        self.token_server.shutdown()
        self.token_server.server_close()
        self.otlp_server.shutdown()
        self.otlp_server.server_close()

    @property
    def token_url(self) -> str:
        host, port = self.token_server.server_address[:2]
        return f"http://{host}:{port}/oauth/token"

    @property
    def otlp_base_url(self) -> str:
        host, port = self.otlp_server.server_address[:2]
        return f"http://{host}:{port}"

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
                    token = f"valid-http-bearer-token-{parent.token_counter}"
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

    def _make_otlp_handler(self) -> type[BaseHTTPRequestHandler]:
        parent = self

        class OTLPHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # pylint: disable=invalid-name
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                if self.headers.get("Content-Encoding", "").lower() == "gzip":
                    body = gzip.decompress(body)

                headers_lower = {k.lower(): v for k, v in self.headers.items()}
                auth_header = headers_lower.get("authorization")

                with parent.lock:
                    parent.received_headers.append(headers_lower)
                    if parent.fail_next_otlp_requests > 0:
                        parent.fail_next_otlp_requests -= 1
                        if parent.rotate_token_on_otlp_503:
                            # Invalidate cached token in server so retry must present refreshed token
                            parent.current_valid_token = "rotated"
                        self.send_response(503)
                        self.send_header("Retry-After", "0.01")
                        self.end_headers()
                        return

                    expected = (
                        f"Bearer {parent.current_valid_token}"
                        if parent.current_valid_token
                        else None
                    )
                    if expected is None or auth_header != expected:
                        self.send_response(401)
                        self.end_headers()
                        return

                    content_type = headers_lower.get("content-type", "")
                    is_json = "application/json" in content_type

                    if self.path == "/v1/traces":
                        if is_json:
                            parent.received_traces.append(json.loads(body.decode("utf-8")))
                            resp_bytes = b"{}"
                        else:
                            req = ExportTraceServiceRequest()
                            req.ParseFromString(body)
                            parent.received_traces.append(req)
                            resp_bytes = ExportTraceServiceResponse().SerializeToString()
                    elif self.path == "/v1/metrics":
                        if is_json:
                            parent.received_metrics.append(json.loads(body.decode("utf-8")))
                            resp_bytes = b"{}"
                        else:
                            req = ExportMetricsServiceRequest()
                            req.ParseFromString(body)
                            parent.received_metrics.append(req)
                            resp_bytes = ExportMetricsServiceResponse().SerializeToString()
                    elif self.path == "/v1/logs":
                        if is_json:
                            parent.received_logs.append(json.loads(body.decode("utf-8")))
                            resp_bytes = b"{}"
                        else:
                            req = ExportLogsServiceRequest()
                            req.ParseFromString(body)
                            parent.received_logs.append(req)
                            resp_bytes = ExportLogsServiceResponse().SerializeToString()
                    else:
                        self.send_response(404)
                        self.end_headers()
                        return

                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/json" if is_json else "application/x-protobuf",
                )
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)

            def log_message(self, format: str, *args: Any) -> None:  # pylint: disable=redefined-builtin
                pass

        return OTLPHandler


class TestOTLPHTTPAuthEndToEnd:
    def test_all_three_proto_http_exporters_authenticate_and_export_e2e(self) -> None:
        harness = _LocalOAuth2AndOTLPHTTPServers()
        harness.start()
        try:
            authenticator = OAuth2Authenticator(
                token_url=harness.token_url,
                client_id=harness.expected_client_id,
                client_secret=harness.expected_client_secret,
                scopes=["otel:write"],
            )
            static_headers = {
                "authorization": "Bearer stale-static-token",
                "X-Custom-Header": "custom-val",
            }

            span_exporter = OTLPSpanExporter(
                endpoint=f"{harness.otlp_base_url}/v1/traces",
                headers=static_headers,
                compression=Compression.Gzip,
                _authenticator=authenticator,
            )
            metric_exporter = OTLPMetricExporter(
                endpoint=f"{harness.otlp_base_url}/v1/metrics",
                headers=static_headers,
                compression=Compression.Gzip,
                _authenticator=authenticator,
            )
            log_exporter = OTLPLogExporter(
                endpoint=f"{harness.otlp_base_url}/v1/logs",
                headers=static_headers,
                compression=Compression.Gzip,
                _authenticator=authenticator,
            )

            assert span_exporter.export(_make_sample_spans()) is SpanExportResult.SUCCESS
            assert metric_exporter.export(_make_sample_metrics()) is MetricExportResult.SUCCESS
            assert log_exporter.export(_make_sample_logs()) is LogRecordExportResult.SUCCESS

            # Token was fetched once and cached across all 3 exporters
            assert harness.token_requests == 1
            assert len(harness.received_traces) == 1
            assert len(harness.received_metrics) == 1
            assert len(harness.received_logs) == 1

            # Verify static_headers was not mutated and X-Custom-Header was preserved
            assert static_headers == {
                "authorization": "Bearer stale-static-token",
                "X-Custom-Header": "custom-val",
            }
            for req_headers in harness.received_headers:
                assert req_headers["authorization"] == "Bearer valid-http-bearer-token-1"
                assert req_headers["x-custom-header"] == "custom-val"
                assert req_headers["content-encoding"] == "gzip"

            span_exporter.shutdown()
            metric_exporter.shutdown()
            log_exporter.shutdown()
        finally:
            harness.stop()

    def test_all_three_json_http_exporters_authenticate_and_export_e2e(self) -> None:
        harness = _LocalOAuth2AndOTLPHTTPServers()
        harness.start()
        try:
            authenticator = OAuth2Authenticator(
                token_url=harness.token_url,
                client_id=harness.expected_client_id,
                client_secret=harness.expected_client_secret,
            )
            span_exporter = JsonOTLPSpanExporter(
                endpoint=f"{harness.otlp_base_url}/v1/traces",
                _authenticator=authenticator,
            )
            metric_exporter = JsonOTLPMetricExporter(
                endpoint=f"{harness.otlp_base_url}/v1/metrics",
                _authenticator=authenticator,
            )
            log_exporter = JsonOTLPLogExporter(
                endpoint=f"{harness.otlp_base_url}/v1/logs",
                _authenticator=authenticator,
            )

            assert span_exporter.export(_make_sample_spans()) is SpanExportResult.SUCCESS
            assert metric_exporter.export(_make_sample_metrics()) is MetricExportResult.SUCCESS
            assert log_exporter.export(_make_sample_logs()) is LogRecordExportResult.SUCCESS

            assert harness.token_requests == 1
            assert len(harness.received_traces) == 1
            assert len(harness.received_metrics) == 1
            assert len(harness.received_logs) == 1

            span_exporter.shutdown()
            metric_exporter.shutdown()
            log_exporter.shutdown()
        finally:
            harness.stop()

    def test_token_expiry_triggers_refresh_and_succeeds(self) -> None:
        harness = _LocalOAuth2AndOTLPHTTPServers()
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
                endpoint=f"{harness.otlp_base_url}/v1/traces",
                _authenticator=authenticator,
            )

            assert span_exporter.export(_make_sample_spans()) is SpanExportResult.SUCCESS
            assert harness.token_requests == 1
            assert harness.received_headers[-1]["authorization"] == "Bearer valid-http-bearer-token-1"

            time.sleep(0.3)
            assert span_exporter.export(_make_sample_spans()) is SpanExportResult.SUCCESS
            assert harness.token_requests == 2
            assert harness.received_headers[-1]["authorization"] == "Bearer valid-http-bearer-token-2"

            span_exporter.shutdown()
        finally:
            harness.stop()

    def test_retry_reinvokes_authenticator_and_coexists_with_custom_session(self) -> None:
        harness = _LocalOAuth2AndOTLPHTTPServers()
        harness.fail_next_otlp_requests = 1
        harness.start()
        try:
            tokens = ["Bearer valid-http-bearer-token-A", "Bearer valid-http-bearer-token-B"]
            call_count = 0

            class RotatingAuthenticator(Authenticator):
                def get_headers(self) -> Mapping[str, str]:
                    nonlocal call_count
                    tok = tokens[min(call_count, len(tokens) - 1)]
                    call_count += 1
                    with harness.lock:
                        harness.current_valid_token = tok.removeprefix("Bearer ")
                    return {"Authorization": tok}

            custom_session = requests.Session()
            custom_session.headers["X-From-Session"] = "session-val"

            span_exporter = OTLPSpanExporter(
                endpoint=f"{harness.otlp_base_url}/v1/traces",
                session=custom_session,
                _authenticator=RotatingAuthenticator(),
            )

            assert span_exporter.export(_make_sample_spans()) is SpanExportResult.SUCCESS
            assert call_count == 2
            assert len(harness.received_headers) == 2
            assert harness.received_headers[0]["authorization"] == "Bearer valid-http-bearer-token-A"
            assert harness.received_headers[1]["authorization"] == "Bearer valid-http-bearer-token-B"
            assert harness.received_headers[1]["x-from-session"] == "session-val"

            span_exporter.shutdown()
        finally:
            harness.stop()

    def test_auth_failure_and_type_validation(self) -> None:
        for cls in (OTLPSpanExporter, OTLPMetricExporter, OTLPLogExporter):
            with pytest.raises(TypeError, match="Authenticator"):
                cls(_authenticator="invalid")  # type: ignore[arg-type]

        harness = _LocalOAuth2AndOTLPHTTPServers()
        harness.fail_token_endpoint = True
        harness.start()
        try:
            auth = OAuth2Authenticator(
                token_url=harness.token_url,
                client_id=harness.expected_client_id,
                client_secret=harness.expected_client_secret,
            )
            span_exporter = OTLPSpanExporter(
                endpoint=f"{harness.otlp_base_url}/v1/traces",
                _authenticator=auth,
            )
            metric_exporter = OTLPMetricExporter(
                endpoint=f"{harness.otlp_base_url}/v1/metrics",
                _authenticator=auth,
            )
            log_exporter = OTLPLogExporter(
                endpoint=f"{harness.otlp_base_url}/v1/logs",
                _authenticator=auth,
            )

            assert span_exporter.export(_make_sample_spans()) is SpanExportResult.FAILURE
            assert metric_exporter.export(_make_sample_metrics()) is MetricExportResult.FAILURE
            assert log_exporter.export(_make_sample_logs()) is LogRecordExportResult.FAILURE

            span_exporter.shutdown()
            metric_exporter.shutdown()
            log_exporter.shutdown()
        finally:
            harness.stop()
