# Writing the documentation

The site is written in Markdown under `docs/` and built with [Zensical](https://zensical.org/) from `zensical.toml`.
It is a single connected text: every page says where it sits in the argument, and links backward and forward.

## Building

```sh
tests/vm/docs.sh                # builds in the guest, strict; the result is in vm/<guest>/site
```

The build is strict: a link to a missing page or anchor fails it. The tooling is pinned with hashes in
`.github/requirements-docs.txt` and never becomes a dependency of appjail. The site loads nothing from other servers:
no web fonts, no CDN scripts, no emoji images, no maths renderer; keep it that way (diagrams are inline SVG).

An inline SVG goes in a plain `<figure>` (no `markdown` attribute), with no blank line inside it and its `<desc>` on one
line: Markdown processing would otherwise insert a `<br />`, and a `<br>` inside SVG makes the browser close the SVG,
so nothing is drawn. Colours come from the theme's CSS variables, so the diagram follows light and dark mode.

The logo in `docs/assets/` is a copy of `assets/logo-light.svg` (`logo.svg`, used in the header and on light pages) and
`assets/logo-dark.svg`; the colours in `docs/stylesheets/appjail.css` are the logo's. Change them together.

## Structure

| Section | Holds | Tense and voice |
|---|---|---|
| Understanding appjail | the problem, the principles, and one page per concept, by topic | present tense, explanatory |
| Guide | tasks: what to type and what it does | imperative, short |
| Decisions | one page per decision: context, options, decision, consequences, revisit when | past tense for what was measured, present for the decision |
| Reference | exact lists: commands, options, keys, values | tables |
| Development | how to work on appjail | |

Every concept page has the same headings: **What it is**, **Why it matters**, **How appjail uses it**, **Connections**,
**Limits**, **References**. A new grant, mechanism or external tool needs its concept page, or a section in one, in
the same change as the code.

## Terminology

One term per idea, used everywhere.

| Term | Meaning | Notes |
|---|---|---|
| **jail** | a bubblewrap sandbox started by appjail | "sandbox" is fine once, for a reader who does not know the word "jail" yet |
| **app jail** / **helper jail** | the jail an app runs in / a jail for one step (download, extraction, git, icon, proxy, audio daemons) | "network-only jail" = the download helper jail; keep that name for it only |
| **grant** (noun and verb) / **permission** | permission = the manifest key; grant = what the user gives | keep both, defined once |
| **evidence tier** | 1-5 | not "trust tier" |
| **source** | where an app comes from (`kind:target`) | also used for **index source**: say "index source" for catalogs |
| **catalog** / **index** | catalog = one JSON document; index = the local set of sources and their snapshots | keep them apart |
| **candidate** | a release not yet installed that `update` found | |
| **quarantine** | the delay before a candidate may be installed | |
| **pin** | the recorded hash, owner id, version and channel | "pinned" is also a channel value; say "pinned channel" for that |
| **registry rule** | the Wayland check on the app's socket | the measurement tools call it "rule A" |
| **confined service** | a D-Bus name with `--call` rules | |
| **private graph** | the per-app PipeWire instance | also "private audio graph" |

## References

Cite primary sources only: specifications, manual pages, kernel documentation, upstream project documentation, and
advisories or measurements where they motivated a choice. Open every link before citing it (from the guest), and
re-check the references, and [related projects](../decisions/project/related-projects.md) with its date, at each minor
release.

## What the tests check

`tests/test_docs.py` fails when a command or option of the parser is missing from
[the command reference](../reference/commands.md), when a page is missing from the navigation in `zensical.toml` (or
the navigation names a page that does not exist), when a concept page under `understand/` lacks one of the six headings
or a reference link, and when [the policy lists](../reference/policy.md) no longer match the source; regenerate those
with `python3 tests/policy_tables.py --write` in the guest. `tests/test_assessment.py` does the same for the compositor
assessment's tables. The strict build catches broken links and anchors.

## The outline

The navigation in `zensical.toml` is the outline of the site. Keep the order of the topics the same in "Understanding
appjail" and "Decisions" (acquisition, isolation, desktop access, updates, catalog), and put a new page where a reader
following the argument would look for it.
