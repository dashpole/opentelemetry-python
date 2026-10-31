# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

# pylint: disable=unused-import

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from logging import getLogger
from threading import Lock
from time import time_ns

# This kind of import is needed to avoid Sphinx errors.
import opentelemetry.sdk.metrics
import opentelemetry.sdk.metrics._internal.instrument
from opentelemetry.metrics._internal.instrument import CallbackOptions
from opentelemetry.sdk.metrics._internal.aggregation import DropAggregation
from opentelemetry.sdk.metrics._internal.exceptions import MetricsTimeoutError
from opentelemetry.sdk.metrics._internal.measurement import Measurement
from opentelemetry.sdk.metrics._internal.metric_reader_storage import (
    _DEFAULT_VIEW,
    MetricReaderStorage,
)
from opentelemetry.sdk.metrics._internal.point import (
    MetricsData,
    ResourceMetrics,
    ScopeMetrics,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.util._stability import _Stability

_logger = getLogger(__name__)


class MeasurementConsumer(ABC):
    @abstractmethod
    def consume_measurement(self, measurement: Measurement) -> None:
        pass

    @abstractmethod
    def register_asynchronous_instrument(
        self,
        instrument: ("opentelemetry.sdk.metrics._internal.instrument._Asynchronous"),
    ):
        pass

    @abstractmethod
    def collect(
        self,
        metric_reader: "opentelemetry.sdk.metrics.export.MetricReader",
        timeout_millis: float = 10_000,
    ) -> MetricsData | None:
        pass

    def _is_instrument_enabled(
        self,
        instrument: "opentelemetry.sdk.metrics._internal.instrument._Instrument",
    ) -> bool:
        return True


class SynchronousMeasurementConsumer(MeasurementConsumer):
    def __init__(
        self,
        sdk_config: "opentelemetry.sdk.metrics._internal.sdk_configuration.SdkConfiguration",
        metric_readers: Iterable["opentelemetry.sdk.metrics.MetricReader"],
    ) -> None:
        self._lock = Lock()
        self._sdk_config = sdk_config
        self._reader_storages: Mapping[opentelemetry.sdk.metrics.export.MetricReader, MetricReaderStorage] = {
            reader: MetricReaderStorage(
                sdk_config,
                reader._instrument_class_temporality,
                reader._instrument_class_aggregation,
                reader._instrument_class_cardinality_limit,
            )
            for reader in metric_readers
        }
        self._async_instruments: list[opentelemetry.sdk.metrics._internal.instrument._Asynchronous] = []

    def consume_measurement(self, measurement: Measurement) -> None:
        should_sample_exemplar = self._sdk_config.exemplar_filter.should_sample(
            measurement.value,
            measurement.time_unix_nano,
            measurement.attributes,
            measurement.context,
        )
        # `_reader_storages` is replaced (never mutated in place) by
        # `add_metric_reader` and `remove_metric_reader`, so it is safe
        # to iterate over without a lock.
        for reader_storage in self._reader_storages.values():
            reader_storage.consume_measurement(measurement, should_sample_exemplar)

    def register_asynchronous_instrument(
        self,
        instrument: ("opentelemetry.sdk.metrics._internal.instrument._Asynchronous"),
    ) -> None:
        with self._lock:
            self._async_instruments.append(instrument)

    def _is_instrument_enabled(
        self,
        instrument: "opentelemetry.sdk.metrics._internal.instrument._Instrument",
    ) -> bool:
        # pylint: disable=protected-access
        if self._reader_storages:
            return any(
                reader_storage._is_instrument_enabled(instrument)
                for reader_storage in self._reader_storages.values()
            )
        matching_views = [
            view
            for view in self._sdk_config.views
            if view._match(instrument)
            and MetricReaderStorage._check_view_instrument_compatibility(view, instrument)
        ] or [_DEFAULT_VIEW]

        opt_in = getattr(instrument, "_opt_in", False) is True
        stability = getattr(instrument, "_stability", _Stability.STABLE)
        below_min_stability = (
            isinstance(stability, _Stability)
            and isinstance(self._sdk_config._minimum_stability, _Stability)
            and stability < self._sdk_config._minimum_stability
        )
        for view in matching_views:
            view_enabled = getattr(view, "_enabled", None)
            if view_enabled is False:
                continue
            if view_enabled is True:
                if not isinstance(view._aggregation, DropAggregation):
                    return True
                continue
            if opt_in or below_min_stability:
                continue
            if not isinstance(view._aggregation, DropAggregation):
                return True
        return False

    def collect(
        self,
        metric_reader: "opentelemetry.sdk.metrics.export.MetricReader",
        timeout_millis: float = 10_000,
    ) -> MetricsData | None:
        with self._lock:
            metric_reader_storage = self._reader_storages[metric_reader]
            # for now, just use the defaults
            callback_options = CallbackOptions()
            deadline_ns = time_ns() + (timeout_millis * 1e6)

            default_timeout_ns = 10000 * 1e6

            for async_instrument in self._async_instruments:
                remaining_time = deadline_ns - time_ns()

                if remaining_time < default_timeout_ns:
                    callback_options = CallbackOptions(timeout_millis=remaining_time / 1e6)

                # callback() is a generator function: the user callback
                # only runs while the loop below iterates it, so the
                # deadline can only be observed after iteration completes.
                for measurement in async_instrument.callback(callback_options):
                    should_sample_exemplar = self._sdk_config.exemplar_filter.should_sample(
                        measurement.value,
                        measurement.time_unix_nano,
                        measurement.attributes,
                        measurement.context,
                    )
                    metric_reader_storage.consume_measurement(measurement, should_sample_exemplar)

                if time_ns() >= deadline_ns:
                    raise MetricsTimeoutError(
                        f"Timed out while executing callback for instrument {async_instrument.name}"
                    )

            result = self._reader_storages[metric_reader].collect()

            if producer_scope_metrics := self._collect_from_producers(metric_reader, deadline_ns):
                result = self._merge_producer_metrics(result, producer_scope_metrics, self._sdk_config.resource)

        return result

    @staticmethod
    def _collect_from_producers(
        metric_reader: "opentelemetry.sdk.metrics.export.MetricReader",
        deadline_ns: float,
    ) -> list[ScopeMetrics]:
        """Collect ScopeMetrics from the reader's MetricProducers.

        Called while holding ``self._lock`` so ``produce()`` calls are
        serialized. A producer that fails or times out is isolated so
        metrics collected by the SDK are not dropped.
        """
        producer_scope_metrics: list[ScopeMetrics] = []
        # pylint: disable-next=protected-access
        for producer in metric_reader._metric_producers:
            remaining_millis = (deadline_ns - time_ns()) / 1e6
            if remaining_millis <= 0:
                _logger.warning("Timed out collecting from metric producers, skipping remaining producers.")
                break

            try:
                scopes = list(producer.produce(timeout_millis=remaining_millis))
            # pylint: disable-next=broad-except
            except Exception:
                _logger.exception(
                    "Metric producer %s failed to produce metrics, skipping.",
                    producer,
                )
                continue

            producer_scope_metrics.extend(scopes)

        return producer_scope_metrics

    @staticmethod
    def _merge_producer_metrics(
        result: MetricsData | None,
        producer_scope_metrics: list[ScopeMetrics],
        resource: Resource,
    ) -> MetricsData:
        if result is not None and result.resource_metrics:
            sdk_resource_metrics = result.resource_metrics[0]
            merged = ResourceMetrics(
                resource=sdk_resource_metrics.resource,
                scope_metrics=[
                    *sdk_resource_metrics.scope_metrics,
                    *producer_scope_metrics,
                ],
                schema_url=sdk_resource_metrics.schema_url,
            )
            return MetricsData(resource_metrics=[merged, *result.resource_metrics[1:]])

        return MetricsData(
            resource_metrics=[
                ResourceMetrics(
                    resource=resource,
                    scope_metrics=producer_scope_metrics,
                    schema_url=resource.schema_url,
                )
            ]
        )

    def add_metric_reader(self, metric_reader: "opentelemetry.sdk.metrics.MetricReader") -> None:
        """Registers a new metric reader."""
        # Build a new mapping and swap it in atomically so that
        # a concurrent consume_measurement never iterates a mapping
        # that is being mutated in place.
        with self._lock:
            new_reader_storages = dict(self._reader_storages)
            new_reader_storages[metric_reader] = MetricReaderStorage(
                self._sdk_config,
                # pylint: disable-next=protected-access
                metric_reader._instrument_class_temporality,
                # pylint: disable-next=protected-access
                metric_reader._instrument_class_aggregation,
                # pylint: disable-next=protected-access
                metric_reader._instrument_class_cardinality_limit,
            )
            self._reader_storages = new_reader_storages

    def remove_metric_reader(self, metric_reader: "opentelemetry.sdk.metrics.MetricReader") -> None:
        """Unregisters the given metric reader."""
        # Mutate using copy-on-write: see add_metric_reader.
        with self._lock:
            new_reader_storages = dict(self._reader_storages)
            new_reader_storages.pop(metric_reader)
            self._reader_storages = new_reader_storages
