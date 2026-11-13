# Helper tools pinned in the source

*Decision on [acquisition](index.md).*

**Context.** Two helpers are not available from the supported distributions in a usable form: the GitHub CLI (for
attestations) and the DwarFS extractor (for AppImages built on DwarFS). appjail never fetches code on its own
([principle 2](../../understand/principles.md#2-appjail-does-not-update-itself)).

**Decision.** Each tool is pinned in `tools.py` by URL, size and sha256. `appjail tools install NAME` downloads it in
the download jail, keeps it only if both match, stores it under appjail's data directory and re-hashes it before every
use; the DwarFS extractor runs only inside the extraction jail. A newer version is a change to the source: a weekly
workflow (`bump-tools.yml`) opens a pull request for each new stable release with the measured size and hash, checked
against GitHub's own digest, and a checklist for the review. It never merges by itself.

**Consequences.** A new tool release reaches users only through an appjail release. Dependabot cannot do this (the pins
are URLs and hashes in Python), hence the dedicated workflow. Pull requests opened with the workflow token do not start
CI; closing and reopening the pull request does, which avoids storing a more powerful token.
