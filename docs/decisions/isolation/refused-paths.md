# Paths that are never granted

*Decision on [isolation](index.md).*

**Context.** A folder grant is the most common way to widen a jail, and the easiest to get wrong: granting `~/.config`
to share one application's settings also grants every other application's tokens.

**Decision.** A fixed policy refuses credentials and secrets, folders that contain them, over-broad folders, system
trees, shared temporary directories and appjail's own files in every mode, and places where a written file would later
run or be decoded outside the jail, or change how your other apps look, in read-write mode ([the filesystem
view](../../understand/isolation/filesystem.md)). There is no option to override it.

One exception is made to the system trees: the mount points of removable media below the user's own `/run/media/USER`,
where udisks mounts drives on Fedora (Debian and Ubuntu use `/media/USER`, which is not a system tree). The rest of
`/run` holds the user's session bus, sockets and keyring, so it stays refused, as do `/run/media` and `/run/media/USER`
themselves and another user's directory there. The name is checked when the app starts, against the account running it;
a stored entry or a typed path is accepted for any name, because the policy does no I/O.

**Consequences.** Some legitimate grants need a narrower path. An override would turn every refusal into a question of
whether to type it, which is the kind of decision [principle
7](../../understand/principles.md#7-you-decide-with-the-facts-in-front-of-you) says a warning cannot make.
