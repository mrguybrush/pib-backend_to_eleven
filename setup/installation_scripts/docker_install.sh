#!/bin/bash

# This script is responsible to setup the Docker Engine + Containers to run Cerebra
# To properly run it, is relies on being sourced by the setup-pib.sh script
# Also see: https://github.com/docker/docker-install for a more comprehensive docker installation script


version_gte() {
	if [ -z "$VERSION" ]; then
			return 0
	fi
	version_compare "$VERSION" "$1"
}

# create a systemd-service that adds the 'local:'-host to the x-server's access-control-list on each startup,
# allowing applications from within a docker container to access the x-server on the host os
function create_xhost_service() {
    # cp statt mv: die Vorlage muss im Repo erhalten bleiben, sonst
    # zerstoert der erste Install die Quelle und ein zweiter Install (oder
    # ein frischer Clone auf einem anderen System) findet die Datei nicht
    # mehr -> xhost-Service wird nie erstellt -> der ros-display-Container
    # bekommt keinen Zugriff auf den X-Server und laeuft im Crash-Loop
    # ("Authorization required, cannot connect to X server").
    sudo cp "$BACKEND_DIR/setup/setup_files/xhost_enable_local.service" /etc/systemd/xhost_enable_local.service
    sudo chmod 700 /etc/systemd/xhost_enable_local.service
    sudo systemctl enable /etc/systemd/xhost_enable_local.service --now
}

# create a systemd-service that sets the default audio output to 100% and
# unmutes it on each boot - a fresh install often starts far too quiet
function create_audio_volume_service() {
    sudo cp "$BACKEND_DIR/setup/setup_files/pib_audio_volume.service" /etc/systemd/system/pib_audio_volume.service
    sudo chmod 644 /etc/systemd/system/pib_audio_volume.service
    sudo systemctl daemon-reload
    sudo systemctl enable pib_audio_volume.service --now
}


# Installs the Docker Engine on supported linux distributions (ubuntu, debian, raspbian)
function install_docker_engine() {
    print INFO "Installing Docker Engine"

    local sh_c='sudo sh -c'
    if command_exists docker; then
        print WARN "Docker Engine already installed; skipping installation"
        return
    fi

    print INFO "Installing Docker Engine for ${DISTRIBUTION} ${DIST_VERSION}"
    print INFO "$USER"

    # Install Docker Engine
    apt_repo="deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$DISTRIBUTION $DIST_VERSION stable"
    (
        $sh_c 'apt-get update -qq >/dev/null'
        $sh_c "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq apt-transport-https ca-certificates curl >/dev/null"
        $sh_c 'install -m 0755 -d /etc/apt/keyrings'
        $sh_c "curl -fsSL \"https://download.docker.com/linux/$DISTRIBUTION/gpg\" -o /etc/apt/keyrings/docker.asc"
        $sh_c "chmod a+r /etc/apt/keyrings/docker.asc"
        $sh_c "echo \"$apt_repo\" > /etc/apt/sources.list.d/docker.list"
        $sh_c 'apt-get update -qq >/dev/null'
    )
    pkg_version=""
    if [ -n "$VERSION" ]; then
        pkg_pattern="$(echo "$VERSION" | sed 's/-ce-/~ce~.*/g' | sed 's/-/.*/g')"
        search_command="apt-cache madison docker-ce | grep '$pkg_pattern' | head -1 | awk '{\$1=\$1};1' | cut -d' ' -f 3"
        pkg_version="$($sh_c "$search_command")"
        if [ -z "$pkg_version" ]; then
            print ERROR "${VERSION} not found"
            return 1
        fi
        if version_gte "18.09"; then
            search_command="apt-cache madison docker-ce-cli | grep '$pkg_pattern' | head -1 | awk '{\$1=\$1};1' | cut -d' ' -f 3"
            cli_pkg_version="=$($sh_c "$search_command")"
        fi
        pkg_version="=$pkg_version"
    fi

    (
        pkgs="docker-ce${pkg_version%=}"
        if version_gte "18.09"; then
            pkgs="$pkgs docker-ce-cli${cli_pkg_version%=} containerd.io"
        fi
        if version_gte "20.10"; then
            pkgs="$pkgs docker-compose-plugin docker-ce-rootless-extras$pkg_version"
        fi
        if version_gte "23.0"; then
            pkgs="$pkgs docker-buildx-plugin"
        fi
        $sh_c "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $pkgs >/dev/null"
    )
    print SUCCESS "Docker Engine installed"
}

function setup_docker_cleaner_service() {
    print INFO "Setting up Docker container cleanup service"
    sudo cp "$BACKEND_DIR/setup/setup_files/docker_cleaner.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable docker_cleaner.service
    sudo systemctl start docker_cleaner.service
    print SUCCESS "Docker container cleanup service installed and started"
}

# Baut jeden Compose-Service einzeln nacheinander statt in einem einzigen
# "docker compose build" - Compose V2 buendelt einen Multi-Service-Build zu
# EINEM Aufruf an BuildKit/buildx, das die Ziele weitgehend selbst und
# parallel einplant; COMPOSE_PARALLEL_LIMIT wirkt darauf nicht (das begrenzt
# nur Nicht-Build-Operationen wie "up"/"pull"). Auf einem Raspberry Pi kam es
# dadurch trotz gesetztem Limit zu 6+ gleichzeitigen Builds - Folge waren
# teils >1h fuer einzelne apt-Schritte und ein BuildKit/containerd-Fehler
# ("failed call to UtimesNanoAt ... no such file or directory", eine
# Snapshot-Race unter Storage-Last), der nach 3 vollen Versuchen den
# kompletten Start scheitern liess (0 Container liefen). Ein Service pro
# "docker compose build <name>"-Aufruf ist die einzige Garantie fuer
# echte Sequenzialitaet.
# phase_label: nur fuer die Fortschrittsanzeige ("Backend"/"Frontend").
# guessed_count: setup-pib.sh's grobe Schaetzung fuer diese Phase (siehe
# dessen initiales progress_start) - wird hier auf den echten Wert korrigiert.
function docker_compose_build_sequential() {
    local compose_file="$1"
    local phase_label="$2"
    local guessed_count="$3"
    shift 3
    local service services
    services="$(sudo docker compose -f "$compose_file" "$@" config --services)" \
        || { print ERROR "konnte Service-Liste aus $compose_file nicht lesen"; return 1; }

    # Die tatsaechliche Service-Anzahl ist erst jetzt bekannt (braucht die
    # geklonten Repos + Docker) - progress_step haelt die Anzeige unabhaengig
    # davon monoton steigend, auch wenn die Korrektur die Schaetzung uebertrifft.
    local count
    count="$(echo "$services" | wc -w)"
    progress_add_total "$((count - guessed_count))"

    for service in $services; do
        progress_step "Baue $service ($phase_label)"
        local attempt built=0
        for attempt in 1 2 3; do
            if sudo docker compose -f "$compose_file" "$@" build "$service"; then
                built=1
                break
            fi
            print WARN "Build von '$service' fehlgeschlagen (Versuch ${attempt}/3), neuer Versuch in 15s..."
            sleep 15
        done
        [ "$built" = "1" ] || { print ERROR "Build von '$service' nach 3 Versuchen fehlgeschlagen"; return 1; }
    done
}

# Startet Container ueber bereits gebaute Images (kein --build hier - das
# passiert vorher sequentiell in docker_compose_build_sequential). Bis zu 3
# Versuche, falls z.B. ein Container beim ersten Start noch auf einen
# anderen wartet. --force-recreate erzwingt einen Neustart auch fuer
# Services, deren Image sich nicht geaendert hat (z.B. das Frontend), damit
# sie z.B. den Hostnamen eines gerade neu gebauten Backend-Containers frisch
# aufloesen statt dessen alte Docker-interne IP weiter zu benutzen (nginx
# cached die Aufloesung sonst fuer die gesamte Prozesslaufzeit).
function docker_compose_up_retry() {
    local compose_file="$1"
    shift
    local attempt
    for attempt in 1 2 3; do
        if sudo docker compose -f "$compose_file" "$@" up -d --force-recreate; then
            return 0
        fi
        print WARN "docker compose up fehlgeschlagen (Versuch ${attempt}/3), neuer Versuch in 15s..."
        sleep 15
    done
    return 1
}

# Baut das gemeinsame ROS-Basis-Image (siehe ros_packages/base/Dockerfile),
# von dem 9 der 10 Backend-Dockerfiles per "FROM pib-ros-base:humble" erben
# (nur camera erbt von luxonis/depthai-ros und braucht es nicht). Muss vor
# docker_compose_build_sequential fuer's Backend laufen, sonst schlagen deren
# Builds mit "pib-ros-base:humble: not found" fehl. Vorher installierte jedes
# der 9 Images build-essential/colcon-Erweiterungen/pip/curl unabhaengig -
# identischer Inhalt, aber 9x heruntergeladen/entpackt (der groesste Teil der
# Gesamt-Bauzeit) und 9x eine eigene Angriffsflaeche fuer transiente apt-
# Fehler. Einmal hier bauen spart beides.
function build_ros_base_image() {
    progress_step "Gemeinsames ROS-Basis-Image bauen"
    local attempt
    for attempt in 1 2 3; do
        if sudo docker build -t pib-ros-base:humble -f "$BACKEND_DIR/ros_packages/base/Dockerfile" "$BACKEND_DIR"; then
            return 0
        fi
        print WARN "Bau des ROS-Basis-Image fehlgeschlagen (Versuch ${attempt}/3), neuer Versuch in 15s..."
        sleep 15
    done
    return 1
}

function start_container() {
    print INFO "Starting container"
    echo "TRYB_URL_PREFIX=https://platform.tryb.ai" > "$BACKEND_DIR"/password.env
    build_ros_base_image || { print ERROR "failed to build shared ROS base image"; return 1; }
    docker_compose_build_sequential "$BACKEND_DIR/docker-compose.yaml" "Backend" 10 --profile all || return 1
    progress_step "Backend-Container starten"
    docker_compose_up_retry "$BACKEND_DIR/docker-compose.yaml" --profile all || return 1
    print SUCCESS "Started pib-backend container"
    docker_compose_build_sequential "$FRONTEND_DIR/docker-compose.yaml" "Frontend" 1 || return 1
    progress_step "Cerebra-Container starten"
    docker_compose_up_retry "$FRONTEND_DIR/docker-compose.yaml" || return 1
    print SUCCESS "Started cerebra container"
}

progress_step "X-Server-Zugriff fuer Docker einrichten"
create_xhost_service || print ERROR "failed to create service for xhost permission management"
progress_step "Lautstaerke-Dienst einrichten"
create_audio_volume_service || print ERROR "failed to create audio volume service"
progress_step "Docker Engine installieren"
install_docker_engine || print ERROR "failed to install docker engine"
start_container || print ERROR "failed to start containers"
progress_step "Docker-Aufraeumdienst einrichten"
setup_docker_cleaner_service || print ERROR "failed to setup docker cleaner service"
progress_step "Datenbank-Berechtigungen setzen"
# Die DB wird von flask-app beim ersten Start angelegt (Bind-Mount). Nur
# chmod'en, wenn sie schon da ist - sonst bricht der Install mit
# "No such file or directory" ab, falls der Container-Build/-Start (noch)
# nicht durchlief.
if [ -f "$BACKEND_DIR/pib_api/flask/pibdata.db" ]; then
    sudo chmod 777 "$BACKEND_DIR/pib_api/flask/pibdata.db"
fi