# Workflows pinned and kept narrow

*Decision on [the project](index.md).*

**Context.** GitHub Actions run third-party code with access to the repository. A tag of an action can be moved to
other code; a broad token turns any flaw in a step into write access.

**Decision.** Every action is pinned to a full commit hash, with the version as a trailing comment (Dependabot updates
both). Workflows keep `permissions: contents: read` unless a job needs more, and then only that job gets it (creating a
release, publishing to PyPI through trusted publishing, opening the tool-bump pull requests). A release is built only
from a commit whose CI passed on `main`. The runner is named explicitly (`ubuntu-26.04`), because `ubuntu-latest` still
pointed to an older system when CI was set up.

**Consequences.** Updates of actions arrive as reviewed pull requests. The runner label is to be moved to
`ubuntu-latest` once GitHub has completed its move to 26.04 (planned for December 2026).
