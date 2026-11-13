# Release notes from the files touched

*Decision on [the project](index.md).*

**Context.** Most work reaches `main` without a pull request (single commits, or local branches merged with a merge
commit), so GitHub's generated release notes, which list pull requests, would be nearly empty. Commit subjects follow no
fixed prefix.

**Decision.** A script lists the commits since the previous tag, without merge commits, grouped by the files they touch:
Security (the security modules, or a security subject), Interface (the CLI and the window), Logic (the rest of the
source), Documentation, Tests, Other. Commits that came through a pull request are left to GitHub's generated notes,
which follow the labels in `.github/release.yml`.

**Rejected.** Grouping by subject prefix (most of the history would land in "Other"); a hand-written changelog (it
drifts from the tags).
