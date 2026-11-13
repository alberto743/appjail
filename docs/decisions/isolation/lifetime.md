# The jail ends with its command

*Decision on [isolation](index.md).*

**Context.** VSCodium's launcher starts the editor detached and exits, so the jail, and the editor, ended at once.

**Options.** Always wait for every process in the jail; wait only for the command; make waiting a permission.

**Decision.** By default the jail ends with its command. The `linger` permission makes it wait for every process,
through a supervisor that becomes the jail's subreaper. Always waiting was rejected: an app that leaves a crash handler
or an agent behind would keep `appjail run` from ever returning, and "closing the app closes everything" would no
longer hold.

**Revisit when** most apps in the catalog need `linger`, or a reliable way appears to tell an app's own processes from
the helpers it leaves behind.
