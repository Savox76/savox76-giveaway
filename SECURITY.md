# Sicherheit

- Twitch- und GitHub-Token werden niemals im Repository gespeichert.
- Geheimnisse liegen im sicheren Schlüsselspeicher des jeweiligen Betriebssystems.
- Für das private GitHub-Repository genügt ein Fine-grained Token mit `Contents: read`.
- Updates werden nur aus veröffentlichten GitHub Releases geladen und vor der Installation per SHA-256 geprüft.
- Der lokale Server bindet ausschließlich an `127.0.0.1` und ist nicht aus dem Netzwerk erreichbar.

Bitte keine Zugangsdaten, Tokens oder Client-Secrets in Issues oder Logdateien veröffentlichen.
