# Terraform (Kubernetes) — deploying to a k3s host

Declares the same three services `docker-compose.yml` runs (postgres, scraper,
adminer) as Kubernetes objects instead, for running this on a dedicated
second machine via [k3s](https://k3s.io) rather than `docker compose up` on
your dev machine. **Not applied against anything yet** — written and
`terraform validate`-checked, but there's no cluster to `apply` it to until
you've done the one-time k3s install below.

## Why not just `docker compose up` on the other PC too?

You can — that still works fine and is less setup. This exists because the
plan is specifically Kubernetes (k3s) on the target host, which needs its
resources declared as k8s objects (Deployments, Services, PersistentVolumeClaims)
rather than a Compose file. Terraform here just means "declare those objects
as code with state tracking" instead of hand-writing/`kubectl apply`-ing raw
YAML — same end result, more repeatable.

## One-time setup on the target PC

1. Install k3s (single command, ships its own containerd + a default
   `local-path` StorageClass, no separate etcd/control-plane setup needed for
   a single node):
   ```bash
   curl -sfL https://get.k3s.io | sh -
   ```
2. Get its kubeconfig onto whichever machine you'll run Terraform from:
   ```bash
   sudo cat /etc/rancher/k3s/k3s.yaml
   # copy it to e.g. ~/.kube/config on your machine, and change the
   # "server: https://127.0.0.1:6443" line to the target PC's actual IP
   ```

## Getting the scraper image onto the cluster

This is the part that trips people up: **k3s cannot use an image `docker
compose build` made on a different machine.** Pick one:

- **Push to a registry** (simplest if you're OK with a (private) image
  living somewhere like GHCR or Docker Hub):
  ```bash
  docker build -t ghcr.io/<you>/apollo-scraper:latest ./scraper
  docker push ghcr.io/<you>/apollo-scraper:latest
  ```
  Set `scraper_image` to that reference in `terraform.tfvars`.
- **Build directly on the target PC** instead of pushing anywhere, then
  reference the local tag the same way `docker-compose.yml` does.
- **Import a locally-built image without a registry**: `docker save
  project_apollo-scraper:latest | gzip > image.tar.gz`, copy it over, then on
  the target PC: `sudo k3s ctr images import image.tar.gz`.

## Apply

```bash
cp terraform.tfvars.example terraform.tfvars   # fill in scraper_image, postgres_password
terraform init
terraform plan
terraform apply
```

Then reach the app at the URL from `terraform output scraper_url` (NodePort
by default — `http://<target-pc-ip>:30800`).

## What's deliberately NOT exposed

Postgres and Adminer are `ClusterIP` only, same rule as the docker-compose
setup's hardening notes in `docs/PUBLIC_ACCESS_DESIGN.md` — reach Adminer with
`kubectl port-forward -n apollo svc/adminer 8081:8080` when you need it,
rather than giving it a NodePort/Ingress of its own.

## Remote access

Same recommendation as `docs/PUBLIC_ACCESS_DESIGN.md`: put the target PC on a
Tailscale network rather than port-forwarding your home router. Works the
same whether the app is running via docker-compose or k3s underneath.
