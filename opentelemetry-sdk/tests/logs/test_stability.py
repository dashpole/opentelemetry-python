# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import unittest

from opentelemetry._logs import LogRecord, SeverityNumber
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    InMemoryLogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.util._stability import _Stability


class TestLogsStability(unittest.TestCase):
    def test_default_logger_provider_drops_development_logs(self):
        exporter = InMemoryLogRecordExporter()
        provider = LoggerProvider()
        provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
        logger = provider.get_logger("test.logger")

        self.assertTrue(logger.enabled())
        self.assertTrue(logger.enabled(_stability=_Stability.STABLE))
        self.assertFalse(logger.enabled(_stability=_Stability.DEVELOPMENT))
        self.assertTrue(logger._is_enabled(_stability=_Stability.STABLE))
        self.assertFalse(logger._is_enabled(_stability=_Stability.DEVELOPMENT))

        logger.emit(
            body="dev_kwarg_log",
            severity_number=SeverityNumber.INFO,
            _stability=_Stability.DEVELOPMENT,
        )
        logger.emit(
            LogRecord(
                body="dev_record_log",
                severity_number=SeverityNumber.INFO,
            ),
            _stability=_Stability.DEVELOPMENT,
        )
        logger.emit(
            body="stable_log",
            severity_number=SeverityNumber.INFO,
            _stability=_Stability.STABLE,
        )

        finished = exporter.get_finished_logs()
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0].log_record.body, "stable_log")

    def test_development_minimum_stability_emits_all_logs(self):
        exporter = InMemoryLogRecordExporter()
        provider = LoggerProvider(_minimum_stability=_Stability.DEVELOPMENT)
        provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
        logger = provider.get_logger("test.logger")

        self.assertTrue(logger.enabled())
        self.assertTrue(logger.enabled(_stability=_Stability.STABLE))
        self.assertTrue(logger.enabled(_stability=_Stability.DEVELOPMENT))

        logger.emit(
            body="dev_log",
            severity_number=SeverityNumber.INFO,
            _stability=_Stability.DEVELOPMENT,
        )
        logger.emit(
            body="stable_log",
            severity_number=SeverityNumber.INFO,
            _stability=_Stability.STABLE,
        )

        finished = exporter.get_finished_logs()
        self.assertEqual(len(finished), 2)
        self.assertEqual(finished[0].log_record.body, "dev_log")
        self.assertEqual(finished[1].log_record.body, "stable_log")
