> **Status**: the "put it on Tailscale" recommendation below is now the plan
> actually being built — see `docs/HOSTING.md` for the concrete setup
> (Docker Desktop's Kubernetes instead of a rented VPS, API decoupled from
> the front end, the security checklist). This doc stays as the reasoning
> for *why* Tailscale over a public URL, and as the reference for the public
> URL path if that's ever needed later.

# Making this reachable from anywhere — design plan (not yet built)

Scope, as confirmed: **single-user remote access** (you, from your phone or
another machine, not on the same network as wherever this runs) — not a
multi-tenant public service. That distinction matters a lot: it means the
design below optimizes for "keep strangers out entirely" rather than "let
strangers in safely at scale." If that scope ever changes, most of this needs
rethinking (see "If this ever needs to be genuinely multi-user" at the end).

**Target, updated**: not a cloud VPS — a second physical PC on your own
network, hosting this via k3s (Kubernetes) with Terraform declaring the
resources. That doesn't change anything below (Tailscale/reverse-proxy/
hardening all apply the same way to a home PC as to a rented one), it just
means "the box" is one you own rather than one you rent. The k3s/Terraform
setup itself is in [infra/terraform-k8s/](../infra/terraform-k8s/README.md) —
this doc stays focused on the network/access question (how you reach it),
that one covers the orchestration question (what runs it).

## Recommended approach: put it on a private mesh network (Tailscale), don't expose it publicly at all

For "just me, from anywhere," the lowest-risk and least-work answer is to not
open this to the public internet in the first place. A mesh VPN like
[Tailscale](https://tailscale.com) (WireGuard-based, generous free tier, apps
for phone/laptop/server) puts your VPS and your other devices on a private
virtual network — you reach the VPS at a private `100.x.y.z` address that only
your own logged-in devices can see or route to. Nothing is listening on the
public internet at all, so there's no auth code to write, no TLS certificate
to manage, and no attack surface for the inevitable internet-wide scanning
bots that hit every public IP within minutes of a server going up.

**Plan:**
1. Provision a small VPS (Ubuntu 22.04+, 2GB RAM minimum — see "Sizing" below).
2. Install Docker + the Compose plugin on it.
3. Install Tailscale on the VPS (`curl -fsSL https://tailscale.com/install.sh | sh && tailscale up`) and on your phone/laptop, both joined to your own tailnet.
4. Get this repo onto the VPS (see "Getting the code there" below).
5. In `docker-compose.yml`, bind the scraper's port to the VPS's Tailscale interface (or just `127.0.0.1` and access via `tailscale serve`/`tailscale funnel` — Tailscale's own docs cover this), **not** `0.0.0.0`. Postgres and Adminer get no public port mapping at all — see "Hardening" below, this matters regardless of which approach you pick.
6. From your phone/laptop, open `http://<vps-tailscale-ip>:8000` — same app, reachable from anywhere your device has internet, invisible to everyone else.

This is genuinely the recommended option, not a placeholder — it's less setup than a reverse proxy + TLS + auth stack, and strictly more secure.

## Alternative: a real public URL (reverse proxy + auth + TLS)

If you'd rather have an actual `https://something.example.com` you can share
or hit without the Tailscale app installed, here's what that needs — all of
it, not some of it, because a public IP gets probed by bots constantly:

1. **A domain name** pointed at the VPS's IP (an A record).
2. **A reverse proxy doing automatic HTTPS.** [Caddy](https://caddyserver.com)
   is the simplest option — a ~10 line Caddyfile gets you a Let's Encrypt
   certificate with no manual renewal setup. Traefik is the other common
   choice if you want Docker-label-based config instead of a static file.
3. **Auth in front of everything**, since this is single-user: HTTP Basic
   Auth at the Caddy layer is enough (`basicauth` directive) — it protects
   the front end *and* every API route with zero changes to the FastAPI app.
   Don't skip this step reasoning "it's just me" — a public URL with no auth
   is a public URL, full stop.
4. **Firewall**: only 22 (SSH, ideally key-only + fail2ban), 80, and 443 open.
   Everything else (5432, 8081, 8000) closed to the outside — the proxy is
   the only public entry point, everything behind it talks over the internal
   Docker network.

## Hardening that applies either way

The current `docker-compose.yml` maps ports as `"8000:8000"`, `"5432:5432"`,
`"8081:8080"` — Compose's shorthand binds those to **all interfaces**
(`0.0.0.0`) by default. Run this file unmodified on a VPS with a public IP and
Postgres (default creds `apollo`/`apollo`) and Adminer (a raw DB admin UI, no
auth) are both reachable by anyone on the internet who finds the port. This
needs fixing regardless of which approach above you take:

- Change Postgres and Adminer to `"127.0.0.1:5432:5432"` and
  `"127.0.0.1:8081:8080"` (or drop their `ports:` mappings entirely and only
  reach them over SSH port-forwarding or Tailscale when you need Adminer) —
  they should never be reachable from outside the machine itself.
- Change the real Postgres password (`POSTGRES_PASSWORD` in `.env`) from the
  local-dev default before this touches a real network.
- Keep `.env` off of whatever you use to get the code onto the VPS if that's
  a public git remote (see below) — it holds the Postgres password and
  whatever cookie value you may have put in `APOLLO_SOUNDCLOUD_COOKIES`.

## Getting the code onto the VPS

This repo isn't in git yet (see the cleanup commands from earlier in this
project's history, still pending). Two options, either is fine:
- `git init`, commit, push to a remote you control (can be a private GitHub/
  GitLab repo), `git clone` on the VPS.
- Skip git entirely and `rsync`/`scp` the directory straight to the VPS —
  simpler if you don't want this in a hosted git remote at all.

## Sizing

Playwright driving a real Firefox instance per scrape is the heaviest part of
this app — budget at least 2GB RAM for the VPS; 1GB instances tend to OOM
under a headless browser plus Postgres plus Adminer running concurrently. CPU
is less of a concern for single-user, occasional-use traffic.

## One thing that doesn't change with the network topology

Every scrape still comes from this one server's IP address, continuously,
rather than your laptop's IP occasionally. That's not a reason not to do this
— it's the same traffic pattern either way from SoundCloud's perspective, just
from a stable address instead of a residential one — but it's worth knowing
if you ever wonder why a server IP behaves differently than your home
connection did during testing.

## If this ever needs to be genuinely multi-user

Flagged here so it's not forgotten, not designed now (out of today's scope):
per-user accounts and sessions, rate limiting sized for many strangers rather
than one person, resource limits per scrape (someone could otherwise queue up
enough concurrent headless-browser scrapes to exhaust the VPS), and a harder
look at what "many people scraping SoundCloud through one server" looks like
from SoundCloud's side versus one person doing it personally. All of the
"just me" design above (Tailscale, Basic Auth) would need replacing, not
extending, if this scope changes later.
