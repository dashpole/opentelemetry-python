# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from enum import IntEnum


class _Stability(IntEnum):
    """Stability level of an instrumentation span, metric instrument, log record, or attribute."""

    DEVELOPMENT = 0
    STABLE = 1
