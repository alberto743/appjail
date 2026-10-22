# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Value checks shared by the manifest parser and the permission policy."""

import re


class ManifestError(ValueError):
    """The manifest is malformed or violates the schema."""


CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def string(value, what, max_len=256):
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{what} must be a non-empty string")
    if len(value) > max_len or CONTROL_RE.search(value):
        raise ManifestError(f"{what} is too long or contains control characters")
    return value


def match(value, regex, what):
    string(value, what)
    if not regex.fullmatch(value):
        raise ManifestError(f"{what} has an invalid format: {value!r}")
    return value


def boolean(value, what):
    if not isinstance(value, bool):
        raise ManifestError(f"{what} must be true or false")
    return value


def str_list(value, what):
    if not isinstance(value, list):
        raise ManifestError(f"{what} must be a list of strings")
    return [string(v, f"{what} entry") for v in value]
