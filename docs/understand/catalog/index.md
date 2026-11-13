# Catalog

*Part of "Understanding appjail".*

## What it is

A **catalog** is a list of applications with, where known, the place each one comes from. `appjail search` looks
through the catalogs of the local **index**: the built-in one, made by the sister project
[appjail-db](https://github.com/alberto743/appjail-db), and any you add yourself. A hit suggests the command to install
the app; it never installs anything.

The built-in catalog is derived from two public lists of AppImages: the install scripts of the [AM](https://github.com/ivan-hc/AM)
project and the [AppImageHub](https://appimage.github.io/) feed. appjail-db converts and merges them weekly in its own
CI, and publishes one JSON file.

## Why it matters

A catalog is written by others, and it sits right where a mistake is easiest: you search for a name, and the catalog
says which repository is behind it. A catalog that could carry commands would bring back the install scripts that
[principle 1](../principles.md#1-nothing-from-the-network-is-executed) rules out. One that pointed a popular name to a
lookalike repository would be a typosquat delivered by your own tool. And every text in it ends up on your terminal.

## How appjail uses it

- **Data in a strict format.** A catalog is one JSON document (`appjail-catalog`, version 1) with a list of apps, each
  with a name, and optionally a description, a source (`github:`, `gitlab:`, `forgejo:`, `codeberg:`, `url:`) and a
  note. An unknown key, a wrong version, a duplicate name, a malformed source, more than 50,000 apps or 16 MiB refuse the
  whole catalog; texts are cleaned of control sequences and cut. appjail stores its own serialisation of what it
  validated, never the downloaded bytes.
- **Pinned to a commit.** `index update` asks GitHub which commit of appjail-db is current, downloads `catalog.json` at
  exactly that commit in the download jail, and records the commit, so the catalog in use can be traced to an exact
  state and fetched again (`--commit`).
- **Reviewed before it replaces the old one.** Every update shows the number of apps, the apps added and removed and
  every app whose source changed, with a loud warning when an app moves to another owner or host, and asks before
  replacing anything (the default is no). One previous catalog is kept per source for `index rollback`.
- **Other sources.** `index add NAME --url https://...` or `--file PATH` adds a catalog in the same format, with the same
  parsing and review.
- **Search.** Every keyword must appear in the name or the description. Results are ranked: exact name, name prefix, all
  keywords in the name, some in the name, description only. Only `github:` and `url:` sources get an `appjail add`
  command; the others are shown as information. An app the two origins place in different repositories has no source,
  and a note names both, for you to choose.

## Connections

- Installing from a hit goes through `add` and its own review: [sources and the resolver](../acquisition/sources.md).
- The text cleaner and strict parsing: [untrusted text](../acquisition/untrusted-text.md).
- Decisions: [The built-in catalog is built by appjail-db](../../decisions/catalog/appjail-db.md),
  [Catalogs are strict data](../../decisions/catalog/strict-data.md).

## Limits

- The catalog is not signed: its integrity rests on HTTPS, on who can write to appjail-db, on the strict parser and on
  your review of each update.
- Listing an app is not an endorsement. A catalog can list unwanted software; containment is what limits it if you
  install it.
- `search` depends on appjail-db; installed apps never do.

## References

- [appjail-db](https://github.com/alberto743/appjail-db), [AM](https://github.com/ivan-hc/AM),
  [AppImageHub](https://appimage.github.io/).
- IETF, [RFC 8259: The JSON Data Interchange Format](https://www.rfc-editor.org/rfc/rfc8259).
- GitHub REST API, [Commits](https://docs.github.com/en/rest/commits/commits): how the current commit of appjail-db is
  resolved.
