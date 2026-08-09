# Grafana dashboards for the Portainer/GHCR deployment path

## Problem

`docker/docker-compose.yml`'s `grafana` service (added in the historian +
Grafana dashboards feature, PR #25) provisions its InfluxDB datasource and 3
dashboards via bind-mounted host files (`./grafana/provisioning`,
`./grafana/dashboards`). `docker/docker-compose.portainer.yml` — a separate,
pre-existing file this repo's live Portainer deployment actually uses — is
explicitly built around "pre-built GHCR image, no build step, no host bind
mounts" (its own header comment) and has no `grafana` service at all.
`COMPOSE_PROFILES=influx` brings up InfluxDB there today (it already
supports the `influx`/`graph` profiles), but nothing surfaces the dashboards
for that deployment path.

## Approach

Publish a small companion image, `ghcr.io/paupier/simengine-grafana`,
alongside the existing `ghcr.io/paupier/simengine` image — a stock
`grafana/grafana` base with the existing provisioning/dashboard files
`COPY`'d in at build time. This was chosen over inlining the provisioning
YAML and 3 dashboard JSONs as a startup heredoc (the pattern this file's
`mosquitto` service already uses for its own config) because that would
duplicate the ~250-line-per-dashboard JSON content that
`docker/grafana/dashboards/*.json` already owns, with no mechanism to keep
the two copies in sync. The custom-image approach has one source of truth —
`docker/grafana/{provisioning,dashboards}/` — built fresh by CI on every
push to `main`, exactly like `simengine` itself.

## Components

**`docker/grafana/Dockerfile`** (new):
```dockerfile
FROM grafana/grafana:11.3.0
COPY provisioning/ /etc/grafana/provisioning/
COPY dashboards/ /var/lib/grafana/dashboards/
```
No build args. The datasource YAML's `${INFLUXDB_TOKEN}`/`${INFLUXDB_ORG}`/
`${INFLUXDB_BUCKET}` placeholders are resolved by Grafana at container
*runtime* from its own environment — identical mechanism whether the file
arrived via bind-mount or `COPY`, so no Dockerfile-side templating is
needed. No Grafana state volume: dashboards are provisioned (file-based),
not user-created, so there's nothing to persist across restarts — matches
the existing `docker-compose.yml` Grafana service, which is equally
stateless.

**`.github/workflows/publish-image.yml`** (modified): restructured from a
single `build-and-push` job into a `strategy.matrix` over two entries —
`simengine` (context `.`, file `docker/Dockerfile`, build-args
`EXTRAS=historian-influx,historian-neo4j,sparkplug,chat`) and
`simengine-grafana` (context `docker/grafana`, file
`docker/grafana/Dockerfile`, no build-args). Both entries share the same
trigger (push to `main`, `v*` tags, `workflow_dispatch`) and the same tag
scheme (`latest` on default branch, `main-<shortsha>`, semver on tags) via
per-entry `docker/metadata-action` invocations keyed off
`ghcr.io/paupier/${{ matrix.image-name }}`. A push to `main` republishes
both images together, so they can never drift out of tag-sync with each
other the way two independently-triggered workflows could.

**`docker/docker-compose.portainer.yml`** (modified): new `grafana`
service —
```yaml
  grafana:
    image: ghcr.io/paupier/simengine-grafana:latest
    profiles: ["influx"]
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: Viewer
      INFLUXDB_TOKEN: ${INFLUXDB_TOKEN:-simengine-dev-token}
      INFLUXDB_ORG: simengine
      INFLUXDB_BUCKET: manufacturing
    depends_on:
      influxdb:
        condition: service_healthy
```
matching the existing `docker-compose.yml` Grafana service's env/profile/
health-gating exactly, minus the two bind-mounted `volumes:` entries (not
needed — the files are already inside the image). Anonymous Viewer access,
same as `docker-compose.yml` and the same repo-wide no-auth posture this
whole feature already established.

The file's header comment (`COMPOSE_PROFILES=influx (adds InfluxDB)`) is
updated to `(adds InfluxDB + Grafana)`.

## Out of scope

- No change to `docker/docker-compose.yml` or the existing
  `docker/grafana/{provisioning,dashboards}/` content — this follow-up only
  adds a second consumer (the Portainer/GHCR path) of files that already
  exist and are already reviewed.
- No new scenario-config or historian behavior — `historians: ["influx"]`
  still has to be set on whichever scenario is run, same as the
  `docker-compose.yml` path; not something a Grafana image change can fix.
- No Grafana authentication — out of scope for this repo's stated
  single-operator, no-auth posture (already the case for
  `docker-compose.yml`'s Grafana service).

## Testing

- `docker build -f docker/grafana/Dockerfile docker/grafana` builds cleanly
  and the resulting image's `/etc/grafana/provisioning/` and
  `/var/lib/grafana/dashboards/` contain the expected files (`docker run
  --rm <image> ls -R /etc/grafana/provisioning /var/lib/grafana/dashboards`).
- `.github/workflows/publish-image.yml`'s matrix restructuring is validated
  by GitHub Actions' own workflow syntax check on push (`act` or a
  `workflow_dispatch` dry-run if available locally; otherwise validated by
  the first real CI run after merge, same as any workflow change).
- `docker compose -f docker/docker-compose.portainer.yml config --profile
  influx` (no image pull required) confirms valid YAML and the new
  `grafana` service rendering correctly.
- End-to-end: after the workflow publishes both images once, pull
  `ghcr.io/paupier/simengine-grafana:latest` and bring up the Portainer
  compose file's `influx` profile locally, confirm Grafana serves the same
  3 dashboards `docker-compose.yml`'s path already validated.
