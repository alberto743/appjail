# Release tooling pinned by hash

*Decision on [the project](index.md).*

**Context.** A release is built on a CI runner from tools downloaded from PyPI. A replaced upload of one of those tools
would run in the release job and could alter what is published.

**Decision.** The build tools and all their dependencies are pinned in `.github/requirements-build.txt` by exact version
and by every file hash PyPI lists, installed with `--require-hashes --only-binary=:all:` (nothing is built from source),
and the build runs with `--no-isolation`, so the build backend is not fetched unpinned either. The same install runs on
every push, so an outdated pin shows before a tag. The documentation tooling is pinned the same way
(`.github/requirements-docs.txt`). Dependabot proposes new versions, reviewed like new dependencies.

**Consequences.** A changed upload fails the job instead of being used. `pip` itself in the runner is not pinned, and a
different Python on the runner may add or drop a conditional dependency, which the CI step then shows.
