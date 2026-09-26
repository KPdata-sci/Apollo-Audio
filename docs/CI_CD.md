# CI/CD

## What CI covers (`.github/workflows/ci.yml`)

Runs on every push and PR to any branch, as four jobs:

- **test** — installs `scraper/requirements.txt` plus `pytest`/`httpx`/
  `pytest-cov`, spins up a real `postgres:16-alpine` service container,
  applies `warehouse/init.sql` against it, then runs the full suite
  (`cd scraper && python -m pytest tests -q --cov=app --cov-report=term-missing`)
  with `APOLLO_WAREHOUSE_DSN` pointed at that database. This includes
  `tests/test_warehouse_integration.py` and `tests/test_favorites_integration.py`,
  which normally skip themselves when no warehouse is reachable — in CI they
  actually run (the latter against its own disposable fixture rows, deleted
  after each test — see that file's docstring for why it's separate from the
  read-only integration file). No Playwright browser install is needed: the
  tests mock `app.scraping.fetch_html` rather than driving a real browser.
  Coverage is printed to the job log, not enforced — no agreed baseline to
  gate on yet.
- **terraform** — `terraform fmt -check -recursive`, `terraform init
  -backend=false`, `terraform validate` for `infra/terraform-k8s/` (the real,
  apply-able-when-ready tree). `infra/terraform-aws/` is checked too but
  can't fail the build: its own README documents it as an unfinished sketch
  (mismatched variable names between files, duplicate resource definitions,
  pre-Terraform-0.12 tag syntax) that isn't meant to validate today.
- **docker-build** — builds `./scraper` and `frontend/Dockerfile` as a smoke
  test that both images still build. No push to any registry, no secrets
  involved.
- **compose-smoke** (runs after `test` passes) — actually boots the real
  `docker compose up -d --build` stack (postgres + api + frontend, using
  docker-compose.yml's own defaults, no `.env` needed) and hits it over real
  HTTP: `/health`, `/api/stats`, `/api/playlists`, the frontend's `/`, and
  that the favorite and login endpoints correctly reject an unauthenticated/
  unknown-user request (`401`) against a freshly-migrated database. This is
  the level below **test** and above **docker-build** — it catches a
  container that builds fine but is wired wrong (bad `CMD`, wrong port/env
  mapping, a migration that silently didn't apply), which mocked unit tests
  and a bare image build can't see.

## Why CD is manual today

This app deploys to a k3s VM reachable only over Tailscale/LAN (see
`docs/HOSTING.md`) — a GitHub-hosted runner has no network path to it, so
there's no way to bolt on a real automated deploy job without lying about
what it does. Deploying today means running, from a machine that *does* have
that network path (see `docs/HOSTING.md` "Setting it up" and
`infra/terraform-k8s/README.md`):

```bash
docker build -t apolloaudio-api:local ./scraper
docker build -t apolloaudio-frontend:local -f frontend/Dockerfile .
docker save apolloaudio-api:local | gzip > api.tar.gz
docker save apolloaudio-frontend:local | gzip > frontend.tar.gz
# copy the .tar.gz files to the VM, then on the VM:
sudo k3s ctr images import api.tar.gz
sudo k3s ctr images import frontend.tar.gz
# then, from wherever the kubeconfig lives:
KUBECONFIG=~/.kube/apollo-vm-config kubectl rollout restart deployment/api deployment/frontend -n apollo
```

## A path to real CD later

The concrete way to close this gap without exposing the VM to the internet is
a **self-hosted GitHub Actions runner** registered directly on the VM (or on
this Windows PC, if it has a network path to the VM) — it polls GitHub over
an outbound connection, so no inbound port needs opening. A workflow
triggered on push to `main` could then run the `docker build` /
`k3s ctr images import` / `kubectl rollout restart` sequence above on that
runner, in place of a person doing it by hand. Not built here — this is a
process change (registering and trusting a runner on that box) that deserves
its own deliberate setup rather than being smuggled into this CI PR.
