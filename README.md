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
- optionale direkte Theme-Ansicht: `http://127.0.0.1:8766/themes`
- OBS-Browserquelle: `http://127.0.0.1:8766/overlay`
- empfohlene OBS-Größe: 1920 × 1080

Der Server lauscht ausschließlich auf `127.0.0.1` und ist nicht öffentlich oder im Heimnetz
erreichbar. Der Port lässt sich unter **GitHub & Updates** ändern. Nach dem Speichern muss das
Tool neu gestartet und die OBS-Adresse auf den gewählten Port angepasst werden. Der Twitch-
Geräte-Login ist unabhängig vom lokalen Port.

## Control, OBS und Sounds

Der Python-Server ist ab Version 0.3.0 der unabhängige Spielleiter: Er verarbeitet den Twitch-
Chat, Anmeldungen, Countdown, Schüsse, Treffer, Gewinner und die 60-Sekunden-Claim-Zeit. `/control`
und `/overlay` zeigen denselben Serverzustand nur noch an. Deshalb läuft ein Giveaway auch weiter,
wenn die Control-Seite in einem anderen Browsertab liegt, minimiert oder ganz geschlossen ist.
Das Python-Terminal muss dafür geöffnet bleiben.

Die OBS-Browserquelle kann vor oder nach der Steuerung geöffnet werden und erhält den letzten
Stand automatisch. Auch Testflotten werden übertragen. In der Control-Seite zeigt eine eigene
Statuszeile, ob und wie viele OBS-Overlays verbunden sind. Ist das Overlay in OBS gerade
ausgeblendet, bleibt die Twitch-Anmeldung trotzdem geöffnet und der Kampf wird serverseitig
weitergerechnet; beim erneuten Einblenden erscheint sofort der aktuelle Stand.

Der letzte Giveaway-Zustand wird regelmäßig in `arena-state.json` gesichert. Nach einem Browser-
oder Tool-Neustart werden Teilnehmer, Runde, HP, Countdown, Claim-Zeit und das gewählte Theme
wiederhergestellt.

## Event-Themes

Oben auf der normalen `/control`-Seite öffnet der Button **THEMES** eine eigene ausklappbare
Theme-Steuerung neben dem bestehenden **CONTROL**-Menü. Dadurch bleiben die Toolsettings
übersichtlich, ohne dass dafür die Seite gewechselt werden muss. Optional ist dieselbe Auswahl
auch direkt unter `/themes` erreichbar. Zur Verfügung stehen fünf sofort umschaltbare Designs:

- Standard – das bisherige Layout unverändert
- Ostern
- Weihnachten
- Halloween
- Kanaljubiläum

Das gewählte Theme gilt sofort gemeinsam für Control und OBS und wird lokal gespeichert. Die
Event-Varianten ändern nur Lichtstimmung, Akzentfarben und dezente Partikel; Arena, Texte und
Bedienelemente bleiben an denselben Stellen.

Der Sound-Schalter oben steuert dezente Signale für Countdown, Kampfbeginn, zerstörte Schiffe,
Gewinner und Claim. Ein Klick auf den Schalter spielt in der Control-Seite einen kurzen Testton.
In OBS bei der Browserquelle **Audio über OBS steuern** aktivieren. Soll der Ton zusätzlich am
Streaming-PC hörbar sein, in den erweiterten Audioeigenschaften **Monitor und Ausgabe** wählen.

Reale Gewinner werden dauerhaft in `winner-stats.json` im lokalen Konfigurationsordner gezählt.
Der Siegerdialog zeigt den aktuellen Wert als `ALLTIME-SIEG #…`. Automatische Testpiloten aus der
Debug-Funktion verändern diese Statistik nicht. Die Control-Seite zeigt zusätzlich die Alltime-
Rangliste mit Siegen und gespielten Runden.

Folgende feste Statistikbefehle stehen im Twitch-Chat zur Verfügung:

- `!wins` oder `!wins @Name` – Siege und Teilnahmen anzeigen
- `!top3` – die drei erfolgreichsten Piloten anzeigen
- `!giveaway` – aktuellen Giveaway-Status anzeigen
- `!leave` – eigene Anmeldung vor Kampfbeginn zurücknehmen

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
[docs/TWITCH_SETUP.md](docs/TWITCH_SETUP.md). Ab Version 0.2.10 wird der offizielle Twitch-Geräte-
Login verwendet: Client-ID eintragen, **Mit Twitch verbinden** anklicken und den Zugriff im
geöffneten Twitch-Fenster bestätigen. Ein Client-Secret wird nicht benötigt. Falls Twitch beim
Anlegen der App eine OAuth Redirect URL verlangt, genügt `http://localhost`; der Geräte-Login
verwendet sie nicht.

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
des Betriebssystems; Darstellungswerte, Kampfhistorie und Siegerstatistik bleiben lokal auf dem
Streaming-PC. Das gilt ebenfalls für den automatisch gesicherten Stand einer aktiven Runde.
