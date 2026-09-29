# Twitch einmalig einrichten

1. In der lokalen Control-Ansicht den eigenen Twitch-Kanalnamen eintragen und speichern.
2. `Mit Twitch verbinden` wählen.
3. Im automatisch geöffneten Twitch-Fenster den Zugriff bestätigen. Das Tool erkennt die
   Freigabe und verbindet den Chat selbstständig.

Das Tool fordert ausschließlich `user:read:chat` und `user:write:chat` an. Damit liest es
Join- und Claim-Nachrichten und sendet Giveaway-Bestätigungen in den verbundenen Kanal.

Die Twitch-Anwendung und ihre öffentliche Client-ID sind bereits fest im Tool integriert. Der
Geräte-Login benötigt kein Client-Secret und verwendet keine Redirect URL. Twitch-Tokens bleiben
weiterhin ausschließlich im sicheren Schlüsselspeicher des eigenen Betriebssystems. Eine
Portänderung hat keinen Einfluss auf die Twitch-Anmeldung.
