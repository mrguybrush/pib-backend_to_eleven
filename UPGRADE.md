# pib installieren oder upgraden

Es gibt zwei Szenarien: eine **komplett neue SD-Karte** (frische Installation) oder ein **bereits laufender pib**, der die neuen Funktionen bekommen soll, ohne alles neu aufzusetzen.

## Neue SD-Karte (Neuinstallation)

Kein Upgrade nötig — `setup/setup-pib.sh` installiert alles in einem Rutsch: ROS, Docker, udev-Regeln für die Kamera, Tinkerforge-Treiber, und klont beide Repos (`cerebra-mod`, `pib-backend-mod`) inklusive des `pib-blockly-mod`-Submoduls.

**Voraussetzung:** Diese Repos sind privat. Auf der neuen Karte muss vorher der SSH-Zugriff eingerichtet sein:

1. Die drei Deploy-Key-Dateien von der alten Installation kopieren (liegen dort unter `~/.ssh/`):
   - `pib_mod_deploy_cerebra` (+ `.pub`)
   - `pib_mod_deploy_backend` (+ `.pub`)
   - `pib_mod_deploy_blockly` (+ `.pub`)

   Z. B. per USB-Stick oder `scp`:
   ```
   scp ~/.ssh/pib_mod_deploy_* pib@<neue-karte>:~/.ssh/
   ```
2. Auf der neuen Karte `~/.ssh/config` anlegen (Inhalt siehe unten) und Rechte setzen:
   ```
   chmod 600 ~/.ssh/config ~/.ssh/pib_mod_deploy_*
   ```
3. Dann `setup-pib.sh` ausführen:
   ```
   bash setup-pib.sh
   ```

`~/.ssh/config`-Inhalt:
```
Host github-cerebra-mod
    HostName github.com
    User git
    IdentityFile ~/.ssh/pib_mod_deploy_cerebra
    IdentitiesOnly yes

Host github-pib-backend-mod
    HostName github.com
    User git
    IdentityFile ~/.ssh/pib_mod_deploy_backend
    IdentitiesOnly yes

Host github-pib-blockly-mod
    HostName github.com
    User git
    IdentityFile ~/.ssh/pib_mod_deploy_blockly
    IdentitiesOnly yes
```

Die Installation startet mit den Standard-Seed-Daten (Startup/Resting-Pose usw.). Eigene Posen/Programme/Lerngruppen und der Gemini-API-Key müssen einmalig neu angelegt werden — es wird keine bestehende Datenbank mitgenommen.

## Bestehende Installation upgraden

Für einen pib, der schon läuft (ROS/Docker/udev sind bereits eingerichtet) und nur den neuen Code bekommen soll, **ohne** `setup-pib.sh` erneut auszuführen und **ohne** die eigene Datenbank zu verlieren.

### 1. Zugriff einrichten

Wie oben: Deploy-Keys + `~/.ssh/config` auf dieser Maschine einrichten (falls noch nicht geschehen).

### 2. Eigene Änderungen sichern

Falls an diesem pib lokal etwas verändert wurde (z. B. individuelle Pin-Zuordnungen im Code), vorher sichern:
```
cd ~/app/cerebra && git status
cd ~/app/pib-backend && git status
```
Bei Unklarheit: pro Repo einen Sicherungs-Branch anlegen (`git branch sicherung-vor-upgrade`) statt direkt zu überschreiben.

### 3. Remote auf die neuen Repos umstellen

In **beiden** Repos (`~/app/cerebra` und `~/app/pib-backend`):
```
git remote set-url origin git@github-cerebra-mod:mrguybrush/cerebra-mod.git   # in cerebra
git remote set-url origin git@github-pib-backend-mod:mrguybrush/pib-backend-mod.git   # in pib-backend
```

### 4. Neuen Stand holen

```
git fetch origin
git checkout main   # cerebra: main / pib-backend: ggf. der Branch, auf dem der neue Stand liegt
git pull --ff-only origin main
```
Falls `--ff-only` wegen eigener Commits fehlschlägt: `git merge origin/main` (kann Konflikte geben, die von Hand aufgelöst werden müssen).

### 5. Submodul umstellen

In beiden Repos zeigt `.gitmodules` jetzt auf `pib-blockly-mod` (kommt automatisch mit dem Pull). Submodul aktualisieren:
```
git submodule sync
git submodule update --init --recursive
```

### 6. Datenbank-Migrationen

Passiert automatisch beim nächsten Container-Build (`flask --app run db upgrade` läuft im Dockerfile). Neue Tabellen (Lerngruppen, LLM-Settings, Motion-Capture-Joint-Mapping, Kamerazugriff pro Persona) werden ergänzt, **bestehende Daten bleiben erhalten**.

### 7. Neu bauen und starten

```
cd ~/app/pib-backend
docker compose -p multirepo --profile all build
docker compose -p multirepo --profile all up -d

cd ~/app/cerebra
docker compose -p multirepo build angular-app
docker compose -p multirepo up -d angular-app
```

### 8. Testen

Seite im Inkognito-/Privatfenster öffnen (nginx cached `index.html` sonst clientseitig). Neue Funktionen prüfen: System → „Programme" (Lerngruppen-Zuordnung), Joint Control → „Alle Gelenke" (Finger-Slider, Invert-Häkchen), Sprachassistent-Einstellungen (Gemini-Kamerazugriff-Schalter).
