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
