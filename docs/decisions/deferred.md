# Deferred and planned work

What has been decided *not yet*, with the reason and the condition for taking it up. Each item has its full reasoning
on the decision page linked.

## Planned code work

None pending.

## Deferred features

| Feature | Why not now | Revisit when | Reasoning |
|---|---|---|---|
| GPG tier (tier 2) | a signature proves a key, not its owner; it needs a per-app key pin, a jailed `gpgv` and update rules, while attestations and the quarantine hash already cover attested and unattested apps | a wanted app signs with GPG and has no attestation | [evidence tiers](acquisition/evidence-tiers.md) |
| Resolvers for other forges (GitLab, Codeberg/Forgejo, SourceForge, vendor sites) | only GitHub is supported; other forges offer no per-asset digest or attestations, so tier 4 at best. The catalog lists 13 apps on GitLab or Forgejo and about 180 pointing to vendor sites | a wanted app is released only on another forge | [sources](acquisition/sources.md) |
| An allowlisting proxy for the LAN | with `network`, other hosts on the LAN stay reachable; attacks on them are outside the threat model | host filtering for `network` is wanted | [network](desktop/network.md) |
| Other architectures (arm64) | evaluated and **paused** by the maintainer: moderate code, expensive verification | the arm64 work is resumed | [platform](project/platform.md) |

## Scheduled

| When | What |
|---|---|
| December 2026 | Switch the workflows from `ubuntu-26.04` to `ubuntu-latest` once GitHub's move completes (planned to end 2026-11-19), and check CI ([workflows](project/workflows.md)). |
| Each minor release | Re-check the facts on [related projects](project/related-projects.md) and the references cited on the concept pages. |

## Not yet verified

Checks that need hardware, a desktop session or a network the test guests do not have. They are manual checks on a real
machine.

- Portals: the GNOME and KDE backends and their interactive dialogs (only the GTK backend is tested).
- Camera: a real V4L2 webcam, unplugging while the app runs, and a real camera through the Camera portal.
- Xwayland: GPU acceleration; clipboard and drag and drop through the `xwayland-rootful` window (briefly tested on
  GNOME).
- D-Bus: real MPRIS players and tray icons with process-id names.
- Audio: a real headset and microphone; two apps at once.
- Network: IPv6 over a real internet route (tested only on a simulated network).
