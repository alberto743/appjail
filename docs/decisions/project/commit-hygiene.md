# Commit messages checked for personal data

*Decision on [the project](index.md).*

**Context.** Everything pushed to the public repository is world-readable, commit messages included. Commits made from
web sessions once carried a trailer linking the session; they were removed from the history and force-pushed, the one
exception to never rewriting pushed history.

**Decision.** A `commit-msg` hook (`.githooks/`, enabled once per clone with `git config core.hooksPath .githooks`) and a
CI job check every commit message against `.githooks/forbidden-patterns`: session links, home and temporary paths,
e-mail addresses other than GitHub's no-reply ones. The project's tool settings turn session links off.

**Consequences.** GitHub keeps old commits reachable by hash until its support purges them.
