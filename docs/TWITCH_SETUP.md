# Twitch einmalig einrichten

1. In der Twitch Developer Console eine Anwendung anlegen.
2. Als OAuth Redirect URL exakt `http://127.0.0.1:8766/api/twitch/callback` eintragen.
3. Kategorie `Application Integration` verwenden.
4. Client-ID und Client-Secret in der lokalen Control-Ansicht speichern.
5. `Mit Twitch anmelden` wählen und den Zugriff bestätigen.

Das Tool fordert ausschließlich `user:read:chat` und `user:write:chat` an. Damit liest es
Join- und Claim-Nachrichten und sendet Giveaway-Bestätigungen in den verbundenen Kanal.

Wenn der lokale Server-Port im Kontrollpanel geändert wird, muss dieselbe Portnummer auch in der
OAuth Redirect URL der Twitch Developer Console stehen. Die Änderung wird nach einem Neustart des
Tools aktiv.
