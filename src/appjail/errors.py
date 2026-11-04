# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Errors of the jail layer, in a module of their own so that the leaf modules can raise them without importing `jail`."""


class JailError(Exception):
    """A helper jail (download, extraction, git) failed or was refused."""


class RunError(Exception):
    """An app cannot be started as asked (a missing helper, session or permission)."""
