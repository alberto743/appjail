# SEED: file the approved upstream reports

This is the briefing for a session (or a person) that files the reports in `upstream-reports/reports/` after the
maintainer has reviewed them. Read `README.md` first, then `CLAUDE.md` at the repository root (its hard rules apply: the
host runs nothing but git and the editor; the reproductions run in the guests; commits stay local until the maintainer
asks to push).

## Preconditions

1. The report's table says `Review: approved`. Anything else (`pending`, `rejected`, `changes: ...`) is not filed. A
   change request is applied to the report first and the review asked again.
2. The maintainer is present for each post: filing is outward-facing and cannot be undone. Prepare, show, wait for a
   yes, per report.

## For each approved report, in this order

1. **Still true?** Start the guests (`tests/vm/start.sh` with `GUEST=...-compositors`) and run
   `upstream-reports/reproduce.sh NN`. If it prints `NOT REPRODUCED`, or the versions moved, stop: update the report
   (and `docs/compositor-assessment/` if the measurement changed), then ask for review again. A newer upstream release
   may have fixed it: say so in the text.
2. **Where and how.** Open the project's own pages (README, `SECURITY.md`, the contribution guide, the tracker's
   templates) and confirm the tracker and the disclosure channel. The channels were checked on 2026-11-27 (the table
   under "Targets" and each report's "Reviewer notes" name the pages read); check again that they still hold, and
   record any change under "Reviewer notes". Security-relevant
   reports (01, 04, 08) go to the private channel the project names, if it has one; the public tracker only if it says
   to. Do not put details in a public place first.
3. **Not a duplicate.** Search the tracker for the interface and symbols (`gtk_surface1`, `set_dbus_properties`,
   `wp_drm_lease_device_v1`, `xapp_shell_v1`, `layer_shell`, and so on). If an issue exists, comment on it instead, with
   the measurements.
4. **The text.** The post is the section "Issue text" of the report, as written, plus the reproduction block. Check
   that it contains no personal data (names, e-mail addresses, home paths, host names, session or chat links) and no
   promotion. One sentence on provenance is enough ("found while measuring Wayland compositors for a sandbox"). Attach a
   minimal reproducer that needs no sandbox where the report has one (`tests/compositors/focus_client.py` for 01 and 02,
   `drm_fd.py` for 03, `layer_shell.py` for 05).
5. **Show it, then hand over the command.** Print the final title and body to the maintainer. For a GitHub tracker,
   give the exact `gh issue create --repo OWNER/REPO --title ... --body-file ...` for the maintainer to run
   (`! gh ...`); for GitLab and Bugzilla, give the text to paste. Claude does not post from the host (CLAUDE.md: no
   network use outside the guests) and has no credentials.
6. **Record it.** When the maintainer gives the URL, set `Filed: <URL> (<date>)` in the report's table and in the index
   of `README.md`, and commit on this branch with a message that names the report and contains no link to a session.

## Order

Reports 01, 04 and 08 first (their drafts are public on this branch, and the details of 01 also in `main`), through
the security contacts; then 02, 03, 05, 06, 07, 09, then 10 and 12; 11 only if the maintainer decides to file it at
all.

## Targets (checked 2026-11-27, from the guest)

| Report | Where | What the project says (page read) |
|---|---|---|
| 01 Mutter | the security report form of `security.gnome.org`, which opens a confidential issue on GNOME's GitLab | all security bugs through that form; confidential until a fix is committed or 90 days pass, no embargoes (`security.gnome.org`; Mutter and GNOME Shell have no `SECURITY.md`) |
| 01 Muffin | `github.com/linuxmint/muffin`, public issue | no security policy found (no `SECURITY.md` in muffin, cinnamon or linuxmint/.github; GitHub's private reporting is off for muffin and cinnamon); the details of 01 are public already |
| 02, 03 | `gitlab.gnome.org/GNOME/gnome-shell`, `gitlab.gnome.org/GNOME/mutter`, public issues | GNOME Shell's README sends bugs to its issue tracker |
| 04 | `security@kde.org` for the clipboard read on 6.3 and 6.6; `bugs.kde.org` (kwin) for the rest | `kde.org/info/security/` and `community.kde.org/Policies/Security_Policy`: findings about KDE software to `security@kde.org`, handled discreetly |
| 05, 06, 07 | `github.com/linuxmint/cinnamon`, `github.com/linuxmint/muffin`, public issues | as 01 Muffin |
| 08 | the Ubuntu Security Team: a private security bug on Launchpad (package `hyprland`) or `security@ubuntu.com` | Hyprland's `SECURITY.md` supports only the latest release (0.57.2, 2026-11-09) and lets users open no issues (a Discussion instead); 0.53.3 is what Ubuntu 26.04 ships, so Ubuntu is the party that can fix it (`ubuntu.com/security/disclosure-policy`) |
| 09 | a Launchpad bug on Ubuntu's `hyprland`, public | Hyprland's `SECURITY.md` lists crashes as not security issues, and supports only the latest release |
| 10 | Weston only, if at all: `gitlab.freedesktop.org/wayland/weston` | Wayfire 0.11.0 (2026-07-27) has `security-context-v1` (PR #2828); Cage's maintainer wrote in cage#505 that `wp_security_context_v1` "should be enough" to secure a socket; Weston's #206 (a security context implementation) was closed on 2024-08-01, reason not read |
| 12 | `gitlab.freedesktop.org/wayland/wayland-protocols`: a comment on #294, or a new issue that links #294, #207 and #56 | related open issues: #294 (list the privileged protocols), #207 (expose chosen privileged globals to a context), #56 (security considerations of protocols) |

## What this session must not do

* Post a security report (01, 04, 08) in a public tracker when the project names a private channel. The drafts are
  public on this branch already; the report itself still goes where the project asks, and says the draft is public.
* Claim more than was measured. The reports say what was read in the source only and what was not tried; keep it so.
* File a report that is not `approved`, or file it in more than one place at once.
* Add personal data, session links, or a `Claude-Session:` line to a report, a commit or an issue.
