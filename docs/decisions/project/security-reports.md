# Vulnerability reports through GitHub

*Decision on [the project](index.md).*

**Context.** A tool that runs untrusted software needs a private way to report flaws in it. The project has one
maintainer and keeps no personal data in its files.

**Decision.** Vulnerabilities are reported through GitHub's private vulnerability reporting (the repository's Security
tab), not by e-mail. No response or disclosure times are promised. Only the latest release receives fixes, as a new
patch release; there are no long-lived branches and no backports. The contents of a catalog are out of scope: a catalog
is untrusted data, and a bad entry is the case appjail contains; a flaw in how a catalog is parsed or shown is in
scope.

**Consequences.** Reporters need a GitHub account. Users of an older release must upgrade to get a fix.
