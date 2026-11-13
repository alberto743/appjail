# Manifest

One TOML file per app, `~/.config/appjail/apps/NAME.toml`, written by appjail. Why it is data only, and how it is
checked, is explained in [the manifest](../understand/acquisition/manifest.md). Unknown keys, wrong types, control
characters and malformed values make the file invalid; `name` must equal the file name.

## Top level

| Key | Applies to | Value |
|---|---|---|
| `schema` | all | `1` |
| `name` | all | `[a-z0-9][a-z0-9._-]{0,63}`, the file name without `.toml` |
| `source` | all | `github:owner/repo`, `url:https://...` (no credentials), or `file:NAME` (a base name, never a path) |
| `channel` | `github:` | `prerelease` or `pinned`; omitted means `stable`. URL and file apps accept only `stable` |
| `asset_pattern` | `github:` | the file-name pattern (`fnmatch`, no `/`) that selects the release asset |
| `owner_id` | `github:` | the numeric GitHub account id of the repository's owner |
| `fingerprint` | `url:` | table: `size`, `etag`, `last_modified`, `chunks` (what the server said, and a hash of sampled windows) |
| `version` | all | the release tag; for URL and file apps `sha256:` plus 12 hex digits |
| `sha256` | all | the pinned hash of the AppImage, 64 lowercase hex digits |
| `evidence_tier` | all | 1 to 5 ([evidence tiers](../understand/acquisition/evidence.md)) |
| `published_at` | all | UTC `YYYY-MM-DDTHH:MM:SSZ`: the release's publication, or the install time for URL and file apps |

## `[permissions]`

Optional; every key defaults to denied. The writer always writes `network`, `audio`, `gpu`, `portals` and `userns`, and
the other switches only when true. Each key is described in the [permission reference](permissions.md).

| Key | Type |
|---|---|
| `network`, `network_host`, `audio`, `mic`, `gpu`, `camera`, `portals`, `userns`, `linger`, `full_wayland` | boolean |
| `audio_mode` | `"pipewire"` (default, not written) or `"pulse"` |
| `display` | `"wayland"` (default), `"xwayland"`, `"xwayland-rootful"`, `"none"` |
| `display_size` | `"WxH"`, each side 320 to 8192; written only when not `1280x800` |
| `dirs` | list of absolute or `~/` paths, each optionally `:ro` or `:rw` |
| `dbus_filter`, `dbus_own` | lists of D-Bus names, optionally ending in `.*` |
| `portal_interfaces` | list of opt-in portal interface names (needs `portals = true`) |

Consistency rules: `network_host` needs `network`, `mic` needs `audio`, `portal_interfaces` needs `portals`.

## Examples

A GitHub app:

```toml
schema = 1
name = "lagrange"
source = "github:skyjake/lagrange"
asset_pattern = "lagrange-*-x86_64.appimage"
owner_id = 1234567
version = "v1.18.5"
sha256 = "1ccdd4decb469fb4c1a77ad0e4b4f6c6e6d1c9f34a8b1e20d5a9c3f7e2b0d841"
evidence_tier = 3
published_at = "2026-10-01T09:12:44Z"

[permissions]
network = true
audio = false
gpu = false
portals = false
userns = false
```

A URL app:

```toml
schema = 1
name = "tool"
source = "url:https://example.org/dl/Tool-x86_64.AppImage"
version = "sha256:1ccdd4decb46"
sha256 = "1ccdd4decb469fb4c1a77ad0e4b4f6c6e6d1c9f34a8b1e20d5a9c3f7e2b0d841"
evidence_tier = 5
published_at = "2026-10-20T08:00:00Z"
fingerprint = { size = 48211968, etag = "\"abc123\"", last_modified = "Tue, 20 Oct 2026 08:00:00 GMT", chunks = "3f9ad4decb469fb4c1a77ad0e4b4f6c6e6d1c9f34a8b1e20d5a9c3f7e2b0d841" }
```
