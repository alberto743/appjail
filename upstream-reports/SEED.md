# SEED: file the approved upstream reports

This is the briefing for a session (or a person) that files the reports in `upstream-reports/reports/` after the
maintainer has reviewed them. Read `README.md` first, then `CLAUDE.md` at the repository root (its hard rules apply: the
host runs nothing but git and the editor; the reproductions run in the guests; commits stay local until the maintainer
asks to push).

## Preconditions

1.  The report's table says `Review: approved`. Anything else (`pending`, `rejected`, `changes: ...`) is not filed. A
   change request is applied to the report first and the review asked again.
2.  The maintainer is present for each post: filing is outward-facing and cannot be undone. Prepare, show, wait for a
   yes, per report.

## For each approved report, in this order

1.  **Still true?** Start the guests (`tests/vm/start.sh` with `GUEST=...-compositors`) and run
   `upstream-reports/reproduce.sh NN`. If it prints `NOT REPRODUCED`, or the versions moved, stop: update the report
   (and `docs/compositor-assessment/` if the measurement changed), then ask for review again. A newer upstream release
   may have fixed it: say so in the text.
2.  **Where and how.** Open the project's own pages (README, `SECURITY.md`, the contribution guide, the tracker's
   templates) and confirm the tracker and the disclosure channel. The channels written in the reports are suggestions
   that were not opened and checked: for each, record the page you read under "Reviewer notes". Security-relevant
   reports (01, 04, 08) go to the private channel the project names, if it has one; the public tracker only if it says
   to. Do not put details in a public place first.
3.  **Not a duplicate.** Search the tracker for the interface and symbols (`gtk_surface1`, `set_dbus_properties`,
   `wp_drm_lease_device_v1`, `xapp_shell_v1`, `layer_shell`, and so on). If an issue exists, comment on it instead, with
   the measurements.
4.  **The text.** The post is the section "Issue text" of the report, as written, plus the reproduction block. Check
   that it contains no personal data (names, e-mail addresses, home paths, host names, session or chat links) and no
   promotion. One sentence on provenance is enough ("found while measuring Wayland compositors for a sandbox"). Attach a
   minimal reproducer that needs no sandbox where the report has one (`tests/compositors/focus_client.py` for 01 and 02,
   `drm_fd.py` for 03, `layer_shell.py` for 05).
5.  **Show it, then hand over the command.** Print the final title and body to the maintainer. For a GitHub tracker,
   give the exact `gh issue create --repo OWNER/REPO --title ... --body-file ...` for the maintainer to run
   (`! gh ...`); for GitLab and Bugzilla, give the text to paste. Claude does not post from the host (CLAUDE.md: no
   network use outside the guests) and has no credentials.
6.  **Record it.** When the maintainer gives the URL, set `Filed: <URL> (<date>)` in the report's table and in the index
   of `README.md`, and commit on this branch with a message that names the report and contains no link to a session.

## Order

Report 01 first (its details are already public in `main`). Then 04 and 08 (security contacts), then 02, 03, 05, 06, 07,
09, then 10 and 12; 11 only if the maintainer decides to file it at all.

## Targets (suggestions: verify each before use)

| Report | Tracker | Disclosure |
|---|---|---|
| 01 Mutter | `gitlab.gnome.org/GNOME/mutter` | GNOME's confidential issue or the security contact in its policy |
| 01 Muffin | `github.com/linuxmint/muffin` | a public issue, or what its policy says |
| 02 | `gitlab.gnome.org/GNOME/gnome-shell` | public |
| 03 | `gitlab.gnome.org/GNOME/mutter` | public |
| 04 | `bugs.kde.org` (kwin, plasmashell) | the KDE security contact for the clipboard read on 6.3 and 6.6 |
| 05, 06, 07 | `github.com/linuxmint/cinnamon`, `github.com/linuxmint/muffin` | public |
| 08, 09 | `github.com/hyprwm/Hyprland` | its security advisories, if it has them |
| 10 | `github.com/WayfireWM/wayfire`, `github.com/cage-kiosk/cage`, `gitlab.freedesktop.org/wayland/weston` | public |
| 12 | `gitlab.freedesktop.org/wayland/wayland-protocols` | public |

## What this session must not do

*  Push this branch, or any of its content, to the public `origin` before the security reports are filed and the
  maintainers have had a reasonable time to answer (the project's own embargo, if it states one).
*  Claim more than was measured. The reports say what was read in the source only and what was not tried; keep it so.
*  File a report that is not `approved`, or file it in more than one place at once.
*  Add personal data, session links, or a `Claude-Session:` line to a report, a commit or an issue.
