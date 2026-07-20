# Deployment (Docker / Portainer)

Two compose files:

| File | Use |
|---|---|
| `docker/docker-compose.yml` | Local dev — **builds** the image from source (`docker compose up --build`), bind-mounts the repo. |
| `docker/docker-compose.portainer.yml` | **Portainer / any host** — pulls a pre-built image from GHCR, no build step, no host bind mounts. |

## How the GHCR flow works (new-to-you version)

You used to point Portainer at the GitHub repo and let it build. The registry flow moves the build to GitHub:

```
push to main ─▶ GitHub Actions builds the image ─▶ pushes ghcr.io/paupier/simengine:latest
                                                          │
                                       Portainer pulls that image ──▶ runs the stack
```

The build happens once, in CI, on a full amd64 runner — Portainer just pulls a finished image. Your "re-pull as needed" habit still applies; it's now "re-pull the image" instead of "rebuild from git".

`.github/workflows/publish-image.yml` does the publishing. It runs on every push to `main` (and on `v*` tags) and needs no secrets — GitHub's built-in `GITHUB_TOKEN` can push to your own `ghcr.io/paupier/*`. Tags produced:

- `latest` — moves with `main`
- `main-<shortsha>` — immutable, for pinning a known-good build
- `vX.Y.Z` + `X.Y` — when you push a git tag like `v0.2.0`

You can also trigger a build by hand: repo → **Actions** → *Publish image* → **Run workflow**.

## One-time setup

1. **Push these files to `main`.** The first workflow run publishes the image and creates the package at `github.com/paupier/simengine` → **Packages** (right sidebar).
2. **Make the package public** (simplest for a homelab): package page → **Package settings** → **Danger Zone** → **Change visibility** → **Public**. Now Portainer can pull it with no credentials.
   - *Alternative if you'd rather keep it private:* in Portainer, **Registries** → **Add registry** → **Custom**, URL `ghcr.io`, username = your GitHub username, password = a Personal Access Token with the `read:packages` scope. Then the stack can pull the private image.

## Deploy the stack in Portainer

**Stacks** → **Add stack** → name it `simengine`, then either:

- **Web editor:** paste the contents of `docker/docker-compose.portainer.yml`, or
- **Git repository:** repository URL `https://github.com/paupier/simengine`, compose path `docker/docker-compose.portainer.yml`.

Optional services are behind compose profiles (Portainer has no profile toggle), so to enable them add a stack **environment variable**:

| To run | Set |
|---|---|
| simengine + mosquitto (default) | *(nothing)* |
| + InfluxDB historian | `COMPOSE_PROFILES=influx` |
| + InfluxDB + Neo4j | `COMPOSE_PROFILES=influx,graph` |

Any other default (passwords, tokens) can be overridden with stack environment variables — see the `${VAR:-default}` entries in the compose file. **Change `INFLUXDB_TOKEN` / `NEO4J_PASSWORD` off the dev defaults for anything exposed.**

Deploy. Ports: **8080** web UI + REST, **4840** OPC UA, **8765** MCP, **1883/9001** MQTT (+ **8086** InfluxDB / **7474** Neo4j when those profiles are on).

## Updating to a new build

After you push changes to `main` and the workflow republishes `:latest`:

- Portainer → the `simengine` stack → **Editor** tab → **Pull and redeploy** (toggle *Re-pull image*), or
- **Images** → pull `ghcr.io/paupier/simengine:latest`, then recreate the stack.

To pin instead of tracking `latest`, change the stack's image tag to a specific `main-<shortsha>` or `vX.Y.Z`.

## Notes

- The image bakes in all optional extras (`historian-influx`, `historian-neo4j`, `sparkplug`, `chat`), so every comms protocol, both historians, and the assistant page work without a rebuild — the assistant still needs your own Anthropic key, entered in the browser.
- `simengine-config` and `simengine-results` are named volumes. On first run they seed from the image (default scenarios + recipes); after that, scenario/recipe edits made through the UI and any CSV historian output persist across redeploys. To reset to the shipped defaults, remove those volumes.
- The build defaults to `linux/amd64`. For an arm64 host (e.g. a Pi), add `platforms: linux/amd64,linux/arm64` to the `build-and-push` step in the workflow (needs a QEMU setup step; slower builds).
