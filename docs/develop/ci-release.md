# CI and releases

All workflows are in `.github/workflows/`, run on GitHub's `ubuntu-26.04` runners, pin every action to a full commit
hash with the version as a comment, and keep `permissions: contents: read` unless a job needs more.

| Workflow | When | What |
|---|---|---|
| `ci.yml` | every push and pull request | the full suite with `APPJAIL_INTEGRATION=1` (the `guest-setup` action, shared with `e2e.yml`, relaxes `kernel.apparmor_restrict_unprivileged_userns` where present, installs `tests/vm/packages.txt` minus the kernel, and prints the versions under test; tests needing missing hardware skip); `package`: the packaging test and the pinned build tooling; `hygiene`: every commit message checked by `.github/scripts/commit_hygiene.py` |
| `reuse.yml` | every push and pull request | REUSE compliance |
| `docs.yml` | pull requests and `main`: build; `v*` tags and by hand: deploy | this site, built strictly and published to GitHub Pages |
| `e2e.yml` | by hand and weekly | every opt-in suite, with `GITHUB_TOKEN` for the API limit |
| `ci-gate.yml` | called by the release workflows | succeeds only if `ci.yml` passed on that commit on `main` |
| `release.yml` | a `vX.Y.Z` tag, after the gate | builds once (`build-dist.yml`: the pinned tooling, `--no-isolation`, an sdist named after the tag, `twine check`), creates the GitHub release with the sdist and the notes; `contents: write` in that job only |
| `pypi.yml` | a `vX.Y.Z` tag, after the gate | builds the same way and publishes with PyPI trusted publishing (no stored token) |
| `bump-tools.yml` | weekly and by hand | `.github/scripts/bump_tools.py` opens a pull request for each new stable release of `cli/cli` and `mhx/dwarfs`, moving the pins in `tools.py` (size and hash measured on the runner and checked against GitHub's digest; the download is never run or unpacked). When the pull request is refused it deletes the branch it pushed and fails, so the next run tries again |

## Making a release

1. Everything is merged to `main` and `ci.yml` is green there.
2. Tag the commit `vX.Y.Z` (a suffix makes a pre-release) and push the tag. The version comes from the tag
   (`hatch-vcs`).
3. `release.yml`, `pypi.yml` and `docs.yml` run after the gate: the GitHub release, PyPI, and this site.

The build tools are pinned by version and hash in `.github/requirements-build.txt`, the documentation tools in
`.github/requirements-docs.txt`; both are installed with `--require-hashes --only-binary=:all:`. Release notes are made
by `.github/scripts/release_notes.py` from the commits since the previous tag, grouped by the files they touch (Security,
Interface, Logic, Documentation, Tests, Other); merge commits are not listed, and commits that came through a pull request
are left to GitHub's generated notes, categorised by `.github/release.yml`. The scripts are tested offline
(`tests/test_release_notes.py`, `tests/test_bump_tools.py`, `tests/test_commit_hygiene.py`).

## Pull requests from automation

- **Dependabot** proposes new versions of the actions and of the pinned Python tooling weekly. Review a pin like a new
  dependency.
- **bump-tools** pull requests move a pinned binary: check the release notes and run the opt-in tool and attestation
  tests in the guest before merging. A pull request opened with the workflow token does not start CI: close and reopen
  it. The workflow needs the repository setting that lets GitHub Actions create pull requests.

After a push, read the results with `gh run list` and `gh run view`. A red CI on `main` is a bug to fix.

Why these choices: [Decisions: project](../decisions/project/index.md).
