1. Änderungen im Code vornehmen und in Version.py die Version erhöhen - speichern
2. neuen Build erstellen im Projektordner: .\.venv\Scripts\pyinstaller.exe --onefile --noconsole --name LWBot --icon "installer\bagger_icon_exe.ico" --collect-all numpy --collect-all cv2 --add-data "Module\data;Module\data" --add-data "bagger_icon.png;." --add-data "bn_close_x.png;." --add-data "bn_blue_btn.png;." --add-data "golden_egg.png;." --add-data "Module\i18n.py;Module" --add-data "Module\config.py;Module" --add-data "Module\log.py;Module" --add-data "Module\telebot.py;Module" --add-data "Module\ui_recipients.py;Module" --add-data "Module\version.py;Module" --add-data "Module\updater.py;Module" bagger_detector.py
>>

2. in den Installerordner ziehen und die .iss ausführen
3. den fertigen Installer auf git hochladen als neues Release
4. achte darauf dass die .exe immer LWBot oder LWBot-Setup heißt
