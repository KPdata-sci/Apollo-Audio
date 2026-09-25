# Next steps and open review items

Snapshot as of **2026-09-25**, written when work paused. Items are listed in
the order to do them.

## 0. Where things stand

**Merged into PR #1** (branch `decouple-api-k8s-hosting`, open, not merged):
- The API and the UI split into separate services.
- k3s/Terraform hosting, with access over Tailscale.
- Security hardening: SSRF allowlist, rate limits, retry/backoff, a startup
  warning when the API key is unset.
- The shared `pipeline.py`, plus scheduled ingest (`ingest.py` and a k8s
  CronJob).

**Done locally but NOT committed:**

| Area | Files | Review status |
|---|---|---|
| Frontend reaches the API on its own hostname (the Windows "tracks not showing" fix) | `frontend/Dockerfile`, `frontend/40-apollo-config.sh`, `docker-compose.yml`, `.env.example`, `infra/terraform-k8s/{frontend.tf,variables.tf,terraform.tfvars.example}` | Checked by curl and on localhost. Deployed to the VM. |
| New API: `/api/stats`; `/api/tracks` gains `genre`/`source_url`/`sort`; literal search; NUL bytes rejected with 422 | `scraper/app/{main,warehouse,models}.py`, `scraper/tests/test_api.py`, new `scraper/tests/test_warehouse_integration.py` | **Critic WOWED.** 37 tests pass against the live DB. |
| Curated catalog: 93 playlists, 19 genres | `scraper/app/playlists.py`, new `scraper/tests/test_playlists.py` | Builder checked all 93 with the real scraper. **The independent critic's re-check was stopped before it finished** (see §2). |
| UI redesign (Library / Discover / Add, scrape queue, docked player, themes) | `scraper/app/static/index.html` | **Critic WOWED on everything except Discover.** The round-4 Discover fixes are done and pass a quick check, but the critic hasn't re-reviewed them (see §1). |
| Docs | `README.md`, `CLAUDE.md`, `docs/API.md`, `.env.example`, this file | Updated to match the above. |

**Deployed to the VM** (`apollo-vm`, LAN 192.168.1.244, Tailscale 100.121.76.28):
- The API image with the pipeline/ingest code, and the ingest CronJob.
- The frontend's derive-the-API-from-hostname fix.

**Not deployed yet:** the new API endpoints, the catalog and the new UI. The
VM's frontend is still the old UI (see §3).

## 1. Finish the frontend review (Discover)

1. The round-4 fixes **were completed** before the pause. A quick check
   passed: Discover loads with 19 genres, no console errors, library status
   showing ("2 of 5 saved"), and the panel above the fold. What's missing is
   the critic's independent re-review of these items:
   - **Desktop:** clicking a genre tile scrolls the playlist panel into view.
     Consider compact tiles, about 56px.
   - **Library status on cards:** cards show "In library · N tracks · Xh ago"
     from `stats.sources`, and the button becomes **Refresh**.
     - "Scrape all" should default to "Scrape N new", with a secondary
       "Refresh all".
   - **Phone genre row:** use two rows that scroll together, or a wrapping chip
     grid, so about 6 genres are visible instead of 2.3.
   - Optional: a "Retry N failed" action, arrow-key movement between genre
     tiles (one tab stop for the group), and dropping the duplicate mobile
     Reload icon.
3. Run the critic once more on Discover only, at desktop and 375px mobile, in
   both themes.
4. Invariants any change must keep. They're listed in `CLAUDE.md` under
   "Front end":
   - the `config.js` API-address logic
   - the key goes only on the two POST requests
   - every API string is escaped
   - playback only through the embed, one track at a time
   - no auto-advance
   - the download link only when `downloadable === true`

## 2. Finish checking the catalog independently

- The critic re-scrape didn't finish. Re-scrape one playlist per genre (19),
  one at a time, 3–5s apart. Use the real scraper inside `apollo-api:latest`;
  the re-check snippet is in the comment block at the top of `playlists.py`.
  The builder's results are in the session scratchpad
  (`catalog/catalog_verification_2026-09-25.json`), which may be gone by now.
- Known weak spots:
  - The **DnB Allstars** profile depends on how far the page scrolls: one run
    gave 6 tracks, another 94.
  - The five `trending-music-us` charts rotate weekly.
  - **UK Garage & Bassline** has only 3 entries.
- Re-check the whole catalog every few months. SoundCloud playlists vanish.

## 3. Deploy to the VM

The VM's k3s can't pull local images, and there's a naming mismatch:
Compose builds `apollo-*`, while `terraform.tfvars` points at
`apolloaudio-*`. Either retag the images, or line the names up once (see §5).

```bash
docker compose build api frontend
docker tag apollo-api:latest apolloaudio-api:latest
docker tag apollo-frontend:latest apolloaudio-frontend:latest
docker save apolloaudio-api:latest | ssh -i ~/.ssh/apollo_vm_ed25519 kieran@192.168.1.244 "sudo k3s ctr images import -"
docker save apolloaudio-frontend:latest | ssh -i ~/.ssh/apollo_vm_ed25519 kieran@192.168.1.244 "sudo k3s ctr images import -"
KUBECONFIG=~/.kube/apollo-vm-config kubectl rollout restart deployment/api deployment/frontend -n apollo
```

Then check:
- `curl http://192.168.1.244:30800/api/stats`
- the UI at `http://192.168.1.244:30880` in a normal browser on the LAN
- the UI at `http://100.121.76.28:30880` from the phone over Tailscale

Run the integration tests against the VM database with `kubectl exec` on the
api pod.

## 4. Commit and PR

- Commit the uncommitted work from §0 to `decouple-api-k8s-hosting`, and
  update the PR #1 description: API-address fix, stats/filter API, catalog,
  UI redesign.
- Never commit `infra/terraform-k8s/terraform.tfvars` (it holds real secrets;
  it's gitignored) or `.claude/scheduled_tasks.lock`.

## 5. Backlog

### Access and testing
- **This Windows PC isn't on the tailnet**, so it can only use the LAN
  address. Install Tailscale on it, or keep using `192.168.1.244`.
- **Confirm the phone** reaches `http://100.121.76.28:30880` with Tailscale
  connected.
- **The built-in browser pane is a testing artifact:** it blocks cross-origin
  requests to private IPs and `localhost` from a LAN origin
  (`ERR_BLOCKED_BY_CLIENT`). Don't read that as an app bug. Test with a real
  browser.
- **Pin the VM's LAN IP.** Reserve a DHCP lease on the router for 192.168.1.244;
  the kubeconfig and SSH use it. Or point the kubeconfig at the Tailscale IP.
- **Stop apollo-vm's Tailscale key expiring.** Disable key expiry for it in
  the Tailscale admin console, or it silently drops off the tailnet.

### Security (from the audit)
- **Tighten VM access:**
  - `kieran ALL=(ALL) NOPASSWD: ALL` in `/etc/sudoers.d/kieran-nopasswd` is
    broad. Narrow it or remove it once setup is done.
  - Remove the setup SSH key (`claude-code@apollo-vm-setup`) from
    `~/.ssh/authorized_keys` if it isn't needed.
- **Plaintext secrets on this PC:**
  - `terraform.tfstate` stores `postgres_password`/`api_key` in plain text
    (it's gitignored, but local).
  - `~/.kube/apollo-vm-config` holds cluster-admin credentials.
  - Keep both private, or move state to an encrypted backend.
- **Harden the containers:**
  - Run the scraper container as a non-root user (`pwuser`). The data
    volume's ownership has to be sorted out first.
  - Pin `adminer:latest` and open-ended `>=` Python dependencies. Add
    Dependabot or Renovate, and run image scans (`docker scout` / Trivy).
- **Protect the data:**
  - Postgres backups: there's nothing yet. Add a `pg_dump` CronJob.
  - Kubernetes Secrets are only base64-encoded. Consider etcd encryption or
    SOPS.
- **Tidy up access rules:**
  - Tighten `cors_origins` from `*` once the frontend's URLs are fixed.
  - Rotate `api_key` from time to time.

### Pipeline and data
- **Scrape results vary run to run**, e.g. 45 vs 58 tracks for the same
  playlist, depending on how far the page scrolls. Compare the hydration track
  count with what was extracted, and retry or scroll longer when it's short.
- **`/scrape` is synchronous**, holding a connection open for up to 60s.
  Submit-and-poll with job IDs would make it robust on mobile.
- **Tracks without a URL** (`_INSERT_NO_URL_SQL`) duplicate on every re-scrape.
- **Lake replay isn't implemented**, even though the raw JSON is kept for it.
- **Ingest CronJob:**
  - It runs daily at 03:00. Check it with `kubectl get jobs -n apollo`.
  - Keep the URL list short and polite (see `docs/CRAWLER_DESIGN.md`).
  - Consider picking ingest URLs from the catalog.
- **Performance:** add an index on `lower(btrim(genre, ...))` if the tracks
  table grows large.
- **Selector drift:** when SoundCloud redesigns, `track_count: 0` plus a
  "selectors may be stale" log line is the signal.

### Frontend
- **Queue lost on reload:** the scrape queue lives in the page. Persisting it
  in `localStorage` is optional.
- **File size:** `index.html` is about 3,000 lines. Splitting it into
  CSS/JS files would need `frontend/Dockerfile` to copy the whole `static/`
  folder.
- **No automated UI tests.** A small Playwright smoke test (load, filter,
  open the player) would catch regressions.

### Repo hygiene
- **Line up the image names:** `apollo-*` from Compose vs `apolloaudio-*` in
  tfvars.
- **Terraform lock file:** consider committing `.terraform.lock.hcl` (it's
  currently gitignored) for reproducible provider versions.
- **Stale `.env` comments:** the local `.env` has old comment lines above
  `APOLLO_API_BASE_URL`. Recopy it from `.env.example`.
