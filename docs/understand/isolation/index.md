# Isolation

When you start an app with `appjail run`, it does not run as an ordinary process of your session. appjail builds a
*jail* around it: a set of restrictions that the Linux kernel enforces on the app and on every process it starts. This
part explains what the jail is made of, layer by layer, and why each layer is there.

The same construction, with less inside it, also holds the steps that come before an app ever runs: the download, the
extraction of the AppImage, the verification of an attestation, the conversion of an icon. Those are the *helper jails*;
the jail the app itself runs in is the *app jail*.

## The layers

<figure markdown="span">
<svg viewBox="0 0 720 390" role="img" aria-labelledby="layers-title layers-desc" style="max-width:100%;height:auto;font-family:inherit">
  <title id="layers-title">The layers of the app jail</title>
  <desc id="layers-desc">The app runs inside its own namespaces, which show it a read-only system, its tree, a private home and
  a window. Around them, seccomp and Landlock restrict what the kernel does for it. Grants are the only openings, each through
  a narrow channel.</desc>
  <style>
    .lj-box { fill: none; stroke: var(--md-default-fg-color--light, #888); stroke-width: 1.5; }
    .lj-band { fill: var(--md-code-bg-color, #f5f5f5); stroke: var(--md-default-fg-color--lighter, #bbb); }
    .lj-in { fill: var(--md-default-bg-color, #fff); stroke: var(--md-accent-fg-color, #526cfe); stroke-width: 1.2; }
    .lj-t { fill: var(--md-default-fg-color, #222); font-size: 14px; }
    .lj-s { fill: var(--md-default-fg-color--light, #555); font-size: 12px; }
    .lj-h { fill: var(--md-default-fg-color, #222); font-size: 15px; font-weight: 700; }
    .lj-door { stroke: var(--md-accent-fg-color, #526cfe); stroke-width: 1.5; fill: none; stroke-dasharray: 4 3; }
  </style>
  <rect class="lj-band" x="10" y="10" width="470" height="370" rx="10"/>
  <text class="lj-h" x="26" y="36">Kernel restrictions</text>
  <text class="lj-s" x="26" y="56">no capabilities · seccomp filter · Landlock scope · no nested namespaces</text>
  <rect class="lj-box" x="30" y="72" width="430" height="290" rx="8"/>
  <text class="lj-h" x="46" y="98">Namespaces (bubblewrap)</text>
  <text class="lj-s" x="46" y="118">own mounts, processes, users, hostname, IPC, cgroup and network</text>
  <rect class="lj-in" x="50" y="134" width="190" height="52" rx="6"/>
  <text class="lj-t" x="62" y="156">/usr, /lib, …</text>
  <text class="lj-s" x="62" y="175">host system, read-only</text>
  <rect class="lj-in" x="250" y="134" width="190" height="52" rx="6"/>
  <text class="lj-t" x="262" y="156">/app</text>
  <text class="lj-s" x="262" y="175">the extracted AppImage, read-only</text>
  <rect class="lj-in" x="50" y="196" width="190" height="52" rx="6"/>
  <text class="lj-t" x="62" y="218">/home/app</text>
  <text class="lj-s" x="62" y="237">private home, kept between runs</text>
  <rect class="lj-in" x="250" y="196" width="190" height="52" rx="6"/>
  <text class="lj-t" x="262" y="218">/tmp, /run, /dev</text>
  <text class="lj-s" x="262" y="237">empty or minimal, private</text>
  <rect class="lj-in" x="50" y="258" width="390" height="88" rx="6"/>
  <text class="lj-t" x="62" y="282">The app and every process it starts</text>
  <text class="lj-s" x="62" y="302">a generated /etc/passwd, a cleared environment,</text>
  <text class="lj-s" x="62" y="320">a Wayland socket that offers no privileged interface</text>
  <text class="lj-h" x="520" y="36">Grants</text>
  <text class="lj-s" x="520" y="56">each through its own channel</text>
  <text class="lj-t" x="520" y="96">folders and files</text>
  <text class="lj-t" x="520" y="132">network (pasta)</text>
  <text class="lj-t" x="520" y="168">D-Bus (filtering proxy)</text>
  <text class="lj-t" x="520" y="204">portals</text>
  <text class="lj-t" x="520" y="240">audio (private graph)</text>
  <text class="lj-t" x="520" y="276">GPU, camera</text>
  <text class="lj-t" x="520" y="312">more of the display</text>
  <path class="lj-door" d="M440 300 C 480 300, 480 92, 512 92"/>
  <path class="lj-door" d="M440 304 C 485 304, 485 128, 512 128"/>
  <path class="lj-door" d="M440 308 C 490 308, 490 164, 512 164"/>
  <path class="lj-door" d="M440 312 C 495 312, 495 200, 512 200"/>
  <path class="lj-door" d="M440 316 C 500 316, 500 236, 512 236"/>
  <path class="lj-door" d="M440 320 C 500 320, 500 272, 512 272"/>
  <path class="lj-door" d="M440 324 C 500 324, 500 308, 512 308"/>
</svg>
<figcaption>The app jail. The grants on the right exist only when the manifest asks for them.</figcaption>
</figure>

Read from the inside out:

1. **[Namespaces](namespaces.md)** give the app its own view of the system: its own mount table, process list, user
   ids, hostname, inter-process communication and network. What it does not see, it cannot reach by name.
2. **[bubblewrap](bubblewrap.md)** is the program that creates those namespaces without root and fills the new mount
   table with exactly what the app should see.
3. **[The filesystem view](filesystem.md)** is what appjail asks bubblewrap to put there: the read-only system, the
   app's own tree, a private home, and the folders and files you grant.
4. **[seccomp](seccomp.md)** limits which requests the app may make to the kernel at all, because a namespace hides
   things but every system call still reaches the same kernel.
5. **[Landlock](landlock.md)** closes one gap the namespaces leave open in one configuration: sockets that live in the
   network namespace rather than in the filesystem.
6. **[Process lifetime](lifetime.md)** makes sure the jail ends when the app ends, and that nothing of it keeps running
   when appjail is stopped.

## Why several layers

A namespace decides what a process can *see*; it does not change what the kernel will *do* for it. A process that sees
nothing can still ask the kernel for a new namespace, load a filter, open a socket of an obscure family or call into a
subsystem with a history of privilege-escalation bugs. Each of those requests reaches the same kernel that runs the rest
of your session. That is why the namespaces are combined with the removal of every capability, a seccomp filter on
system calls, the refusal of nested namespaces, and Landlock: each closes a way around the others.

None of the layers is new. Flatpak builds its sandbox from the same parts, and appjail follows its choices where they
apply (the seccomp deny list, the allowed socket families). What differs is what goes *in*: appjail starts with less
(no session bus, no sound, no network, no GPU by default) and checks the openings it makes more closely, because it
has to assume that what runs inside was never reviewed by anyone.

## Helper jails

The helper jails are built from the same parts, with even less inside:

| Helper jail | Sees | Network |
|---|---|---|
| download (also catalogs and pinned tools) | the read-only system, `/etc/ssl`, the downloader, one staging directory | a private namespace made by `pasta`, or the host's with a warning when `pasta` is missing |
| attestation check | the downloaded file, the attestation bundles, a scratch directory, the pinned `gh` | as the download |
| extraction | the AppImage (read-only) and one work directory | none |
| manifest history (`git`) | appjail's configuration directory | none |
| icon conversion | the SVG and an output directory | none |
| D-Bus proxy | your session bus socket and a private directory for the filtered one | none |
| private audio graph | its own runtime directory and your audio server's socket | none |

Each helper jail also refuses nested namespaces and loads the same seccomp filter as the app jail, because some of them
run code taken from the AppImage (the extraction fallback runs the AppImage's own runtime) and all of them parse
untrusted data.

## References

- Flatpak documentation, [Sandbox permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html): the
  sandbox appjail's construction is closest to.
- Michael Kerrisk, [Namespaces in operation, part 1](https://lwn.net/Articles/531114/), LWN.net, 2013: an introduction
  to the namespaces the jail is built from.
