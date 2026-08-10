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
