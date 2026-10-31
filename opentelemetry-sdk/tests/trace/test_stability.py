# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest.mock import Mock

from opentelemetry import trace as trace_api
from opentelemetry.sdk import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.util._stability import _Stability


class TestTraceStability(unittest.TestCase):
    def test_default_tracer_provider_drops_development_spans(self):
        exporter = InMemorySpanExporter()
        sampler = Mock(wraps=trace.sampling.ALWAYS_ON)
        provider = trace.TracerProvider(sampler=sampler)
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("test.tracer")

        self.assertTrue(tracer._is_enabled())
        self.assertTrue(tracer._is_enabled(_Stability.STABLE))
        self.assertFalse(tracer._is_enabled(_Stability.DEVELOPMENT))

        dev_root = tracer.start_span(
            "dev_root", _stability=_Stability.DEVELOPMENT
        )
        self.assertIsInstance(dev_root, trace_api.NonRecordingSpan)
        self.assertFalse(dev_root.is_recording())
        self.assertEqual(
            dev_root.get_span_context(), trace_api.INVALID_SPAN_CONTEXT
        )
        dev_root.end()
        sampler.should_sample.assert_not_called()
        self.assertEqual(len(exporter.get_finished_spans()), 0)

        with tracer.start_as_current_span("stable_parent") as parent_span:
            parent_ctx = parent_span.get_span_context()
            self.assertTrue(parent_span.is_recording())

            with tracer.start_as_current_span(
                "dev_middle", _stability=_Stability.DEVELOPMENT
            ) as dev_span:
                self.assertIsInstance(dev_span, trace_api.NonRecordingSpan)
                self.assertFalse(dev_span.is_recording())
                # Parent SpanContext is preserved unchanged across a suppressed span
                self.assertEqual(dev_span.get_span_context(), parent_ctx)

                with tracer.start_as_current_span(
                    "stable_child", _stability=_Stability.STABLE
                ) as child_span:
                    self.assertTrue(child_span.is_recording())

        finished = exporter.get_finished_spans()
        self.assertEqual(len(finished), 2)
        child_exported, parent_exported = finished[0], finished[1]
        self.assertEqual(parent_exported.name, "stable_parent")
        self.assertEqual(child_exported.name, "stable_child")
        self.assertEqual(
            child_exported.parent.span_id, parent_exported.context.span_id
        )
        self.assertEqual(
            child_exported.context.trace_id, parent_exported.context.trace_id
        )
        self.assertEqual(sampler.should_sample.call_count, 2)

    def test_development_minimum_stability_records_all_spans(self):
        exporter = InMemorySpanExporter()
        provider = trace.TracerProvider(
            _minimum_stability=_Stability.DEVELOPMENT
        )
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("test.tracer")

        self.assertTrue(tracer._is_enabled())
        self.assertTrue(tracer._is_enabled(_Stability.STABLE))
        self.assertTrue(tracer._is_enabled(_Stability.DEVELOPMENT))

        with tracer.start_as_current_span("stable_parent") as parent_span:
            with tracer.start_as_current_span(
                "dev_child", _stability=_Stability.DEVELOPMENT
            ) as dev_span:
                self.assertTrue(dev_span.is_recording())
                self.assertNotEqual(
                    dev_span.get_span_context().span_id,
                    parent_span.get_span_context().span_id,
                )

        finished = exporter.get_finished_spans()
        self.assertEqual(len(finished), 2)
        self.assertEqual(finished[0].name, "dev_child")
        self.assertEqual(finished[1].name, "stable_parent")
        self.assertEqual(
            finished[0].parent.span_id, finished[1].context.span_id
        )
