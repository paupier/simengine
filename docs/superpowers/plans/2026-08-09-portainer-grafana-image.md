# Portainer/GHCR Grafana Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 3 Grafana dashboards (already shipped for the local `docker-compose.yml` path) available on the Portainer/GHCR-pull deployment path, via a companion pre-built image instead of bind-mounted files.

**Architecture:** A new `docker/grafana/Dockerfile` (`FROM grafana/grafana`, `COPY`s the existing `docker/grafana/provisioning/` and `docker/grafana/dashboards/` in) gets built and published to `ghcr.io/paupier/simengine-grafana` by extending the existing `publish-image.yml` workflow into a 2-entry matrix (alongside the existing `simengine` image build), so both images always ship together on every push to `main`. `docker/docker-compose.portainer.yml` gets a new `grafana` service referencing that image, with no volumes — the files are already baked in.

**Tech Stack:** Docker, GitHub Actions (`docker/build-push-action`, `docker/metadata-action`), Docker Compose.

## Global Constraints

- No build args on the `simengine-grafana` image — the datasource YAML's `${INFLUXDB_TOKEN}`/`${INFLUXDB_ORG}`/`${INFLUXDB_BUCKET}` are resolved by Grafana at container *runtime* from its own environment, not at build time.
- No new Grafana state volume — dashboards are provisioned (file-based), nothing to persist across restarts.
- Both matrix entries (`simengine`, `simengine-grafana`) must share the same trigger and tag scheme (`latest` on default branch, `main-<shortsha>`, semver on `v*` tags) so a push to `main` always republishes both in sync.
- GitHub Actions cache (`type=gha`) must be **scoped per matrix entry** (`scope: ${{ matrix.image }}` on both `cache-from` and `cache-to`) — without this, the two matrix jobs' build caches collide since they'd otherwise share the same default cache scope.
- `docker-compose.portainer.yml`'s new `grafana` service must match the existing `docker-compose.yml` Grafana service's `environment`/`profiles`/`depends_on` exactly (same values), differing only in `image:` (GHCR pull vs. no `build:`) and the absence of `volumes:`.

---

### Task 1: `docker/grafana/Dockerfile`

**Files:**
- Create: `docker/grafana/Dockerfile`

**Interfaces:**
- Produces: a buildable image containing `/etc/grafana/provisioning/datasources/influxdb.yml`, `/etc/grafana/provisioning/dashboards/dashboards.yml`, and `/var/lib/grafana/dashboards/{line_overview,station_kpis,root_cause}.json` — Task 3's compose service assumes these paths exist inside the image with no volume mounts.

- [ ] **Step 1: Create the Dockerfile**

Create `docker/grafana/Dockerfile`:

```dockerfile
FROM grafana/grafana:11.3.0
COPY provisioning/ /etc/grafana/provisioning/
COPY dashboards/ /var/lib/grafana/dashboards/
```

- [ ] **Step 2: Build it locally**

Run: `docker build -f docker/grafana/Dockerfile -t simengine-grafana-test docker/grafana`
Expected: build completes successfully (pulls `grafana/grafana:11.3.0`, two `COPY` layers, no errors).

- [ ] **Step 3: Verify the expected files are present in the built image**

Run:
```bash
docker run --rm simengine-grafana-test sh -c \
  "ls /etc/grafana/provisioning/datasources/influxdb.yml \
      /etc/grafana/provisioning/dashboards/dashboards.yml \
      /var/lib/grafana/dashboards/line_overview.json \
      /var/lib/grafana/dashboards/station_kpis.json \
      /var/lib/grafana/dashboards/root_cause.json"
```
Expected: all 5 paths printed, no "No such file or directory" errors, exit code 0.

- [ ] **Step 4: Clean up the local test image**

Run: `docker rmi simengine-grafana-test`

- [ ] **Step 5: Commit**

```bash
git add docker/grafana/Dockerfile
git commit -m "feat: add Dockerfile for the companion Grafana GHCR image"
```

---

### Task 2: Restructure `publish-image.yml` into a matrix

**Files:**
- Modify: `.github/workflows/publish-image.yml` (entire `jobs:` block, plus the header comment)

**Interfaces:**
- Consumes: `docker/grafana/Dockerfile` from Task 1 (referenced by the new matrix entry's `file:`).
- Produces: on push to `main`, publishes both `ghcr.io/paupier/simengine:latest` (unchanged behavior) and `ghcr.io/paupier/simengine-grafana:latest` (new) — Task 3's compose service references the latter by exact tag.

- [ ] **Step 1: Rewrite the workflow file**

Replace the entire contents of `.github/workflows/publish-image.yml` with:

```yaml
name: Publish image

# Builds the simengine container and its companion Grafana image, and pushes
# both to GitHub Container Registry:
#   ghcr.io/paupier/simengine           — the engine + REST/UI + OPC UA
#   ghcr.io/paupier/simengine-grafana   — grafana/grafana with this repo's
#                                          Influx datasource + 3 dashboards
#                                          baked in (docker/grafana/)
# Portainer then pulls these pre-built images instead of building from the
# repo. Both images always publish together on the same trigger, so they
# never drift out of tag-sync with each other.
#
# Tags produced (for both images):
#   - `latest`            on every push to main
#   - `main-<shortsha>`   on every push to main (immutable, for pinning)
#   - `vX.Y.Z` + `X.Y`    when you push a git tag like v0.2.0
# Trigger a rebuild by hand from the Actions tab via "Run workflow".

on:
  push:
    branches: [ main ]
    tags: [ 'v*' ]
  workflow_dispatch:

env:
  REGISTRY: ghcr.io

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write        # required to push to GHCR
    strategy:
      fail-fast: false
      matrix:
        include:
          - image: simengine
            context: .
            file: docker/Dockerfile
            # All optional extras baked in so the deployed image works
            # whether the stack enables influx, graph, SparkplugB, or the
            # assistant chat.
            build-args: |
              EXTRAS=historian-influx,historian-neo4j,sparkplug,chat
          - image: simengine-grafana
            context: docker/grafana
            file: docker/grafana/Dockerfile
            build-args: ""

    steps:
    - uses: actions/checkout@v5

    # Creates a buildx builder on the docker-container driver. Required for the
    # type=gha build cache below — the runner's default `docker` driver cannot
    # export cache and buildx aborts ("Cache export is not supported for the
    # docker driver").
    - name: Set up Buildx
      uses: docker/setup-buildx-action@v4

    - name: Log in to GHCR
      uses: docker/login-action@v4
      with:
        registry: ${{ env.REGISTRY }}
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}   # auto-provided, no PAT needed

    - name: Derive image tags and labels
      id: meta
      uses: docker/metadata-action@v6
      with:
        images: ${{ env.REGISTRY }}/${{ github.repository_owner }}/${{ matrix.image }}
        tags: |
          type=raw,value=latest,enable={{is_default_branch}}
          type=sha,prefix=main-,enable={{is_default_branch}}
          type=semver,pattern={{version}}
          type=semver,pattern={{major}}.{{minor}}

    - name: Build and push
      uses: docker/build-push-action@v7
      with:
        context: ${{ matrix.context }}
        file: ${{ matrix.file }}
        push: true
        build-args: ${{ matrix.build-args }}
        tags: ${{ steps.meta.outputs.tags }}
        labels: ${{ steps.meta.outputs.labels }}
        cache-from: type=gha,scope=${{ matrix.image }}
        cache-to: type=gha,mode=max,scope=${{ matrix.image }}
```

- [ ] **Step 2: Validate YAML syntax locally**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/publish-image.yml'))" && echo "valid YAML"`
Expected: `valid YAML`, no exceptions.

- [ ] **Step 3: Validate with GitHub's own workflow linter if available**

Run: `gh workflow view "Publish image" 2>&1 || echo "gh cannot preview unpushed workflow changes — will be validated on first real push, per this task's note in the design doc"`
Expected: either a clean view (if `gh` can resolve it against the pushed branch) or the fallback message — this workflow change cannot be fully validated without a real GitHub Actions run, since there's no local GHA emulator installed in this environment. Note this explicitly in your task report as a known gap closed only by the first real CI run after merge (matches this plan's spec's own "Testing" section, which flags the same thing).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/publish-image.yml
git commit -m "feat: publish a companion simengine-grafana GHCR image via workflow matrix"
```

---

### Task 3: `grafana` service in `docker-compose.portainer.yml`

**Files:**
- Modify: `docker/docker-compose.portainer.yml` (header comment lines 1-10; add a new `grafana:` service after the `influxdb:` service, before `neo4j:`)

**Interfaces:**
- Consumes: `ghcr.io/paupier/simengine-grafana:latest` (Task 2's published image — not yet published at the time this task runs locally, since publishing only happens on a real push to `main`; this task's own validation is YAML/config-only, not a real `docker compose up`, per Step 3 below).

- [ ] **Step 1: Update the header comment**

In `docker/docker-compose.portainer.yml`, change lines 5-8 from:

```yaml
# Optional services are gated behind compose profiles. Portainer has no profile
# toggle in the UI, so enable them by adding this stack environment variable:
#   COMPOSE_PROFILES=influx        (adds InfluxDB)
#   COMPOSE_PROFILES=influx,graph  (adds InfluxDB + Neo4j)
```

to:

```yaml
# Optional services are gated behind compose profiles. Portainer has no profile
# toggle in the UI, so enable them by adding this stack environment variable:
#   COMPOSE_PROFILES=influx        (adds InfluxDB + Grafana)
#   COMPOSE_PROFILES=influx,graph  (adds InfluxDB + Grafana + Neo4j)
```

- [ ] **Step 2: Add the `grafana` service**

In `docker/docker-compose.portainer.yml`, insert immediately after the `influxdb:` service's block (after its `healthcheck:` section, before the `neo4j:` service):

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

- [ ] **Step 3: Validate the compose file parses**

Run: `docker compose -f docker/docker-compose.portainer.yml config --profile influx`
Expected: valid YAML output showing the `grafana` service with the fields above, alongside `simengine`, `mosquitto`, and `influxdb`. This does not pull any images or start any containers — `config` only validates and renders the merged config, so it works even though `ghcr.io/paupier/simengine-grafana:latest` doesn't exist yet (Task 2's workflow only publishes it on the next real push to `main`).

- [ ] **Step 4: Commit**

```bash
git add docker/docker-compose.portainer.yml
git commit -m "feat: add grafana service to the Portainer compose stack"
```
