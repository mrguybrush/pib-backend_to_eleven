# pib installieren oder upgraden

Es gibt zwei Szenarien: eine **komplett neue SD-Karte** (frische Installation) oder ein **bereits laufender pib**, der die neuen Funktionen bekommen soll, ohne alles neu aufzusetzen.

## Neue SD-Karte (Neuinstallation)

Kein Upgrade nötig — `setup/setup-pib.sh` installiert alles in einem Rutsch: ROS, Docker, udev-Regeln für die Kamera, Tinkerforge-Treiber, und klont beide Repos ([`cerebra_to_eleven`](https://github.com/mrguybrush/cerebra_to_eleven), [`pib-backend_to_eleven`](https://github.com/mrguybrush/pib-backend_to_eleven)).

Beide Repos sind öffentlich — kein SSH-Deploy-Key oder sonstiges Zugriffs-Setup nötig, ein einfaches `git clone` reicht.

```
bash setup-pib.sh
```

Die Installation startet mit den Standard-Seed-Daten (Startup/Resting-Pose usw.). Eigene Posen/Programme/Lerngruppen und der Gemini-API-Key müssen einmalig neu angelegt werden — es wird keine bestehende Datenbank mitgenommen.

## Bestehende Installation upgraden

Für einen pib, der schon läuft (ROS/Docker/udev sind bereits eingerichtet) und nur den neuen Code bekommen soll, **ohne** `setup-pib.sh` erneut auszuführen und **ohne** die eigene Datenbank zu verlieren.

### 1. Eigene Änderungen sichern

Falls an diesem pib lokal etwas verändert wurde (z. B. individuelle Pin-Zuordnungen im Code), vorher sichern:
```
cd ~/app/cerebra && git status
cd ~/app/pib-backend && git status
```
Bei Unklarheit: pro Repo einen Sicherungs-Branch anlegen (`git branch sicherung-vor-upgrade`) statt direkt zu überschreiben.

### 2. Remote auf die aktuellen Repos umstellen

In **beiden** Repos (`~/app/cerebra` und `~/app/pib-backend`):
```
git remote set-url origin https://github.com/mrguybrush/cerebra_to_eleven.git   # in cerebra
git remote set-url origin https://github.com/mrguybrush/pib-backend_to_eleven.git   # in pib-backend
```

### 3. Neuen Stand holen

```
git fetch origin
git checkout main
git pull --ff-only origin main
```
Falls `--ff-only` wegen eigener Commits fehlschlägt: `git merge origin/main` (kann Konflikte geben, die von Hand aufgelöst werden müssen).

### 4. Datenbank-Migrationen

Passiert automatisch beim nächsten Container-Build (`flask --app run db upgrade` läuft im Dockerfile). Neue Tabellen werden ergänzt, **bestehende Daten bleiben erhalten**.

### 5. Neu bauen und starten

```
cd ~/app/pib-backend
docker compose -p multirepo --profile all build
docker compose -p multirepo --profile all up -d

cd ~/app/cerebra
docker compose -p multirepo build angular-app
docker compose -p multirepo up -d angular-app
```

### 6. Testen

Seite im Inkognito-/Privatfenster öffnen (nginx cached `index.html` sonst clientseitig). Neue Funktionen prüfen: System → „Programme" (Lerngruppen-Zuordnung), Joint Control → „Alle Gelenke" (Finger-Slider, Invert-Häkchen), Sprachassistent-Einstellungen (Gemini-Kamera-/Bewegungszugriff-Schalter), Posen-Seite → „Gesichtsausdrücke verwalten".
