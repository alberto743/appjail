#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# The package names of packages.txt, one per line, without comments.
sed 's/#.*//' "$(dirname "$0")/packages.txt" | tr -s ' \t' '\n\n' | grep -v '^$'
