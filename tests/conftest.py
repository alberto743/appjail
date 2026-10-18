# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import pytest

from bjail import history


@pytest.fixture(autouse=True)
def no_history(monkeypatch):
    """Most tests do not need (or want) a git repository in the fake config directory."""
    monkeypatch.setattr(history, "enabled", False)
