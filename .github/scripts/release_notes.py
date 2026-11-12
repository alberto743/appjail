# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Release notes for a version tag (run by release.yml): `release_notes.py vX.Y.Z > notes.md`.

Commits since the previous v* tag are grouped by the files they touch (Interface, Logic, Documentation,
Tests; Security also by the subject's area, "Area: text"); what fits none goes under "Other". Commits that came in through a pull request
(squash-merged "... (#12)", or behind a "Merge pull request #12" merge) are left to GitHub's own generated notes (grouped by
.github/release.yml), which are appended. Merge commits themselves are not listed. Stdlib only; `git` and `gh` come from the runner.
"""

import os
import re
import subprocess
import sys

# Security: the subject names it, or the commit touches only these modules
SECURITY_AREAS = {"security", "seccomp", "landlock", "audit"}
SECURITY_FILES = {"seccomp.py", "landlock.py", "attest.py", "snappy.py", "textsafe.py", "dbusproxy.py", "grants.py"}
# Interface: the commit's changes under src/ are all in the GUI, the parser/commands or the console output
INTERFACE_RE = re.compile(r"src/appjail/(gui/|cli\.py$|cmd_[a-z]+\.py$|console\.py$|permargs\.py$)")
DOC_RE = re.compile(r"[^/]+\.md$|REUSE\.toml$|docs/")
HEADINGS = ["Security", "Interface", "Logic", "Documentation", "Tests", "Other"]
PREFIX_RE = re.compile(r"([^:]{1,60}):\s")
AREA_RE = re.compile(r"[a-z0-9_-]+")
PR_RE = re.compile(r"\(#\d+\)$")
MERGE_PR_RE = re.compile(r"Merge pull request #\d+ ")


def area(subject):
    m = PREFIX_RE.match(subject)
    first = AREA_RE.match(m.group(1).strip().lower()) if m else None
    return first.group(0) if first else None


def heading(subject, files):
    """The notes section of a commit: by what it says (security) and by the files it touches."""
    src = [f for f in files if f.startswith("src/")]
    if area(subject) in SECURITY_AREAS or (src and all(f.rsplit("/", 1)[-1] in SECURITY_FILES for f in src)):
        return "Security"
    if src:
        return "Interface" if all(INTERFACE_RE.match(f) for f in src) else "Logic"
    if files and all(DOC_RE.match(f) for f in files):
        return "Documentation"
    if files and all(f.startswith("tests/") or DOC_RE.match(f) for f in files):
        return "Tests"
    return "Other"


def group(commits):
    """{heading: [(sha, subject)]} in display order, empty groups left out. Pull-request commits are skipped."""
    out = {h: [] for h in HEADINGS}
    for sha, subject, files in commits:
        if subject.startswith("Merge ") or PR_RE.search(subject):
            continue
        out[heading(subject, files)].append((sha, subject))
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


def pull_request_commits(rng):
    """The commits brought in by the "Merge pull request #N" merges in rng: GitHub's notes list them already."""
    shas = set()
    for line in git("log", "--merges", "--format=%P\t%s", rng).splitlines():
        parents, subject = line.split("\t", 1)
        parents = parents.split()
        if MERGE_PR_RE.match(subject) and len(parents) == 2:
            shas.update(git("rev-list", f"{parents[0]}..{parents[1]}").split())
    return shas


def commits(tag, prev):
    """[(sha, subject, files)] of the non-merge commits in prev..tag, without those merged through a pull request."""
    rng = f"{prev}..{tag}" if prev else tag
    skip = pull_request_commits(rng)
    out = []
    for line in git("log", "--no-merges", "--format=@@%H\t%s", "--name-only", rng).splitlines():
        if line.startswith("@@"):
            sha, subject = line[2:].split("\t", 1)
            out.append((sha, subject, []))
        elif line:
            out[-1][2].append(line)
    return [c for c in out if c[0] not in skip]


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
