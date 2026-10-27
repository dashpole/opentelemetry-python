# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest

from opentelemetry.context import _SUPPRESS_INSTRUMENTATION_KEY, get_value
from opentelemetry.exporter.http.transport._base import (
    BaseHTTPResult,
    BaseHTTPTransport,
)
from opentelemetry.exporter.otlp.common.http import _OTLPHTTPClient
from opentelemetry.sdk._auth import (
    AuthenticationError,
    Authenticator,
    OAuth2Authenticator,
)


@dataclass(frozen=True, slots=True)
class _MockResult(BaseHTTPResult):
    resp_headers: dict[str, str] = field(default_factory=dict)

    def headers(self) -> Mapping[str, str]:
        return self.resp_headers

    def content(self) -> bytes:
        return b""


class _RecordingTransport(BaseHTTPTransport):
    def __init__(self, responses: list[_MockResult] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.responses = list(responses) if responses else [_MockResult(200, "OK")]
        self.closed = False

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        data: bytes | None = None,
        timeout: float | None = None,
    ) -> BaseHTTPResult:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers) if headers else {},
                "data": data,
                "timeout": timeout,
            }
        )
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]

    def is_connection_error(self, error: Exception | None) -> bool:
        return isinstance(error, ConnectionError)

    def close(self) -> None:
        self.closed = True


class _CountingAuthenticator(Authenticator):
    def __init__(self, tokens: list[str] | None = None) -> None:
        self.tokens = list(tokens) if tokens else ["tok-1"]
        self.calls: int = 0
        self.shut_down = False

    def get_headers(self) -> Mapping[str, str]:
        self.calls += 1
        idx = min(self.calls - 1, len(self.tokens) - 1)
        return {"Authorization": f"Bearer {self.tokens[idx]}"}

    def shutdown(self) -> None:
        self.shut_down = True


class TestOTLPHTTPClientAuthenticator:
    def test_auth_symbols_available_from_sdk_auth(self) -> None:
        assert Authenticator is not None
        assert OAuth2Authenticator is not None
        assert AuthenticationError is not None

    def test_type_validation_at_init(self) -> None:
        transport = _RecordingTransport()
        with pytest.raises(TypeError, match="Authenticator"):
            _OTLPHTTPClient(
                transport=transport,
                endpoint="http://localhost:4318/v1/traces",
                kind="spans",
                _authenticator="invalid",  # type: ignore[arg-type]
            )

    def test_case_insensitive_header_override_without_mutating_static_headers(self) -> None:
        transport = _RecordingTransport()
        static_headers = {
            "authorization": "Bearer static-token",
            "X-Static-Custom": "preserve-me",
        }
        auth = _CountingAuthenticator(["dynamic-token-1"])
        client = _OTLPHTTPClient(
            transport=transport,
            endpoint="http://localhost:4318/v1/traces",
            kind="spans",
            headers=static_headers,
            _authenticator=auth,
        )

        result = client.export(b"payload")
        assert result.success is True
        assert len(transport.calls) == 1
        sent_headers = transport.calls[0]["headers"]
        assert isinstance(sent_headers, dict)
        assert sent_headers == {
            "Authorization": "Bearer dynamic-token-1",
            "X-Static-Custom": "preserve-me",
        }
        # Static headers dict passed by caller and client._headers must not be mutated
        assert static_headers == {
            "authorization": "Bearer static-token",
            "X-Static-Custom": "preserve-me",
        }
        assert client._headers == {
            "authorization": "Bearer static-token",
            "X-Static-Custom": "preserve-me",
        }

    def test_invoked_on_each_retry_attempt(self) -> None:
        transport = _RecordingTransport(
            responses=[
                _MockResult(503, "Service Unavailable", resp_headers={"retry-after": "0.01"}),
                _MockResult(200, "OK"),
            ]
        )
        auth = _CountingAuthenticator(["retry-tok-1", "retry-tok-2"])
        client = _OTLPHTTPClient(
            transport=transport,
            endpoint="http://localhost:4318/v1/traces",
            kind="spans",
            timeout=5.0,
            jitter=0.0,
            _authenticator=auth,
        )

        result = client.export(b"payload")
        assert result.success is True
        assert auth.calls == 2
        assert transport.calls[0]["headers"] == {"Authorization": "Bearer retry-tok-1"}
        assert transport.calls[1]["headers"] == {"Authorization": "Bearer retry-tok-2"}

    def test_invoked_on_immediate_connection_error_retry(self) -> None:
        transport = _RecordingTransport(
            responses=[
                _MockResult(None, None, ConnectionError("stale connection")),
                _MockResult(200, "OK"),
            ]
        )
        auth = _CountingAuthenticator(["conn-tok-1", "conn-tok-2"])
        client = _OTLPHTTPClient(
            transport=transport,
            endpoint="http://localhost:4318/v1/traces",
            kind="spans",
            timeout=5.0,
            _authenticator=auth,
        )

        result = client.export(b"payload")
        assert result.success is True
        assert auth.calls == 2
        assert transport.calls[0]["headers"] == {"Authorization": "Bearer conn-tok-1"}
        assert transport.calls[1]["headers"] == {"Authorization": "Bearer conn-tok-2"}

    def test_auth_failure_does_not_leak_exception_and_redacts_logs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        class FailingAuthenticator(Authenticator):
            def get_headers(self) -> Mapping[str, str]:
                raise AuthenticationError("failed with Bearer super-secret-jwt-999")

        transport = _RecordingTransport()
        logger = logging.getLogger("test.otlp.http.auth")
        client = _OTLPHTTPClient(
            transport=transport,
            endpoint="http://localhost:4318/v1/traces",
            kind="spans",
            logger=logger,
            _authenticator=FailingAuthenticator(),
        )

        with caplog.at_level(logging.ERROR, logger="test.otlp.http.auth"):
            result = client.export(b"payload")

        assert result.success is False
        assert isinstance(result.error, AuthenticationError)
        assert len(transport.calls) == 0
        assert "super-secret-jwt-999" not in caplog.text
        assert "[REDACTED]" in caplog.text

    def test_suppress_instrumentation_context_attached_during_get_headers(self) -> None:
        observed_suppress: list[object] = []

        class ContextCheckingAuthenticator(Authenticator):
            def get_headers(self) -> Mapping[str, str]:
                observed_suppress.append(get_value(_SUPPRESS_INSTRUMENTATION_KEY))
                return {"Authorization": "Bearer ctx-tok"}

        transport = _RecordingTransport()
        client = _OTLPHTTPClient(
            transport=transport,
            endpoint="http://localhost:4318/v1/traces",
            kind="spans",
            _authenticator=ContextCheckingAuthenticator(),
        )
        assert get_value(_SUPPRESS_INSTRUMENTATION_KEY) is None
        result = client.export(b"payload")
        assert result.success is True
        assert observed_suppress == [True]
        assert get_value(_SUPPRESS_INSTRUMENTATION_KEY) is None

    def test_shutdown_forwards_to_authenticator(self) -> None:
        transport = _RecordingTransport()
        auth = _CountingAuthenticator()
        client = _OTLPHTTPClient(
            transport=transport,
            endpoint="http://localhost:4318/v1/traces",
            kind="spans",
            _authenticator=auth,
        )
        client.shutdown()
        assert transport.closed is True
        assert auth.shut_down is True
