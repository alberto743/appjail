# Camera, screen sharing, playback and microphone: the evidence

Working notes, not a specification: the behaviour is on [Devices](../understand/desktop/devices.md),
[Audio](../understand/desktop/audio.md) and [Portals](../understand/desktop/portals.md), and the decisions drawn from
these measurements are [Camera: the capture nodes only](../decisions/desktop/camera.md) and
[the private audio graph](../decisions/desktop/audio-graph.md). Written in November 2026 from experiments in the qemu
guest. "Measured" means a test or command ran in the guest; "read" means source code or documentation only; "not done"
means neither. Nothing here was run on the maintainer's own machine.

The decision pages record the conclusions, not every observation; this page keeps the observations, in particular the
WirePlumber question below (now explained) and the tables of what the tools and portals showed. The start-up failure of
the graph on the Ubuntu 26.04 runner, which this note once pointed to, was fixed (start order; see the audio decision).
Versions in the environment table are those of the time of writing.

## Environment of the measurements

| | Guest (Debian 13) | CI runner (Ubuntu 26.04) |
|---|---|---|
| Kernel | 6.12.115 | 7.0.0-azure |
| PipeWire | 1.4.2 | 1.6.2 |
| WirePlumber | 0.5.8 | 0.5.13 |
| bubblewrap | 0.12 | 0.11.1 |
| Other | sway 1.10.1, `vivid` virtual camera, `snd-aloop` | xdg-desktop-portal 1.21.1, Python 3.14.4, no `vivid` |

Test devices: the `vivid` kernel module (`video0` capture, `video1` output, `video2`/`video3` metadata), PipeWire's
`videotestsrc` and `audiotestsrc`, a null sink as the speaker. There is no real camera, microphone or headset.

## How frames reach an app

| Source | Mechanism | Who connects source and app |
|---|---|---|
| Webcam, direct | The app opens `/dev/videoN` (mmap buffers, or GStreamer `v4l2src`) | Nobody: the app talks to the driver |
| Webcam, portal | The Camera portal returns a PipeWire fd limited to camera-role nodes; the app connects a stream on it | The session manager links the camera node to the app's stream. In the guest WirePlumber's automatic link failed (reproduced with plain PipeWire, WirePlumber and `gst-launch`, no portal, no appjail), so the test links with `pw-link` from the host side |
| Screen, portal | ScreenCast portal: `Start` returns stream ids, `OpenPipeWireRemote` returns a limited fd | Same |
| Screen, direct | Wayland `wlr-screencopy` (what `grim` uses) over the app's Wayland socket | The compositor; refused on appjail's restricted socket |

## Camera (V4L2 device bind, `camera`)

| Claim | Evidence | Status |
|---|---|---|
| A jailed app captures a real frame | `v4l2src` in the jail wrote a PNG, decoded on the host: 640x480, 8 colours (colour bars) | measured |
| Raw mmap capture works under seccomp and `--cap-drop ALL` | ioctl sequence returned a frame; GStreamer ran 3 buffers | measured |
| Only capture nodes are bound | `video0` present; `video1`, `video2`, `video3`, `media0` absent | measured |
| Sysfs narrowed to the node's directory | `/sys` holds `dev` and `devices` only; `v4l2-ctl --all` works. Either `/sys/dev/char` or `/sys/devices` alone is not enough | measured, `vivid` only |
| The seccomp filter lets V4L2 ioctls through | it blocks only `TIOCSTI` and `TIOCLINUX` on `ioctl` | measured |
| No camera present, or two cameras | the jail starts with none; both usable with two | measured |
| The camera grant gives no audio | no `/dev/snd` | measured |
| Real USB webcam, hot-unplug, effect of the capability query on a real device | not tested | not done |

## Camera and screen through portals

| Claim | Evidence | Status |
|---|---|---|
| Camera portal limits the app's PipeWire view to camera-role nodes | registry listed through the portal fd with `pw-dump` over a bridged socket: camera node present, Screen node absent | measured, synthetic node |
| A real frame reaches the app through the Camera portal | PNG 320x240, 264 colours | measured, synthetic source, linked by `pw-link` |
| The portal exposes a real V4L2 node (`v4l2_input.platform-vivid.0`) | it did not; the synthetic Camera-role node was exposed. See "The V4L2 node and WirePlumber" below | measured, negative; cause found (a test control of vivid) |
| ScreenCast handshake through appjail's filtered bus | `CreateSession`, `SelectSources`, `Start`, `OpenPipeWireRemote` completed with the existing `ScreenCast` opt-in; the backend saw `app.appjail.<name>` | measured, fake backend |
| The ScreenCast remote is limited to the shared stream | registry through the fd: the shared node only; a second node with the same role absent | measured |
| A real frame of the shared stream | PNG 320x240, 264 colours | measured, synthetic source, linked by `pw-link` |
| `xdg-desktop-portal-wlr` works on headless sway | failed: "unable to receive a valid format from wlr_screencopy"; `grim` works there only with the pixman renderer | measured, negative |
| Direct Wayland capture: host side | `grim` on headless sway (pixman): 640x480 PNG | measured |
| Direct Wayland capture: in the jail | "compositor doesn't support wlr-screencopy-unstable-v1", no file | measured |
| X11 app in the private Xwayland | root has 0 children; `xwd -root` fails with `BadMatch` | measured, rootless only |
| `appjail remove` forgets stored screen-cast decisions | `portal.STORE_TABLES` includes `screencast` and `remote-desktop` | read |
| GNOME and KDE backends, persisted shares, RemoteDesktop and InputCapture | not tested | not done |
| How Firefox, Chromium, OBS and Zoom reach camera and screen | not researched | not done |

## The V4L2 node and WirePlumber (explained: a test control of vivid)

All in the guest with `vivid`.

| Observation | Result |
|---|---|
| WirePlumber's portal script (an instrumented copy) when the portal's client connects | its node set held only the synthetic camera; node 50, the V4L2 node (`Video/Source`, `media.role = Camera`), was never in it, even after 5 s |
| The script's unconstrained node list, with object-added events | only the daemon-created nodes; the V4L2 node never added |
| `pw-dump` at the same time | the V4L2 node is in the registry, created before the portal's client |
| `wpctl status` | lists it ("vivid (V4L2)") as a video source |
| A separate WirePlumber client (`wpexec`, same object manager) | sees it, with `role=Camera` |
| The guest's own systemd user session | streaming it by name fails with "target not found" too, so it is not the hand-started stack |
| Audio in that session | a stream links automatically to WirePlumber's own fallback sink, so WirePlumber-created nodes are not broken in general |
| `vivid` limited to one capture node | same result; the daemon's "can't create node: No such file or directory" disappears, so it came from vivid's other devices |
| WirePlumber 0.5.19 built from source in the guest | its V4L2 monitor starts but created no node in that ad-hoc install, so it neither confirms nor refutes a fix |
| WirePlumber 0.5.19 source | the portal script was rewritten around a permission-manager API but reads the same `devices/camera` table and `Camera` role (read) |

Reading: the node reaches the registry and other clients but not the main WirePlumber process's object managers, which
both its linking policy and its portal script use.

**Explained on 2026-11-13** (`debian-compositors`: PipeWire 1.4.2, WirePlumber 0.5.8; `ubuntu-compositors`: PipeWire 1.6.2,
WirePlumber 0.5.13, same result; `vivid` with `n_devs=1 node_types=0x1`):

| Step | Observation |
|---|---|
| WirePlumber's log at debug level when the node appears | `enum params id:2 (Spa:Enum:ParamId:Props) failed` (res -22), then `proxy activation failed: Object activation aborted` in each of its object managers |
| The node's parameters (`pw-cli info`) | `Props` is declared readable (`rw`), but enumerating it returns nothing; `PropInfo` lists 56 controls, `EnumFormat` works |
| PipeWire 1.4.2's V4L2 plugin (source read) | `Props` calls `spa_v4l2_update_controls`, which reads every INTEGER, BOOLEAN and MENU control with `VIDIOC_G_CTRL` and fails the whole parameter on any error but EACCES; the controls are enumerated with `VIDIOC_QUERY_EXT_CTRL` and `NEXT_COMPOUND`, so array controls are included |
| `vivid`'s controls | `s32_2_element_array` (0x0098f90f) is of type INTEGER with `dims=[2]`, `has-payload`; `VIDIOC_G_CTRL` on it fails with EINVAL (an ordinary control, brightness, reads fine); the 52 non-array INTEGER, BOOLEAN and MENU controls all read |
| `no_error_inj=1` (removes most buttons) | no change, as expected: buttons are skipped anyway |
| Stream by name (`gst-launch-1.0 pipewiresrc target-object=v4l2_input.platform-vivid.0`) | WirePlumber: `target not found`, the stream is destroyed: with no activation there is no `node-added` event and no session item to link to |
| PipeWire upstream | `6734d69c` (2026-08-24, "do not expose compound controls as props", skips `V4L2_CTRL_FLAG_HAS_PAYLOAD`) and `919de4c5` (2026-09-02, "keep reading the other controls when one cannot be read"); in no release yet (2026-11-13); 1.6.2's `spa_v4l2_update_controls` is the same as 1.4.2's |

So the missing node is an artefact of the test camera with these PipeWire releases, not of WirePlumber or appjail. An
ordinary webcam (UVC) has no INTEGER array controls, so its node would be activated; a real camera through the portal is
still a manual check. `vimc`, another virtual camera without such controls, is not in Debian's kernel.

## Playback (`audio`, `audio_mode = pipewire`)

| Claim | Evidence | Status |
|---|---|---|
| Sound from the jail reaches the host speaker | tone recorded from the speaker's monitor, peak above 3000, for a Pulse client (`paplay`) and a native client (`pw-cat`) | measured |
| The app sees only the tunnel nodes | `pw-dump` in the jail: `app-speaker` (plus `app-mic` with `mic`); no host device, no camera, even with `vivid` loaded | measured |
| Pulse-only apps work | a private `pipewire-pulse` socket bound as the app's Pulse socket | measured |
| The daemons can be jailed | no network; runtime directory, read-only config and the host Pulse socket only; no `/dev/video*`, `/dev/snd` or `/sys` device tree in it | measured |
| Cost and cleanup | about 36 MiB resident; the socket is ready in about 0.12 s; killing the jail's init removes all daemons | measured |
| The host shows the app's name | stream "Tunnel for user@HOSTNAME" with client name "PipeWire"; the jail's hostname carries the app name. `PULSE_PROP` does not change the client name | measured |
| Survives a restart of the host's audio server | no: the tunnel did not reconnect in 15 s | measured, limitation |
| Latency, two apps at once | not tested | not done |
| PulseAudio host without `pipewire-pulse` | the private graph is unavailable and the fallback refuses the PulseAudio server: no audio, with or without `mic` (`tests/test_pulseaudio.py`; checked once with the package removed) | measured |

## Microphone (`mic`)

| Claim | Evidence | Status |
|---|---|---|
| With `mic`, apps record the host microphone | native `pw-record` and Pulse `parec` captured the host tone, peak above 1000 | measured |
| Without `mic`, no host audio is recordable | no source tunnel: `pw-record` falls back to the private sink's monitor and records peak 0 | measured |
| A Pulse filtering proxy can enforce it | it denied `parec`, but a client could still load modules and mute the host microphone (a denylist); rejected | measured, branch `exp/audio-pulse-proxy` |
| `mic = false` is enforceable on the host Pulse socket | cannot be: the socket always includes capture | design |
| A real microphone, the desktop's privacy indicator | not tested | not done |

## Device changes in `pipewire` mode

Measured on the real graph with `pw-link` (`pactl` shows only one source per stream and hides the second link), with a null
sink standing in for a headset. Naming the devices in the tunnel's configuration gave identical results: the host's
WirePlumber policy acts on the tunnel's streams.

| Step | Where the tunnel is linked |
|---|---|
| Start | microphone `host-mic`, playback `host-speaker` |
| Headset plugged, not the default | unchanged |
| Default sink becomes the headset | playback on both the speaker and the headset |
| Default source becomes the headset | microphone from both the old microphone and the headset (mixed) |
| Headset unplugged | its links disappear; the old device's links stay |
| Headset plugged again | nothing re-attaches |
| The headset was the only device at start, then unplugged | no links at all: silent playback and microphone, the app is not told (its graph is unchanged) |
| Recreating the tunnel | destroying the module globals from outside did nothing; a long-lived `pw-cli` session could unload them, but `pw-cli` segfaulted doing so (PipeWire 1.4.2) |

## Checks that need a real machine

1. GNOME and KDE: the Camera and ScreenCast portal dialogs for a jailed app, and that revoking in the desktop's privacy settings takes effect.
2. A real USB webcam with `camera`: which nodes appear, `v4l2-ctl --all`, a capture, a browser or video-call app.
3. A real microphone and headset with the private graph: the app records the default input; the desktop's microphone indicator; changing the default input; restarting the audio server.
4. The Camera portal with a real webcam: does the portal list it and does automatic linking work?
5. PipeWire and WirePlumber versions on Ubuntu 26.04 against the findings above (the tables were measured on PipeWire 1.4.2
   and WirePlumber 0.5.8; the private-graph tests also pass on the Ubuntu guest, PipeWire 1.6).

## Experiment branches (deleted)

Built from `main` at `4eb5134`; each held the code and tests of one experiment. The product code was re-done on
`camera-permission`, `audio-mic-mode` and `audio-private-graph` (merged). The branches were deleted from `origin` on
2026-11-11 and no local copy was kept; the tips are listed so a clone that still has them can find them
(`git branch exp/... <tip>`), and what they showed is in the tables above.

| Branch | Tip | Holds |
|---|---|---|
| `exp/camera-v4l2` | `07db4ba` | broad V4L2 bind (round 1) |
| `exp/camera-v4l2-narrow` | `1ad8a56` | capture-node filter, narrow sysfs, real frame as PNG, `png_info` |
| `exp/camera-portal` | `8809188` | Camera portal restricted remote, fake Access backend, registry bridge |
| `exp/screencast-portal` | `3c7c0c2` | portal frames, ScreenCast handshake with a fake backend, `grim`, X11 probe, `link_stream_when_ready` |
| `exp/audio-private-pipewire` | `b4b698d` | first private-graph prototype, `mic`/`audio` split, defaults, headset and unplug observations, playback and mic tests |
| `exp/audio-pulse-proxy` | `fcd4573` | the Pulse protocol proxy prototype (rejected) |

To rerun an experiment: check out the branch, start the guest (`tests/vm/start.sh`), `tests/vm/provision.sh`, then for
example `tests/vm/sync.sh && tests/vm/ssh.sh 'cd ~/appjail && APPJAIL_INTEGRATION=1 python3 -m pytest tests/test_camera_portal.py -q'`.
The camera tests load `vivid` with `sudo modprobe` inside the guest.
