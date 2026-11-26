# Camera: the capture nodes only

*Decision on [desktop access](index.md).*

**Context.** Apps reach a camera in two ways: by opening `/dev/video*` themselves (V4L2), or through PipeWire. PipeWire
cannot hide a camera from a jailed client (see [A private audio graph per app](audio-graph.md)), so for apps that open
the device, binding the device is the only path that works.

**Decision.** `camera` binds only the `/dev/video*` nodes whose driver reports video capture, and for each only its own
`/sys` directory (read-only, with the `/sys/dev/char` link that tools follow to identify it). Video output, metadata
and codec nodes and the media controller stay out. A first version bound every video node and the whole of
`/sys/devices`; capture needs neither. Apps that use PipeWire for the camera (browsers) use the Camera portal instead,
which needs no device in the jail.

**Consequences.** Every capture device present at start is visible: there is no per-camera choice, and a camera plugged
in later appears at the next start. The nodes are opened briefly at every start to ask the driver what they are. Tested
with the `vivid` virtual camera (frames through GStreamer and raw ioctls, one camera, two, none); not yet with a real
USB webcam, whose sysfs path is deeper, nor with hot-unplugging. Through the portal, the test camera's node becomes
usable only from PipeWire 1.6.9, which fixed a bug with one of its test controls (Debian 13 and Ubuntu 26.04 ship older
versions); an ordinary webcam has no such control, so a real camera through the portal remains a manual check. The
measurements are on [Camera and audio measurements](../../develop/camera-audio-evidence.md).

**Known limit.** The nodes are bound over placeholder files in bwrap's tmpfs `/dev`, so listing `/dev` reports them as
regular files. Apps that enumerate `/dev` by file type (Webcamoid's V4L2 plugin) find no camera, though opening by path
works. Rejected: binding the host's `/dev` whole (every device, including input and sound nodes, becomes visible; the
narrow bind is the point of this decision) and masking everything else in it (a deny list that new devices escape). The
Camera portal is no substitute: it hands a PipeWire connection to apps that ask for it, and these apps do not. The cure
is in the app, which should open or `stat` the nodes instead of trusting the listing.

The Camera portal path is tested with `vivid`'s V4L2 node (a virtual camera) where PipeWire can read the test
camera's controls (Fedora 45, PipeWire 1.6.11): the session manager links it and an app in its jail receives a frame
through the portal ([measurements](../../develop/camera-audio-evidence.md#fedora-45-measured-2026-11-14)).

**Revisit when** a real webcam shows a missing sysfs attribute, or per-camera selection is wanted. The fault that skips
the portal camera test on Debian 13 and Ubuntu 26.04 is fixed in PipeWire 1.6.9, which their stable releases do not
ship; the test runs by itself on a guest with that PipeWire, and nothing is waited for.
