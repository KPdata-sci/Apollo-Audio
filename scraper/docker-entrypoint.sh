#!/bin/sh
# Runs as root (this image's actual default — see Dockerfile) so it can fix
# ownership of whatever's actually mounted at /data and the log dirs *at
# container start*, then drops to the image's own non-root pwuser before
# exec'ing the real command. Same standard pattern official images like
# postgres/mysql use for exactly this problem.
#
# A build-time `chown` in the Dockerfile only ever touches the image's own
# layers — it can't reach a volume that gets mounted over that path at
# runtime, whether that's a docker-compose bind mount or a Kubernetes PVC.
# Kubernetes has its own fix for its case (fs_group in api.tf's
# security_context, applied on every mount). docker-compose's bind mounts
# have no such mechanism, and this isn't just a "migrating an existing
# volume" edge case: on a real Linux Docker host (unlike this project's own
# Docker Desktop dev machine, which is more lenient about it), a bind
# mount's source directory that doesn't exist yet gets auto-created by
# dockerd as root — so this bites a completely fresh `docker compose up`
# clone too, not just an existing one. Confirmed exactly this way: it passed
# every local check on Docker Desktop and then failed on GitHub Actions'
# real Linux runners.
set -e
mkdir -p /data/lake /data/logs /var/log/apollo
chown -R pwuser:pwuser /data /var/log/apollo
# setpriv changes the process' uid/gid but — unlike `su`/`gosu` — leaves the
# environment alone, so $HOME stays "/root" even after dropping to pwuser.
# pwuser can't write there, and Firefox/Playwright's driver silently hang
# trying to set up a profile/cache under it (found by testing this directly,
# not guessed at: reproduced standalone, confirmed by checking $HOME under
# setpriv, fixed here rather than shipped and found later in CI again).
export HOME=/home/pwuser USER=pwuser LOGNAME=pwuser
exec setpriv --reuid=pwuser --regid=pwuser --init-groups "$@"
