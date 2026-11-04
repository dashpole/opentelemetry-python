# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest.mock import Mock

from opentelemetry import _logs, metrics, trace
from opentelemetry._logs._internal import ProxyLogger
from opentelemetry.metrics._internal import _ProxyMeter
from opentelemetry.util._stability import _Stability


class TestStabilityAPI(unittest.TestCase):
    def test_stability_enum_ordering_and_exports(self):
        self.assertLess(_Stability.DEVELOPMENT, _Stability.STABLE)
        self.assertIs(trace._Stability, _Stability)
        self.assertIs(metrics._Stability, _Stability)
        self.assertIs(_logs._Stability, _Stability)

    def test_noop_and_proxy_tracer_stability(self):
        noop_tracer = trace.NoOpTracer()
        self.assertFalse(noop_tracer._attribute_enabled("k"))
        self.assertFalse(noop_tracer._attribute_enabled("k", _Stability.DEVELOPMENT))
        self.assertFalse(noop_tracer._attribute_enabled("k", _Stability.STABLE))

        with noop_tracer.start_as_current_span("dev_span", _stability=_Stability.DEVELOPMENT) as span:
            self.assertFalse(span.is_recording())

        proxy_tracer = trace.ProxyTracer("scope")
        self.assertFalse(proxy_tracer._attribute_enabled("k", _Stability.DEVELOPMENT))
        real_tracer = Mock()
        real_tracer._attribute_enabled.return_value = True
        proxy_tracer._real_tracer = real_tracer
        self.assertTrue(proxy_tracer._attribute_enabled("k", _Stability.DEVELOPMENT))
        real_tracer._attribute_enabled.assert_called_once_with("k", _Stability.DEVELOPMENT, context=None)

    def test_noop_and_proxy_meter_stability_and_opt_in(self):
        noop_meter = metrics.NoOpMeter("scope")
        self.assertFalse(noop_meter._attribute_enabled("k"))
        self.assertFalse(noop_meter._attribute_enabled("k", _Stability.DEVELOPMENT))
        self.assertFalse(noop_meter._attribute_enabled("k", _Stability.STABLE))
        noop_meter.create_counter("c", _stability=_Stability.DEVELOPMENT, _opt_in=True)

        proxy_meter = _ProxyMeter("scope")
        self.assertFalse(proxy_meter._attribute_enabled("k", _Stability.DEVELOPMENT))
        proxy_meter.create_counter("c", _stability=_Stability.DEVELOPMENT, _opt_in=True)

        real_mp = Mock()
        real_meter = Mock()
        real_meter._attribute_enabled.return_value = True
        real_mp.get_meter.return_value = real_meter

        proxy_meter.on_set_meter_provider(real_mp)
        real_meter.create_counter.assert_called_once_with(
            "c",
            "",
            "",
            _stability=_Stability.DEVELOPMENT,
            _opt_in=True,
        )
        self.assertTrue(proxy_meter._attribute_enabled("k", _Stability.DEVELOPMENT))
        real_meter._attribute_enabled.assert_called_once_with("k", _Stability.DEVELOPMENT, context=None)

    def test_noop_and_proxy_logger_stability(self):
        noop_logger = _logs.NoOpLogger("scope")
        self.assertFalse(noop_logger.enabled(_stability=_Stability.DEVELOPMENT))
        self.assertFalse(noop_logger._attribute_enabled("k"))
        self.assertFalse(noop_logger._attribute_enabled("k", _Stability.DEVELOPMENT))
        self.assertFalse(noop_logger._attribute_enabled("k", _Stability.STABLE))
        noop_logger.emit(body="msg", _stability=_Stability.DEVELOPMENT)

        proxy_logger = ProxyLogger("scope")
        self.assertFalse(proxy_logger.enabled(_stability=_Stability.DEVELOPMENT))
        self.assertFalse(proxy_logger._attribute_enabled("k", _Stability.DEVELOPMENT))
        real_logger = Mock()
        real_logger.enabled.return_value = False
        real_logger._attribute_enabled.return_value = True
        proxy_logger._real_logger = real_logger

        self.assertFalse(
            proxy_logger.enabled(
                severity_number=_logs.SeverityNumber.INFO,
                _stability=_Stability.DEVELOPMENT,
            )
        )
        real_logger.enabled.assert_called_once_with(
            context=None,
            severity_number=_logs.SeverityNumber.INFO,
            event_name=None,
            _stability=_Stability.DEVELOPMENT,
        )
        self.assertTrue(proxy_logger._attribute_enabled("k", _Stability.DEVELOPMENT))
        real_logger._attribute_enabled.assert_called_once_with("k", _Stability.DEVELOPMENT, context=None)
        record = _logs.LogRecord(body="dev")
        proxy_logger.emit(record, _stability=_Stability.DEVELOPMENT)
        real_logger.emit.assert_called_once_with(record, _stability=_Stability.DEVELOPMENT)
