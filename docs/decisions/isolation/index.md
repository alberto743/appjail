# Isolation

Decisions about the jail an app runs in. How it works is explained in
[Isolation](../../understand/isolation/index.md).

| Decision | Covers |
|---|---|
| [bubblewrap, not Firejail or sas](bubblewrap.md) | the sandbox engine, and the tools rejected for it |
| [Extract, never mount](extraction.md) | AppImages are extracted, never mounted or run outside a jail |
| [Nothing granted by default](default-grants.md) | a new app gets only a window |
| [Paths that are never granted](refused-paths.md) | the paths no grant can reach, with no override |
| [Grants bound by descriptor](grants-by-descriptor.md) | the race between checking a path and binding it |
| [A seccomp deny list](seccomp.md) | which system calls are refused, and how |
| [Landlock for abstract sockets only](landlock.md) | Landlock is used for abstract sockets only |
| [The jail ends with its command](lifetime.md) | when a jail ends, and the `linger` permission |
