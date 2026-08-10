"""Cross-file consistency checks for the docker/ configs.

Nothing here talks to Docker -- these are plain-text checks that two
independently-maintained files agree on values nothing else keeps in sync.
"""
import re
from pathlib import Path

DOCKER_DIR = Path(__file__).resolve().parent.parent / "docker"


def _grafana_image_tag(text: str) -> str:
    match = re.search(r"grafana/grafana:(\S+)", text)
    assert match, "no grafana/grafana:<tag> reference found"
    return match.group(1)


class TestGrafanaVersionPin:
    def test_dockerfile_and_compose_pin_the_same_grafana_version(self):
        dockerfile_tag = _grafana_image_tag(
            (DOCKER_DIR / "grafana" / "Dockerfile").read_text())
        compose_tag = _grafana_image_tag(
            (DOCKER_DIR / "docker-compose.yml").read_text())
        assert dockerfile_tag == compose_tag, (
            f"docker/grafana/Dockerfile pins grafana/grafana:{dockerfile_tag} "
            f"but docker/docker-compose.yml pins grafana/grafana:{compose_tag} "
            "-- the baked-in image (Portainer/GHCR path) and the bind-mounted "
            "dev service (local docker-compose.yml path) should run the same "
            "Grafana version. Bump whichever one is behind."
        )


# Matches ${VARNAME:-default}. `default` may be empty (e.g. ${SIMENGINE_EXTRAS:-}).
_VAR_DEFAULT_RE = re.compile(r"\$\{([A-Z0-9_]+):-([^}]*)\}")


def _var_defaults(text: str) -> dict:
    """varname -> set of distinct default values used for it in this file."""
    defaults: dict = {}
    for name, default in _VAR_DEFAULT_RE.findall(text):
        defaults.setdefault(name, set()).add(default)
    return defaults


class TestComposeEnvDefaultsAreSelfConsistent:
    """Two services in the same compose file referencing the same env var
    (e.g. simengine's NEO4J_PASSWORD used to connect, neo4j's own
    NEO4J_PASSWORD used to set its own auth) must fall back to the same
    default when the var is unset -- docker compose resolves each
    ${VAR:-default} independently, so mismatched defaults silently produce
    two different containers that can't authenticate to each other. This
    caught a real bug: docker-compose.yml's simengine service defaulted
    NEO4J_PASSWORD to empty while the neo4j service itself defaulted to
    "simengine-dev"."""

    def _assert_self_consistent(self, path: Path) -> None:
        defaults = _var_defaults(path.read_text())
        conflicts = {name: sorted(vals) for name, vals in defaults.items()
                     if len(vals) > 1}
        assert not conflicts, (
            f"{path.name} uses different ${{VAR:-default}} fallbacks for the "
            f"same variable(s) in different places: {conflicts} -- when the "
            "variable is unset, each occurrence resolves independently, so "
            "services relying on the same credential/value can silently "
            "diverge. Make every occurrence of each variable use the same "
            "default."
        )

    def test_docker_compose_yml(self):
        self._assert_self_consistent(DOCKER_DIR / "docker-compose.yml")

    def test_docker_compose_portainer_yml(self):
        self._assert_self_consistent(DOCKER_DIR / "docker-compose.portainer.yml")
