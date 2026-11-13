# appjail

<div class="aj-hero" markdown>
<img src="assets/logo.svg#only-light" alt="appjail logo">
<img src="assets/logo-dark.svg#only-dark" alt="appjail logo">
<p>AppImages from sources you name, pinned by hash, each in its own jail.</p>
</div>

appjail installs and runs [AppImages](https://appimage.org/) on Linux and treats every one of them as untrusted
software. You name where an app comes from (a GitHub repository, a URL or a file); appjail downloads it in a sandbox,
pins it by its hash, records what evidence there is about who built it, and runs it in a
[bubblewrap](https://github.com/containers/bubblewrap) sandbox of its own (a *jail*) that starts with nothing but a
window. Everything else, from sound to a folder of your documents, is a permission you grant and can read back.
It works in user mode (no root), on Wayland desktops, with X11-only apps through a private Xwayland.

!!! warning "Young software"
    appjail has had no external security review. Read [the problem](understand/problem.md#what-appjail-does-not-do)
    for what it does not protect against before relying on it.

## Two lines of defence

An AppImage is a program you run with your own privileges: it can read your files, watch your other windows and talk
to every service of your session. appjail answers with two defences, each built on the assumption that the other can
fail:

**Provenance.** The source is the one you name, never one the software suggests. The downloaded bytes are pinned by
their SHA-256 hash and checked again before every start. The evidence about who published them (a build attestation,
the publisher's digest, or only "first seen") is recorded as an *evidence tier* that is never lowered silently. A new
version waits in quarantine and is shown to you as a difference before it replaces the old one.

**Containment.** Every step that touches the untrusted bytes runs in a jail with only the access that step needs: the
download has a network and nothing else, the extraction has neither network nor anything outside its work directory,
and the app itself gets a private home, a read-only system and a window. What it may reach beyond that is written in
its manifest, and what appjail cannot enforce it refuses rather than ignores.

## Where to go next

| You want to | Read |
|---|---|
| Understand why appjail is built this way | [The problem](understand/problem.md), then [the principles](understand/principles.md) |
| See how an app is fetched and checked | [Acquisition](understand/acquisition/index.md) |
| See how an app is isolated | [Isolation](understand/isolation/index.md) |
| See what an app can reach of your desktop | [Desktop access](understand/desktop/index.md) |
| Know how updates are checked | [Updates](understand/updates/index.md) |
| Know where search results come from | [Catalog](understand/catalog/index.md) |
| Give an app access to something | [Permissions](guide/permissions.md) |
| Know why a choice was made | [Decisions](decisions/index.md) |
| Look up a permission | [Permission reference](reference/permissions.md) |
| Work on appjail | [Architecture](develop/architecture.md) |

The source code, issues and releases are on [GitHub](https://github.com/alberto743/appjail); appjail is published on
[PyPI](https://pypi.org/project/appjail/) under the MPL-2.0.
