# Operating the production server

How the inventory runs in production and how to update, back up and restore it. Development
needs none of this; see the [project README](../README.md#development-setup).

## What runs where

The production checkout of this repository holds the whole installation. Containers are
managed with `podman-compose` (`docker compose` works the same; the scripts use whichever is
installed, or `COMPOSE="..."`).

| Service (`docker-compose.yml`) | What | Data on the host |
|---|---|---|
| `db` | PostgreSQL | `data/db/` (never copy it while running; back up with `ops/backup.sh`) |
| `python` | Django app (gunicorn); collects static files and applies migrations on every start (`web-entrypoint.sh`) | `data/media/`, `data/static/`, `exports/` |
| `web` | nginx on port 80, serves `data/static/` and `data/media/`, proxies the rest (`nginx.conf`) | |

The app's code is built into its image (`Dockerfile`), with the configuration from `.env`.
Changing files in the checkout therefore has no effect until the image is rebuilt:
`ops/update.sh` does that, or `podman-compose up -d --build` for a local change.

| Path | Content | In git |
|---|---|---|
| `.env` | configuration and secrets (from `.env.example`) | no |
| `data/media/` | uploaded photos and documents | no |
| `data/static/` | collected static files, rebuilt on every start | no |
| `backups/` | backups of `ops/backup.sh` | no |
| `exports/` | exports for development of `ops/export.sh` | no |
| `ops/` | maintenance scripts and this guide | yes |

## Tasks at a glance

All scripts run from any directory and act on the checkout they belong to. Run them as the
user that runs the containers (with rootful Podman: root).

| Task | Command |
|---|---|
| Status | `podman-compose ps` |
| Logs | `podman-compose logs -f --tail 100 python` (or `web`, `db`) |
| Update code and images | `ops/update.sh` |
| Back up | `ops/backup.sh` |
| Restore a backup | `ops/restore.sh backups/<name>` |
| Management command | `ops/manage.sh <command>`, e.g. `ops/manage.sh createsuperuser` |
| Export for development | `ops/export.sh` ([details](../docs/data-export.md)) |
| Restart | `podman-compose restart python` |
| Health | `podman ps` (column STATUS), `curl http://localhost/healthz` |

Requirements on the server: Podman with `podman-compose` 1.0.6 or newer (older versions
write their own messages into database dumps; the backup detects this and stops), `git`,
`rsync`.

## First installation

1. Clone this repository, e.g. to `/srv/inventory_management`.
2. Copy `.env.example` to `.env` and edit at least:
   * `ALLOWED_HOSTS`: the main domains (`inventar.zam.haus`, the label ID hosts); other
     domains are redirected before this check (see [Domains](../README.md#domains))
   * `DEFAULT_URL`: the main address, default `https://inventar.zam.haus` (a bare
     domain means HTTPS)
   * `SECRET_KEY`: a long random string (`openssl rand -base64 48`)
   * `POSTGRES_PASSWORD`: a random string
   * `MQTT_PASSWORD`: only needed for label printing
   * `OIDC_RP_CLIENT_ID` and `OIDC_RP_CLIENT_SECRET`: for login via SSO
   * optionally `GUNICORN_WORKERS` (default 3) and `GUNICORN_TIMEOUT` (seconds, default 120)

   `.env.example` lists all variables; `imzam/local_settings.py` is not used in production
   (it is not part of the image). For a secure deployment, also consult Django's
   [deployment checklist](https://docs.djangoproject.com/en/stable/howto/deployment/checklist/).
3. Build and start: `podman-compose up -d --build`. The app creates the database tables on
   its first start.
4. Either load the basic dataset: `ops/manage.sh loaddata initial_inventory`, or restore a
   backup (see [Moving to a new server](#moving-to-a-new-server)).
5. Create an administrator: `ops/manage.sh createsuperuser`.
6. Set up [daily backups](#scheduled-backups), [start on boot](#start-on-boot) and the
   [load balancer's health check](#health-checks).

nginx only speaks HTTP on port 80; HTTPS has to be provided by a proxy in front of it.

## Update

```sh
ops/update.sh
```

1. Stops if tracked files have local changes, so the update never overwrites them
   (commit or stash them first).
2. Backs up (`backups/<date>-pre-update`); skip with `--no-backup`.
3. `git pull --ff-only`, and shows the new commits.
4. Pulls the PostgreSQL and nginx images (`postgres:18`, `nginx:stable`: bugfixes only) and
   rebuilds the app image with the new code, a fresh Python base image and the current
   `requirements.txt`.
5. Recreates all containers. The app applies new migrations; the script waits until
   `/healthz` answers and stops with the app's log otherwise. Meanwhile the load balancer
   shows its maintenance page ([Health checks](#health-checks)).

If the update fails, the script prints how to go back: reset the checkout to the previous
commit, rebuild, and restore the pre-update backup. The backup is needed because migrations
may have changed the database already.

To go back to an older version later, see [Restore](#restore).

## Backup

```sh
ops/backup.sh [LABEL]
```

Creates `backups/<date>_<time>[-LABEL]/`:

| File | Content |
|---|---|
| `db.dump` | the database (`pg_dump` custom format; restore with `pg_restore`) |
| `media/` | all uploaded files |
| `env` | a copy of `.env` |
| `info.txt` | date, git commit and host |

* **Size:** `media/` is a full copy, but files unchanged since the previous backup are hard
  links to it and take no extra space. A backup costs about the size of the database
  dump plus new uploads.
* **Consistency:** the database is dumped first, then the files are copied, so every file
  that a row in the dump refers to is there. The app keeps running.
* **Secrets:** backups contain `.env` (all passwords) and all data, including personal data.
  They are readable only by their owner; keep copies just as protected.
* **Incomplete backups** end in `.partial` and are never used; delete them.
* `BACKUP_DIR=/path` puts backups elsewhere (e.g. another disk); `BACKUP_KEEP=30` deletes
  all but the newest 30 afterwards.

### Scheduled backups

Daily at 03:15, keeping 30, e.g. in the crontab of the user that runs the containers
(`crontab -e`):

```cron
15 3 * * * BACKUP_KEEP=30 /srv/inventory_management/ops/backup.sh >> /srv/inventory_management/backups/backup.log 2>&1
```

Cron has a short `PATH`: if `podman-compose` lives in `~/.local/bin`, add
`PATH=/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin` above the line. Check
`backups/backup.log` after the first night.

### Off-site copies

Backups on the same disk do not survive a lost server. Copy them elsewhere, keeping the
hard links (`-H`), otherwise every copy of `media/` takes full space:

```sh
rsync -aH --delete /srv/inventory_management/backups/ backup-host:/backups/inventory/
```

Restore a backup on another machine now and then, to know that it works.

## Restore

```sh
ops/restore.sh backups/<name>
```

1. Shows the backup's `info.txt` and warns if it was made with code that this checkout does
   not contain. Then the database may not fit the code: `git checkout <commit>` from
   `info.txt` first.
2. Asks for confirmation (`--yes` skips it).
3. Backs up the current state (`backups/<date>-pre-restore`), so a restore can be undone;
   skip with `--no-safety-backup`.
4. Stops the app, replaces the database and `data/media/` with the backup's, and starts the
   app again. With a backup older than the code, the app applies the newer migrations.

`.env` is not replaced; the script warns when it differs from the backup's copy (`env`).

### Moving to a new server

1. On the new server: install the requirements and clone the repository
   ([First installation](#first-installation), step 1).
2. Copy the backup directory over (e.g. with `rsync -aH`).
3. `cp backups/<name>/env .env`, and adjust it if domains or hosts change.
4. If the backup was made with an older commit (`info.txt`), check that out.
5. `podman-compose up -d --build`
6. `ops/restore.sh backups/<name> --no-safety-backup`

## PostgreSQL major upgrade

The `db` image is pinned to a major version (`postgres:18`); its data directory cannot be
used by the next major version. Upgrade by dump and restore:

1. `ops/backup.sh pre-pg-upgrade`
2. `podman-compose down`
3. `mv data/db data/db.pg18` (keep it until the new version runs)
4. Change the image in `docker-compose.yml`, e.g. to `docker.io/library/postgres:19`, and
   commit the change.
5. `podman-compose up -d db` (creates an empty database)
6. `ops/restore.sh backups/<date>-pre-pg-upgrade --no-safety-backup`

## Start on boot

`restart: unless-stopped` restarts crashed containers, but Podman has no daemon that starts
them after a reboot. If the server does not start them yet, a systemd unit can, e.g.
`/etc/systemd/system/inventory.service` for rootful Podman:

```ini
[Unit]
Description=ZAM inventory (podman-compose)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/srv/inventory_management
ExecStart=/usr/bin/podman-compose up -d
ExecStop=/usr/bin/podman-compose stop

[Install]
WantedBy=multi-user.target
```

`systemctl daemon-reload && systemctl enable inventory.service`. With rootless Podman,
put it in `~/.config/systemd/user/`, use `WantedBy=default.target`, `systemctl --user enable`,
and `loginctl enable-linger <user>`.

## Health checks

`/healthz` answers `ok` while the app runs and reaches its database, and status 503
otherwise (`imzam/health.py`). It answers for any host name and is not logged by nginx.

* **Containers:** the `python` container checks the app, the `web` container the whole chain
  through nginx; `podman ps` shows `healthy` or `unhealthy`. An unhealthy container is not
  restarted automatically. Podman runs these checks with systemd timers; without systemd,
  `podman healthcheck run <container>` checks once.
* **Load balancer:** HAProxy in front of this server can check the same URL and show its own
  maintenance page while the app is down (during updates, restores or after a failure),
  for example:

  ```haproxy
  backend inventory
      option httpchk GET /healthz
      http-check expect status 200
      # A complete HTTP response (status line, headers, page), shown while no server is up
      errorfile 503 /etc/haproxy/errors/inventory-maintenance.http
      server inventory <this server>:80 check inter 5s fall 2 rise 2
  ```

## Troubleshooting

* **502 Bad Gateway or maintenance page:** the app is not running. `podman-compose logs --tail 100 python`
  shows why. A failed migration stops the start on purpose.
* **502 or 504 after about two minutes for one page or upload:** the request took longer than
  `GUNICORN_TIMEOUT` (default 120 s); gunicorn logs `WORKER TIMEOUT`.
* **A change on the server has no effect:** the code is in the image, so rebuild it:
  `podman-compose up -d --build`.
* **Backup stops with "not a PostgreSQL dump":** `podman-compose` is older than 1.0.6; update it
  (e.g. `pip install --user --upgrade podman-compose`).
* **Disk full:** old backups (`BACKUP_KEEP`), old exports (`exports/`), unused images
  (`podman image prune`).
* **SELinux** (Fedora, RHEL): bind mounts need a label; if containers cannot read
  `data/`, add `:Z` to the volumes in `docker-compose.yml`.
