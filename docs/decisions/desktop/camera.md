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
in later appears at the next start. The nodes are opened briefly at every start to ask the driver what they are.
Tested with the `vivid` virtual camera (frames through GStreamer and raw ioctls, one camera, two, none); not yet with a
real USB webcam, whose sysfs path is deeper, nor with hot-unplugging. Through the portal, the test camera's node never
became usable because of a PipeWire bug with one of its test controls (fixed upstream, unreleased); an ordinary webcam
has no such control, so a real camera through the portal remains a manual check.

**Revisit when** a real webcam shows a missing sysfs attribute, or per-camera selection is wanted.
