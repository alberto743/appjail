# Acquisition

Before an app ever runs, appjail has to get it: find the release you asked for, download it, decide what is known about
who made it, unpack it, and record all of that so it can be checked again later. Every one of these steps handles bytes
and text from someone else, so each is either a check or happens in a jail. This part follows an app from the name you
type to the files on your disk.

## The path of an install

<figure>
<svg viewBox="0 0 720 470" role="img" aria-labelledby="acq-title acq-desc" style="max-width:100%;height:auto;font-family:inherit">
  <title id="acq-title">What appjail add does, step by step</title>
  <desc id="acq-desc">Review the repository, resolve the release and asset, ask, download in a jail with only a network, check size, digest and format, verify the attestation in a jail, extract in a jail without network, validate the tree, then write the pins and the manifest. Each step can stop the install.</desc>
  <style>
    .aq-host { fill: var(--md-default-bg-color, #fff); stroke: var(--md-default-fg-color--light, #777); stroke-width: 1.3; }
    .aq-jail { fill: var(--md-code-bg-color, #f2f4f7); stroke: var(--md-accent-fg-color, #0284c7); stroke-width: 1.6; stroke-dasharray: 6 3; }
    .aq-t { fill: var(--md-default-fg-color, #222); font-size: 14px; font-weight: 600; }
    .aq-s { fill: var(--md-default-fg-color--light, #555); font-size: 12px; }
    .aq-a { stroke: var(--md-default-fg-color--light, #777); stroke-width: 1.4; fill: none; marker-end: url(#aq-arrow); }
    .aq-ah { fill: var(--md-default-fg-color--light, #777); }
  </style>
  <defs><marker id="aq-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path class="aq-ah" d="M0,0 L10,5 L0,10 z"/></marker></defs>
  <rect class="aq-host" x="20" y="10" width="320" height="58" rx="8"/>
  <text class="aq-t" x="34" y="34">1. Review the repository</text>
  <text class="aq-s" x="34" y="54">owner, account id and age, stars, fork, archived</text>
  <rect class="aq-host" x="380" y="10" width="320" height="58" rx="8"/>
  <text class="aq-t" x="394" y="34">2. Resolve release and asset</text>
  <text class="aq-s" x="394" y="54">x86-64 AppImage, digest, attestation present?</text>
  <rect class="aq-host" x="380" y="98" width="320" height="58" rx="8"/>
  <text class="aq-t" x="394" y="122">3. Ask you</text>
  <text class="aq-s" x="394" y="142">nothing is downloaded before you agree</text>
  <rect class="aq-jail" x="20" y="98" width="320" height="58" rx="8"/>
  <text class="aq-t" x="34" y="122">4. Download (jail: network only)</text>
  <text class="aq-s" x="34" y="142">https, allowed hosts, stops at the size</text>
  <rect class="aq-host" x="20" y="186" width="320" height="58" rx="8"/>
  <text class="aq-t" x="34" y="210">5. Check the bytes</text>
  <text class="aq-s" x="34" y="230">size, SHA-256 against the digest, AppImage type 2</text>
  <rect class="aq-jail" x="380" y="186" width="320" height="58" rx="8"/>
  <text class="aq-t" x="394" y="210">6. Verify the attestation (jail)</text>
  <text class="aq-s" x="394" y="230">pinned gh, then the certificate re-read</text>
  <rect class="aq-jail" x="380" y="274" width="320" height="58" rx="8"/>
  <text class="aq-t" x="394" y="298">7. Extract (jail: no network)</text>
  <text class="aq-s" x="394" y="318">unsquashfs at the offset; size and time limits</text>
  <rect class="aq-host" x="20" y="274" width="320" height="58" rx="8"/>
  <text class="aq-t" x="34" y="298">8. Validate the tree</text>
  <text class="aq-s" x="34" y="318">no special files, AppRun inside, tree hashed</text>
  <rect class="aq-host" x="20" y="362" width="680" height="58" rx="8"/>
  <text class="aq-t" x="34" y="386">9. Pin and record</text>
  <text class="aq-s" x="34" y="406">image and tree hashes, evidence tier, owner id, manifest written last, history commit</text>
  <path class="aq-a" d="M340 39 H376"/>
  <path class="aq-a" d="M540 68 V94"/>
  <path class="aq-a" d="M380 127 H344"/>
  <path class="aq-a" d="M180 156 V182"/>
  <path class="aq-a" d="M340 215 H376"/>
  <path class="aq-a" d="M540 244 V270"/>
  <path class="aq-a" d="M380 303 H344"/>
  <path class="aq-a" d="M180 332 V358"/>
  <rect class="aq-jail" x="20" y="438" width="22" height="14" rx="3"/>
  <text class="aq-s" x="50" y="450">dashed: runs in a helper jail</text>
  <rect class="aq-host" x="250" y="438" width="22" height="14" rx="3"/>
  <text class="aq-s" x="280" y="450">solid: appjail itself, which never runs code from the download</text>
</svg>
<figcaption><code>appjail add owner/repo</code>. Any failed check deletes what was downloaded and writes nothing.</figcaption>
</figure>

For an app added from a URL the first two steps are replaced by the URL you give, and from a file by the file you
give; the rest is the same, without the attestation.

## The pages

1. **[The AppImage format](appimage.md)**: what is inside the file, and why appjail never runs or mounts it.
2. **[Sources and the resolver](sources.md)**: where an app may come from, and how a release and its file are chosen.
3. **[Hashes and evidence tiers](evidence.md)**: what a hash proves, what a digest adds, and how much is known about
   who built the bytes.
4. **[Build attestations](attestations.md)**: the strongest evidence, and what it does and does not prove.
5. **[Jailed download and extraction](jailed-steps.md)**: the helper jails that handle the bytes before anything is
   known about them.
6. **[Untrusted text](untrusted-text.md)**: release names, descriptions and menu entries as an attack in their own
   right.
7. **[The manifest](manifest.md)**: where the decisions end up, and why it is data only.

Every step can stop the install, and none of them is skipped silently: a check that cannot be made is reported, and the
evidence tier records what was actually verified.

The decisions behind this part are in [Decisions: acquisition](../../decisions/acquisition/index.md).
