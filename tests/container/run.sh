#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Documentation and static checks in a rootless podman container: the repository is mounted read-only and the container
# has no network, except for `serve` (it needs the live sources, so the repository is read-write) which publishes
# 127.0.0.1:8000. Nothing here runs appjail or a jail; docs/develop/testing.md#the-tooling-container describes it.
#   run.sh image   build the image (needs network: the base image, the apt packages, and the requirements of
#                  .github/requirements-docs.txt and .github/requirements-ruff.txt)
#   run.sh build   zensical build --strict --clean; the site lands in ./site (ignored by git)
#   run.sh serve   zensical serve with live reload at http://127.0.0.1:8000
#   run.sh check   ruff, reuse lint and the tests that need no jail (lint, reuse, docs, the CI scripts)
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
img=localhost/appjail-tools
cmd=${1:-}
# zensical writes its cache next to the sources: work on a copy in a tmpfs (without the
# guests' vm/ directory), so the mounted repository stays read-only
prep='mkdir -p /work && cd /src && tar --anchored --exclude=vm -cf - $(ls -A) | tar -C /work -xf - && cd /work'
run() { podman run --rm --userns=keep-id --security-opt=no-new-privileges --cap-drop=all \
	--tmpfs /tmp/home:rw,mode=1777 --tmpfs /work:rw,exec,mode=1777 -v "$root:/src:ro" "$@"; }
case "$cmd" in
image) exec podman build -t "$img" -f "$root/tests/container/Containerfile" "$root" ;;
build) rm -rf "$root/site"; mkdir -p "$root/site"
	run --network=none -v "$root/site:/out:rw" "$img" sh -c "$prep && zensical build --strict --clean && cp -r site/. /out/"
	echo "site: site/index.html" ;;
# serve needs the live sources: the repository is mounted read-write (zensical writes site/ and .cache/, both ignored)
serve) podman run --rm -it --userns=keep-id --security-opt=no-new-privileges --cap-drop=all --tmpfs /tmp/home:rw,mode=1777 \
		-p 127.0.0.1:8000:8000 -v "$root:/src:rw" "$img" zensical serve -a 0.0.0.0:8000 ;;
check) run --network=none "$img" sh -c "$prep && rm -rf site .cache && "'ruff check --no-cache src tests && reuse lint -q &&
	/usr/bin/python3 -m pytest -q -p no:cacheprovider tests/test_lint.py tests/test_reuse.py tests/test_docs.py \
	tests/test_check_platforms.py tests/test_bump_tools.py' ;;
*) echo "usage: $0 image|build|serve|check" >&2; exit 2 ;;
esac
