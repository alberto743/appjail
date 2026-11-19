# Redirects to private addresses are refused

*Decision on [acquisition](index.md).*

**Context.** An app added with `--url`, and a catalog added with `index add --url`, are downloaded from a server you
name, which may answer with a redirect to any host. The download runs in a jail with a private network namespace, so it
cannot reach the services of your own machine; the other machines of your local network stay reachable. A server on the
internet could therefore send the download to a printer, a router or a NAS on your LAN: a request you never meant to
make, from inside your network.

**Options.** Leave it to the threat model, which keeps the LAN out of scope; refuse redirects to private addresses
always; refuse them by default, with a switch.

**Decision.** A redirect that leads to an address that is not on the public internet (private IPv4 ranges, loopback,
link-local, carrier-grade NAT, unique-local IPv6, and those addresses written as IPv6) is refused. The rule is applied
in the downloader, inside the jail, to every hop: the target's host name is resolved there, with the same DNS the
download uses. Two cases are allowed:

- the URL you gave is itself on a private address (an intranet server): redirects within your network are then what
  you asked for;
- you pass `--allow-private-redirects` (`add --url`, `update APP` for a URL app, `index add --url`, `index update`): it
  holds for that command only.

The URL you type is never judged: naming a private address yourself is your decision.

**Consequences.** An internet download that legitimately ends on a private address (a mirror inside a company network
reached through a public front) needs the switch at every update. Each connection resolves its host once, refuses it
when any address is private, and connects to an address it checked, so a redirect target cannot answer public first and
private second (DNS rebinding). Whether the URL you gave is an intranet server is decided by what its own name resolves
to, whoever answers its DNS. GitHub downloads are unaffected: they may only go to GitHub's own hosts.
