# Testing in the guests

appjail runs untrusted software, so its own tests do too: they download real AppImages, start real jails and talk to
real compositors and audio servers. None of that runs on the developer's machine. Everything that executes software runs
in a disposable qemu-kvm guest built from tracked files; the host only edits files, runs `git` and runs qemu.

## The guests

| `GUEST=` | System | Purpose | ssh port |
|---|---|---|---|
| `debian` (default) | Debian 13 | the reference | 2222 |
| `ubuntu` | Ubuntu 26.04 | the CI runner's system, to reproduce runner-only failures | 2223 |
| `debian-pulse` | Debian 13 with PulseAudio as the sound server | `tests/test_pulseaudio.py` | 2224 |
| `debian-compositors`, `ubuntu-compositors` | the base guest plus the compositors of `tests/vm/packages-compositors.txt` | `tests/compositors/` | 2225, 2226 |

The variants reuse their base's image. Each guest has its own directory `vm/<guest>/run` (overlay disk, ssh key, known
hosts, console log), which is ignored by git and can be deleted and rebuilt. The packages a guest needs are listed in
`tests/vm/packages.txt`, one commented line each; change requirements there, never by hand in a guest.

Host requirements (Debian 13): qemu with KVM, `qemu-img`, `cloud-localds`, `genisoimage`, OVMF, `curl`, and access to
`/dev/kvm`.

The images are the distributions' cloud images: Debian 13 genericcloud (about 340 MB, verified against `SHA512SUMS`)
and Ubuntu 26.04 `resolute-server-cloudimg-amd64.img` (about 860 MB, verified against `SHA256SUMS`). Provisioning
replaces the cloud kernel with the regular one (`linux-image-amd64`, `linux-image-virtual`) so that `/dev/dri` exists,
and adds `tester` to the `video` and `render` groups; the guest has passwordless sudo inside it only. The camera tests
load the kernel's `vivid` virtual camera with `sudo modprobe` inside the guest and skip where they cannot.
`tests/vm/guest.sh` holds the differences between the guests.

## The scripts (`tests/vm/`, all honour `GUEST`)

1. `create.sh` downloads the cloud image (verified against the distribution's checksums), creates the overlay disk, the
   ssh key and the cloud-init seed. `--force` rebuilds the overlay and the seed.
2. `start.sh` boots the guest (ssh on 127.0.0.1 at its port, user `tester`); wait with
   `tests/vm/ssh.sh 'cloud-init status --wait'`.
3. `provision.sh` brings it to the expected state: packages, a regular kernel for `/dev/dri`, group memberships. It is
   idempotent; rerun it after editing `packages.txt`.
4. `sync.sh` copies the project to `~/appjail` in the guest; `ssh.sh CMD` runs a command there; `test.sh` syncs and runs
   the suite; `docs.sh` builds this site; `down.sh` stops the guest.

To resume work: `start.sh`, wait for ssh, `provision.sh` if `packages.txt` changed, then `test.sh`.

## Running the tests

```sh
tests/vm/test.sh                    # the full suite on Debian 13
GUEST=ubuntu tests/vm/test.sh       # and on Ubuntu 26.04
tests/vm/test.sh -k appimage -x     # any pytest arguments
```

Both minimum systems must pass before a commit and before a push: a pass on one is not a pass. Tests that start real
jails run only with `APPJAIL_INTEGRATION=1`, which `test.sh` sets. Opt-in suites download from the network and are run
by hand, one group at a time:

| Suite | Environment | File |
|---|---|---|
| live GitHub metadata (no downloads) | `APPJAIL_LIVE=1` | `tests/test_github.py -k live` |
| `add`, run and tamper with a GUI app under weston (the tamper test damages the shared image and must stay last) | `APPJAIL_E2E=1` | `tests/test_e2e.py` |
| an X11-only app under Xwayland | `APPJAIL_E2E=1` | `tests/test_xwayland_e2e.py` |
| real `update`, the tier 4 quarantine hash, URL apps | `APPJAIL_E2E=1` | `tests/test_update_e2e.py` |
| the DwarFS helper | `APPJAIL_E2E=1 APPJAIL_INTEGRATION=1` | `tests/test_tools.py` |
| Sigstore verification with the pinned `gh` | `APPJAIL_E2E=1 APPJAIL_INTEGRATION=1` | `tests/test_attest.py` |
| packaging (pip install in a venv, sdist) | `APPJAIL_E2E=1` | `tests/test_packaging.py` |
| the appjail-db catalog | `APPJAIL_E2E=1` | `tests/test_index_e2e.py` |

```sh
tests/vm/sync.sh && tests/vm/ssh.sh 'cd ~/appjail && APPJAIL_E2E=1 python3 -m pytest tests/test_e2e.py -v'
```

GitHub allows 60 unauthenticated requests an hour, shared by every run from the guest; a full run with the opt-in
suites uses about 45. Check `https://api.github.com/rate_limit` (it is free) before an end-to-end run. Downloading an
AppImage or any other binary for a test needs the maintainer's approval; the approved ones are listed in the project's
instructions.

To try the command line in the guest: `tests/vm/ssh.sh 'cd ~/appjail && PYTHONPATH=src python3 -m appjail ...'`. It
writes to the guest's own `~/.local/share/appjail` and `~/.config/appjail`.

## What the tests cover

- **Real software:** `add` and `run` of real AppImages (SquashFS and DwarFS); tier 3 and tier 4 downloads and the
  quarantine hash; Sigstore verification with the real `gh`; the private Xwayland with an X11-only app; a GUI app with
  `network` behind `pasta`; the real xdg-desktop-portal with a fake backend and with the GTK backend; the real
  `xdg-dbus-proxy`; the menu entry through `gio`; the real appjail-db catalog; a real PipeWire and `pipewire-pulse`;
  the real permission store; Landlock ABI 6 on Linux 6.12; the `vivid` virtual camera.
- **Tampering:** a changed pin, stored AppImage or extracted tree makes `run` refuse; a changed digest on `update` is a
  new candidate; a granted file, folder or parent folder swapped for a symbolic link just before the jail starts does
  not reach its target, with and without `pasta`.
- **Policy:** the compositor registries measured on real compositors are replayed against the Wayland rule; the
  seccomp table is checked against the kernel's header; the documentation is checked against the parser (every command
  and option documented) and against the policy lists ([policy lists](../reference/policy.md)).
- What is not verified yet is listed in [Deferred and planned work](../decisions/deferred.md#not-yet-verified).

## Test conventions

A test that starts a jail behind `pasta` must kill the whole process group: stopping `pasta` alone leaves the jail
running. Background jobs started in a guest session do not survive it.

All tests are plain pytest. Shared fixtures are in `tests/conftest.py`, shared helpers in `tests/helpers.py`; a test
module never imports from another. `tests/test_lint.py` runs `ruff`, `tests/test_reuse.py` runs `reuse lint`. More on
fixtures and the `Services` seam: [Reading the source](source-tour.md#testing-a-change).

## Known behaviour on the CI runner

- On the runner's Xwayland 24.1, a bare Xwayland crashes on ImageMagick's `display` under headless weston, with no jail
  involved; the X11 end-to-end test skips on that signature (the "Caught signal 11" message, or the client's "X connection
  to :0 broken" when the message does not reach standard error). Re-check when the runner's Xwayland changes.
- `e2e.yml` has shown two intermittent failures whose cause was not found: the GUI test hitting its 60 s limit, and a
  read timeout downloading a pinned tool. Rerun once before investigating.
- A test that fails only on CI is often a fixture assumption (the runner's uid is 1001, the guest's 1000): find the
  cause with a captured log before adding a workaround.
