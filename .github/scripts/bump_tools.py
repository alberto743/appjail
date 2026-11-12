# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Open one pull request per new upstream release of a pinned helper tool (run by bump-tools.yml).

Reads the pins in src/appjail/tools.py, asks GitHub for the latest stable release of each tool's
repository, and for a newer one: downloads the asset to a temporary file, checks size and sha256
against the digest GitHub publishes for it, hashes the executable inside a tarball without
extracting it, rewrites the pin and opens a PR. The downloaded bytes are only measured, never run
or unpacked to disk. Stdlib only; `git` and `gh` come from the runner.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

TOOLS_PY = Path("src/appjail/tools.py")
MAX_ASSET = 200 * 1024 * 1024
TAG_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)")

# name -> upstream repository, release asset and (for a tarball) the executable inside it, comment label in tools.py
SPECS = {
    "dwarfs": {
        "repo": "mhx/dwarfs",
        "asset": "dwarfs-universal-small-{v}-Linux-x86_64",
        "member": None,
        "label": "mhx/dwarfs v",
    },
    "gh": {
        "repo": "cli/cli",
        "asset": "gh_{v}_linux_amd64.tar.gz",
        "member": "gh_{v}_linux_amd64/bin/gh",
        "label": "GitHub CLI v",
    },
}


def version_key(v):
    return tuple(int(x) for x in v.split("."))


def tool_block(text, name):
    """(start, end) of the `"name": Tool(...)` entry in tools.py."""
    m = re.search(rf'^    "{re.escape(name)}": Tool\(', text, re.M)
    if not m:
        raise SystemExit(f"tools.py: no entry for {name}")
    nxt = re.compile(r'\n    "|\n\}').search(text, m.end())
    return m.start(), nxt.start() if nxt else len(text)


def pinned_version(text, name):
    a, b = tool_block(text, name)
    m = re.search(r"/releases/download/v(\d+\.\d+\.\d+)/", text[a:b])
    if not m:
        raise SystemExit(f"tools.py: no pinned version for {name}")
    return m.group(1)


def rewrite(text, name, new, size, sha256, exe_size=None, exe_sha256=None):
    """tools.py text with the pin of `name` moved to version `new`."""
    spec = SPECS[name]
    old = pinned_version(text, name)
    a, b = tool_block(text, name)
    block = text[a:b].replace(old, new)
    block, n = re.subn(r'(\d+)(, ")[0-9a-f]{64}(")', lambda m: f"{size}{m.group(2)}{sha256}{m.group(3)}", block, count=1)
    if n != 1:
        raise SystemExit(f"tools.py: cannot find size and sha256 of {name}")
    if spec["member"]:
        block, n1 = re.subn(r"exe_size=\d+", f"exe_size={exe_size}", block)
        block, n2 = re.subn(r'exe_sha256="[0-9a-f]{64}"', f'exe_sha256="{exe_sha256}"', block)
        if n1 != 1 or n2 != 1:
            raise SystemExit(f"tools.py: cannot find the executable pin of {name}")
    text = text[:a] + block + text[b:]
    return text.replace(spec["label"] + old, spec["label"] + new)


def sha256_stream(f):
    h, size = hashlib.sha256(), 0
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
        size += len(chunk)
    return size, h.hexdigest()


def measure(path, member=None):
    """(size, sha256) of the file and, for a tarball, (exe_size, exe_sha256) of the member, read in place."""
    with open(path, "rb") as f:
        size, sha = sha256_stream(f)
    if not member:
        return size, sha, None, None
    with tarfile.open(path, "r:gz") as tar:
        m = tar.getmember(member)
        if not m.isreg():
            raise SystemExit(f"{member} is not a regular file in the archive")
        exe_size, exe_sha = sha256_stream(tar.extractfile(m))
    if exe_size != m.size:
        raise SystemExit(f"{member}: size read differs from the archive header")
    return size, sha, exe_size, exe_sha


def download(url, dest, expected_size):
    if expected_size > MAX_ASSET:
        raise SystemExit(f"{url}: asset larger than {MAX_ASSET} bytes")
    req = urllib.request.Request(url, headers={"User-Agent": "appjail-bump-tools"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        got = 0
        for chunk in iter(lambda: r.read(1 << 20), b""):
            got += len(chunk)
            if got > expected_size:
                raise SystemExit(f"{url}: more bytes than the {expected_size} announced")
            f.write(chunk)


def run(*cmd, capture=False, check=True):
    return subprocess.run(cmd, check=check, text=True, capture_output=capture)


def latest_release(repo):
    out = run("gh", "api", f"repos/{repo}/releases/latest", capture=True).stdout
    rel = json.loads(out)
    m = TAG_RE.fullmatch(rel.get("tag_name", ""))
    if rel.get("draft") or rel.get("prerelease") or not m:
        return None, rel
    return ".".join(m.groups()), rel


def body(name, spec, old, new, rel, size, sha, exe_size, exe_sha):
    lines = [
        f"Bumps the pinned `{name}` helper from {old} to {new} ({rel['html_url']}).",
        "",
        f"- asset `{spec['asset'].format(v=new)}`: {size} bytes, sha256 `{sha}`",
        "- the sha256 equals the digest GitHub publishes for the asset; the download was only measured, never run",
    ]
    if exe_sha:
        lines.append(f"- executable `{spec['member'].format(v=new)}`: {exe_size} bytes, sha256 `{exe_sha}`")
    lines += [
        "",
        "To review before merging:",
        "- [ ] release notes (breaking changes, security fixes)",
        "- [ ] the explanatory comment above the pin in `tools.py` is still true (its Debian packaging check has a date)",
        "- [ ] `APPJAIL_E2E=1 APPJAIL_INTEGRATION=1` run of `tests/test_tools.py` and `tests/test_attest.py` in the guest",
        "- [ ] CI: a PR opened with the workflow token does not start the workflows; close and reopen it",
    ]
    return "\n".join(lines)


def bump(name):
    spec = SPECS[name]
    text = TOOLS_PY.read_text()
    old = pinned_version(text, name)
    new, rel = latest_release(spec["repo"])
    if new is None or version_key(new) <= version_key(old):
        print(f"{name}: {old} is current")
        return
    branch = f"bump-{name}-{new}"
    if run("git", "ls-remote", "--exit-code", "--heads", "origin", branch, check=False, capture=True).returncode == 0:
        print(f"{name}: {branch} already exists")
        return
    asset_name = spec["asset"].format(v=new)
    asset = next((a for a in rel["assets"] if a["name"] == asset_name), None)
    if asset is None:
        raise SystemExit(f"{name}: release {new} has no asset {asset_name}")
    url = asset["browser_download_url"]
    if not url.startswith(f"https://github.com/{spec['repo']}/releases/download/"):
        raise SystemExit(f"{name}: unexpected download URL {url}")
    digest = asset.get("digest") or ""
    if not digest.startswith("sha256:"):
        raise SystemExit(f"{name}: GitHub publishes no sha256 digest for {asset_name}; refusing to pin it")
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "asset"
        download(url, dest, asset["size"])
        member = spec["member"].format(v=new) if spec["member"] else None
        size, sha, exe_size, exe_sha = measure(dest, member)
    if size != asset["size"] or sha != digest[len("sha256:"):]:
        raise SystemExit(f"{name}: downloaded asset does not match GitHub's size and digest")
    TOOLS_PY.write_text(rewrite(text, name, new, size, sha, exe_size, exe_sha))
    run("git", "switch", "-c", branch)
    run("git", "commit", "-am", f"tools: bump {name} to {new}")
    run("git", "push", "origin", branch)
    run("gh", "label", "create", "tools", "--description", "Pinned helper tools", "--force")
    open_pr(branch, f"tools: bump {name} to {new}", body(name, spec, old, new, rel, size, sha, exe_size, exe_sha))
    run("git", "switch", "-")


def open_pr(branch, title, text):
    """Open the pull request of a pushed branch. If GitHub refuses, delete the branch: a branch left behind without a
    pull request would make every later run skip this release as already proposed."""
    if run("gh", "pr", "create", "--label", "tools", "--base", "main", "--head", branch, "--title", title,
           "--body", text, check=False).returncode == 0:
        return
    run("git", "push", "origin", "--delete", branch, check=False)
    raise SystemExit(f"{branch}: the pull request could not be opened (gh's message is above), so the branch was deleted "
                     "and the next run tries again. If gh says GitHub Actions may not create pull requests, allow it in "
                     "the repository settings: Actions, General, Workflow permissions.")


def main():
    os.chdir(Path(__file__).resolve().parents[2])
    for name in SPECS:
        bump(name)


if __name__ == "__main__":
    sys.exit(main())
