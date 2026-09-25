# Terraform (Kubernetes) — local hosting on a k3s VM

Declares this app as Kubernetes objects — two Deployments/Services now
(`api`, the standalone FastAPI backend, and `frontend`, the static UI — see
"Decoupled from the front end" below), plus `postgres` and `adminer`,
matching what `docker-compose.yml` runs for local dev. Primary target: real
[k3s](https://k3s.io) on a separate Linux box — a VM (VirtualBox/VMware/
Hyper-V, **bridged networking** so it gets its own LAN IP) or a physical PC.
Docker Desktop's own built-in Kubernetes on this same Windows machine also
works and needs less setup if you don't have a separate box — see
"Alternative: Docker Desktop instead of a VM" at the end. `terraform
validate`-checked; not yet `apply`'d anywhere.

## Decoupled from the front end

The API (`scraper/`) no longer mounts or serves `scraper/app/static/index.html`
— it's a pure JSON API now (`/scrape`, `/api/tracks`, `/api/discover-playlists`,
`/api/playlists`, `/health`). The front end is a separate `nginx` image
(`frontend/Dockerfile`) serving that same HTML file, pointed at the API's
address via the `API_BASE_URL` env var / `api_base_url` Terraform variable.
This means:
- They can be exposed differently (e.g. only the frontend reachable from your
  phone, or both, or neither if you're just running docker-compose locally).
- The API needs CORS configured (`APOLLO_CORS_ORIGINS` / `cors_origins`) since
  browser requests now cross an origin boundary that didn't exist before.
- `POST /scrape` and `POST /api/discover-playlists` can require an `X-API-Key`
  header (`APOLLO_API_KEY` / `api_key`) — see `docs/HOSTING.md` for what this
  does and doesn't protect against.

## Setup: k3s on a Linux VM/PC

1. **VM networking must be bridged**, not NAT'd — the VM needs its own LAN IP
   so it can join your Tailscale network directly and be reachable from your
   phone. (VirtualBox: Settings → Network → Attached to: Bridged Adapter.
   VMware: Bridged. Hyper-V: an External virtual switch.)

2. **Install k3s** on the VM:
   ```bash
   curl -sfL https://get.k3s.io | sh -
   ```
   Ships its own containerd + a default `local-path` StorageClass — no
   separate etcd/control-plane setup needed for a single node.

3. **Install Tailscale directly inside the VM** (not on the Windows host —
   the VM has its own routable IP, so it can join your tailnet as its own
   device, same as your phone does):
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   tailscale ip -4   # note this — it's what api_base_url and your phone will use
   ```

4. **Get the kubeconfig onto whichever machine you'll run Terraform from**
   (this Windows PC, most likely):
   ```bash
   sudo cat /etc/rancher/k3s/k3s.yaml
   ```
   Copy it to e.g. `~/.kube/apollo-vm-config`, and change the
   `server: https://127.0.0.1:6443` line to the VM's actual (bridged) LAN IP
   — `127.0.0.1` in that file means "the VM itself," not useful from outside it.

5. **Get the two images onto the VM** — k3s can't use an image `docker build`
   made on a different machine. Pick one:
   - **Push to a registry** (simplest if a private image on GHCR/Docker Hub
     is fine):
     ```bash
     docker build -t ghcr.io/<you>/apollo-api:latest ./scraper
     docker build -t ghcr.io/<you>/apollo-frontend:latest -f frontend/Dockerfile .
     docker push ghcr.io/<you>/apollo-api:latest
     docker push ghcr.io/<you>/apollo-frontend:latest
     ```
   - **Build directly on the VM** instead (clone/copy this repo there, run
     the same `docker build` commands, reference the local tags — no
     registry, no transfer step).
   - **Import without a registry**: build on the Windows host, then
     ```bash
     docker save apolloaudio-api:local | gzip > api.tar.gz
     docker save apolloaudio-frontend:local | gzip > frontend.tar.gz
     # scp both to the VM, then on the VM:
     sudo k3s ctr images import api.tar.gz
     sudo k3s ctr images import frontend.tar.gz
     ```

6. **Apply**:
   ```bash
   cp terraform.tfvars.example terraform.tfvars   # fill in image refs, postgres_password, api_key, api_base_url
   terraform init
   terraform plan
   terraform apply
   ```

7. Reach it at the URLs from `terraform output api_url` /
   `terraform output frontend_url` — with the example `tfvars`' `nodeport`
   setting, that's `http://<vm-tailscale-ip>:30800` (api) and `:30880`
   (frontend), from any device on your tailnet, phone included.

## What's deliberately NOT exposed

Postgres and Adminer are `ClusterIP` only — reach Adminer with `kubectl
port-forward -n apollo svc/adminer 8081:8080` when you need it, rather than
giving it a NodePort/Ingress of its own. This is the main practical network
control at this cluster size: k3s's default Flannel CNI (and Docker
Desktop's networking) don't enforce `NetworkPolicy` objects out of the box,
so "never gets a Service exposing it externally" is what's actually keeping
these two off the network, not a policy that could silently be a no-op.

## Security

See `docs/HOSTING.md` for the full picture (edge/DNS options via Tailscale,
the API-key design's real limits, secrets hygiene, image hardening,
backups). Short version of what's already wired up here:
- `terraform.tfvars` is gitignored (holds `postgres_password` and `api_key`)
  — never commit a filled-in copy.
- Postgres/Adminer have no external Service at all (see above).
- `POST /scrape` / `POST /api/discover-playlists` can require `api_key` — set
  one before this is reachable by anything other than trusted devices on your
  tailnet.
- Every container now has resource `requests`/`limits` — a runaway Playwright
  process can't take down the node.

## Alternative: Docker Desktop instead of a VM

If you'd rather not run a separate VM, Docker Desktop's own Kubernetes
(Settings → Kubernetes → Enable Kubernetes) works too, entirely on this one
Windows machine:
- Its default StorageClass is `hostpath`, not `local-path`.
- `expose_via = "loadbalancer"` — Docker Desktop auto-assigns `localhost` as
  the external IP for `LoadBalancer` Services, which is simpler than NodePort
  specifically on Docker Desktop.
- No image transfer needed at all: Docker Desktop's Kubernetes shares the
  same Docker Engine `docker build` uses, so a locally-built tag like
  `apolloaudio-api:local` is immediately usable.
- Install Tailscale on the Windows host itself (rather than inside a VM) —
  see the commented block at the bottom of `terraform.tfvars.example`.
