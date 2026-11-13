# Nothing granted by default

*Decision on [isolation](index.md).*

**Context.** Early versions granted sound and the GPU at install, while the documentation said everything was denied.
Sound, through the host's Pulse socket, also meant the microphone and the sound of other apps; the GPU is a large driver
attack surface and exposes hardware details through `/sys`. Most command-line tools, converters and editors need
neither.

**Options.** Keep sound and GPU on for convenience; infer what an app needs from its own menu entry (untrusted data may
only ever *reduce* permissions); grant nothing but the window.

**Decision.** `add` grants only the window. Sound, microphone, GPU and the rest are explicit grants, and an app with no
window at all can be given `display = none`, chosen by you, never inferred.

**Consequences.** Installing a media or Electron app takes one more option. A missing grant fails visibly (no sound,
slow rendering) and is fixed with `perms APP --allow ...`; an unneeded grant fails silently. Apps installed before the
change keep the grants recorded in their manifests.

**Revisit when** the audio defaults change.
