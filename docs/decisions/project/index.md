# Project

Decisions about the platform appjail supports, its interface, and how it is built, released and maintained.

| Decision | Covers |
|---|---|
| [x86-64, Debian 13 and Ubuntu 26.04](platform.md) | supported systems, and the paused arm64 work |
| [A window over the command line](gui.md) | the tkinter front end |
| [One output vocabulary, errors on stderr](output.md) | how commands print |
| [Vulnerability reports through GitHub](security-reports.md) | the reporting channel and supported versions |
| [Release tooling pinned by hash](build-pins.md) | the build of a release |
| [Workflows pinned and kept narrow](workflows.md) | GitHub Actions, the CI runner |
| [Release notes from the files touched](release-notes.md) | how release notes are grouped |
| [Commit messages checked for personal data](commit-hygiene.md) | the hook and the CI check |
| [Related projects](related-projects.md) | other tools that cover parts of the same need |
