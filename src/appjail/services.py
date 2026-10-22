# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The things `update` does to the outside world, gathered in one place so tests can replace them."""

from collections.abc import Callable
from dataclasses import dataclass

from . import appimage, attest, jail


@dataclass(frozen=True)
class Services:
    download: Callable = jail.download  # a GitHub asset, in the network-only jail
    download_url: Callable = jail.download_url  # any https URL (`url:` apps)
    check_url: Callable = jail.check_url  # the cheap changed/unchanged test of a `url:` app
    extract: Callable = appimage.extract
    extract_ok: Callable = appimage.have_unsquashfs
    verify: Callable = attest.verify  # Sigstore attestation check
