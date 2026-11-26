# Workflows pinned and kept narrow

*Decision on [the project](index.md).*

**Context.** GitHub Actions run third-party code with access to the repository. A tag of an action can be moved to
other code; a broad token turns any flaw in a step into write access.

**Decision.** Every action is pinned to a full commit hash, with the version as a trailing comment (Dependabot updates
both). Workflows keep `permissions: contents: read` unless a job needs more, and then only that job gets it (creating a
release, publishing to PyPI through trusted publishing, opening the tool-bump pull requests). A release is built only
from a commit whose CI passed on `main`. The runner is `ubuntu-latest`. It was named explicitly (`ubuntu-26.04`) while
`ubuntu-latest` still pointed to an older system; GitHub completed its move to 26.04 in November 2026 and the workflows
ran unchanged on it.

**Consequences.** Updates of actions arrive as reviewed pull requests. The runner moves to the next Ubuntu LTS when
GitHub moves `ubuntu-latest`; the monthly platform check reads the Ubuntu target from the guest image, not from the
label, so it still reports a new LTS. A failure that appears only after such a move is handled as a change of platform
(the project supports the current Ubuntu LTS), not worked around by pinning.
