# Security policy

appjail exists to run untrusted software with less access, so reports about its isolation and verification are welcome.
It is maintained by one person, unaudited, and handled on a best-effort basis (see "Limits" in the README).

## Supported versions

Only the latest release (PyPI and GitHub) receives security fixes, published as a new patch release. There are no
backports. Supported systems are Debian 13 and Ubuntu 26.04, with Python 3.12 or later.

## Reporting a vulnerability

Please report privately through GitHub: the repository's **Security** tab, **Report a vulnerability**. Do not open a
public issue or pull request for a vulnerability.

Useful details: the appjail version (`appjail --version`), kernel, bubblewrap version, compositor, the app's manifest
(`appjail perms APP`), and steps to reproduce. A reproduction that runs in a virtual machine is preferred.

Reports are handled in private and fixed before they are disclosed; reporters are credited in the release notes unless
they prefer not to be.

## In scope

- An app getting more than its manifest grants: files, D-Bus names, portals, sockets, network, devices.
- A way around the hash, attestation, quarantine, tier-downgrade or owner-change checks of `add` and `update`.
- Unsafe handling of untrusted data: catalogs, manifests, release metadata, AppImage contents (path traversal, symlinks,
  terminal escape sequences).
- Weaknesses in the release workflows or the pinned helper binaries (`gh`, DwarFS).

## Out of scope

- What the README documents as limits: for example an app granted `full_wayland` running although its Wayland socket
  lists privileged or unknown interfaces, the Wayland interfaces the README allows after a decision (such as idle
  notification), or reaching the LAN with `network`. An interface in appjail's allowed list that lets an app act on other
  apps is in scope. A granted D-Bus name reaching the other objects of the process that owns it is a known limit with a
  fix pending; another refused name or object reached that way is in scope.
- What a granted permission allows, and what a tier means: tiers 3 to 5 prove "unchanged", not "safe".
- Flaws in the installed apps, or in bubblewrap, the kernel, pasta, `gh` or DwarFS themselves. Report those upstream; if
  appjail's use of them makes the flaw reachable, report that here.
- The contents of any index source, the built-in one or one you added. Listing an app is not an endorsement, and
  appjail trusts no entry. A catalog that makes appjail run code, write outside its own directories, print unescaped
  text, or skip a check is in scope. A catalog that merely lists unwanted software is not.

## Research

Test on your own machine and accounts only. Reproducing an issue never needs root.

The design and its trust model are described in [DESIGN.md](https://github.com/alberto743/appjail/blob/main/DESIGN.md)
and the README's "Trust and updates" and "Limits" sections.
