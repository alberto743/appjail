# One granted name reaches its whole connection

*Decision on [desktop access](index.md).*

**Context.** `xdg-dbus-proxy` with `--talk=NAME` filters by destination name, but one process answers on all the names
it owns: a call to a granted name reaches every object of the connection that owns it. Desktop shells own ordinary
names on the same connection as refused ones. Measured through the proxy as appjail started it: on GNOME Shell,
`org.gtk.Notifications` and the keyring prompter reached Mutter's `RemoteDesktop.CreateSession`; on Cinnamon,
`org.freedesktop.Notifications` and five other names reached `org.Cinnamon.Eval`. The refused-name list protected only
where every name of the privileged connection was refused.

**Options.** (a) At `run`, refuse a granted name whose owner also owns a refused name: simple, but it refuses grants
that work when confined (notifications on Cinnamon) and is blind to owners that change later. (b) Replace `--talk` with
`--call` rules that confine a name to its own objects and interfaces: exact, but each service's paths and interfaces
must be known. (c) Both: rules for the known services, the owner check for every other name.

**Decision.** (c). Known services (desktop notifications, `org.gtk.Notifications`, the Secret Service, MPRIS players,
the status-notifier watcher) get `--call` and `--broadcast` rules for the interfaces their specifications define, on
their object path only; whoever owns them, the proxy refuses everything else. Every other granted name keeps `--talk`,
and before starting the proxy `run` reads the owners of the granted and refused names and stops if one connection
owns both, failing closed when the owners cannot be read. Checked on a private bus with a fake shell, and on GNOME
Shell, Cinnamon and Plasma's shell: every allowed name was either confined or refused at launch.

**Rejected for now.** Rules written by the user in the manifest (a format change, and wrong rules fail silently);
deriving an object path from the name (MPRIS and status-notifier break the convention); re-checking owners while the
app runs (the proxy cannot be told, and stopping a running app on a name change is new behaviour).

**Consequences.** A name that nobody owns at launch, or that changes owner while the app runs, is not checked again.
MPRIS players and tray icons that need a name with a process-id suffix cannot be expressed (the proxy matches only a
trailing `.*`).
