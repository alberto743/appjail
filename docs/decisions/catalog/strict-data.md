# Catalogs are strict data

*Decision on [catalog](index.md).*

**Context.** A catalog is written by someone else, and every text in it ends up on your terminal. A catalog that could
carry commands, or that different versions of appjail read differently, would be a way in.

**Decision.** A catalog is one JSON document in a versioned format (`appjail-catalog`, version 1), parsed strictly: an
unknown key, a wrong version, duplicate names, a malformed source, more than 50,000 apps or 16 MiB refuse the whole
catalog. Texts are cleaned of terminal escape sequences and cut to fixed lengths. What is stored is appjail's own
serialisation of what it validated, never the downloaded bytes. A hit is a suggestion: it prints the `appjail add`
command, and installing goes through `add` and its own review. An update of a catalog shows the apps added and removed
and every changed source, with a loud warning when an app moves to another owner, and replaces nothing before you
agree. One previous catalog is kept for `index rollback`.

**Consequences.** Catalogs from other sources work the same way (`index add`). A catalog can list unwanted software;
that is the case appjail is built to contain, not a flaw of the catalog format.
