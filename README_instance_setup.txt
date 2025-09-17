README – Zentrale Steuerung, Instanznamen & Admin-Channel
=========================================================

Wie benutzt du’s?
-----------------
1) Erstelle EINEN Installer/Build für alle PCs (keine separaten EXEs).
2) In der ausgelieferten config.json stehen nur deine fixen Werte:
   - telegram_bot_token
   - admin_channel_id
   - optional: language
   WICHTIG: "instance_name" lässt du auf "auto" (oder weglassen).

3) Beim ERSTEN Start auf jedem PC:
   - Die App erzeugt / liest APP_DIR\instance_id.txt (stabile Kurz-ID).
   - Sie setzt automatisch instance_name = "<HOSTNAME>-<KurzID>".
   - Sie speichert das sofort dauerhaft in APP_DIR\config.json.

4) Du siehst jede Instanz am Prefix im Admin-Channel:
   Beispiel: "[DESKTOP-1234-a1b2c3] online ✓"
   → Dieser eckige Klammer-Prefix IST der instance_name.

5) Broadcasts vom Admin-Channel:
   - /broadcast all <TEXT>        → an alle Instanzen
   - /broadcast group=<NAME> <TEXT>  → nur an Instanz mit exakt diesem instance_name
   - Sprachblöcke: [ALL].., [DE]..[/DE], [EN]..[/EN]
   Beispiele:
     /broadcast all [ALL]Hello world!
     /broadcast group=DESKTOP-1234-a1b2c3 [DE]Hallo![/DE][EN]Hello![/EN]

6) Logs + Empfänger-Zusammenfassung:
   - Beim Start pingt jede Instanz den Admin-Channel und schickt
     eine kurze Empfänger-Übersicht.
   - /logs  → die letzten Logdateien werden als Dokumente gesendet.


FAQ
---
• Muss ich pro PC die EXE mit eigener config bauen?
  Nein. Ein Build reicht. instance_name wird automatisch gesetzt.

• Wo sehe ich den instance_name?
  - Im Admin-Channel im Prefix jeder Status-/Admin-Nachricht.
  - In APP_DIR\config.json unter "instance_name".
  - Er besteht aus <Hostname>-<6stellige Kurz-ID> (z.B. "PC01-7f9a3c").

• Wird die lokale config.json überschrieben?
  Beim ersten Start wird nur "instance_name" gesetzt (persistiert),
  sonst bleibt alles wie in deiner Datei.

• Wie finde ich die admin_channel_id?
  - Bot als Admin zum Kanal hinzufügen
  - Kanal auf öffentlich stellen ODER per Bot-API (getUpdates, Channel-Post absetzen)
  - Die ID beginnt mit -100… (z.B. -1002990182932)





Schnelltest
-----------
1) Starte eine frische Installation.
2) Im Admin-Channel sollte erscheinen:
   [<HOST>-<KurzID>] online ✓
   [<HOST>-<KurzID>] recipients: N → …
3) /broadcast all [ALL]Test
   → Alle gekoppelten Empfänger dieser Instanz bekommen "Test".
4) /broadcast group=<EXAKTER_INSTANCE_NAME> [DE]Hallo![/DE][EN]Hello![/EN]
   → Nur diese Instanz verschickt an IHRE Empfänger.


Troubleshooting
---------------
• Prefix fehlt? → admin_channel_id prüfen und ob Bot Admin ist.
• instance_name ändert sich nicht? → Prüfe config.json ("instance_name"),
  und ob instance_id.txt existiert; lösche instance_id.txt für eine neue Kurz-ID.
• getUpdates leer? → Kanal war privat/ohne Post; sende eine Nachricht in den Kanal,
  oder prüfe, ob der Bot Admin-Rechte hat.
