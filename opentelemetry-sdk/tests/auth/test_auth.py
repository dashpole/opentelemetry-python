# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.parse
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import MagicMock

import pytest

from opentelemetry.sdk._auth import (
    AuthenticationError,
    Authenticator,
    OAuth2Authenticator,
    redact_sensitive_text,
)
from opentelemetry.util._importlib_metadata import entry_points


class _TokenServerState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.request_count = 0
        self.last_headers: dict[str, str] = {}
        self.last_form: dict[str, list[str]] = {}
        self.status_code = 200
        self.response_body: dict[str, Any] | str = {
            "access_token": "token-1",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        self.delay_seconds = 0.0
        self.token_sequence: list[dict[str, Any]] = []


def _start_token_server(state: _TokenServerState) -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # pylint: disable=invalid-name
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8")
            if state.delay_seconds > 0:
                time.sleep(state.delay_seconds)
            with state.lock:
                state.request_count += 1
                state.last_headers = {k.lower(): v for k, v in self.headers.items()}
                state.last_form = urllib.parse.parse_qs(raw_body, keep_blank_values=True)
                status = state.status_code
                if state.token_sequence:
                    body_obj: Any = state.token_sequence.pop(0)
                else:
                    body_obj = state.response_body

            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            payload = (
                body_obj.encode("utf-8")
                if isinstance(body_obj, str)
                else json.dumps(body_obj).encode("utf-8")
            )
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:  # pylint: disable=redefined-builtin
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/oauth/token"


class TestOAuth2Authenticator:
    def test_validation_errors(self) -> None:
        with pytest.raises(ValueError, match="token_url"):
            OAuth2Authenticator("", "client", "secret")
        with pytest.raises(ValueError, match="token_url"):
            OAuth2Authenticator("ftp://example.com/token", "client", "secret")
        with pytest.raises(ValueError, match="client_id"):
            OAuth2Authenticator("https://example.com/token", "", "secret")
        with pytest.raises(ValueError, match="client_secret"):
            OAuth2Authenticator("https://example.com/token", "client", None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="timeout"):
            OAuth2Authenticator("https://example.com/token", "client", "secret", timeout=0)
        with pytest.raises(ValueError, match="expiry_margin_seconds"):
            OAuth2Authenticator(
                "https://example.com/token",
                "client",
                "secret",
                expiry_margin_seconds=-1.0,
            )

    def test_repr_and_str_redact_secret(self) -> None:
        auth = OAuth2Authenticator(
            "https://auth.example.com/oauth/token",
            "my-client-id",
            "super-secret-value-123",
            scopes=["otel:write", "otel:logs"],
            audience="https://otlp.example.com",
        )
        for text in (repr(auth), str(auth)):
            assert "super-secret-value-123" not in text
            assert "[REDACTED]" in text
            assert "my-client-id" in text
            assert "https://auth.example.com/oauth/token" in text

    def test_redact_sensitive_text(self) -> None:
        raw = (
            "Error with Bearer eyJhbGciOiJIUzI1NiJ9.secret and client_secret=topsecret "
            'and {"client_secret": "json-secret", "access_token": "json-token"}'
        )
        redacted = redact_sensitive_text(raw)
        assert "eyJhbGciOiJIUzI1NiJ9" not in redacted
        assert "topsecret" not in redacted
        assert "json-secret" not in redacted
        assert "json-token" not in redacted
        assert "[REDACTED]" in redacted

    def test_token_fetch_and_caching(self) -> None:
        state = _TokenServerState()
        server, token_url = _start_token_server(state)
        try:
            auth = OAuth2Authenticator(
                token_url=token_url,
                client_id="test-client",
                client_secret="test-secret",
                scopes=["traces:write", "metrics:write"],
                audience="https://collector.example.com",
                extra_params={"resource": "urn:otel"},
            )
            headers1 = auth.get_headers()
            headers2 = auth.get_headers()

            assert headers1 == {"Authorization": "Bearer token-1"}
            assert headers2 == {"Authorization": "Bearer token-1"}
            assert state.request_count == 1
            assert state.last_form["grant_type"] == ["client_credentials"]
            assert state.last_form["client_id"] == ["test-client"]
            assert state.last_form["client_secret"] == ["test-secret"]
            assert state.last_form["scope"] == ["traces:write metrics:write"]
            assert state.last_form["audience"] == ["https://collector.example.com"]
            assert state.last_form["resource"] == ["urn:otel"]

            expected_basic = base64.b64encode(b"test-client:test-secret").decode("ascii")
            assert state.last_headers.get("authorization") == f"Basic {expected_basic}"
        finally:
            server.shutdown()
            server.server_close()

    def test_token_refresh_on_expiry(self) -> None:
        state = _TokenServerState()
        state.token_sequence = [
            {"access_token": "short-token-1", "token_type": "bearer", "expires_in": 1},
            {"access_token": "short-token-2", "token_type": "Bearer", "expires_in": 3600},
        ]
        server, token_url = _start_token_server(state)
        try:
            auth = OAuth2Authenticator(
                token_url=token_url,
                client_id="client",
                client_secret="secret",
                expiry_margin_seconds=0.8,
            )
            assert auth.get_headers() == {"Authorization": "Bearer short-token-1"}
            assert state.request_count == 1

            time.sleep(0.3)
            assert auth.get_headers() == {"Authorization": "Bearer short-token-2"}
            assert state.request_count == 2
        finally:
            server.shutdown()
            server.server_close()

    def test_concurrent_single_flight_refresh(self) -> None:
        state = _TokenServerState()
        state.delay_seconds = 0.05
        server, token_url = _start_token_server(state)
        try:
            auth = OAuth2Authenticator(
                token_url=token_url,
                client_id="client",
                client_secret="secret",
            )
            results: list[Mapping[str, str]] = []
            errors: list[Exception] = []
            barrier = threading.Barrier(8)

            def worker() -> None:
                try:
                    barrier.wait()
                    results.append(auth.get_headers())
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors
            assert len(results) == 8
            assert all(r == {"Authorization": "Bearer token-1"} for r in results)
            assert state.request_count == 1
        finally:
            server.shutdown()
            server.server_close()

    def test_timeout_handling(self) -> None:
        state = _TokenServerState()
        state.delay_seconds = 0.5
        server, token_url = _start_token_server(state)
        try:
            auth = OAuth2Authenticator(
                token_url=token_url,
                client_id="client",
                client_secret="secret",
                timeout=0.05,
            )
            with pytest.raises(TimeoutError):
                auth.get_headers()
        finally:
            server.shutdown()
            server.server_close()

    def test_error_handling_never_leaks_secret(self) -> None:
        state = _TokenServerState()
        state.status_code = 401
        state.response_body = {"error": "invalid_client", "secret_echo": "my-ultra-secret"}
        server, token_url = _start_token_server(state)
        try:
            auth = OAuth2Authenticator(
                token_url=token_url,
                client_id="client",
                client_secret="my-ultra-secret",
            )
            with pytest.raises(AuthenticationError) as exc_info:
                auth.get_headers()
            assert "401" in str(exc_info.value)
            assert "my-ultra-secret" not in str(exc_info.value)
        finally:
            server.shutdown()
            server.server_close()

    def test_invalid_token_responses(self) -> None:
        state = _TokenServerState()
        server, token_url = _start_token_server(state)
        try:
            auth = OAuth2Authenticator(token_url, "client", "secret")

            state.response_body = "not-json{"
            with pytest.raises(AuthenticationError, match="invalid JSON"):
                auth.get_headers()

            state.response_body = {"token_type": "Bearer"}
            with pytest.raises(AuthenticationError, match="access_token"):
                auth.get_headers()

            state.response_body = {"access_token": "tok", "expires_in": "not-a-number"}
            with pytest.raises(AuthenticationError, match="expires_in"):
                auth.get_headers()

            for invalid_exp in (True, False, 0, -10, "nan", "inf", "-inf"):
                state.response_body = {"access_token": "tok", "expires_in": invalid_exp}
                with pytest.raises(AuthenticationError, match="expires_in"):
                    auth.get_headers()
        finally:
            server.shutdown()
            server.server_close()

    def test_shutdown_and_custom_session(self) -> None:
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = json.dumps(
            {"access_token": "session-tok", "token_type": "Bearer", "expires_in": 3600}
        ).encode("utf-8")
        mock_session.post.return_value = mock_response

        auth = OAuth2Authenticator(
            token_url="https://auth.example.com/token",
            client_id="client",
            client_secret="secret",
            session=mock_session,
        )
        assert auth.get_headers() == {"Authorization": "Bearer session-tok"}
        auth.shutdown()
        auth.shutdown()  # Idempotent
        mock_session.close.assert_called_once()

        with pytest.raises(AuthenticationError, match="shut down"):
            auth.get_headers()

    def test_entry_point_registration(self) -> None:
        eps = list(entry_points(group="opentelemetry_authenticator", name="oauth2"))
        assert len(eps) == 1
        assert eps[0].load() is OAuth2Authenticator
