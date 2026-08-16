# Twitch einmalig einrichten

1. In der [Twitch Developer Console](https://dev.twitch.tv/console/apps) eine Anwendung anlegen.
2. Als Kategorie `Application Integration` und als Client-Typ `Public` verwenden.
3. Falls Twitch eine OAuth Redirect URL verlangt, `http://localhost` eintragen. Der Geräte-Login
   selbst verwendet diese Adresse nicht.
4. Die angezeigte Client-ID in der lokalen Control-Ansicht eintragen.
5. `Mit Twitch verbinden` wählen.
6. Im automatisch geöffneten Twitch-Fenster den Zugriff bestätigen. Das Tool erkennt die
   Freigabe und verbindet den Chat selbstständig.

Das Tool fordert ausschließlich `user:read:chat` und `user:write:chat` an. Damit liest es
Join- und Claim-Nachrichten und sendet Giveaway-Bestätigungen in den verbundenen Kanal.

Der Geräte-Login benötigt kein Client-Secret und verwendet keine Redirect URL. Die Client-ID ist
keine geheime Zugangsinformation; Twitch-Tokens bleiben weiterhin ausschließlich im sicheren
Schlüsselspeicher des eigenen Betriebssystems. Eine Portänderung hat keinen Einfluss mehr auf die
Twitch-Anmeldung.
