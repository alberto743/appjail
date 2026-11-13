# History and rollback

*Part of [Updates](index.md). Previous: [URL and file apps](url-and-file.md).*

## What it is

Two mechanisms keep an update from leaving an app half-replaced or changed without a trace: an **atomic swap** of the
installed version, with rollback when a step fails, and a **history** of every manifest change in a local git repository.

## Why it matters

An update that fails in the middle (a full disk, an image that does not extract) must not leave an app whose tree no
longer matches its pin. And the manifests hold the pins in a directory any program of yours can write: a pin changed
behind appjail's back would make it trust other bytes without you knowing.

## How appjail uses it

- **Staged, then swapped.** The new image is extracted into a staging directory first. Only when that succeeded are the
  image, the tree, the markers and, last, the manifest replaced; the previous image and tree are kept aside until then
  and restored if anything fails. A new install that fails removes everything it created.
- **The history.** Every change appjail makes to its configuration (installing, updating, a new channel or tier, changed
  permissions, removing) is committed to a git repository in `~/.config/appjail`, by `git` running in a jail with no
  network that sees only that directory, with your git configuration and hooks ignored. Nothing is ever pushed.
- **Tamper evidence.** `run` warns when an app's manifest differs from its last recorded state; `appjail history [APP]`
  lists the changes.
- **Best effort.** Without `git`, or when the configuration directory is already inside another repository (a dotfiles
  repository), there is no history and no error.

## Connections

- The manifest's role and format: [the manifest](../acquisition/manifest.md).
- Decision: [A local history of the manifests](../../decisions/updates/history.md).

## Limits

- The history detects edits made outside appjail; a process that also rewrites the repository is not detected. It is
  evidence, not prevention.
- There is no command to roll back to an earlier version of an app; the previous AppImage is not kept after a
  successful update.

## References

- [git](https://git-scm.com/docs/git) documentation.
