#!/bin/bash

# Color definitions for logging
export ERROR="\e[31m"
export WARN="\e[33m"
export SUCCESS="\e[32m"
export INFO="\e[36m"
export RESET_TEXT_COLOR="\e[0m"
export NEW_LINE="\n"

# Github repositories - alle drei (FRONTEND/BACKEND/IMITATION) sind
# oeffentlich, ein einfacher https-Clone reicht, keine Deploy-Keys noetig.
export FRONTEND="https://github.com/mrguybrush/cerebra_to_eleven.git"
export BACKEND="https://github.com/mrguybrush/pib-backend_to_eleven.git"
export IMITATION="https://github.com/pib-rocks/imitation.git"
export APP_DIR="$HOME/app"
export BACKEND_DIR="$APP_DIR/pib-backend"
export FRONTEND_DIR="$APP_DIR/cerebra"
export IMITATION_DIR="$HOME/imitation"
export SETUP_INSTALLATION_DIR="$BACKEND_DIR/setup/installation_scripts"

# Function to support printing consistent log messages
function print() {
    local color=$1
    local text=$2

    # If only one argument is provided, assume it is the text
    if [ -z "$text" ]; then
        text=$color
        color="RESET_TEXT_COLOR"
    fi

    # Check if the provided color exists
    if [ -n "$color" ] && [ -z "${!color}" ]; then
        color="RESET_TEXT_COLOR"
    fi

    # Print the text in the specified color
    echo -e "${!color}[$(date -u)][[ ${text} ]]${RESET_TEXT_COLOR}"
}

function command_exists() {
    command -v "$@" >/dev/null 2>&1
}

# --- Grafische Fortschrittsanzeige (whiptail) -------------------------------
# Zeigt eine Fortschrittsleiste mit dem aktuellen Installationsschritt statt
# einer Wand aus rohem apt/docker-Output, und baut alles nacheinander statt
# gleichzeitig auf (siehe docker_compose_build_sequential in
# docker_install.sh). Faellt automatisch auf reines Text-Logging zurueck,
# wenn whiptail fehlt oder kein echtes Terminal vorhanden ist (z.B. wenn das
# Skript per "nohup ... &" ohne tty im Hintergrund laeuft).
PROGRESS_ENABLED=0
PROGRESS_TOTAL=0
PROGRESS_CURRENT=0
PROGRESS_MAX_SHOWN=0
PROGRESS_FIFO=""
PROGRESS_WHIPTAIL_PID=""

function progress_supported() {
  # NICHT "[ -t 1 ]" verwenden: stdout ist zu diesem Zeitpunkt schon per
  # "exec > >(tee -a $LOG_FILE) 2>&1" (siehe oben) auf eine Pipe umgeleitet,
  # also ist fd 1 nie ein Terminal, selbst in einer echten interaktiven
  # Sitzung. Whiptail zeichnet ohnehin direkt auf /dev/tty (siehe
  # progress_start) - massgeblich ist also, ob ueberhaupt ein steuerndes
  # Terminal existiert, nicht was fd 1 gerade ist.
  command_exists whiptail && { : </dev/tty; } 2>/dev/null
}

# progress_start <geschaetzte_gesamtschritte>
# Die genaue Schrittzahl steht erst fest, wenn die Docker-Compose-Services
# bekannt sind (nach clone_repositories + install_docker_engine); bis dahin
# reicht eine grobe Schaetzung, progress_add_total korrigiert sie spaeter.
# progress_step haelt die Anzeige unabhaengig davon monoton steigend.
function progress_start() {
  PROGRESS_TOTAL="$1"
  PROGRESS_CURRENT=0
  PROGRESS_MAX_SHOWN=0

  if ! progress_supported; then
    PROGRESS_ENABLED=0
    return 0
  fi

  PROGRESS_ENABLED=1
  PROGRESS_FIFO="$(mktemp -u)"
  mkfifo "$PROGRESS_FIFO"
  exec 3<>"$PROGRESS_FIFO"

  # whiptail schreibt direkt auf /dev/tty statt auf fd 1/2, damit es
  # unabhaengig davon funktioniert, dass wir gleich unser eigenes stdout/
  # stderr auf die Log-Datei umlenken.
  whiptail --title "pib Setup" --gauge "Installation wird vorbereitet..." 10 70 0 <&3 >/dev/tty 2>/dev/tty &
  PROGRESS_WHIPTAIL_PID=$!

  # Ab hier nur noch die Log-Datei fuellen - das Terminal gehoert bis
  # progress_end allein der Gauge-Box, sonst wuerde rohes apt/docker-Output
  # die Anzeige zerreissen. fd 4/5 sichern das bisherige stdout/stderr
  # (den "tee -a $LOG_FILE" von weiter oben) fuer die Wiederherstellung.
  exec 4>&1 5>&2
  exec 1>>"$LOG_FILE" 2>&1
}

# progress_add_total <delta> - erweitert die Gesamtschrittzahl nachtraeglich
# (z.B. sobald die tatsaechliche Anzahl Docker-Services bekannt ist), ohne
# dass die Anzeige dadurch zurueckspringt.
function progress_add_total() {
  PROGRESS_TOTAL=$((PROGRESS_TOTAL + $1))
}

# progress_step "<Beschreibung>" - ein Schritt weiter, aktualisiert Balken
# und Beschriftung. Schreibt die Beschreibung immer auch ins Log, damit man
# im Log genauso nachvollziehen kann, was gerade installiert wurde.
function progress_step() {
  local label="$1"
  PROGRESS_CURRENT=$((PROGRESS_CURRENT + 1))
  local percent=0
  if [ "$PROGRESS_TOTAL" -gt 0 ]; then
    percent=$(( PROGRESS_CURRENT * 100 / PROGRESS_TOTAL ))
  fi
  [ "$percent" -gt 100 ] && percent=100
  [ "$percent" -lt "$PROGRESS_MAX_SHOWN" ] && percent=$PROGRESS_MAX_SHOWN
  PROGRESS_MAX_SHOWN=$percent

  echo "[$(date -u)][[ (${PROGRESS_CURRENT}/${PROGRESS_TOTAL}) ${label} ]]"

  if [ "$PROGRESS_ENABLED" = "1" ]; then
    { echo "XXX"; echo "$percent"; echo "$label"; echo "XXX"; } >&3
  fi
}

function progress_end() {
  [ "$PROGRESS_ENABLED" = "1" ] || return 0
  { echo "XXX"; echo 100; echo "Fertig"; echo "XXX"; } >&3
  sleep 1
  exec 3>&-
  wait "$PROGRESS_WHIPTAIL_PID" 2>/dev/null
  rm -f "$PROGRESS_FIFO"
  exec 1>&4 2>&5
  exec 4>&- 5>&-
  PROGRESS_ENABLED=0
}

# Get Linux distribution name, e.g. 'ubuntu', 'debian'
get_distribution() {
    local distribution=""
    if [ -r /etc/os-release ]; then
        distribution="$(. /etc/os-release && echo "$ID")"
    fi
    echo "$distribution"
}

# Get Linux distribution version, e.g. (ubuntu) 'noble', (debian) 'bookworm'
get_dist_version() {
  local distribution=$1
  case "$distribution" in

    ubuntu)
        if command_exists lsb_release; then
            dist_version="$(lsb_release --codename | cut -f2)"
        fi
        if [ -z "$dist_version" ] && [ -r /etc/lsb-release ]; then
            dist_version="$(. /etc/lsb-release && echo "$DISTRIB_CODENAME")"
        fi
        ;;

    debian | raspbian)
        dist_version="$(sed 's/\/.*//' /etc/debian_version | sed 's/\..*//')"
        case "$dist_version" in
        13)
            dist_version="trixie"
            ;;
        12)
            dist_version="bookworm"
            ;;
        11)
            dist_version="bullseye"
            ;;
        10)
            dist_version="buster"
            ;;
        esac
        ;;
    esac
    echo "$dist_version" |  tr '[:upper:]' '[:lower:]'
}

function is_ubuntu_noble() {
  [[ "$DISTRIBUTION" == "ubuntu" && "$DIST_VERSION" == "noble" ]]
}

function is_supported_raspbian(){
  local supported_versions=("bookworm" "trixie")
  [[ ("$DISTRIBUTION" == "raspbian" || "$DISTRIBUTION" == "debian") &&
  " ${supported_versions[@]} " =~ " ${DIST_VERSION} " ]]
}

function check_distribution() {
  if is_ubuntu_noble || is_supported_raspbian; then
    print INFO "You are running the setup-script on: $DISTRIBUTION $DIST_VERSION which is one of the supported operating-systems! So, we can happily start the setup…"
    if is_supported_raspbian && [ "$DIST_VERSION" = "bookworm" ]; then
      print WARN "Raspberry Pi OS bookworm is deprecated for pib setup. ROS 2 Jazzy (Rospian) requires Trixie. Consider upgrading to Pi OS Trixie."
    fi
    return 0
  else
    print WARN "This script expects Raspberry Pi OS on pib or Ubuntu 24.04 for systems that run the digital twin only. We detected $DISTRIBUTION $DIST_VERSION. Do you want to continue? (Y/N):"
    read -r answer
      case "$answer" in
        [Yy]*)
          echo "Continuing..."
          return 0
          ;;
        *)
          echo "Stopping setup, no changes were made."
          exit 1
          ;;
      esac
    return 1
  fi
}

function remove_apps() {
    print INFO "Removing unused default software"

    PACKAGES_TO_BE_REMOVED=("aisleriot" "gnome-sudoku" "ace-of-penguins" "gbrainy" "gnome-mines" "gnome-mahjongg" "libreoffice*" "thunderbird*")
    installed_packages_to_be_removed=""

    # Create a list of all currently installed packaged that should be removed to reduce software bloat
    for package_name in "${PACKAGES_TO_BE_REMOVED[@]}"; do
      if dpkg-query -W -f='${Status}\n' "$package_name" 2>/dev/null | grep -q "install ok installed"; then
        installed_packages_to_be_removed+="$package_name "
      fi
    done

    # Remove unnecessary packages, if any are found
    if  [ -n "$installed_packages_to_be_removed" ]; then
      sudo apt-get -y purge "$installed_packages_to_be_removed"
      sudo apt-get autoclean
    fi

    print SUCCESS "Removed unused default software"
}


function install_system_packages() {
    print INFO "Installing system packages"
    sudo apt update -qq && \
    sudo apt-get install -y git curl gnupg openssh-server >/dev/null
    print SUCCESS "Installing system packages completed"
}

function install_locale() {
  sudo apt-get install -y locales
  sudo sed -i '/en_US.UTF-8/d' /etc/locale.gen
  echo "en_US.UTF-8 UTF-8" | sudo tee -a /etc/locale.gen
  sudo locale-gen en_US.UTF-8
  sudo update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
  export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
}

# Clone a repo to $dir, or if $dir already contains a git checkout, bring it
# in line with $repo_url/$branch instead of silently leaving it untouched.
#
# Bug this fixes: a plain 'git clone ... "$dir" || print WARN "already exists"'
# no-ops whenever $dir is already present - e.g. a pib that was previously set
# up from a *different* fork/remote (or an older checkout of this one) keeps
# running that stale code forever, because the warning is easy to miss in the
# install log and nothing actually updates the checkout. That is exactly how a
# robot ends up running an old version after re-running this script.
function clone_or_update_repo() {
  local repo_url="$1"
  local branch="$2"
  local dir="$3"
  local label="$4"

  if [ -d "$dir/.git" ]; then
    local current_origin
    current_origin="$(git -C "$dir" remote get-url origin 2>/dev/null)"
    if [ "$current_origin" = "$repo_url" ]; then
      print INFO "$label already checked out at $dir - fetching and resetting to origin/$branch"
      git -C "$dir" fetch origin "$branch" || { print ERROR "failed to fetch $label"; return 1; }
      git -C "$dir" checkout "$branch" || { print ERROR "failed to checkout '$branch' for $label"; return 1; }
      git -C "$dir" reset --hard "origin/$branch" || { print ERROR "failed to reset $label to origin/$branch"; return 1; }
      return 0
    fi
    print WARN "$label at $dir points to '$current_origin' instead of '$repo_url' - moving aside and re-cloning"
  elif [ -e "$dir" ]; then
    print WARN "$dir exists but is not a git checkout for $label - moving aside and re-cloning"
  else
    git clone -b "$branch" "$repo_url" "$dir" || { print ERROR "failed to clone $label"; return 1; }
    return 0
  fi

  # Move the stale checkout aside instead of deleting it outright - it may
  # still hold runtime state (e.g. pib-backend's SQLite DB) that isn't
  # tracked by git and would otherwise be lost for good.
  local backup_dir
  backup_dir="${dir}.stale.$(date +%Y%m%d%H%M%S)"
  mv "$dir" "$backup_dir"
  git clone -b "$branch" "$repo_url" "$dir" || { print ERROR "failed to clone $label"; return 1; }

  local db_file="pib_api/flask/pibdata.db"
  if [ -f "$backup_dir/$db_file" ] && [ ! -f "$dir/$db_file" ]; then
    mkdir -p "$(dirname "$dir/$db_file")"
    cp "$backup_dir/$db_file" "$dir/$db_file"
    print INFO "Restored existing pibdata.db from $backup_dir into fresh $label checkout"
  fi
}

# function to clone pib repositories to APP_DIR (~/app) directory
function clone_repositories() {
  # Validate branches
  if ! command_exists git; then
    print ERROR "git not found"
    exit 1
  fi

  if ! git ls-remote --exit-code --heads "$FRONTEND" "$BRANCH_FRONTEND" >/dev/null 2>&1; then
    print ERROR "Branch '${BRANCH_FRONTEND}' for Cerebra not found"
    exit 1
  fi
  if ! git ls-remote --exit-code --heads "$BACKEND" "$BRANCH_BACKEND" >/dev/null 2>&1; then
    print ERROR "Branch '${BRANCH_BACKEND}' for pib-backend not found"
    exit 1
  fi

  print INFO "Using branch '${BRANCH_FRONTEND}' for Cerebra, '${BRANCH_BACKEND}' for pib-backend"

  # Clone Repositories
  if [ ! -d "$APP_DIR" ]; then
    mkdir $APP_DIR
    print INFO "${APP_DIR} created"
  fi

  clone_or_update_repo "$BACKEND" "$BRANCH_BACKEND" "$BACKEND_DIR" "pib-backend" || exit 1
  clone_or_update_repo "$FRONTEND" "$BRANCH_FRONTEND" "$FRONTEND_DIR" "cerebra" || exit 1

  print SUCCESS "Completed cloning repositories to $APP_DIR"
}


# Install Luxonis udev rules so depthai can access the OAK camera as a non-root user.
# Without this, depthai logs "Insufficient permissions to communicate with
# X_LINK_UNBOOTED device ... Make sure udev rules are set" and cannot boot the device.
function install_depthai_udev_rules() {
  local rules_file="/etc/udev/rules.d/80-movidius.rules"
  local rule='SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"'

  if [ -f "$rules_file" ] && grep -q '03e7' "$rules_file"; then
    print INFO "Luxonis udev rules already present"
  else
    echo "$rule" | sudo tee "$rules_file" > /dev/null
    print INFO "Installed Luxonis udev rules to $rules_file"
  fi

  # Reload so the rule applies without a reboot (no-op effect if udev is unavailable).
  sudo udevadm control --reload-rules && sudo udevadm trigger \
    || print WARN "could not reload udev rules; a reboot/replug may be required"
}

# Clone the imitation project into the home directory and set up its virtual environment
function install_imitation() {
  if ! command_exists git; then
    print ERROR "git not found"
    return 1
  fi

  # Wie clone_or_update_repo (siehe dort): ein blosses "git clone ||
  # print WARN" no-opt beim zweiten Lauf und liesse die imitation-Kopie
  # dauerhaft veraltet, statt sie zu aktualisieren.
  if [ -d "$IMITATION_DIR/.git" ]; then
    print INFO "imitation project already cloned at $IMITATION_DIR - pulling latest"
    git -C "$IMITATION_DIR" pull --ff-only \
      || print WARN "failed to update imitation project, continuing with existing checkout"
  else
    print INFO "Cloning imitation project to $IMITATION_DIR"
    git clone "$IMITATION" "$IMITATION_DIR" || { print ERROR "failed to clone imitation project"; return 1; }
  fi

  # venv tooling is not guaranteed to be present on a fresh system
  sudo apt-get install -y python3-venv python3-pip

  # Ein zweiter Lauf muss die venv nicht neu anlegen, wenn sie schon
  # funktioniert - "python3 -m venv" auf einem bestehenden Verzeichnis ist
  # zwar meist unschaedlich, aber unnoetig langsam.
  if [ -x "$IMITATION_DIR/.venv/bin/pip" ]; then
    print INFO "imitation venv already exists - skipping creation"
  else
    # Create the venv with access to the system ROS packages (rclpy,
    # datatypes, trajectory_msgs) which are provided by the ROS overlay, not pip.
    python3 -m venv --system-site-packages "$IMITATION_DIR/.venv" \
      || { print ERROR "failed to create imitation virtual environment"; return 1; }
  fi

  "$IMITATION_DIR/.venv/bin/pip" install --upgrade pip
  "$IMITATION_DIR/.venv/bin/pip" install -r "$IMITATION_DIR/requirements.txt" \
    || { print ERROR "failed to install imitation requirements"; return 1; }

  # The imitation script drives the OAK camera via depthai, which needs udev rules.
  install_depthai_udev_rules || print WARN "failed to install depthai udev rules"

  print SUCCESS "Installed imitation project and its virtual environment"
}


# Download the local Piper TTS voice models that Cerebra's "Lokale
# Sprachausgabe (Piper)" dropdown offers. Without them the ros-voice-assistant
# container logs 'local voice "<id>" enabled but not installed', falls back to
# the (by default unconfigured) cloud TTS and then produces NO audio at all -
# i.e. a fresh install is mute until these files exist.
#
# voice_assistant/piper_tts.py expects each voice under:
#   $HOME/piper/voices/<id>/<id>.onnx   (+ <id>.onnx.json)
# which docker-compose bind-mounts read-only into the container as
# PIPER_HOME=/opt/piper. The <id> list below must stay in sync with the voices
# pib_api/flask/controller/voice_settings_controller.py serves to the frontend.
function install_piper_voices() {
  local voices_dir="$HOME/piper/voices"
  local base="https://huggingface.co/rhasspy/piper-voices/resolve/main"

  # "<model-id>|<huggingface-subpath>"  (subpath = de/de_DE/<name>/<quality>)
  local voices=(
    "de_DE-thorsten-low|de/de_DE/thorsten/low"
    "de_DE-thorsten-medium|de/de_DE/thorsten/medium"
    "de_DE-thorsten-high|de/de_DE/thorsten/high"
    "de_DE-thorsten_emotional-medium|de/de_DE/thorsten_emotional/medium"
    "de_DE-karlsson-low|de/de_DE/karlsson/low"
    "de_DE-pavoque-low|de/de_DE/pavoque/low"
    "de_DE-eva_k-x_low|de/de_DE/eva_k/x_low"
    "de_DE-kerstin-low|de/de_DE/kerstin/low"
    "de_DE-ramona-low|de/de_DE/ramona/low"
    "de_DE-mls-medium|de/de_DE/mls/medium"
  )

  # A previous Docker run may have created $HOME/piper root-owned (compose
  # bind-mounts a non-existent host path, which Docker creates as root). Make
  # sure the pib user can populate it before we start downloading.
  if [ -e "$HOME/piper" ] && [ ! -w "$HOME/piper" ]; then
    sudo chown -R "$USER":"$USER" "$HOME/piper"
  fi
  mkdir -p "$voices_dir" || { print ERROR "could not create $voices_dir"; return 1; }

  local entry id subpath dir ok_count=0
  for entry in "${voices[@]}"; do
    id="${entry%%|*}"
    subpath="${entry#*|}"
    dir="$voices_dir/$id"
    mkdir -p "$dir"

    # Skip voices already fully present (a valid .onnx is well over 1 MB), so
    # re-running the setup does not re-download ~600 MB every time.
    if [ -s "$dir/$id.onnx.json" ] \
       && [ "$(stat -c%s "$dir/$id.onnx" 2>/dev/null || echo 0)" -gt 1000000 ]; then
      print INFO "Piper voice $id already present - skipping"
      ok_count=$((ok_count + 1))
      continue
    fi

    print INFO "Downloading Piper voice $id"
    # -c resumes a partial file, --tries/--timeout survive a transient CDN
    # hiccup (this Pi has no RTC and networking can still be settling right
    # after a reboot). Download the small .json first, then the large model.
    if wget -q -c --tries=3 --timeout=60 "$base/$subpath/$id.onnx.json" -O "$dir/$id.onnx.json" \
       && wget -q -c --tries=3 --timeout=60 "$base/$subpath/$id.onnx" -O "$dir/$id.onnx"; then
      ok_count=$((ok_count + 1))
    else
      print WARN "failed to download Piper voice $id - speech output for this voice will not work"
    fi
  done

  if [ "$ok_count" -eq 0 ]; then
    print ERROR "no Piper voices could be installed - local speech output will not work"
    return 1
  fi
  print SUCCESS "Installed $ok_count/${#voices[@]} Piper voices to $voices_dir"
}


# Install update script; move animated eyes, etc.
function move_setup_files() {
  local update_target_dir="/usr/local/bin"
  local source_file="$BACKEND_DIR/setup/update-pib.sh"
  local target_file="$update_target_dir/update-pib"

  if [[ ! -f "$source_file" ]]; then
    print ERROR "$source_file not found"
    return 1
  fi

  # -f: ein zweiter Lauf soll den bereits bestehenden Symlink ersetzen
  # statt mit "File exists" fehlzuschlagen.
  sudo ln -sf "$source_file" "$target_file"

  sudo chmod 755 "$source_file"
  print SUCCESS "Installed update script"

  cp "$BACKEND_DIR/setup/setup_files/pib-eyes-animated.gif" "$HOME/Desktop/pib-eyes-animated.gif"
  print SUCCESS "Moved animated eyes to Desktop"

  # Add HTML that opens Cerebra + Database to the Desktop
  printf '<meta content="0; url=http://localhost" http-equiv=refresh>' > "$HOME/Desktop/Cerebra.html"
  printf '<meta content="0; url=http://localhost:8000" http-equiv=refresh>' > "$HOME/Desktop/pib_data.html"
}

function install_DBbrowser() {
  sudo apt install -y sqlitebrowser
  print SUCCESS "Installed DB browser"
}

function install_tinkerforge() {
  wget https://download.tinkerforge.com/apt/$(. /etc/os-release; echo $ID)/tinkerforge.asc -q -O - | sudo tee /etc/apt/trusted.gpg.d/tinkerforge.asc > /dev/null
  echo "deb https://download.tinkerforge.com/apt/$(. /etc/os-release; echo $ID $VERSION_CODENAME) main" | sudo tee /etc/apt/sources.list.d/tinkerforge.list
  sudo apt update
  sudo apt install -y brickd brickv python3-tinkerforge
  print SUCCESS "Installed tinkerforge"
}

function disable_power_notification() {
	local file="/boot/firmware/config.txt"
	
	if [ -f "$file" ]; then
    	echo "Disabling under-voltage warnings..."
		  echo "avoid_warnings=2" | sudo tee -a "$file" > /dev/null

    	echo "Preventing CPU throttling..."
    	echo "force_turbo=1" | sudo tee -a "$file" > /dev/null

    	# Pi 5: vollen USB-Strom freigeben (bis 1.6A/Port statt 600mA-Drossel).
    	# Noetig mit dem 27W/5A-Netzteil, sonst bekommen ReSpeaker
    	# (Mikro + Lautsprecher) und OAK-D zu wenig Strom (bis Absturz/Reboot).
    	echo "Enabling full USB current (Pi 5)..."
    	grep -q "^usb_max_current_enable=1" "$file" || \
    		echo "usb_max_current_enable=1" | sudo tee -a "$file" > /dev/null
	fi

	echo "Installing and configuring watchdog service..."
	sudo apt-get install -y watchdog
	sudo systemctl enable watchdog
	sudo systemctl start watchdog

	echo "Modifying watchdog configuration..."
	sudo sed -i 's/#reboot=1/reboot=0/' /etc/watchdog.conf

	echo "Disabling kernel panic reboots..."
	echo "kernel.panic = 0" | sudo tee -a /etc/sysctl.conf

	sudo sysctl -p
}

# Install a NetworkManager dispatcher script that observes IP changes and writes the current host IP to a file
setup_ip_dispatcher() {
  local dispatcher_script="/etc/NetworkManager/dispatcher.d/99-update-ip.sh"
  local outfile="/home/pib/app/pib-backend/pib_api/flask/host_ip.txt"

  print INFO "Creating dispatcher script..."

  sudo tee "$dispatcher_script" > /dev/null << 'EOF'
#!/bin/bash
LOG="/tmp/nm-dispatcher.log"
OUTFILE="/home/pib/app/pib-backend/pib_api/flask/host_ip.txt"

echo "$(date): Dispatcher triggered with IFACE=$1 STATE=$2" >> "$LOG"

IP=$(ip route get 1 | grep -oP 'src \K[\d.]+' || echo "")

CURRENT_IP=""
if [[ -f "$OUTFILE" ]]; then
    CURRENT_IP=$(cat "$OUTFILE")
fi

if [[ "$IP" != "$CURRENT_IP" ]]; then
    if [[ -n "$IP" ]]; then
        echo "$IP" > "$OUTFILE"
        echo "$(date): Updated IP to $IP" >> "$LOG"
    else
        > "$OUTFILE"
        echo "$(date): No IP found" >> "$LOG"
    fi
fi
EOF

  sudo chmod +x "$dispatcher_script"

  print INFO "Manually running dispatcher script to generate host_ip.txt..."
  sudo bash -c "$dispatcher_script wlan0 dhcp4-change"

  if [[ -f "$outfile" ]]; then
    print INFO "host_ip.txt was filled with the following IP:"
    cat "$outfile"
  else
    print WARN "host_ip.txt does not exist!"
  fi
}

# clean setup files if local install + remove user from sudoers file again
function cleanup() {
  if [ "$INSTALL_METHOD" = "legacy" ]; then
    sudo rm -r "$HOME/app"
    print INFO "Removed repositories from $HOME due to local installation"
  fi
  sudo rm /etc/sudoers.d/"$USER"
}


show_help()
{
	echo -e "The setup-pib.sh script has two execution modes:"
	echo -e "(normal mode and development mode)""$NEW_LINE"
	echo -e "$INFO""Normal mode (don't add any arguments or options)""$RESET_TEXT_COLOR"
	echo -e "$INFO""If you are do not know what the flags for development mode do, use the normal mode""$RESET_TEXT_COLOR"
	echo -e "Example: ./setup-pib""$NEW_LINE"
	echo -e "$INFO""Development mode (specify the branches you want to install)""$RESET_TEXT_COLOR"

	echo -e "You can either use the short or verbose command versions:"
	echo -e "-f=YourBranchName or --frontend-branch=YourBranchName"
	echo -e "-b=YourBranchName or --backend-branch=YourBranchName"
	echo -e "-l or --local for a local installation of the software over using a containerized setup using Docker"

	echo -e "$NEW_LINE""Examples:"
	echo -e "    ./setup-pib -b=main -f=PR-566"
    echo -e "    ./setup-pib --backend-branch=main --frontend-branch=PR-566"

	exit
}


# ---------- SETUP STARTS FROM HERE -----------

# Reduplicate output to an extra log file as well
LOG_FILE="$HOME/setup-pib.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "Hello $USER! We start the setup by allowing you permanently to run commands with admin-privileges. This change is reverted at the end of the setup."
if [[ "$(id)" == *"(sudo)"* ]]; then
	echo "For this change please enter your password..."
	sudo bash -c "echo '$USER ALL=(ALL) NOPASSWD:ALL' | tee /etc/sudoers.d/$USER"
else
	echo "For this change please enter the root-password. It is most likely just your normal one..."
	su root bash -c "usermod -aG sudo $USER ; echo '$USER ALL=(ALL) NOPASSWD:ALL' | tee /etc/sudoers.d/$USER"
fi


DISTRIBUTION=$(get_distribution) # e.g., 'ubuntu'
export DISTRIBUTION
DIST_VERSION=$(get_dist_version "$DISTRIBUTION")  # e.g., 'noble'
export DIST_VERSION
check_distribution


# VALIDATE CLI ARGUMENTS
BRANCH_BACKEND="main"
BRANCH_FRONTEND="main"
INSTALL_METHOD="docker"
# Check if branch was specified
while [ $# -gt 0 ]; do
  case "$1" in
    -f=* | --frontend-branch=*)
      BRANCH_FRONTEND="${1#*=}"
      ;;
    -b=* | --backend-branch=*)
      BRANCH_BACKEND="${1#*=}"
      ;;
    -l | --legacy)
      INSTALL_METHOD="legacy"
      ;;
    -h | --help)
      show_help
      ;;
    *)
      print ERROR "invalid input options"
  esac
  shift
done

# Ab hier laufen keine interaktiven Prompts mehr (Sudoers-Setup und die
# Distributions-Abfrage oben sind durch) - die Gauge kann jetzt uebernehmen.
# 17 fixe Schritte + eine grobe Schaetzung von 13 fuer die Docker-Phase
# (10 Backend-Services + hoch + 1 Frontend-Service + hoch); die Schaetzung
# wird in docker_install.sh per progress_add_total auf die echte Anzahl
# korrigiert, sobald die Compose-Dateien ausgelesen werden koennen.
progress_start 30

if is_ubuntu_noble; then
  progress_step "Entferne ungenutzte Standard-Software"
  remove_apps || print ERROR "failed to remove default software"
fi

if is_supported_raspbian; then
  progress_step "Stromversorgung/Watchdog konfigurieren"
  disable_power_notification || print ERROR "failed to disable power notifications"
fi

progress_step "Systempakete installieren"
install_system_packages || { print ERROR "failed to install system packages"; exit 1; }
progress_step "Locale einrichten"
install_locale || { print ERROR "failed to install locale"; exit 1; }
progress_step "pib-backend und Cerebra klonen/aktualisieren"
clone_repositories || { print ERROR "failed to clone repositories"; exit 1; }
progress_step "Imitation-Projekt einrichten"
install_imitation || print ERROR "failed to install imitation project"
if is_supported_raspbian && [ "$DIST_VERSION" = "trixie" ]; then
  progress_step "ROS 2 Jazzy (optionales Host-Overlay) installieren"
  # Non-fatal: this only builds an OPTIONAL native ROS 2 Jazzy overlay so the
  # host CLI can inspect ROS nodes running inside the Docker containers (see
  # ros_jazzy_install.sh) - Cerebra/pib-backend themselves run entirely via
  # Docker (docker_install.sh below) and don't need this overlay, so a
  # failure here must not block them.
  source "$SETUP_INSTALLATION_DIR/ros_jazzy_install.sh" || print ERROR "failed to install ROS 2 Jazzy (native host overlay) - continuing without it, Cerebra runs via Docker regardless"
fi
progress_step "Piper-Sprachmodelle herunterladen"
install_piper_voices || print ERROR "failed to install Piper voices - local speech output may not work"
progress_step "Update-Skript und Desktop-Dateien einrichten"
move_setup_files || print ERROR "failed to move setup files"
progress_step "DB-Browser installieren"
install_DBbrowser || print ERROR "failed to install DB browser"
progress_step "Tinkerforge-Treiber installieren"
install_tinkerforge || print ERROR "failed to install tinkerforge"
progress_step "IP-Dispatcher einrichten"
setup_ip_dispatcher || print ERROR "failed to setup ip dispatcher"
progress_step "Systemeinstellungen setzen"
source "$SETUP_INSTALLATION_DIR/set_system_settings.sh" || print ERROR "failed to set system settings"
if [ "$INSTALL_METHOD" = "legacy" ]; then
  progress_step "Cerebra lokal installieren (Legacy-Modus)"
  source "$SETUP_INSTALLATION_DIR/local_install.sh" || print ERROR "failed to install Cerebra locally"
elif is_ubuntu_noble || is_supported_raspbian; then
  source "$SETUP_INSTALLATION_DIR/docker_install.sh" || print ERROR "failed to install Cerebra via Docker"
  progress_step "Benutzer zur docker-Gruppe hinzufuegen"
  sudo usermod -aG docker pib || { print ERROR "failed to add user 'pib' to docker group"; exit 1; }
fi
progress_step "Aufraeumen"
cleanup
progress_end

print SUCCESS "Finished installation, for more information on how to use pib and Cerebra, visit https://pib-rocks.atlassian.net/wiki/spaces/kb/overview?homepageId=65077450"
print SUCCESS "Reboot pib to apply all changes"
