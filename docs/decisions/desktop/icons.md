# Icons rewritten, not decoded

*Decision on [desktop access](index.md).*

**Context.** The menu shows the app's icon, which the desktop shell and the file manager decode outside any jail. A
crafted image is a known way to attack image loaders. A security review suggested re-encoding icons in a jail.

**Options.** Re-encode in a jail with an image tool; rewrite the file's structure without decoding it.

**Decision.** appjail rewrites each PNG icon with its own standard-library code (`pngclean.py`): every chunk and checksum
is checked, the image data is inflated to exactly the size its header promises (with a hard limit), and a new file is
written with only the essential chunks (`IHDR`, `PLTE`, `tRNS`, `IDAT`, `IEND`). No pixel is interpreted. A file that
does not fit is refused, not repaired. An SVG icon is first rendered to PNG by `rsvg-convert` in a jail with no
network, and the result goes through the same rewrite; the host never decodes the SVG.

**Why not a jail for PNG.** It would need an image tool that is not a dependency, and that tool would itself decode the
untrusted file. The rewrite removes what crafted icons rely on: malformed structure, text and profile chunks, trailing
bytes, oversized data.

**Consequences.** A loader bug triggered by the pixel values of a well-formed image is not removed.

**Revisit when** a tool that decodes and re-encodes safely is already a dependency.
