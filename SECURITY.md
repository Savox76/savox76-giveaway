# Sicherheit

- Twitch-Token und Client-Secret werden niemals im Repository gespeichert.
- Geheimnisse liegen im sicheren Schlüsselspeicher des jeweiligen Betriebssystems.
- Das öffentliche GitHub-Repository wird für Updateprüfungen ohne Zugangstoken gelesen.
- Updates werden nur aus veröffentlichten GitHub Releases geladen und vor der Installation per SHA-256 geprüft.
- Jede einzelne Programmdatei wird zusätzlich anhand des geprüften Release-Manifests kontrolliert.
- Vor dem Austausch wird eine lokale Sicherung angelegt; bei einem Fehler erfolgt eine Wiederherstellung.
- Der lokale Server bindet ausschließlich an `127.0.0.1` und ist nicht aus dem Netzwerk erreichbar.

Bitte keine Zugangsdaten, Tokens oder Client-Secrets in Issues oder Logdateien veröffentlichen.
