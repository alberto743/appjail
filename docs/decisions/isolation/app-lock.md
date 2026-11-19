# No change under a running app

*Decision on [isolation](index.md).*

**Context.** `remove` and `reset` deleted an app's private home without knowing whether the app was running; whatever
it wrote afterwards was lost, without a message. An update moved the old tree aside and deleted it, while the running
jail still bound it, so files the app had not loaded yet disappeared. Two commands on the same app (a launch extracting its tree while an
update swaps it) could also interleave.

**Options.** Check the process list for the app's jail; record the running instances in a file; hold a lock for the
app's lifetime.

**Decision.** Two `flock` locks per app under `~/.local/share/appjail/locks/`, which the kernel releases when the
process that holds them exits, so none can go stale:

- `NAME.lock`, exclusive, held while the app's files change or its tree is extracted: `add`, `update`, a launch
  preparing the tree, `remove`, `reset`. A command that finds it taken waits up to 60 seconds, then fails with a message.
- `NAME.run`, shared, taken by every launch before it releases `NAME.lock` and held by appjail until the jail ends.
  `remove`, `reset`, and an `update` or `add` that replaces an installed tree, try to take it exclusively while they
  hold `NAME.lock`, and refuse when a launch holds it; since a launch needs `NAME.lock` to start, none can begin between
  that check and the change.

The descriptors are close-on-exec and never passed to the jail, so an app cannot hold its own lock. The process list
was rejected: a jail has no name the host can match reliably. A file of instances was rejected: it outlives a launcher
that is killed.

Keeping the old tree until the last launch ends was rejected: it needs a tree per running version and a cleanup
that survives a killed launcher, for a case a restart solves.

**Consequences.** Close the app before removing, resetting or updating it. An update of a running app is reported as
failed after its download and checks; a candidate in quarantine stays pending. The lock files stay after `remove` (deleting a lock
file someone may be about to open is a race); they are empty.

**Revisit when** a command needs to stop a running app itself.
