# Sources and the resolver

*Part of [Acquisition](index.md). Previous: [the AppImage format](appimage.md). Next: [hashes and evidence tiers](evidence.md).*

## What it is

A **source** is where an app comes from. appjail knows three kinds, written in the manifest with a prefix:

| Source | Written as | Given by |
|---|---|---|
| a GitHub repository's releases | `github:owner/repo` | `appjail add owner/repo` |
| a file on a web server | `url:https://...` | `appjail add --url URL` |
| a file you already have | `file:NAME` (the file name only, never a path) | `appjail add --file PATH` |

The **resolver** is the part of appjail that turns `owner/repo` into a concrete file to download: it asks the GitHub API
about the repository, its latest release (or the one you name with `--tag`) and the files attached to that release,
the *assets*.

## Why it matters

The question "where does this program come from" is where supply-chain attacks start. A name can be typed wrong, or be
deliberately close to a popular one; a repository can change owner; a release can carry several files for different
systems, some of them not what you want; and an AppImage may suggest its own next source. Each of these is a way to
make you run something you did not choose.

## How appjail uses it

### Reviewing the repository

Before anything is downloaded, `add` shows the repository and its owner: the owner's name, whether it is a person or an
organisation, its **numeric account id** and when the account was created, the number of stars, and whether the
repository is a fork, archived or renamed. A young account or very few stars produce a warning. This is the moment to
notice a typosquat: a lookalike name rarely has an old account and an established project behind it.

The account id is recorded in the manifest as `owner_id`. GitHub never gives the same id to two accounts, so an update
from a repository whose owner id changed is blocked: the name now belongs to someone else.

### Choosing the release and the file

- The latest release, a pre-release with `--prerelease`, or a fixed one with `--tag` (the app is then *pinned* and
  `update` leaves it alone).
- Among the assets, only files ending in `.AppImage` whose download address is under that repository's own releases are
  considered. Files for other architectures are excluded by name (`aarch64`, `armhf`, `i686`, ...), and names that say
  `x86_64` or `amd64` win over names that say nothing. If several remain, you choose; if none, the install stops.
- appjail derives a pattern from the chosen file name, replacing the version with `*`, and records it as
  `asset_pattern`, so later updates pick the same file.
- GitHub's per-asset **digest** (a SHA-256 computed by GitHub when the file was uploaded) is read and, when there is one,
  the presence of a build attestation is looked up by it. Both are shown before you are asked to download; an asset
  without a digest gets a warning that it can reach tier 4 at most, unless an attestation verifies after the download.

### Talking to GitHub

The resolver uses GitHub's public REST API over HTTPS. Redirects are followed by hand and only within `api.github.com`
(a renamed repository is followed and reported); a redirect anywhere else is refused. Everything GitHub returns is
treated as untrusted: unexpected shapes are errors, not crashes, and every text shown passes through
[the text cleaner](untrusted-text.md). One `add` costs four or five requests of the 60 per hour GitHub allows without
a token; a `GITHUB_TOKEN` in the environment raises the limit and is sent only to `api.github.com`.

### URL and file sources

For an app that is not a GitHub release, you give the file. A URL must be https and without credentials; the download
may be redirected to another host, and a redirect through plain http needs an extra confirmation unless you give the
expected hash with `--sha256`. A local file must be a regular file; it is copied, and the copy is what gets checked and
installed. Nothing identifies the publisher in either case, which the [evidence tier](evidence.md) records.

## Connections

- The owner id and the digest feed the [evidence tier](evidence.md) and the update rules.
- The download itself runs in a [jail](jailed-steps.md) whose allowed hosts come from the resolver, never from the
  server.
- Decisions: [You name the source; releases from GitHub only](../../decisions/acquisition/sources.md),
  [The owner account is pinned](../../decisions/acquisition/owner-pinning.md).

## Limits

- Only GitHub releases are resolved. Apps on GitLab, Codeberg, Forgejo or a vendor's site can be added by URL, at a
  lower evidence tier.
- The review gives you facts, not a verdict: an established account can still be compromised.
- Asset selection by name relies on publishers naming their files; an unusual name may need you to choose.
- The pattern replaces the version only when the release tag appears in the file name. Otherwise it is the exact file
  name, and a later release whose file is named differently matches nothing: `update` stops and lists the release's
  files. The way out is to edit `asset_pattern` in the manifest (which `run` then reports as an edit made outside
  appjail).

## References

- GitHub REST API: [Releases](https://docs.github.com/en/rest/releases/releases),
  [Release assets](https://docs.github.com/en/rest/releases/assets),
  [Repositories](https://docs.github.com/en/rest/repos/repos),
  [Rate limits](https://docs.github.com/en/rest/rate-limit/rate-limit).
- GitHub Changelog, [Releases now expose digests for release assets](https://github.blog/changelog/2025-06-03-releases-now-expose-digests-for-release-assets/),
  June 2025.
- AppImage documentation, [Making AppImages updateable](https://docs.appimage.org/packaging-guide/optional/updates.html):
  the embedded update information appjail ignores.
- MITRE, [CWE-1007: Insufficient Visual Distinction of Homoglyphs](https://cwe.mitre.org/data/definitions/1007.html):
  lookalike names.
