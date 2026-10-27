# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from unittest.mock import patch

import pytest

from opentelemetry.configuration._common import _create_authenticator
from opentelemetry.configuration._exceptions import ConfigurationError
from opentelemetry.configuration._logger_provider import (
    _create_otlp_grpc_log_exporter,
    _create_otlp_http_log_exporter,
)
from opentelemetry.configuration._meter_provider import (
    _create_otlp_grpc_metric_exporter,
    _create_otlp_http_metric_exporter,
)
from opentelemetry.configuration._tracer_provider import (
    _create_otlp_grpc_span_exporter,
    _create_otlp_http_span_exporter,
)
from opentelemetry.configuration.file._loader import load_config_file
from opentelemetry.configuration.models import (
    ExperimentalAuthenticator,
    OtlpGrpcExporter,
    OtlpGrpcMetricExporter,
    OtlpHttpEncoding,
    OtlpHttpExporter,
    OtlpHttpMetricExporter,
)
from opentelemetry.sdk._auth import Authenticator, OAuth2Authenticator


class _CustomPluginAuthenticator(Authenticator):
    def __init__(self, api_key: str = "default") -> None:
        self.api_key = api_key

    def get_headers(self) -> Mapping[str, str]:
        return {"X-API-Key": self.api_key}


class TestAuthenticatorConfiguration:
    def test_load_yaml_with_oauth2_authenticator_across_signals(self, tmp_path: Path) -> None:
        yaml_content = """\
file_format: "1.0"
tracer_provider:
  processors:
    - batch:
        exporter:
          otlp_http:
            endpoint: http://localhost:4318/v1/traces
            authenticator/development:
              oauth2:
                token_url: https://auth.example.com/oauth/token
                client_id: trace-client
                client_secret: trace-secret
                scopes:
                  - traces:write
                audience: https://traces.example.com
meter_provider:
  readers:
    - periodic:
        exporter:
          otlp_grpc:
            endpoint: http://localhost:4317
            authenticator/development:
              oauth2:
                token_url: https://auth.example.com/oauth/token
                client_id: metric-client
                client_secret: metric-secret
logger_provider:
  processors:
    - batch:
        exporter:
          otlp_http:
            endpoint: http://localhost:4318/v1/logs
            encoding: json
            authenticator/development:
              oauth2:
                token_url: https://auth.example.com/oauth/token
                client_id: log-client
                client_secret: log-secret
"""
        cfg_file = tmp_path / "otel-config.yaml"
        cfg_file.write_text(yaml_content, encoding="utf-8")

        config = load_config_file(cfg_file)
        assert config.tracer_provider is not None
        span_http_cfg = config.tracer_provider.processors[0].batch.exporter.otlp_http
        assert span_http_cfg is not None
        assert span_http_cfg.authenticator_development is not None
        oauth2_props = span_http_cfg.authenticator_development.additional_properties.get("oauth2")
        assert oauth2_props is not None
        assert oauth2_props["client_id"] == "trace-client"
        assert oauth2_props["scopes"] == ["traces:write"]
        assert oauth2_props["audience"] == "https://traces.example.com"

        span_exporter = _create_otlp_http_span_exporter(span_http_cfg)
        assert isinstance(span_exporter._client._authenticator, OAuth2Authenticator)
        assert span_exporter._client._authenticator.client_id == "trace-client"

        assert config.logger_provider is not None
        log_http_cfg = config.logger_provider.processors[0].batch.exporter.otlp_http
        assert log_http_cfg is not None
        log_exporter = _create_otlp_http_log_exporter(log_http_cfg)
        assert isinstance(log_exporter._client._authenticator, OAuth2Authenticator)
        assert log_exporter._client._authenticator.client_id == "log-client"

    def test_create_exporters_pass_authenticator_to_http_and_grpc(self) -> None:
        auth_cfg = ExperimentalAuthenticator(
            oauth2={
                "token_url": "https://auth.example.com/oauth/token",
                "client_id": "my-client",
                "client_secret": "my-secret",
            }
        )

        http_metric_exporter = _create_otlp_http_metric_exporter(
            OtlpHttpMetricExporter(
                endpoint="http://localhost:4318/v1/metrics",
                authenticator_development=auth_cfg,
            )
        )
        assert isinstance(http_metric_exporter._client._authenticator, OAuth2Authenticator)

        json_metric_exporter = _create_otlp_http_metric_exporter(
            OtlpHttpMetricExporter(
                endpoint="http://localhost:4318/v1/metrics",
                encoding=OtlpHttpEncoding.json,
                authenticator_development=auth_cfg,
            )
        )
        assert isinstance(json_metric_exporter._client._authenticator, OAuth2Authenticator)

        with (
            patch("grpc.insecure_channel"),
            patch("opentelemetry.exporter.otlp.proto.grpc.exporter.insecure_channel"),
        ):
            grpc_span_exporter = _create_otlp_grpc_span_exporter(
                OtlpGrpcExporter(
                    endpoint="http://localhost:4317",
                    authenticator_development=auth_cfg,
                )
            )
            assert isinstance(grpc_span_exporter._authenticator, OAuth2Authenticator)

            grpc_metric_exporter = _create_otlp_grpc_metric_exporter(
                OtlpGrpcMetricExporter(
                    endpoint="http://localhost:4317",
                    authenticator_development=auth_cfg,
                )
            )
            assert isinstance(grpc_metric_exporter._authenticator, OAuth2Authenticator)

            grpc_log_exporter = _create_otlp_grpc_log_exporter(
                OtlpGrpcExporter(
                    endpoint="http://localhost:4317",
                    authenticator_development=auth_cfg,
                )
            )
            assert isinstance(grpc_log_exporter._authenticator, OAuth2Authenticator)

    def test_custom_authenticator_plugin_via_entry_point(self) -> None:
        auth_cfg = ExperimentalAuthenticator(my_custom_auth={"api_key": "secret-key-42"})
        with patch(
            "opentelemetry.configuration._common.load_entry_point",
            return_value=_CustomPluginAuthenticator,
        ) as mock_ep:
            auth = _create_authenticator(auth_cfg)
            mock_ep.assert_called_once_with("opentelemetry_authenticator", "my_custom_auth")
            assert isinstance(auth, _CustomPluginAuthenticator)
            assert auth.api_key == "secret-key-42"

    def test_empty_authenticator_config_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="No authenticator type specified"):
            _create_authenticator(ExperimentalAuthenticator())
