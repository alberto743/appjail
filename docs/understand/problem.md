# The problem

This page describes what appjail protects, against whom, and where its protection ends. Every other part of the
design follows from it: the [principles](principles.md) answer it, and the pages under "Understanding appjail" explain
the mechanisms that put those principles into practice.

## What running an AppImage means

An AppImage is a single executable file that carries a program and the libraries it needs. The usual way to use one is
to download it from a release page, mark it executable and run it. From that moment it is an ordinary process of yours:

- it can read and change every file you can: documents, photos, source code, and the credentials in `~/.ssh`,
  `~/.gnupg`, your browser profile or your password manager's database;
- it can talk to every service of your desktop session over D-Bus: the notification daemon, but also the settings
  database (where a custom keyboard shortcut is a command that runs on a key press), the desktop shell, the
  screensaver and the services that start other programs;
- it can connect to the services listening on your own machine (a database on `localhost`, a development server, a
  printer's web interface) and to any host on the internet;
- on an X11 session it can read the keystrokes and the contents of every other window; on Wayland it can do whatever
  the compositor lets any client do, which on some desktops includes capturing the screen and typing into other
  windows;
- it can record from the microphone and the camera, and listen to what other applications play;
- it can install itself to start at every login (an autostart entry, a systemd user unit, a line in your shell's
  startup file), and so keep any of the above going after you stopped using it.

None of this needs a vulnerability: it is what any program you run is allowed to do. The question is only whether the
program does it, and that depends on who made it and on whether it is still what they made.

## Who appjail defends against

The **software itself**, malicious from the start or turned malicious later. Most AppImages are honest; appjail does
not try to tell which ones are, it limits what any of them can do.

**Whoever can change what you download.** The usual attacks on software distribution need no flaw in the program:

- a publisher's account or repository is taken over and a new release is published by someone else;
- an asset of an existing release is replaced with different bytes under the same name;
- a repository is deleted and its name registered again by another account, so the same `owner/repo` now points to
  someone else;
- a name close to a popular one (typosquatting) catches users who search for the popular one;
- the server behind a download URL, or a network on the path, serves something else.

**The untrusted data that comes with the software.** Release notes, file names, the AppImage's own menu entry and
icon, catalogs of applications, and any text that ends up on your terminal are written by others. A menu entry can name
any command to run; an icon is decoded by the desktop's image loaders outside any sandbox; text can carry terminal
escape sequences that rewrite what you see.

**The tools that manage the software.** An installer that downloads and runs scripts, or updates itself from the
network, can be compromised once and reach everyone who uses it. appjail was started after studying one such manager,
[AM](https://github.com/ivan-hc/AM), which updates itself and runs install scripts fetched from its repository outside
any sandbox, and whose scripts almost never check a hash or a signature.

## What appjail does

Two defences, each built on the assumption that the other can fail.

**Provenance**: knowing what you run and noticing when it changes. You name the source and nothing else may choose it;
the bytes are pinned by their SHA-256 hash and checked before every start; the evidence about who built them is
recorded and never lowered silently; the account that owns the repository is pinned, so a re-registered name is
noticed; a new version waits for a quarantine period and is shown to you as a difference before it is installed.
Provenance cannot tell you that software is safe. It tells you that it is the software you decided to trust, from the
place you decided to trust, and it gives the rest of the world time to notice when that place is compromised.

**Containment**: limiting what the software can do, whatever it is. Each app runs in a jail of its own that sees a
read-only system, its own files, a private home and a window, and nothing else unless you grant it. The steps before
the app runs (download, extraction, verification) are jailed too, each with only what it needs, because they handle
the untrusted bytes before anything about them is known. Containment cannot make a grant harmless: an app given your
`~/Documents` read-write can damage them. It keeps the damage to what you granted.

## What appjail does not do

- **It does not judge software.** An evidence tier proves "unchanged" and, for GitHub, "from the same account". A
  publisher who ships malware from the start passes every check; containment is what limits them.
- **It does not make grants safe.** Each permission widens what a compromised app can do, within the limits that the
  permission describes.
- **It trusts the platform.** The Linux kernel, bubblewrap, the compositor, the desktop's services and the helper
  programs appjail starts are trusted. A flaw in them can let an app out. appjail reduces how much of them an app
  can reach (fewer system calls, no nested namespaces, no privileged Wayland interfaces), but cannot fix them.
- **It does not protect the local network.** An app with the `network` permission reaches the internet and the other
  machines of your LAN; it does not reach the services of your own machine.
- **It does not stop other programs of yours.** A process of your user that runs outside appjail can change appjail's
  files, including the manifests and the pins. appjail keeps a history of its manifests and warns when one was changed
  behind its back; that is evidence, not prevention.
- **It is not audited.** It is maintained by one person and has had no external review.
- **It runs on x86-64 Linux only**, with Debian 13 and Ubuntu 26.04 as the minimum supported systems.

The design's own measured limits (which desktops it was tested on, which devices and services were checked by hand)
are stated on the page of each mechanism.

## References

- AppImage project, [Concepts](https://docs.appimage.org/introduction/concepts.html) and
  [AppImage documentation](https://docs.appimage.org/).
- SLSA, [Supply chain threats](https://slsa.dev/spec/v1.0/threats-overview): a map of the ways software is
  attacked between its source and its users.
- MITRE, [CWE-494: Download of Code Without Integrity Check](https://cwe.mitre.org/data/definitions/494.html).
- MITRE ATT&CK, [Supply Chain Compromise (T1195)](https://attack.mitre.org/techniques/T1195/).
- X.Org Foundation, [Access control and authentication in X](https://www.x.org/wiki/Development/Documentation/Security/): ordinary ("trusted") clients can read other clients' windows and input.
