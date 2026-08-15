# Savox76 Giveaway System

Lokales Twitch-Giveaway für OBS mit frei wählbarem Chatbefehl und einem dreidimensionalen
Weltraumkampf zwischen Fregatten und Cruisern.

## Voraussetzungen

- Python 3.11 oder neuer
- eine Internetverbindung für die einmalige Einrichtung und Twitch
- OBS Studio mit Browserquelle

Node.js, GitHub CLI und betriebssystemspezifische Programmdateien werden für die Nutzung nicht
benötigt. Es gibt nur noch ein universelles Python-Paket.

## Start

1. Das aktuelle `Savox76Giveaway-python.zip` aus den
   [GitHub Releases](https://github.com/Savox76/savox76-giveaway/releases/latest) herunterladen.
2. ZIP vollständig in einen eigenen Ordner entpacken.
3. `Savox76Giveaway.py` mit Python starten.

Alternativ im Terminal:

```bash
python Savox76Giveaway.py
```

Unter Linux oder macOS kann der Python-Befehl `python3` heißen. Beim ersten Start wird im
Programmordner automatisch eine abgeschlossene `.venv`-Umgebung erstellt und mit allen benötigten
Python-Paketen eingerichtet. Danach öffnet sich die lokale Steuerung im Browser.

Das Terminal bleibt während der Nutzung geöffnet und zeigt die aktiven Adressen an. Falls der
Start fehlschlägt, bleibt das Fenster unter Windows ebenfalls geöffnet. Die genaue Fehlermeldung
wird zusätzlich als `Savox76Giveaway.log` direkt im Programmordner gespeichert. Das Python-Skript
darf nicht direkt innerhalb der ZIP-Vorschau gestartet werden; das Archiv muss vollständig
entpackt sein.

## Lokale Adressen

- Steuerung: `http://127.0.0.1:8766/control`
- OBS-Browserquelle: `http://127.0.0.1:8766/overlay`
- empfohlene OBS-Größe: 1920 × 1080

Der Server lauscht ausschließlich auf `127.0.0.1` und ist nicht öffentlich oder im Heimnetz
erreichbar. Der Port lässt sich unter **GitHub & Updates** ändern. Nach dem Speichern muss das
Tool neu gestartet werden; anschließend müssen auch die OBS-Adresse und die OAuth Redirect URL
bei Twitch auf den gewählten Port angepasst werden.

## Automatische Updates

Das Tool prüft beim Start und danach alle sechs Stunden das öffentliche GitHub-Repository. Wenn
eine neuere geprüfte Version vorliegt, geschieht automatisch Folgendes:

1. das einzige universelle Python-ZIP und seine SHA-256-Prüfsumme werden geladen;
2. das Archiv und jede enthaltene Programmdatei werden geprüft;
3. die bisher verwalteten Dateien werden unter `.updates/backups` gesichert;
4. ausschließlich Programmdateien werden ersetzt oder entfernt;
5. die lokale Python-Umgebung wird bei Bedarf aktualisiert;
6. das Giveaway-Tool startet automatisch neu.

Die letzten drei Sicherungen bleiben erhalten. Lokale Twitch-Zugangsdaten, Einstellungen, die
`.venv`-Umgebung und nicht vom Programm verwaltete Dateien werden nicht überschrieben. Da das
Repository öffentlich ist, wird kein GitHub-Token benötigt.

Der Wechsel von der alten ausführbaren Version `v0.1.0` auf die Python-Version erfordert einmalig
den manuellen Download des neuen Python-ZIPs. Ab `v0.2.0` funktionieren weitere Updates automatisch.

## Twitch einmalig einrichten

Die Twitch-Anbindung verwendet EventSub WebSocket und die Helix Chat API. Die Anleitung steht in
[docs/TWITCH_SETUP.md](docs/TWITCH_SETUP.md). Als OAuth Redirect URL muss exakt
`http://127.0.0.1:8766/api/twitch/callback` eingetragen werden.

## Entwicklung

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
cd frontend
npm install
npm run build
cd ..
ruff check backend scripts Savox76Giveaway.py
pytest
python Savox76Giveaway.py
```

Neue Veröffentlichungen entstehen nach einer Versionsänderung in `pyproject.toml` automatisch:
GitHub prüft Backend und Frontend, erzeugt das Versionstag und veröffentlicht genau ein
`Savox76Giveaway-python.zip` samt SHA-256-Datei.

## Lizenz und Datenschutz

Das Projekt steht unter der [Savox76 Non-Commercial Source License](LICENSE). Kommerzielle Nutzung
ist ohne vorherige schriftliche Genehmigung nicht erlaubt.

Konfiguration und Twitch-Tokens werden nicht eingecheckt. Geheimnisse liegen im Schlüsselspeicher
des Betriebssystems; Darstellungswerte und Kampfhistorie bleiben lokal auf dem Streaming-PC.
