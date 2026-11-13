# GPU and camera

*Part of [Desktop access](index.md). Previous: [audio](audio.md). Next: [network](network.md).*

## What it is

Programs reach hardware through **device nodes** in `/dev`, special files that lead to a kernel driver.

- The GPU is reached through the **DRM** subsystem: `/dev/dri/card*` nodes (the display hardware, mostly for the
  compositor) and `/dev/dri/renderD*` **render nodes**, which allow rendering and computing without control of the
  display. NVIDIA's proprietary driver adds `/dev/nvidia*`. Graphics libraries also read details of the hardware in
  `/sys` and configuration for Vulkan and GLVND.
- Cameras are **V4L2** devices, `/dev/video*`. One camera often has several nodes: video capture, metadata, sometimes
  output or codec nodes; a *media controller* node (`/dev/media*`) describes how they connect. A driver tells what a node
  is through the `VIDIOC_QUERYCAP` request.

## Why it matters

A device node is a direct line to a kernel driver: each one is attack surface, and GPU drivers are large. The GPU also
reveals hardware details through `/sys`. A camera node is the camera itself, with no prompt. Many apps need neither:
most command-line tools, converters and editors render fine without a GPU.

## How appjail uses it

- **Nothing by default.** The jail has a minimal `/dev` (null, zero, random, terminal devices).
- **`gpu`** binds `/dev/dri` (card and render nodes) and `/dev/nvidia*`, and read-only `/sys/dev/char`, `/sys/devices`
  and the Vulkan and GLVND data. Your supplementary groups are kept in the jail, so group-owned render nodes stay
  usable.
- **`camera`** binds only the `/dev/video*` nodes whose driver reports video capture, and for each only its own `/sys`
  directory (read-only, with the `/sys/dev/char` link that tools follow to identify it). Output, metadata and codec nodes
  and the media controller stay out; the rest of `/sys` is absent unless `gpu` is granted too. The seccomp filter lets
  the V4L2 requests through.
- **The Camera portal** is the route for apps that reach the camera through PipeWire (browsers): `--allow portals
  --portal Camera`. No device is bound into the jail then; the portal asks you.

## Connections

- PipeWire cannot hide a camera from a client it does not recognise as sandboxed ([audio](audio.md)), which is why the
  camera is either device nodes or the portal, never the host's PipeWire.
- A webcam's microphone is an audio device, covered by `mic`, not by `camera`.
- Decision: [Camera: the capture nodes only](../../decisions/desktop/camera.md).

## Limits

- Every capture device present at start is visible; there is no per-camera choice, and a camera plugged in later appears
  at the next start.
- Tested with the kernel's `vivid` virtual camera; a real USB webcam, unplugging while the app runs, and a real camera
  through the portal are still to check.

## References

- Linux kernel documentation, [DRM userspace interface](https://docs.kernel.org/gpu/drm-uapi.html) (render nodes);
  [V4L2](https://docs.kernel.org/userspace-api/media/v4l/v4l2.html) and
  [VIDIOC_QUERYCAP](https://docs.kernel.org/userspace-api/media/v4l/vidioc-querycap.html);
  [the vivid driver](https://docs.kernel.org/admin-guide/media/vivid.html).
