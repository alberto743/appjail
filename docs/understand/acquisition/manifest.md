# The manifest

*Part of [Acquisition](index.md). Previous: [untrusted text](untrusted-text.md).*

## What it is

Every installed app is described by one file, its **manifest**: `~/.config/appjail/apps/NAME.toml`. It is written in
TOML, a small configuration format that holds keys, values, lists and tables and nothing else. It says where the app
comes from, which bytes were pinned, what evidence there was, which releases it follows, and what it may do:

```toml
schema = 1
name = "lagrange"
source = "github:skyjake/lagrange"
asset_pattern = "lagrange-*-x86_64.appimage"
owner_id = 1234567
version = "v1.18.5"
sha256 = "1ccdd4decb469fb4c1a77ad0e4b4f6c6e6d1c9f34a8b1e20d5a9c3f7e2b0d841"
evidence_tier = 3
published_at = "2026-10-01T09:12:44Z"

[permissions]
network = true
audio = false
gpu = false
portals = false
userns = false
```

## Why it matters

Installers built on scripts let the package decide what happens on your machine, and every script is code that runs
with your privileges. A manifest cannot *do* anything; it can only state facts that appjail checks and enforces. The
whole trust decision about an app is written in one place you can read, edit, copy to another machine, or keep under
version control.

## How appjail uses it

- **Strict schema.** An unknown key, a wrong type, a control character, a malformed hash, URL or date, or a name that
  does not match the file name makes the manifest invalid; appjail refuses to use it rather than guess. Keys that do not
  belong to the source's kind (an owner id on a URL app) are refused too.
- **Permissions default to denied.** A missing key in `[permissions]` means no; the writer always records the main
  switches explicitly, so a manifest shows what was decided.
- **Written by appjail, last.** The writer is deterministic and atomic (a temporary file renamed over the old one), and
  refuses to write an invalid manifest. On install and update it is written after the image and the tree are in place,
  so a failure never leaves a manifest that points at nothing.
- **Recorded.** Every change appjail makes is committed to a local git repository in the configuration directory, and
  `run` warns when a manifest was changed outside appjail.

You may edit a manifest by hand; the next command reads it with the same checks, `run` reports that it changed, and
`appjail history` shows what appjail itself recorded.

## Connections

- The pins (`sha256`, `owner_id`, `evidence_tier`) come from [the resolver](sources.md) and the
  [evidence](evidence.md); the permissions are listed in the [permission reference](../../reference/permissions.md).
- Decision: [A local history of the manifests](../../decisions/updates/history.md).

## Limits

- The manifest sits where any process of yours can write. The history detects a change appjail did not make; it does
  not prevent it, and a process that also rewrites the history repository is not detected.

## References

- [TOML v1.0.0](https://toml.io/en/v1.0.0) specification; Python's [tomllib](https://docs.python.org/3/library/tomllib.html),
  the standard-library parser appjail uses.
