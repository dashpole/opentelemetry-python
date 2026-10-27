# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
import json
import math
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any, Final

_SENSITIVE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)(bearer\s+\S+|basic\s+\S+|(?:client_secret|access_token|refresh_token)[\s\"']*[=:][\s\"']*[^\s\"',}]+)"
)


def redact_sensitive_text(text: str) -> str:
    """Redact potential bearer tokens, basic credentials, or secrets from error strings."""
    return _SENSITIVE_PATTERN.sub("[REDACTED]", text)


class AuthenticationError(RuntimeError):
    """Raised when an Authenticator fails to acquire or refresh credentials."""


class Authenticator(ABC):
    """Interface for pluggable per-export OTLP authentication providers.

    Implementations MUST:
    - Be safe for concurrent calls to :meth:`get_headers` from multiple threads.
    - Not block indefinitely when acquiring or refreshing credentials.
    - Redact sensitive credentials (such as client secrets or bearer tokens) in
      ``__repr__``, ``__str__``, logs, and exception messages.
    """

    @abstractmethod
    def get_headers(self) -> Mapping[str, str]:
        """Return authentication headers/metadata to attach to an outbound export request.

        Returns:
            Mapping of header/metadata names to string values.
        """

    def shutdown(self) -> None:
        """Release any resources held by the authenticator.

        Must be idempotent.
        """


class OAuth2Authenticator(Authenticator):
    """OAuth 2.0 Client Credentials grant authenticator for OTLP HTTP and gRPC exporters.

    Acquires bearer tokens from an OAuth 2.0 token endpoint using ``grant_type=client_credentials``,
    caches tokens in memory, and refreshes them proactively before expiration in a thread-safe manner.
    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        *,
        scopes: Sequence[str] | str | None = None,
        audience: str | None = None,
        extra_params: Mapping[str, str] | None = None,
        timeout: float = 10.0,
        expiry_margin_seconds: float | None = None,
        ca_file: str | None = None,
        session: Any | None = None,
    ) -> None:
        if not isinstance(token_url, str) or not token_url.strip():
            raise ValueError("token_url must be a non-empty URL string")
        parsed = urllib.parse.urlparse(token_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"token_url must be a valid http or https URL, got {token_url!r}")
        if not isinstance(client_id, str) or not client_id:
            raise ValueError("client_id must be a non-empty string")
        if not isinstance(client_secret, str):
            raise ValueError("client_secret must be a string")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if expiry_margin_seconds is not None and expiry_margin_seconds < 0:
            raise ValueError("expiry_margin_seconds must be non-negative")

        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        if isinstance(scopes, str):
            self._scopes: tuple[str, ...] = tuple(s for s in scopes.split() if s)
        elif scopes is not None:
            self._scopes = tuple(str(s) for s in scopes if s)
        else:
            self._scopes = ()
        self._audience = audience
        self._extra_params = dict(extra_params) if extra_params is not None else {}
        self._timeout = float(timeout)
        self._expiry_margin_seconds = (
            float(expiry_margin_seconds) if expiry_margin_seconds is not None else None
        )
        self._ca_file = ca_file
        self._session = session

        self._lock = threading.Lock()
        self._cached_headers: dict[str, str] | None = None
        self._expires_at: float | None = None
        self._shutdown = False

    @property
    def token_url(self) -> str:
        return self._token_url

    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def scopes(self) -> tuple[str, ...]:
        return self._scopes

    @property
    def audience(self) -> str | None:
        return self._audience

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"token_url={self._token_url!r}, "
            f"client_id={self._client_id!r}, "
            f"client_secret='[REDACTED]', "
            f"scopes={self._scopes!r}, "
            f"audience={self._audience!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def _is_token_valid(self, now: float) -> bool:
        if self._cached_headers is None:
            return False
        if self._expires_at is None:
            return True
        return now < self._expires_at

    def get_headers(self) -> Mapping[str, str]:
        with self._lock:
            if self._shutdown:
                raise AuthenticationError("OAuth2Authenticator has been shut down")

            now = time.monotonic()
            if self._is_token_valid(now):
                assert self._cached_headers is not None
                return dict(self._cached_headers)

            fetched_at = time.monotonic()
            token_data = self._fetch_token()
            access_token = token_data.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise AuthenticationError(
                    "OAuth2 token response did not contain a valid 'access_token'"
                )

            raw_token_type = token_data.get("token_type", "Bearer")
            if not isinstance(raw_token_type, str) or not raw_token_type.strip():
                token_type = "Bearer"
            elif raw_token_type.strip().lower() == "bearer":
                token_type = "Bearer"
            else:
                token_type = raw_token_type.strip()

            expires_in_raw = token_data.get("expires_in")
            if expires_in_raw is not None:
                if isinstance(expires_in_raw, bool):
                    raise AuthenticationError(
                        "OAuth2 token response contained boolean 'expires_in'"
                    )
                try:
                    expires_in = float(expires_in_raw)
                except (TypeError, ValueError) as exc:
                    raise AuthenticationError(
                        "OAuth2 token response contained non-numeric 'expires_in'"
                    ) from exc
                if not math.isfinite(expires_in) or expires_in <= 0:
                    raise AuthenticationError(
                        "OAuth2 token response contained non-positive or non-finite 'expires_in'"
                    )
                if self._expiry_margin_seconds is not None:
                    margin = self._expiry_margin_seconds
                else:
                    margin = min(60.0, max(expires_in * 0.1, 0.0))
                self._expires_at = fetched_at + expires_in - margin
            else:
                self._expires_at = None

            self._cached_headers = {"Authorization": f"{token_type} {access_token}"}
            return dict(self._cached_headers)

    def _fetch_token(self) -> dict[str, Any]:
        form_params: dict[str, str] = {}
        if self._extra_params:
            form_params.update(self._extra_params)
        form_params["grant_type"] = "client_credentials"
        form_params["client_id"] = self._client_id
        form_params["client_secret"] = self._client_secret
        if self._scopes:
            form_params["scope"] = " ".join(self._scopes)
        if self._audience:
            form_params["audience"] = self._audience

        encoded_body = urllib.parse.urlencode(form_params).encode("utf-8")
        basic_raw = (
            f"{urllib.parse.quote(self._client_id, safe='')}:"
            f"{urllib.parse.quote(self._client_secret, safe='')}"
        ).encode("utf-8")
        basic_b64 = base64.b64encode(basic_raw).decode("ascii")

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Authorization": f"Basic {basic_b64}",
        }

        if self._session is not None:
            try:
                response = self._session.post(
                    self._token_url,
                    data=encoded_body,
                    headers=headers,
                    timeout=self._timeout,
                    verify=self._ca_file if self._ca_file is not None else True,
                )
                status_code = response.status_code
                body_bytes = response.content
            except TimeoutError:
                raise
            except Exception as exc:
                if "timeout" in type(exc).__name__.lower():
                    raise TimeoutError(
                        f"OAuth2 token request to {self._token_url} timed out"
                    ) from None
                raise AuthenticationError(
                    f"OAuth2 token request to {self._token_url} failed: {type(exc).__name__}"
                ) from None

            if status_code < 200 or status_code >= 300:
                raise AuthenticationError(
                    f"OAuth2 token request to {self._token_url} failed with HTTP status {status_code}"
                )
        else:
            req = urllib.request.Request(
                self._token_url,
                data=encoded_body,
                headers=headers,
                method="POST",
            )
            ssl_context: ssl.SSLContext | None = None
            if self._ca_file is not None:
                ssl_context = ssl.create_default_context(cafile=self._ca_file)
            try:
                with urllib.request.urlopen(
                    req, timeout=self._timeout, context=ssl_context
                ) as resp:
                    status_code = resp.status
                    body_bytes = resp.read()
            except urllib.error.HTTPError as exc:
                raise AuthenticationError(
                    f"OAuth2 token request to {self._token_url} failed with HTTP status {exc.code}"
                ) from None
            except TimeoutError as exc:
                raise TimeoutError(
                    f"OAuth2 token request to {self._token_url} timed out"
                ) from exc
            except urllib.error.URLError as exc:
                if isinstance(exc.reason, TimeoutError) or "timed out" in str(exc.reason).lower():
                    raise TimeoutError(
                        f"OAuth2 token request to {self._token_url} timed out"
                    ) from None
                raise AuthenticationError(
                    f"OAuth2 token request to {self._token_url} failed: {type(exc.reason).__name__}"
                ) from None
            except Exception as exc:
                raise AuthenticationError(
                    f"OAuth2 token request to {self._token_url} failed: {type(exc).__name__}"
                ) from None

            if status_code < 200 or status_code >= 300:
                raise AuthenticationError(
                    f"OAuth2 token request to {self._token_url} failed with HTTP status {status_code}"
                )

        try:
            parsed_json = json.loads(body_bytes.decode("utf-8"))
        except Exception as exc:
            raise AuthenticationError(
                f"OAuth2 token endpoint {self._token_url} returned invalid JSON"
            ) from exc

        if not isinstance(parsed_json, dict):
            raise AuthenticationError(
                f"OAuth2 token endpoint {self._token_url} did not return a JSON object"
            )
        return parsed_json

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._cached_headers = None
            self._expires_at = None
            if self._session is not None and hasattr(self._session, "close"):
                try:
                    self._session.close()
                except Exception:  # pylint: disable=broad-exception-caught
                    pass


__all__ = [
    "AuthenticationError",
    "Authenticator",
    "OAuth2Authenticator",
    "redact_sensitive_text",
]
