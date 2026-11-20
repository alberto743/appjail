# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Value checks shared by the manifest parser and the permission policy."""

import re


class ManifestError(ValueError):
    """The manifest is malformed or violates the schema."""


CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
DISPLAY_SIZE_RE = re.compile(r"([1-9][0-9]{2,3})x([1-9][0-9]{2,3})")
DISPLAY_SIZE_RANGE = (320, 8192)
# Limits in systemd's own syntax (MemoryMax=, CPUQuota=, TasksMax=); the value reaches `systemd-run -p`, so only these shapes pass.
MEMORY_MAX_RE = re.compile(r"[1-9][0-9]{0,9}[KMGT]?|[1-9][0-9]?%|100%")
CPU_QUOTA_RE = re.compile(r"[1-9][0-9]{0,3}%|10000%")
TASKS_MAX_RE = re.compile(r"[1-9][0-9]{0,6}|[1-9][0-9]?%|100%")


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


def display_size(value, what="permissions.display_size"):
    """WxH in pixels, each side between 320 and 8192."""
    m = DISPLAY_SIZE_RE.fullmatch(value) if isinstance(value, str) else None
    low, high = DISPLAY_SIZE_RANGE
    if not m or not all(low <= int(side) <= high for side in m.groups()):
        raise ManifestError(f"{what} must be WIDTHxHEIGHT, each between {low} and {high}")
    return value


def _limit(value, regex, what, shape):
    if not isinstance(value, str) or not regex.fullmatch(value):
        raise ManifestError(f"{what} must be {shape}")
    return value


def memory_max(value, what="permissions.memory_max"):
    """Bytes with an optional K, M, G or T suffix (1024-based), or a percentage of the host's memory (systemd's MemoryMax=)."""
    return _limit(value, MEMORY_MAX_RE, what, "a size such as 512M or 2G, or a percentage such as 50%")


def cpu_quota(value, what="permissions.cpu_quota"):
    """A percentage of one CPU, which may exceed 100% (systemd's CPUQuota=): 200% is two CPUs."""
    return _limit(value, CPU_QUOTA_RE, what, "a percentage of one CPU such as 50% or 200%")


def tasks_max(value, what="permissions.tasks_max"):
    """A number of processes and threads, or a percentage of the host's limit (systemd's TasksMax=)."""
    return _limit(value, TASKS_MAX_RE, what, "a number such as 512, or a percentage such as 20%")
