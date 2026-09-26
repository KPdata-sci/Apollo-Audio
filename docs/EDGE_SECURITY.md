# Edge / perimeter security

This doc is scoped to the **network boundary** — what sits between a device
and the cluster, before a request ever reaches FastAPI. `docs/HOSTING.md`
already covers application-layer hardening (the SSRF allowlist on `/scrape`,
`slowapi` rate limits, the `X-API-Key` gate and its real limits, the
Tailscale-as-VPC-equivalent table) — this doc doesn't re-explain any of that,
it links to it. `docs/NEXT_STEPS.md` §"Security (from the audit)" tracks
specific open items (sudoers, the setup SSH key, secret storage); this doc
cross-references those rather than duplicating them.

Two tracks, because the honest answer to "what's the edge security posture"
is different depending on which world this project is in:

- **Track 1**: today's reality — Tailscale-only, nothing public.
- **Track 2**: what changes if it ever gets a real public URL.

---

## Track 1 — current posture (Tailscale-only, not public)

The premise HOSTING.md sets up still holds: there is no public edge, so most
"edge security" questions don't apply in their usual form. What's left is
narrower — who can reach the tailnet, what the bridged VM exposes to the LAN
regardless of Tailscale, and what a compromised credential on this side of
the boundary could do.

### Tailscale ACLs — a concrete policy, not just "optional"

HOSTING.md flags ACLs as available but unconfigured, with the default (every
device reaches every device) being fine for a single identity. A concrete
policy is worth having on file even before there's a second user, because it
documents intent and because adding a second device later (a laptop, a
guest's phone) is exactly the moment the default silently becomes too broad.

Illustrative policy for this tailnet (edit in the Tailscale admin console,
not a file in this repo):

```jsonc
{
  "tagOwners": {
    "tag:apollo-vm": ["autogroup:admin"],
  },
  "acls": [
    // Owner's own devices reach the VM on the app ports and SSH.
    // Replace with real device/user identifiers from the admin console.
    {
      "action": "accept",
      "src":    ["autogroup:member"],
      "dst":    ["tag:apollo-vm:22,30800,30880"],
    },
  ],
  // Everything not explicitly accepted is denied once any ACL exists —
  // there's no separate "default deny" line to add.
}
```

Two things this buys even for one person:
- **Tagging the VM** (`tag:apollo-vm`) makes it a stable policy target
  independent of whoever's logged into it, and shows up distinctly in the
  Tailscale admin console's device list.
- **Port-scoping** means a future second device (guest, family member sharing
  the tailnet for something unrelated) doesn't get implicit access to 22
  (SSH) and the Kubernetes-facing ports just by being on the same tailnet.

Not worth doing today if it's genuinely one person, one device — but it's a
five-minute change the moment that stops being true, and the policy above is
the shape it should take.

### The `NetworkPolicy` gap — what a real CNI would buy, and whether it's worth it here

HOSTING.md already notes k3s's default Flannel CNI doesn't enforce
`NetworkPolicy` objects, so adding one today would be a no-op that looks like
a control without being one. Concretely, what installing **Calico** or
**Cilium** instead would add: pod-to-pod traffic inside the `apollo`
namespace is currently a flat network — any pod that got compromised (say,
a dependency-confusion attack landing code in the `api` pod via a poisoned
PyPI package) could open a connection to `postgres:5432` or `adminer:8080`
directly, because nothing at the network layer stops it; only the fact that
nothing *currently has a reason to* is doing that job. A `NetworkPolicy`-
enforcing CNI turns "nothing else needs to talk to Postgres" from an
assumption into an enforced rule.

Is it worth it at this scale? Honestly, no — not yet. It's a real
architecture change (swapping the CNI on a running k3s node is more
disruptive than most Terraform changes here), for a threat model where the
likeliest attacker path is a leaked API key or a stale SoundCloud selector,
not lateral movement between pods that are all owned by the same person
anyway. It's the right thing to revisit only if this cluster ever hosts a
second, less-trusted workload alongside Apollo, or genuinely goes multi-user.

For reference, this is what the policy would look like — **illustrative
only, not applied, would need Calico/Cilium installed first**:

```yaml
# NOT APPLIED — illustrative example for a future NetworkPolicy-enforcing CNI.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: postgres-allow-api-only
  namespace: apollo
spec:
  podSelector:
    matchLabels: { app: postgres }
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector: { matchLabels: { app: api } }
      ports:
        - port: 5432
  # No rule for adminer here deliberately: this doc doesn't add adminer
  # back onto the ingress list, since kubectl port-forward is how it's
  # meant to be reached (see adminer.tf).
```

### Windows Firewall / Hyper-V External Switch — what the bridged VM actually exposes

This is the one place Track 1 has a real, concrete gap worth naming plainly:
**the VM is bridged onto the home LAN, not NAT'd**, per HOSTING.md's setup
step 1 and `NEXT_STEPS.md`'s recorded LAN address (`192.168.1.244`). Bridged
networking means the VM has its own address on the home LAN and is reachable
by *any device on that LAN* — every other laptop, phone, smart-TV, or IoT
device on the home network, not just Tailscale peers. Tailscale ACLs (above)
govern the tailnet interface only; they have no effect on LAN traffic hitting
the VM's bridged NIC directly. Concretely, on this setup right now:

- `api` (NodePort `30800`) and `frontend` (NodePort `30880`) are reachable
  from **any device on the home LAN**, unauthenticated for reads, exactly as
  they're reachable over Tailscale — `expose_via = "nodeport"` in
  `infra/terraform-k8s/variables.tf` doesn't distinguish the two paths.
- `postgres` and `adminer` are `ClusterIP` (`infra/terraform-k8s/postgres.tf`,
  `adminer.tf`) — not exposed on *any* interface, LAN or tailnet. This is the
  one part of the stack where "no route out" genuinely holds regardless of
  network topology.
- SSH (`22`) on the VM's guest OS is reachable from the LAN the same way,
  guarded only by whatever the guest OS's own firewall/sshd config allows —
  this repo doesn't declare that config, so it's worth checking directly on
  the VM (`sudo ufw status` or equivalent) rather than assuming.

Practically: anyone with access to the home Wi-Fi password (a guest, a
smart-device compromise, a visiting laptop) can already reach the app UI and
the unauthenticated read API today, with no Tailscale client needed. That's
a materially different exposure than "Tailscale-only" suggests, even though
it's still far short of public — the mitigation, if it matters for this
household, is either firewalling those NodePorts to specific LAN sources at
the VM's OS level, or moving to a NAT'd VM network and reaching it only via
Tailscale (trading away the "reachable from any LAN device without the
Tailscale app" convenience). Not fixing this now is a reasonable call for a
single-occupant home network; it stops being reasonable the moment the LAN
has less-trusted devices on it.

### kubeconfig and SSH key handling

`docs/NEXT_STEPS.md` already flags the specific open items here — the broad
`kieran ALL=(ALL) NOPASSWD: ALL` sudoers rule and the leftover
`claude-code@apollo-vm-setup` SSH key — see that doc's "Tighten VM access"
section rather than repeating the remediation here. The edge-security framing
worth adding: `~/.kube/apollo-vm-config` and any SSH private key that can
reach the VM are themselves perimeter credentials — either one grants a
path onto the VM that's completely orthogonal to Tailscale ACLs or Kubernetes
`NetworkPolicy`. No amount of tailnet ACL tuning matters if the kubeconfig
sitting on the Windows host (per NEXT_STEPS' "Plaintext secrets on this PC")
leaks. Treat those two files with at least the same care as `api_key`/
`postgres_password` in `terraform.tfvars`.

### CI supply-chain / edge-adjacent concerns

A CI workflow is being added to this repo in parallel with this doc. From an
edge-security standpoint, the concrete rule worth stating here (independent
of what that workflow ends up doing) is: **CI should never hold a credential
that can reach the VM** — no kubeconfig, no SSH key, no `api_key` secret in
GitHub Actions secrets, unless a genuine CD step to the VM is intentionally
being built (not the case today — deploys are the manual `docker save | ssh
... k3s ctr images import` flow in `NEXT_STEPS.md` §3). If that ever changes:
scope any deploy credential as narrowly as possible (a key that can only
`k3s ctr images import`, not a full kubeconfig with cluster-admin), and treat
GitHub Actions secrets with the standard hygiene of least-privilege scoping,
no secrets in workflow logs, and pinned action versions (`uses: actions/x@<sha>`
rather than a floating tag) to reduce the chance a compromised third-party
Action reads them.

---

## Track 2 — if this ever gets a real public edge

Everything below is deferred work, not a to-do list — HOSTING.md's closing
section and `PUBLIC_ACCESS_DESIGN.md`'s "Alternative: a real public URL"
already say not to build this preemptively. This section exists so that
*when* it's needed, the options and their real tradeoffs are written down
once.

### Domain, DNS, and TLS termination

A real public URL needs a domain and an A/AAAA record, per
`PUBLIC_ACCESS_DESIGN.md`. For TLS, there are genuinely two different paths
depending on which way this goes:

- **Staying on Tailscale but wanting HTTPS**: already covered in
  HOSTING.md's "Optional: HTTPS via `tailscale serve`" — no change needed,
  nothing below applies.
- **Going fully public**: `tailscale serve` no longer applies (it only fronts
  the tailnet, not the public internet). That means standing up real
  certificate automation — **cert-manager** with the Let's Encrypt ACME
  issuer is the standard Kubernetes-native choice, since it plugs into
  whatever ingress controller is chosen below and auto-renews. The
  alternative from `PUBLIC_ACCESS_DESIGN.md` (Caddy as a standalone reverse
  proxy with automatic HTTPS) is simpler to reason about but sits outside
  Kubernetes' own model — worth choosing cert-manager if an ingress
  controller is being installed anyway, Caddy if avoiding a second moving
  part in-cluster is preferred.

### A real ingress controller

k3s ships **Traefik** built in (referenced already in `variables.tf`'s
`expose_via = "ingress"` option, which today has no Traefik `Ingress` objects
actually wired up). Going public is the point where that matters: an ingress
controller is where rate-limiting and basic WAF-style rules belong once
`/scrape` and `/api/discover-playlists` are reachable by strangers, not just
the current per-endpoint `slowapi` limits in `main.py`.

- **Traefik** (already present on k3s, zero extra install): supports rate
  limiting and IP allow/deny via `Middleware` CRDs
  (`traefik.io/v1alpha1.Middleware`, `rateLimit`/`ipAllowList` specs) —
  the lowest-effort option since nothing new needs installing.
- **ingress-nginx**: more common in tutorials and has a larger annotation
  surface (`nginx.ingress.kubernetes.io/limit-rps`, ModSecurity WAF can be
  compiled in), but it's a second controller running alongside Traefik unless
  Traefik is disabled at k3s install time (`--disable traefik`). Only worth
  the swap if a specific ingress-nginx feature is actually needed — Traefik
  covers rate limiting and IP allowlisting on its own.

Either way, this is additive to — not a replacement for — the SSRF allowlist
and `slowapi` limits HOSTING.md already documents; those stay the
application-layer backstop even with an ingress-level rate limit in front.

### DDoS / bot mitigation — sized honestly for a single-user hobby project

Enterprise WAF/DDoS spend is not warranted here even in the fully-public
scenario — this is worth saying plainly rather than padding the doc with
enterprise checklist items that don't fit a personal project's threat model
or budget:

- **Cheap and worth it if this goes public**: putting **Cloudflare's free
  tier** in front as a reverse proxy (orange-clouded DNS) gets basic L3/L4
  DDoS absorption, a shared bot-fingerprinting layer, and free TLS at the
  edge, for zero cost and roughly the same setup effort as pointing DNS at
  the VM directly. This is the one Track-2 item that's genuinely a "why
  wouldn't you" if a domain is in play at all.
- **Overkill at this scale**: a dedicated self-hosted WAF (ModSecurity core
  rule set, a commercial WAF SaaS, rate-limiting-as-a-service products) —
  these solve problems that come with real traffic volume and multi-tenant
  exposure, neither of which applies to a personal scraper with one user.
  The ingress-level rate limiting above plus Cloudflare's free tier covers
  the realistic threat (opportunistic scanning bots hitting a newly-public
  IP) at effectively no cost or complexity; anything past that is spend
  without a matching risk.

### Geographic / IP allowlisting

If the intent is still "only the owner reaches this" even after going
public (i.e., a public URL chosen for convenience — no Tailscale client on
some device — rather than a genuine multi-user goal), IP allowlisting at
the ingress or Cloudflare layer is simpler and cheaper than it sounds:
Cloudflare's free tier supports IP Access Rules and country-level blocking
in its dashboard with no extra infrastructure; Traefik's `ipAllowList`
middleware does the same in-cluster if avoiding a third-party proxy matters
more than the convenience. Either is far less work than the WAF options
above and directly matches the actual goal ("keep strangers out") rather
than "detect and mitigate strangers already in."

---

## Prioritized checklist

What's actually worth doing now, given this project's real scale (a personal
tool, Tailscale-only, no public exposure) — most of Track 2 and a fair chunk
of Track 1 is deliberately **not** on this list, because it's genuine
enterprise-grade advice that doesn't fit a single-user home deployment:

**Do now:**
1. Firewall the two NodePorts (`30800`/`30880`) at the VM's guest-OS level to
   the home LAN's actual subnet if any less-trusted device might join that
   LAN — the "Windows Firewall / Hyper-V External Switch" gap above is the
   most concrete, already-real exposure this doc found, more pressing than
   anything Tailscale-ACL-related. This got a real stake in it once user
   accounts existed: `POST /api/auth/login` sends a password, and every
   gated request afterward sends a bearer token, both in plain HTTP — fine
   over the Tailscale tunnel itself (WireGuard encrypts that hop), not fine
   over the bridged-LAN path this item is about, where there's no transport
   encryption at all.
2. Resolve the two credential items `NEXT_STEPS.md` already flags — the
   NOPASSWD sudoers rule and the leftover setup SSH key — since either one
   is a perimeter bypass regardless of any Tailscale or NetworkPolicy work.
3. Keep the CI workflow being added credential-free with respect to the VM
   (no kubeconfig/SSH key/api_key in GitHub Actions secrets) — cheapest
   possible insurance against a supply-chain compromise reaching this
   project's only real infrastructure.
4. Confirm the VM's own SSH exposure (`sshd_config`, guest firewall) matches
   what's assumed above — this doc infers it from bridged networking, it
   hasn't been directly verified.

**Worth doing, not urgent:**
5. Write the Tailscale ACL policy above into the admin console once a second
   device joins the tailnet — trivial effort, but genuinely not needed for
   one person on one device today.
6. Login tokens are a client-stored `Authorization: Bearer` header
   (`localStorage`), not an `httpOnly` cookie — a deliberate choice (see
   `CLAUDE.md`'s Authentication section) since the frontend/API are
   different origins with no TLS anywhere in this stack, and a cross-origin
   cookie needs `Secure`, which needs TLS. The trade-off: a token sitting in
   `localStorage` is exposed to any successful XSS in a way an `httpOnly`
   cookie wouldn't be. Revisit this only alongside the TLS-termination work
   in Track 2 below — an `httpOnly` cookie without TLS behind it wouldn't
   actually be safer, just differently exposed.

**Defer until/unless this goes public:**
7. Everything in Track 2 (domain/DNS, cert-manager, an ingress controller,
   Cloudflare, geo/IP allowlisting) — none of it does anything for a service
   with no public listener.
8. The `NetworkPolicy`/Calico/Cilium work — correct in principle, but a CNI
   migration is disproportionate effort for a single-owner cluster with no
   untrusted workloads sharing it.
9. Enterprise WAF/DDoS products of any kind — out of proportion at any point
   this project is likely to reach as a personal tool.

The single most load-bearing fact this doc surfaces: Tailscale ACLs and
`NetworkPolicy` both govern boundaries that **bridged LAN networking
bypasses entirely**. "This is Tailscale-only" is true for how the owner
reaches it, but not a complete description of what's reachable — item 1
above is the gap between those two statements, and it's the one item here
that's already live today rather than a hypothetical.
