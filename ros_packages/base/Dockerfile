# Gemeinsames Basis-Image fuer alle ROS-Humble-Container (ausser camera, das
# von luxonis/depthai-ros erbt). build-essential, colcon-Erweiterungen, pip
# und curl wurden bisher in jedem der ~8 einzelnen Service-Dockerfiles separat
# per "apt-get update && apt-get install ..." installiert - identischer
# Inhalt, aber 8x eigenstaendig heruntergeladen/entpackt (der groesste Teil
# der Gesamt-Bauzeit) und 8x eine eigene Angriffsflaeche fuer transiente
# apt/Netzwerk-Fehler. Einmal hier bauen (siehe docker_install.sh, das dieses
# Image vor den eigentlichen Services baut), ueberall per
# "FROM pib-ros-base:humble" wiederverwenden.
FROM ros:humble-ros-core

SHELL ["/bin/bash", "-c"]

RUN apt-get update && apt-get install --no-install-recommends -y \
    build-essential \
    python3-colcon-common-extensions \
    python3-colcon-mixin \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*
