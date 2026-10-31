# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import unittest

from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.metrics.view import SumAggregation, View
from opentelemetry.util._stability import _Stability


def _collected_metric_names(reader: InMemoryMetricReader) -> set[str]:
    data = reader.get_metrics_data()
    if data is None:
        return set()
    names: set[str] = set()
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                names.add(metric.name)
    return names


class TestMetricsStabilityAndOptIn(unittest.TestCase):
    def _create_and_record_four_matrix_counters(self, meter):
        c_stable_default = meter.create_counter(
            "c.stable.default",
            _stability=_Stability.STABLE,
            _opt_in=False,
        )
        c_stable_opt_in = meter.create_counter(
            "c.stable.opt_in",
            _stability=_Stability.STABLE,
            _opt_in=True,
        )
        c_dev_default = meter.create_counter(
            "c.dev.default",
            _stability=_Stability.DEVELOPMENT,
            _opt_in=False,
        )
        c_dev_opt_in = meter.create_counter(
            "c.dev.opt_in",
            _stability=_Stability.DEVELOPMENT,
            _opt_in=True,
        )

        c_stable_default.add(1)
        c_stable_opt_in.add(1)
        c_dev_default.add(1)
        c_dev_opt_in.add(1)
        return (
            c_stable_default,
            c_stable_opt_in,
            c_dev_default,
            c_dev_opt_in,
        )

    def test_2x2_matrix_default_minimum_stability_stable(self):
        reader = InMemoryMetricReader()
        provider = MeterProvider(metric_readers=[reader])
        meter = provider.get_meter("test.meter")

        (
            c_stable_default,
            c_stable_opt_in,
            c_dev_default,
            c_dev_opt_in,
        ) = self._create_and_record_four_matrix_counters(meter)

        self.assertTrue(c_stable_default._is_enabled())
        self.assertFalse(c_stable_opt_in._is_enabled())
        self.assertFalse(c_dev_default._is_enabled())
        self.assertFalse(c_dev_opt_in._is_enabled())

        self.assertEqual(
            _collected_metric_names(reader),
            {"c.stable.default"},
        )

    def test_2x2_matrix_minimum_stability_development(self):
        reader = InMemoryMetricReader()
        provider = MeterProvider(
            metric_readers=[reader],
            _minimum_stability=_Stability.DEVELOPMENT,
        )
        meter = provider.get_meter("test.meter")

        (
            c_stable_default,
            c_stable_opt_in,
            c_dev_default,
            c_dev_opt_in,
        ) = self._create_and_record_four_matrix_counters(meter)

        self.assertTrue(c_stable_default._is_enabled())
        self.assertFalse(c_stable_opt_in._is_enabled())
        self.assertTrue(c_dev_default._is_enabled())
        self.assertFalse(c_dev_opt_in._is_enabled())

        self.assertEqual(
            _collected_metric_names(reader),
            {"c.stable.default", "c.dev.default"},
        )

    def test_2x2_matrix_view_enabled_true_enables_all_rows(self):
        reader = InMemoryMetricReader()
        provider = MeterProvider(
            metric_readers=[reader],
            views=[View(instrument_name="c.*", _enabled=True)],
        )
        meter = provider.get_meter("test.meter")

        (
            c_stable_default,
            c_stable_opt_in,
            c_dev_default,
            c_dev_opt_in,
        ) = self._create_and_record_four_matrix_counters(meter)

        self.assertTrue(c_stable_default._is_enabled())
        self.assertTrue(c_stable_opt_in._is_enabled())
        self.assertTrue(c_dev_default._is_enabled())
        self.assertTrue(c_dev_opt_in._is_enabled())

        self.assertEqual(
            _collected_metric_names(reader),
            {
                "c.stable.default",
                "c.stable.opt_in",
                "c.dev.default",
                "c.dev.opt_in",
            },
        )

    def test_2x2_matrix_view_enabled_false_disables_all_rows(self):
        reader = InMemoryMetricReader()
        provider = MeterProvider(
            metric_readers=[reader],
            _minimum_stability=_Stability.DEVELOPMENT,
            views=[View(instrument_name="c.*", _enabled=False)],
        )
        meter = provider.get_meter("test.meter")

        (
            c_stable_default,
            c_stable_opt_in,
            c_dev_default,
            c_dev_opt_in,
        ) = self._create_and_record_four_matrix_counters(meter)

        self.assertFalse(c_stable_default._is_enabled())
        self.assertFalse(c_stable_opt_in._is_enabled())
        self.assertFalse(c_dev_default._is_enabled())
        self.assertFalse(c_dev_opt_in._is_enabled())

        self.assertEqual(_collected_metric_names(reader), set())

    def test_view_without_enabled_does_not_enable_opt_in_or_development(self):
        reader = InMemoryMetricReader()
        provider = MeterProvider(
            metric_readers=[reader],
            views=[
                View(
                    instrument_name="c.*",
                    description="custom description",
                    aggregation=SumAggregation(),
                )
            ],
        )
        meter = provider.get_meter("test.meter")

        (
            c_stable_default,
            c_stable_opt_in,
            c_dev_default,
            c_dev_opt_in,
        ) = self._create_and_record_four_matrix_counters(meter)

        self.assertTrue(c_stable_default._is_enabled())
        self.assertFalse(c_stable_opt_in._is_enabled())
        self.assertFalse(c_dev_default._is_enabled())
        self.assertFalse(c_dev_opt_in._is_enabled())

        self.assertEqual(
            _collected_metric_names(reader),
            {"c.stable.default"},
        )

    def test_all_synchronous_and_asynchronous_instrument_types(self):
        reader = InMemoryMetricReader()
        provider = MeterProvider(
            metric_readers=[reader],
            views=[
                View(instrument_name="*.enabled_by_view", _enabled=True),
            ],
        )
        meter = provider.get_meter("test.meter")

        cb_calls = []

        def make_cb(name: str):
            def _cb(_options: CallbackOptions):
                cb_calls.append(name)
                return [Observation(1)]

            return [_cb]

        # Suppressed development instruments across all 7 types
        udc_dev = meter.create_up_down_counter(
            "udc.dev", _stability=_Stability.DEVELOPMENT
        )
        hist_dev = meter.create_histogram(
            "hist.dev", _stability=_Stability.DEVELOPMENT
        )
        gauge_dev = meter.create_gauge(
            "gauge.dev", _stability=_Stability.DEVELOPMENT
        )
        meter.create_observable_counter(
            "obs_c.dev",
            callbacks=make_cb("obs_c.dev"),
            _stability=_Stability.DEVELOPMENT,
        )
        meter.create_observable_up_down_counter(
            "obs_udc.dev",
            callbacks=make_cb("obs_udc.dev"),
            _stability=_Stability.DEVELOPMENT,
        )
        meter.create_observable_gauge(
            "obs_gauge.dev",
            callbacks=make_cb("obs_gauge.dev"),
            _stability=_Stability.DEVELOPMENT,
        )

        # Opt-in instruments enabled by matching View(_enabled=True)
        udc_opt_in = meter.create_up_down_counter(
            "udc.enabled_by_view", _opt_in=True
        )
        hist_opt_in = meter.create_histogram(
            "hist.enabled_by_view",
            _stability=_Stability.DEVELOPMENT,
            _opt_in=True,
        )
        gauge_opt_in = meter.create_gauge(
            "gauge.enabled_by_view", _opt_in=True
        )
        meter.create_observable_counter(
            "obs_c.enabled_by_view",
            callbacks=make_cb("obs_c.enabled_by_view"),
            _opt_in=True,
        )
        meter.create_observable_up_down_counter(
            "obs_udc.enabled_by_view",
            callbacks=make_cb("obs_udc.enabled_by_view"),
            _stability=_Stability.DEVELOPMENT,
            _opt_in=True,
        )
        meter.create_observable_gauge(
            "obs_gauge.enabled_by_view",
            callbacks=make_cb("obs_gauge.enabled_by_view"),
            _opt_in=True,
        )

        self.assertFalse(udc_dev._is_enabled())
        self.assertFalse(hist_dev._is_enabled())
        self.assertFalse(gauge_dev._is_enabled())
        self.assertTrue(udc_opt_in._is_enabled())
        self.assertTrue(hist_opt_in._is_enabled())
        self.assertTrue(gauge_opt_in._is_enabled())

        udc_dev.add(5)
        hist_dev.record(10)
        gauge_dev.set(15)
        udc_opt_in.add(5)
        hist_opt_in.record(10)
        gauge_opt_in.set(15)

        self.assertEqual(
            _collected_metric_names(reader),
            {
                "udc.enabled_by_view",
                "hist.enabled_by_view",
                "gauge.enabled_by_view",
                "obs_c.enabled_by_view",
                "obs_udc.enabled_by_view",
                "obs_gauge.enabled_by_view",
            },
        )
        # Callbacks for disabled async instruments should not even be invoked
        self.assertEqual(
            set(cb_calls),
            {
                "obs_c.enabled_by_view",
                "obs_udc.enabled_by_view",
                "obs_gauge.enabled_by_view",
            },
        )
