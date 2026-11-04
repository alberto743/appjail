# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Release notes for a version tag (run by release.yml): `release_notes.py vX.Y.Z > notes.md`.

Commits since the previous v* tag are grouped by the area in their subject ("Area: text", any case);
a subject without a known area goes under "Other". Commits that came in through a pull request
("... (#12)") are left to GitHub's own generated notes (grouped by .github/release.yml), which are
appended. Stdlib only; `git` and `gh` come from the runner.
"""

import os
import re
import subprocess
import sys

# heading -> areas (the first word of the subject's prefix, lower case); order is the order in the notes
GROUPS = {
    "Security": {"security", "seccomp", "landlock", "audit"},
    "Permissions and sandbox": {"permissions", "perms", "display", "audio", "gpu", "grants", "dirs", "linger",
                                "portals", "portal", "runner", "network_host", "jail", "wayland", "dbus"},
    "Command line": {"cli", "add", "update", "list", "search", "desktop", "output", "tools", "open", "remove",
                     "history"},
    "Catalog": {"index", "catalog"},
    "GUI": {"gui", "appjail-gui"},
    "Documentation": {"docs", "doc", "readme"},
    "Tests and CI": {"tests", "test", "ci", "vm", "pyproject", "release", "packaging"},
    "Maintenance": {"cleanup", "housekeeping", "refactor", "chore"},
}
OTHER = "Other"
PREFIX_RE = re.compile(r"([^:]{1,60}):\s")
AREA_RE = re.compile(r"[a-z0-9_-]+")
PR_RE = re.compile(r"\(#\d+\)$")


def area(subject):
    m = PREFIX_RE.match(subject)
    first = AREA_RE.match(m.group(1).strip().lower()) if m else None
    return first.group(0) if first else None


def heading(subject):
    a = area(subject)
    return next((h for h, areas in GROUPS.items() if a in areas), OTHER)


def group(commits):
    """{heading: [(sha, subject)]} in display order, empty groups left out. Pull-request commits are skipped."""
    out = {h: [] for h in [*GROUPS, OTHER]}
    for sha, subject in commits:
        if subject.startswith("Merge ") or PR_RE.search(subject):
            continue
        out[heading(subject)].append((sha, subject))
    return {h: items for h, items in out.items() if items}


def render(groups, url):
    lines = []
    for h, items in groups.items():
        lines += [f"## {h}", ""]
        lines += [f"- {subject} ([`{sha[:7]}`]({url}/commit/{sha}))" if url else f"- {subject} (`{sha[:7]}`)"
                  for sha, subject in items]
        lines.append("")
    return "\n".join(lines)


def git(*args):
    return subprocess.run(["git", *args], check=True, text=True, capture_output=True).stdout


def previous_tag(tag):
    r = subprocess.run(["git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", f"{tag}^"],
                       text=True, capture_output=True)
    return r.stdout.strip() or None


def commits(tag, prev):
    rng = f"{prev}..{tag}" if prev else tag
    return [tuple(line.split("\t", 1)) for line in git("log", "--no-merges", "--format=%H%x09%s", rng).splitlines()]


def github_notes(repo, tag, prev):
    cmd = ["gh", "api", "-X", "POST", f"repos/{repo}/releases/generate-notes", "-f", f"tag_name={tag}",
           "--jq", ".body"]
    if prev:
        cmd += ["-f", f"previous_tag_name={prev}"]
    return subprocess.run(cmd, check=True, text=True, capture_output=True).stdout.strip()


def main(tag):
    repo = os.environ["GITHUB_REPOSITORY"]
    prev = previous_tag(tag)
    body = render(group(commits(tag, prev)), f"https://github.com/{repo}")
    print(body + github_notes(repo, tag, prev))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
