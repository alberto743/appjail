# The built-in catalog is built by appjail-db

*Decision on [catalog](index.md).*

**Context.** A catalog of AppImages exists in the AM project, as thousands of install scripts. Converting it on the
user's machine meant a network `git` jail, a 39 MB fetch and a parser of untrusted shell text, on every client.

**Options.** Convert AM on the client (the earlier design); download an unpinned file (no way to say which state was
reviewed, and a failed lookup would silently skip the pin); build the catalog in one place and download it at a pinned
commit.

**Decision.** The sister project [appjail-db](https://github.com/alberto743/appjail-db) converts the AM list and the
AppImageHub feed weekly in its CI, merging them without duplicates, with size and shrink checks (fewer than 5,000 apps,
or a drop of more than 10%, is refused). `appjail index update` asks the GitHub API which commit the default branch
points to, downloads `catalog.json` at exactly that commit in the download jail, and records the commit, so a catalog can
be traced to an exact state and an older one fetched again (`--commit`).

**Consequences.** `search` depends on appjail-db; installing never does. The catalog is not signed: its integrity rests
on HTTPS, on who can write to appjail-db, on the strict parser and on the review of every update.

**Revisit when** appjail-db is no longer maintained (any other catalog can be added with `index add`), or signing the
catalog with a key pinned in appjail becomes worthwhile.

## Facts about AM this rests on

Analysed for appjail-db, which now does the conversion; appjail itself no longer reads AM.

- AM's `appman` is a stub that downloads the manager from AM's `main` branch; AM updates itself and runs install and
  updater scripts from `main` outside any sandbox. At the commit analysed, 6 of 8,735 install scripts mentioned a checksum
  or a signature (AM's own release notes later count about 3,600 unique apps; recount before quoting). Its own sandbox
  option wraps `sas` or `aisap`.
- The list `programs/x86_64-appimages` has lines `◆ name : description`; `programs/x86_64/APP` holds the scripts. 8,247
  scripts set `SITE="owner/repo"`, about 224 point elsewhere. The first `SITE=` assignment counts, matched as text, never
  sourced.
- Of the last 200 commits at the analysed state, 139 carried a PGP signature (GitHub's web-flow key), 2 an SSH signature
  and 59 none; the maintainer's own commits are unsigned. Commit signatures cannot prove the maintainer's authorship.
