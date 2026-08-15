# Savox76 Giveaway System

Lokales, plattformübergreifendes Twitch-Giveaway für OBS. Zuschauer treten per frei wählbarem
Chatbefehl bei und kämpfen als Fregatten oder Cruiser in einer 3D-Weltraumarena.

## Adressen

- Steuerung: `http://127.0.0.1:8765/control`
- OBS-Browserquelle: `http://127.0.0.1:8765/overlay`
- Empfohlene OBS-Größe: 1920 × 1080

Der Server lauscht nur auf `127.0.0.1`. Die Oberfläche ist daher nicht öffentlich und nicht
aus dem Heimnetz erreichbar.

## Schnellstart aus dem Quellcode

### Windows

`start-windows.bat` doppelt anklicken.

### Linux oder macOS

```bash
chmod +x start-linux-macos.sh
./start-linux-macos.sh
```

Python 3.11 oder neuer wird benötigt. Node.js wird beim Start aus dem Quellcode einmalig zum
Bauen der 3D-Oberfläche verwendet. Fertige GitHub-Releases benötigen weder Python noch Node.js.

## Entwicklung

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
cd frontend
npm install
npm run build
cd ..
pytest
python -m savox_giveaway
```

## Versionen und automatische Updates

Jede Änderung wird als Git-Commit sichtbar. Tags wie `v0.1.0` erzeugen über GitHub Actions
automatisch geprüfte Pakete für Windows, Linux und macOS. Das installierte Tool prüft GitHub
alle sechs Stunden und beim Start auf eine neuere Release-Version. Es lädt nur das passende
Paket, prüft dessen SHA-256-Wert, sichert die alte Programmdatei und startet nach dem Austausch neu.

Bei einem privaten Repository muss lokal ein Fine-grained GitHub Token mit ausschließlich
`Contents: read` hinterlegt werden. Wird das Repository später öffentlich, ist kein Token mehr nötig.

## Twitch

Die Twitch-Anbindung verwendet EventSub WebSocket für eingehende Nachrichten und die Helix Chat
API für Bestätigungen, Anmeldeschluss, Gewinner und Claim-Ergebnis. Die einmalige Einrichtung ist
in [docs/TWITCH_SETUP.md](docs/TWITCH_SETUP.md) beschrieben.

## Datenschutz

Konfiguration und Tokens werden nicht eingecheckt. Zugangsdaten liegen im Schlüsselspeicher des
Betriebssystems; Kampfhistorie und Darstellungswerte bleiben lokal auf dem Streaming-PC.
