# Narrowing the host's system view

*Decision on [isolation](index.md). Decided in November 2026 by the maintainer, after the study below: the host's view
is kept, and what it shows is documented. An opt-in per-app list stays a deferred option.*

**Context.** The jail binds the host's `/usr`, `/bin`, `/sbin` and `/lib*` read-only ([bubblewrap](bubblewrap.md)), so
an app can run any program of the host and list what is installed, and its behaviour depends on the host; Flatpak mounts
a runtime there instead ([Flatpak compared](../project/flatpak-comparison.md)). A runtime is out of scope. The question
is whether the host's view could be narrowed. The list of libraries an ELF file links does not answer it, because it
leaves out the programs an app starts, the files it opens at run time and what the kernel opens by itself, so the
[measurements](../../develop/host-view-evidence.md) traced real runs of htop, Galculator, Lagrange and ImageMagick in
the Debian 13 guest, in four variants of the view, three rounds each, then on Ubuntu 26.04 and Fedora 45:

- **A**, a fixed minimal set (`sh`, `env`) with `/usr/bin`, `/usr/sbin`, `/usr/libexec` and `/usr/share/applications`
  emptied, broke two of four apps in every scenario: Galculator (its start-up hook runs `ln`) and ImageMagick (its
  `AppRun` needs `bash`, `dirname` and `readlink`). htop and Lagrange ran; htop lost the `strace` screen without an
  error.
- **A2**, the programs each app was seen to run, put back, ran everything it was trained on, and missed the helper of a
  feature that the training run did not use (htop's `strace`, trained on its text screen only).
- **B**, only the files a run was seen to open, ran three of four apps, never ran Galculator (an XKB keymap compile
  fails, cause not found), needs 1000 to 1250 single-file mounts for a GUI app, and depends on the host's own library
  versions. The first version started nothing at all, because the ELF loader and script interpreters are opened by the
  kernel and appear in no trace of open calls.
- What narrowing hides is the list of programs and menu entries (1029 programs and 11 entries became 2 and 0). It does
  not hide the installed packages (`/usr/share/doc`, 916 entries), the library files and versions, or the distribution
  release: apps need those directories.
- Not measured: anything interactive (links, file and print dialogs, drag and drop), Electron apps, Ubuntu and Fedora.
  The static scan shows that all four apps name `xdg-open` and none ran it.

**Options.**

- *Keep the host's view (variant C).* No work and no breakage; an app sees the programs and the package list of the
  host. What the jail does about them is [the rest of the isolation](../../understand/isolation/index.md): no network
  without `network`, no host files, no new privileges.
- *A narrower default (A).* Rejected by the measurements: a fixed list that works for these four apps is at least `sh`,
  `bash`, `env`, `ln`, `dirname`, `basename` and `readlink`, plus on Ubuntu and Fedora `bwrap`, `xdg-user-dir` and a
  loader under `/usr/libexec/glycin-loaders` that GTK's image library runs; and it would be the list of these four. The
  next app, or the next release of one, can need another, and the failure is a missing program inside the app, not a
  message from appjail (principle 4 asks that what cannot be honoured is refused, not ignored).
- *A per-app allowlist (A2).* It works when its list is right. It would need a way to record the list (a trace mode of
  `run`, which means a tracer in the jail's command line), a place in the manifest, review at `update` (a new release
  can run a new helper), and a way to see which feature failed for lack of a program. That is a permission with
  maintenance, for a gain that this study did not measure in any attack.
- *Only the traced files (B).* Rejected: too many mounts, fragile, one app unexplained, and the same recording problem
  as A2.
- *An opt-in strict grant on top of C.* The cheapest honest form of A2: off by default, the user turns it on for one app
  and accepts that features may stop. Unlike A, a breakage would be the user's choice, shown by `perms`.

**Decision.** Keep variant C. The measurements do not show a narrowing that is both safe by default and cheap, and what
it hides (programs, not package names or library versions) is a small part of what the host's view gives away. What the
view shows is now written down where a reader looks for it:
[the filesystem view](../../understand/isolation/filesystem.md#the-hosts-system-directories),
[the problem](../../understand/problem.md#what-appjail-does-not-do), the README's limits and SECURITY.md's out-of-scope
list. If it is wanted later, the form to build is the opt-in per-app list (A2), after a trial of the interactive paths
and the Electron apps that this study could not run.

**Consequences.** No code changes. The row in [deferred work](../deferred.md) becomes a deferred feature, the opt-in
list, with its condition. The measurement scripts (`tests/hostview/`) stay, so the matrix can be rerun on other systems
and apps, and the page of the filesystem view states the limit.
