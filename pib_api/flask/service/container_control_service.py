import docker


def restart_service_container(compose_service_name: str) -> None:
    """Restarts the container belonging to the given Docker Compose service
    name. Needs /var/run/docker.sock mounted into this container (see
    docker-compose.yaml); callers must only ever pass a fixed, known-safe
    service name, never one derived from user input."""
    client = docker.from_env()
    containers = client.containers.list(
        filters={"label": f"com.docker.compose.service={compose_service_name}"}
    )
    if not containers:
        raise ValueError(
            f"Container für Service '{compose_service_name}' nicht gefunden."
        )
    containers[0].restart(timeout=10)
