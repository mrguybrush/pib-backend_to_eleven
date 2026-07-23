import docker


def reboot_host() -> None:
    """Startet den kompletten Host (den Raspberry Pi) neu.

    Der flask-app-Container selbst kann den Host nicht direkt rebooten, hat
    aber die Docker-Socket gemountet. Deshalb wird ein kurzlebiger,
    privilegierter Helfer-Container gestartet, der ueber den Host-PID-
    Namespace in die Namespaces von PID 1 (Host-init) wechselt und dort
    /sbin/reboot aufruft. Wiederverwendet das ohnehin vorhandene
    flask_api-Image, damit nichts nachgeladen werden muss."""
    client = docker.from_env()
    client.containers.run(
        image="flask_api",
        command=[
            "nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p",
            "--", "/sbin/reboot",
        ],
        privileged=True,
        pid_mode="host",
        remove=True,
        detach=True,
    )


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
