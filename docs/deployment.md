# Deployment (Docker / Portainer)

Two compose files:

| File | Use |
|---|---|
| `docker/docker-compose.yml` | Local dev — **builds** the image from source (`docker compose up --build`), bind-mounts the repo. |
| `docker/docker-compose.portainer.yml` | **Portainer / any host** — pulls pre-built images from GHCR, no build step, no host bind mounts. |

## How the GHCR flow works (new-to-you version)

You used to point Portainer at the GitHub repo and let it build. The registry flow moves the build to GitHub:

```
push to main ─▶ GitHub Actions builds two images ─▶ pushes ghcr.io/paupier/simengine:latest
                                                     ─▶ pushes ghcr.io/paupier/simengine-grafana:latest
                                                          │
                                       Portainer pulls those images ──▶ runs the stack
```

The build happens once, in CI, on a full amd64 runner — Portainer just pulls finished images. Your "re-pull as needed" habit still applies; it's now "re-pull the images" instead of "rebuild from git".

`.github/workflows/publish-image.yml` does the publishing, as a build matrix over both images: `simengine` (the engine + REST/UI + OPC UA) and `simengine-grafana` (a `grafana/grafana` base with this repo's InfluxDB datasource + 3 dashboards baked in — see `docker/grafana/Dockerfile`). Both publish together on every push to `main` (and on `v*` tags) so they never drift out of tag-sync with each other, and it needs no secrets — GitHub's built-in `GITHUB_TOKEN` can push to your own `ghcr.io/paupier/*`. Tags produced (for both images):

- `latest` — moves with `main`
- `main-<shortsha>` — immutable, for pinning a known-good build
- `vX.Y.Z` + `X.Y` — when you push a git tag like `v0.2.0`

You can also trigger a build by hand: repo → **Actions** → *Publish image* → **Run workflow**.

## One-time setup

1. **Push these files to `main`.** The first workflow run publishes **two** packages — `simengine` and `simengine-grafana` — at `github.com/paupier?tab=packages`.
2. **Make both packages public** (simplest for a homelab): each package page → **Package settings** → **Danger Zone** → **Change visibility** → **Public**. GHCR visibility is per-package, not inherited — making `simengine` public does *not* make `simengine-grafana` public, and a stack with `COMPOSE_PROFILES=influx` set will fail to pull the Grafana image with an unauthorized/denied error until you do this for both. Now Portainer can pull them with no credentials.
   - *Alternative if you'd rather keep them private:* in Portainer, **Registries** → **Add registry** → **Custom**, URL `ghcr.io`, username = your GitHub username, password = a Personal Access Token with the `read:packages` scope. Then the stack can pull both private images.

## Deploy the stack in Portainer

**Stacks** → **Add stack** → name it `simengine`, then either:

- **Web editor:** paste the contents of `docker/docker-compose.portainer.yml`, or
- **Git repository:** repository URL `https://github.com/paupier/simengine`, compose path `docker/docker-compose.portainer.yml`.

Optional services are behind compose profiles (Portainer has no profile toggle), so to enable them add a stack **environment variable**:

| To run | Set |
|---|---|
| simengine + mosquitto (default) | *(nothing)* |
| + InfluxDB + Grafana | `COMPOSE_PROFILES=influx` |
| + InfluxDB + Grafana + Neo4j | `COMPOSE_PROFILES=influx,graph` |

Any other default (passwords, tokens) can be overridden with stack environment variables — see the `${VAR:-default}` entries in the compose file. **Change `INFLUXDB_TOKEN` / `NEO4J_PASSWORD` off the dev defaults for anything exposed.** Grafana has no login (anonymous Viewer access, by design — matches every other interface in this stack) and its datasource holds the same `INFLUXDB_TOKEN`, which is InfluxDB's *admin* token, not read-only — don't expose port **3000** beyond your LAN.

Deploy. Ports: **8080** web UI + REST, **4840** OPC UA, **8765** MCP, **1883/9001** MQTT (+ **8086** InfluxDB / **3000** Grafana / **7474** Neo4j when those profiles are on).

## Updating to a new build

After you push changes to `main` and the workflow republishes `:latest` for both images:

- Portainer → the `simengine` stack → **Editor** tab → **Pull and redeploy** (toggle *Re-pull image* — this re-pulls every image in the stack, including `simengine-grafana` if the `influx` profile is on), or
- **Images** → pull `ghcr.io/paupier/simengine:latest` and `ghcr.io/paupier/simengine-grafana:latest`, then recreate the stack.

To pin instead of tracking `latest`, change the stack's image tag(s) to a specific `main-<shortsha>` or `vX.Y.Z` — both images are tagged in sync, so the same tag exists for both.

## Notes

- The `simengine` image bakes in all optional extras (`historian-influx`, `historian-neo4j`, `sparkplug`, `chat`), so every comms protocol, both historians, and the assistant page work without a rebuild — the assistant still needs your own Anthropic key, entered in the browser.
- The `simengine-grafana` image bakes in `docker/grafana/{provisioning,dashboards}/` at build time (no bind mounts, matching this file's pattern) — the same files `docker/docker-compose.yml`'s local-dev Grafana service bind-mounts directly. If you edit a dashboard JSON, it takes effect immediately for local dev but only reaches Portainer after the next push to `main` republishes the image.
- `simengine-config` and `simengine-results` are named volumes. On first run they seed from the image (default scenarios); after that, scenario edits made through the UI and any CSV historian output persist across redeploys. To reset to the shipped defaults, remove those volumes.
- The build defaults to `linux/amd64`. For an arm64 host (e.g. a Pi), add `platforms: linux/amd64,linux/arm64` to the `build-and-push` step in the workflow (needs a QEMU setup step; slower builds).
