# Local Kubernetes hosting, reachable from your phone

The concrete plan actually being built (as of this doc): real **k3s**
Kubernetes running inside a **Linux VM** (VirtualBox/VMware/Hyper-V, bridged
networking) on your PC, declared with Terraform (`infra/terraform-k8s/`),
reachable from a mobile device via **Tailscale** (a private mesh VPN)
installed directly inside that VM, with the API decoupled from the front end
so each is its own Deployment/Service. Docker Desktop's own Kubernetes on the
Windows host works too and needs less setup if you don't have a VM to spare —
see "Alternative: Docker Desktop" below; everything else in this doc applies
either way. `docs/PUBLIC_ACCESS_DESIGN.md` is the earlier, more general
design doc this narrows down — read that one for the reasoning behind
"Tailscale over a public URL," this one for what's actually wired up and the
security checklist around it.

## Architecture

```
                    Tailscale (private, WireGuard-encrypted)
                              |
      your phone  <----------+----------->  Linux VM (bridged, its own LAN IP,
                                             Tailscale installed inside it)
                                              |
                                   +----------+----------+
                                   |   k3s (ns: apollo)   |
                                   |                       |
                        NodePort   |  +-----------+        |
                :30880  --------->  | frontend  |          |
                     (nginx)      |  +-----------+         |
                                   |       |  fetch()       |
                                   |       v  (cross-origin,|
                        NodePort   |  +-----------+ CORS)   |
                :30800  --------->  |    api    |           |
                                   |  +-----------+         |
                                   |    |      |            |
                                   |    v      v            |
                                   |  +-----+ +--------+    |
                                   |  | PVC | |postgres|    |
                                   |  |lake | |(Cluster|    |
                                   |  +-----+ | IP only|    |
                                   |          +--------+    |
                                   |               ^        |
                                   |          +--------+    |
                                   |          |adminer |    |
                                   |          |(Cluster|    |
                                   |          | IP only|    |
                                   |          +--------+    |
                                   +-----------------------+
```

`frontend` and `api` each get a `NodePort` Service, fixed at `:30880`/`:30800`
on the VM's own IP. `postgres` and `adminer` stay `ClusterIP` — never
reachable outside the cluster at all, gated behind `kubectl port-forward`
when you actually need Adminer. The Windows host and your other devices only
come into it as Tailscale peers — the VM being bridged means it's a full
citizen of your tailnet, not something the host has to proxy for.

## Why Tailscale instead of a "real" VPC + edge setup

You asked what else a normal hosting setup would need — VPC boundaries, edge
security, DNS. Those solve a problem this setup doesn't have: a cloud VPC
exists to fence off resources that live on a shared provider's network from
everyone else's; edge/WAF and public DNS exist because a public IP gets
scanned by bots within minutes. None of that applies to a single PC on your
own home network that you're reaching from your own phone. Tailscale replaces
all three at once, more simply:

| Cloud concept | Tailscale equivalent |
|---|---|
| VPC (network boundary) | Your tailnet — only devices logged into your account can route to this PC at all |
| Security groups / firewall rules | Tailscale ACLs (see below) — fine-grained, but the default (only your own devices) is already the whole point |
| Public DNS (A/AAAA records) | MagicDNS — stable hostnames like `this-pc.your-tailnet.ts.net`, no registrar, no propagation delay |
| Edge TLS termination (ALB/CloudFront cert) | `tailscale serve` — automatic HTTPS cert for your MagicDNS name, no cert-manager/Let's Encrypt setup needed |
| WAF / DDoS protection | Not needed — nothing is listening on the public internet, so there's no public attack surface to protect |

If you ever *do* want a real public URL later, `docs/PUBLIC_ACCESS_DESIGN.md`'s
"Alternative: a real public URL" section covers what that actually needs (a
domain, a reverse proxy doing ACME/Let's Encrypt, a firewall) — don't build
that until you actually need strangers to reach this without a Tailscale
client installed.

## Setting it up

Full step-by-step is in `infra/terraform-k8s/README.md` ("Setup: k3s on a
Linux VM/PC") — short version:

1. Make sure the VM's networking is **bridged**, not NAT'd (its own LAN IP).
2. Install k3s inside the VM (`curl -sfL https://get.k3s.io | sh -`).
3. Install Tailscale *inside the VM* (not the Windows host) and note its
   Tailscale IP (`tailscale ip -4`) — install the Tailscale app on your phone
   too, same account.
4. Get the API's and frontend's Docker images onto the VM (push to a
   registry, build directly on the VM, or `docker save`/`k3s ctr images
   import` — three options, see the README) and copy the VM's kubeconfig
   over.
5. Fill in `terraform.tfvars` (copy from `.example`) — image refs,
   `postgres_password`, `api_key`, `api_base_url` set to
   `http://<vm-tailscale-ip>:30800`.
6. `terraform init && terraform apply`.
7. From your phone (Tailscale connected), open `http://<vm-tailscale-ip>:30880`.

## Alternative: Docker Desktop (no VM)

Same result, one machine instead of two: enable Kubernetes in Docker Desktop
(Settings → Kubernetes → Enable Kubernetes), build the images locally with no
registry needed, install Tailscale on the Windows host itself, and use
`expose_via = "loadbalancer"` / `storage_class = "hostpath"` — the commented
block at the bottom of `terraform.tfvars.example` has the exact values. Trade-off:
one less moving part, but the Windows host itself is now the thing that needs
Tailscale and needs to stay running, rather than an isolated VM you can
snapshot/restart independently of your desktop session.

## Optional: HTTPS via `tailscale serve`

Tailscale can front any local port with a browser-trusted HTTPS cert for the
VM's MagicDNS name, no cert management required — run this inside the VM:
```bash
tailscale serve --bg --https=443 http://localhost:30880
```
Then your phone reaches `https://<vm-name>.<your-tailnet>.ts.net` instead of
a bare IP:port. Repeat for the API port if you want the frontend's `fetch()`
calls to also go over HTTPS (browsers are generally fine mixing HTTP
API-calls from an HTTPS page on a private network, but matching schemes is
simpler to reason about).

## Optional: restrict who's allowed to reach what, via Tailscale ACLs

By default every device on your tailnet can reach every other device. If you
ever add other people or devices to your tailnet and want to limit which of
them can reach this app, Tailscale's ACL file (in the admin console) lets you
scope access by tag/user/port — e.g. "only my phone and laptop can reach port
8000/8080 on this PC." Not needed for a single-user tailnet, but this is the
actual access-control lever once more than one identity shares it.

## Security practices — what's in place, what to add next

**Already wired up** (this change):
- API and front end are separate services with CORS configured between them,
  instead of one process trusting same-origin implicitly.
- `POST /scrape` and `POST /api/discover-playlists` can require an `X-API-Key`
  header (`APOLLO_API_KEY` / Terraform `api_key`) — reads stay open. See "The
  API key's real limits" below for what this is and isn't.
- Postgres and Adminer have no Kubernetes Service exposing them outside the
  cluster at all — not "protected by a rule," just never given a route out.
- Every container has resource `requests`/`limits` (`infra/terraform-k8s/*.tf`)
  — a runaway Playwright process can't starve the node or the other pods.
- `terraform.tfvars` is actually gitignored now (`**/terraform.tfvars` in the
  repo root `.gitignore` — it was documented as ignored before but wasn't
  actually listed).
- Liveness + readiness probes on the API and Postgres, so Kubernetes restarts
  a wedged container instead of leaving it silently dead.
- **Domain allowlist on `/scrape` and `/api/discover-playlists`** (`main.py`'s
  `_require_soundcloud_host`): both endpoints drive a real headless browser to
  a caller-supplied URL, which is an SSRF primitive without this — now
  restricted to `soundcloud.com`/`*.soundcloud.com`, a 422 for anything else.
- **Rate limiting** (`slowapi`, keyed by `X-API-Key` when set, else by IP):
  `/scrape` capped at 10/minute, `/api/discover-playlists` at 20/minute —
  stops a runaway client or naive abuse from queuing up concurrent headless
  browser sessions.
- **A startup warning when `APOLLO_API_KEY` is unset**, so "the write
  endpoints are unauthenticated" is a log line you see, not a silent default.
- **A concurrency semaphore around Playwright** (`scraping.py`) — only one
  browser session runs per pod at a time, so two simultaneous `/scrape` calls
  in the same pod can't both spin up Firefox and exceed the pod's resource
  limits.
- **Bounded retry with backoff on page navigation** (`_goto_with_retry` in
  `scraping.py`) — a transient timeout/network blip no longer fails the whole
  scrape on the first try.
- **The data lake write is wrapped in try/except** (`main.py`) — a disk-full
  or S3-unreachable failure now returns a clean `502` instead of an unhandled
  exception.

**The API key's real limits** — worth understanding, not just enabling: the
front end stores it in the browser's `localStorage` (set via the 🔑 button),
not baked into the static file, so a random visitor loading the page doesn't
see it in view-source. But it's still a shared secret sent as a plain header
— anyone who *does* have it (or intercepts unencrypted traffic) can call the
write endpoints directly, and it does nothing to stop someone who already
knows it from hammering `/scrape` in a loop. Treat it as "stops
drive-by/automated abuse of a URL someone stumbled on," not "authentication."
Real auth (per-user accounts, OAuth) is out of scope per your "open reads,
gated writes" call — this is the lightweight version of that.

**Recommended next, not yet built:**
- **Rotate `api_key` periodically** and after any point you suspect it leaked
  (e.g. if you ever screen-share with the browser's Network tab open).
- **Postgres backups**: the `postgres-data` PVC is a single point of failure
  — nothing dumps or ships it anywhere. Even a manual
  `kubectl exec -n apollo deploy/postgres -- pg_dump -U apollo apollo > backup.sql`
  on a schedule beats nothing; a `CronJob` doing the same on a timer is the
  next step up.
- **Pin the Adminer image tag**: `adminer:latest` in `infra/terraform-k8s/adminer.tf`
  will silently pick up whatever's newest on your next `terraform apply` /
  image pull — pin it to a specific version like the other images already are
  (`postgres:16-alpine`, `nginx:1.27-alpine`).
- **Non-root containers**: the scraper image runs as root (inherited from the
  Playwright base image) — the image does ship a `pwuser` non-root user, but
  switching to it needs the `/data/lake` and `/data/logs` volume permissions
  worked out first (the PVC is currently root-owned by default), so this
  wasn't changed as part of this pass to avoid breaking the running app
  untested. Worth doing as a follow-up: add `RUN chown -R pwuser /data` at
  build time (or an `initContainer` that `chown`s the mounted volume) and
  `USER pwuser` in `scraper/Dockerfile`.
- **`NetworkPolicy` isn't real protection here**: Docker Desktop's
  Kubernetes (and k3s's default Flannel CNI) don't enforce `NetworkPolicy`
  objects out of the box, so adding one would look like a control without
  being one. If you later move to a CNI that enforces it (Calico, Cilium),
  revisit this — it's the correct way to formally restrict "only `api` can
  talk to `postgres`" instead of relying on "nothing else needs to."
- **Image scanning**: run `docker scout cves apolloaudio-api:local` (ships
  with Docker Desktop) or [Trivy](https://github.com/aquasecurity/trivy)
  against both images periodically — the Playwright base image in particular
  is large and updates often.

## If this ever needs to be genuinely public

Don't build this preemptively — it's real ongoing surface area (TLS renewal,
abuse monitoring, a bigger blast radius for the same API-key limits above).
When/if you do want it: `docs/PUBLIC_ACCESS_DESIGN.md`'s "Alternative: a real
public URL" section is the checklist (domain + DNS A record, reverse proxy
with automatic HTTPS, firewall closed to everything but 80/443, and — since
you'd then have strangers hitting `/scrape` — the rate limiting above stops
being optional).
