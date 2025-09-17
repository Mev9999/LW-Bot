try:
    from Module.updater import check_and_offer_update
    check_and_offer_update(auto=False)  # auto=True = ohne Nachfrage
except Exception as _e:
    print("Updater skip:", _e)



import cv2
import numpy as np
import pyautogui
import time
import winsound
import os
import sys
import pytesseract
import re
import json
import requests, random, string, webbrowser
import tkinter as tk
import threading
from PIL import Image
import pystray
from pystray import MenuItem, Menu
from tkinter import messagebox, simpledialog
from difflib import get_close_matches
from datetime import datetime, timedelta
from collections import Counter
from glob import glob
from Module.config import APP_DIR, resource_path, cfg, init_env, save_cfg
from Module.i18n import tr as _tr, res_name as _res_name_by_lang, normalize_lang


from Module.log import (
    LOG_DIR, log_event, read_json_list,
    load_logs_in_range, posted_report_exists_for_range, iter_broadcast_logs,
)
from Module.telebot import send_alert, broadcast_localized, auto_reply_worker
from Module.ui_recipients import open_recipients_ui, open_broadcast_dialog



pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05





# --- Fenster-Findung (Windows) ---
try:
    import pygetwindow as gw
except Exception:
    gw = None  # wir prüfen später und geben eine klare Meldung aus

import ctypes
from ctypes import wintypes

from requests.exceptions import ConnectionError, Timeout, HTTPError

GAME_WINDOW_TITLES = ["Last War: Survival Game", "Last War", "Last War – Survival Game"]

_fired_slots = set()  # merkt pro Tag+Zeit, dass bereits geklickt wurde

# Datei zum Speichern der relativen Klickpunkte (pro PC einmal kalibrieren)
BN_CLICKMAP_FILE = os.path.join(APP_DIR, "bn_clickmap.json")
DEFAULT_BN_CLICKMAP = {
    "x_close": [0.968, 0.095],   # sehr grobe Defaults – bitte kalibrieren!
    "blue_button": [0.500, 0.865],
    # NEU: Goldenes Ei – zwei Klickpunkte (X und Button oder zwei Buttons)
    "egg_click1": [0.85, 0.18],   # Platzhalter: X oben rechts o. ä.
    "egg_click2": [0.50, 0.86],   # Platzhalter: Bestätigen unten o. ä.
}












# >>> FEST VERDRAHTET (dein Token & Bot-Name) <<<
TELEGRAM_BOT_TOKEN = cfg["telegram_bot_token"]
BOT_USERNAME = cfg["bot_username"]
ADMIN_CONTACT = cfg["admin_contact"]



# === BAGGER-DEBOUNCE ===
bagger_lock = False          # True, wenn zuletzt ein Bagger gepostet wurde und Symbol weiterhin sichtbar ist
bagger_absent_since = None   # Zeitstempel, seit wann das Symbol weg ist (oder None)
BAGGER_ABSENCE_RESET_SEC = 3 # so lange muss das Symbol am Stück weg sein, bevor neu gepostet werden darf

running = True   # steuert die Hauptschleife
paused  = False  # Pause/Weiter vom Tray-Menü
tray_icon = None
ui_request = None  # "recipients" | "info" | "broadcast" | None



# === EINSTELLUNGEN ===
THRESHOLD = cfg["thresholds"]["bagger"]
# falls du EGG_THRESHOLD definierst (weiter unten):
# EGG_THRESHOLD = cfg["thresholds"]["egg"]

pytesseract.pytesseract.tesseract_cmd = init_env()


# === ZUSTÄNDE ===
next_bagger_check = 0
next_ocr_check = 0
gepostete_ressourcen = {}

# Report: Woche = Mo 04:00 -> Mo 04:00, posten um 04:01 (nachholen beim Start)
REPORT_POST_MINUTE_AFTER = 1  # 04:01
posted_report_runtime_cache = set()  # Laufzeit-Sperre gegen Doppelpost

SUCHBEGRIFFE = {
    "heiliges": "Heiliges",
    "ressourcenfeld": "Ressourcenfeld",
    "eisen": "Eisen",
    "diamant": "Diamant",
    "gold": "Gold",
    "nahrung": "Nahrung",
    "sammelstelle": "Sammelstelle",
    "mithrilfeld": "Mithrilfeld",
    "öl": "Öl",
    "ol": "Öl",
    "oel": "Öl"
}

try:
    print("[BOOT] file:", os.path.abspath(__file__))
except NameError:
    print("[BOOT] exe:", sys.executable)


# ---- Minimal-Theme & Restart-Helfer ---------------------------------
import tkinter.ttk as ttk

ACCENT = "#1E88E5"     # Blau
ACCENT_D = "#1565C0"
BG_WIN = "#0f1115"     # sehr dunkles Grau
BG_CARD = "#171a21"
FG = "#e7eaf0"

def apply_ttk_theme(root: tk.Tk | tk.Toplevel):
    style = ttk.Style(root)
    # auf Windows/Classic: 'clam' ist stabil
    try: style.theme_use("clam")
    except: pass

    style.configure(".", background=BG_WIN, foreground=FG, fieldbackground=BG_CARD)
    style.configure("TLabel", background=BG_WIN, foreground=FG)
    style.configure("Card.TFrame", background=BG_CARD, relief="flat")
    style.configure("TButton", padding=8)
    style.map("TButton",
              background=[("active", ACCENT_D), ("!active", ACCENT)],
              foreground=[("!disabled", "#ffffff")])
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
    style.map("Accent.TButton",
              background=[("active", ACCENT_D), ("!active", ACCENT)])

def restart_app():
    """Soft-Restart mit gleicher Python/EXE."""
    import subprocess
    python = sys.executable
    args = [python] + sys.argv
    # Für PyInstaller-EXE funktioniert das genauso
    os.execv(python, args)


# ---- NEU: kleine Win32-Helfer (bei deinen anderen Helfern einfügen) ----
def _win_get_text(hwnd):
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value or ""

def _win_get_rect(hwnd):
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top

def _find_game_hwnd_by_enum():
    """Fallback: alle Fenster durchgehen und 'last war' im Titel suchen."""
    user32 = ctypes.windll.user32
    results = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _enum_proc(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _win_get_text(hwnd)
        if "last war" in title.lower():
            l, t, w, h = _win_get_rect(hwnd)
            results.append((w * h, hwnd))
        return True

    user32.EnumWindows(_enum_proc, 0)
    if results:
        results.sort(reverse=True)  # größtes Fenster zuerst
        return results[0][1]
    return None

# ---- NEU: robustere Suche nach dem Spiel-Fenster ----
def _find_game_window():
    """
    1) pygetwindow: beliebiges Fenster, dessen Titel 'last war' enthält
    2) Vordergrundfenster
    3) vollständige Windows-Enumeration (EnumWindows)
    Gibt ein Objekt mit _hWnd, left, top, width, height zurück (pygetwindow-like).
    """
    # 1) pygetwindow – fuzzy
    if gw is not None:
        try:
            wins = [w for w in gw.getAllWindows()
                    if (w.title or "") and "last war" in w.title.lower()]
            wins = [w for w in wins if getattr(w, "isVisible", True)]
            if wins:
                wins.sort(key=lambda w: w.width * w.height, reverse=True)
                return wins[0]
        except Exception:
            pass

    # 2) Vordergrundfenster
    user32 = ctypes.windll.user32
    fg = user32.GetForegroundWindow()
    if fg and "last war" in _win_get_text(fg).lower():
        D = type("WinWrap", (), {})  # kleines Dummy-Objekt wie pygetwindow
        d = D()
        d._hWnd = fg
        l, t, ww, hh = _win_get_rect(fg)
        d.left, d.top, d.width, d.height = l, t, ww, hh
        d.title = _win_get_text(fg)
        d.isVisible = True
        return d

    # 3) EnumWindows-Fallback
    hwnd = _find_game_hwnd_by_enum()
    if hwnd:
        D = type("WinWrap", (), {})
        d = D()
        d._hWnd = hwnd
        l, t, ww, hh = _win_get_rect(hwnd)
        d.left, d.top, d.width, d.height = l, t, ww, hh
        d.title = _win_get_text(hwnd)
        d.isVisible = True
        return d

    return None

def get_game_client_rect():
    """(left, top, width, height) des Clientbereichs (Fallback: Außenrahmen)."""
    w = _find_game_window()
    if not w:
        return None
    try:
        cr = _get_client_rect(w._hWnd)
        if cr:
            return cr
    except Exception:
        pass
    return (w.left, w.top, w.width, w.height)





def _bn_load_clickmap():
    try:
        with open(BN_CLICKMAP_FILE, "r", encoding="utf-8") as f:
            m = json.load(f)
            # Sanity
            if "x_close" in m and "blue_button" in m:
                return m
    except Exception:
        pass
    return DEFAULT_BN_CLICKMAP.copy()

def _bn_save_clickmap(m):
    tmp = BN_CLICKMAP_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
    os.replace(tmp, BN_CLICKMAP_FILE)

def _bn_abs_xy(key):
    """Abs. Pixel für einen gespeicherten relativen Punkt liefern."""
    rect = get_game_client_rect()
    if not rect:
        print("❌ Spiel-Fenster nicht gefunden.")
        return None
    left, top, w, h = rect
    m = _bn_load_clickmap()
    rx, ry = m.get(key, DEFAULT_BN_CLICKMAP[key])
    x = int(left + rx * w)
    y = int(top  + ry * h)
    return x, y

def _focus_game_window():
    w = _find_game_window()
    if not w:
        return
    try:
        w.activate()
    except Exception:
        pass

def bn_click_fixed(key, clicks=1):
    _focus_game_window()
    pt = _bn_abs_xy(key)
    if not pt:
        return False
    x, y = pt

    # Kleine Zufallsabweichung und Bewegung wie ein Mensch
    jx = random.randint(-6, 6)
    jy = random.randint(-6, 6)
    dur = random.uniform(0.10, 0.25)
    pyautogui.moveTo(x + jx, y + jy, duration=dur)

    for _ in range(clicks):
        time.sleep(random.uniform(0.05, 0.20))
        pyautogui.click()
    return True

# --- wieder einfügen ---
def _get_client_rect(hwnd):
    """Client-Rechteck (ohne Titelleiste/Rahmen) in Bildschirmkoordinaten."""
    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    left, top = pt.x, pt.y
    width  = rect.right - rect.left
    height = rect.bottom - rect.top
    return left, top, width, height

def close_bloodnight_popups():
    """
    Koordinaten-basierte Variante: einfach die beiden bekannten Stellen klicken.
    Funktioniert auch im Vollbild/verschobenen Fenster, weil relativ zum Client-Bereich.
    """
    ok1 = bn_click_fixed("x_close")
    time.sleep(0.2)
    ok2 = bn_click_fixed("blue_button")
    return ok1 or ok2

def open_egg_calibrator():
    """
    Drei Punkte speichern (relativ zum Spielfenster):
      1) Ei-Position (nur Fallback/Test; Erkennung klickt sonst den Match)
      2) Allianz-Chat
      3) Zurück-Button
    """
    m = _bn_load_clickmap()
    root = tk.Tk()
    root.title("Golden Egg – Koordinaten kalibrieren")
    root.geometry("560x260")

    tk.Label(root, text=(
        "Nach OK hast du jeweils 4 Sekunden, die Maus im Spiel\n"
        "auf den gewünschten Punkt zu bewegen.\n"
        "1) Ei-Position (optional, für Test/Fallback)\n"
        "2) Allianz-Chat\n"
        "3) Zurück-Button"
    ), justify="left").pack(padx=12, pady=10, anchor="w")

    def _cap(key, labeltext):
        root.withdraw()
        messagebox.showinfo("Aufnahme", f"Nach OK hast du 4 Sekunden.\nBewege die Maus im Spiel über {labeltext}.")
        time.sleep(4)

        rect = get_game_client_rect()
        if not rect:
            messagebox.showerror("Kalibrieren", "Spiel-Fenster nicht gefunden. Bitte Spiel fokussieren und nochmal.")
            root.deiconify(); return

        x, y = pyautogui.position()
        left, top, w, h = rect
        rx = round((x - left) / w, 4)
        ry = round((y - top) / h, 4)
        m[key] = [max(0.0, min(1.0, rx)), max(0.0, min(1.0, ry))]
        _bn_save_clickmap(m)
        update_status()
        root.deiconify()

    def update_status():
        status.config(text=(
            f"Aktuell: Ei={m.get('egg_target')} | "
            f"Allianz={m.get('egg_alliance')} | "
            f"Zurück={m.get('egg_back')}"
        ))

    status = tk.Label(root, text="")
    status.pack(padx=12, pady=6, anchor="w")
    update_status()

    btns = tk.Frame(root); btns.pack(pady=8)
    tk.Button(btns, text="Ei-Position festlegen",
              command=lambda: _cap("egg_target","die Ei-Position")).grid(row=0, column=0, padx=6)
    tk.Button(btns, text="Allianz-Chat festlegen",
              command=lambda: _cap("egg_alliance","den Allianz-Chat")).grid(row=0, column=1, padx=6)
    tk.Button(btns, text="Zurück-Button festlegen",
              command=lambda: _cap("egg_back","den Zurück-Button")).grid(row=0, column=2, padx=6)

    tk.Button(root, text="Testklicks (Sequenz)",
              command=lambda: run_egg_sequence(center=None)).pack(pady=6)
    tk.Button(root, text="Schließen", command=root.destroy).pack(pady=6)
    root.mainloop()

def run_egg_sequence(center: tuple[int,int] | None):
    """
    center: (x,y) des erkannten Eies (Screen-Pixel). Wenn None -> benutze kalibrierte 'egg_target'-Koordinate.
    Ablauf: Ei-Klick -> 2s -> Allianz-Chat -> 2s -> Zurück.
    """
    _focus_game_window()

    # 1) Ei klicken (Match oder Fallback-Punkt)
    if center:
        x, y = center
        pyautogui.moveTo(x + random.randint(-4,4), y + random.randint(-4,4),
                         duration=random.uniform(0.10, 0.25))
        pyautogui.click()
    else:
        bn_click_fixed("egg_target", clicks=1)

    # 2) Allianz-Chat
    time.sleep(2.0)
    bn_click_fixed("egg_alliance", clicks=1)

    # 3) Zurück
    time.sleep(2.0)
    bn_click_fixed("egg_back", clicks=1)

def _egg_search_region(pad_rel=0.14):
    # nutzt deine bestehende Clickmap + Fenstergröße
    # sucht rund um den kalibrierten "egg_target"-Punkt (nicht Fullscreen!)
    return _bn_search_region("egg_target", pad_rel=pad_rel)

def detect_egg():
    """
    Sucht das Ei NUR in der ROI um 'egg_target'.
    Bei bestätigtem Treffer (>= EGG_THRESHOLD in 2 aufeinanderfolgenden Scans)
    wird 1x die Klick-Sequenz ausgeführt und Debug-Screenshots gespeichert.
    """
    global egg_lock, egg_absent_since, _egg_seen_hits

    tpl_path = resource_path("golden_egg.png")
    if not os.path.exists(tpl_path):
        return False

    tpl = cv2.imread(tpl_path, cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        print(f"❌ Fehler: Template '{tpl_path}' konnte nicht geladen werden!")
        return False

    # Region um den kalibrierten 'egg_target'-Punkt
    region = _egg_search_region(pad_rel=0.14)   # ~14% vom Spielfenster rundherum
    if region is None:
        print("❌ Spiel-Fenster nicht gefunden.")
        return False
    L, T, W, H = region

    # Screenshot ziehen
    screenshot = pyautogui.screenshot()
    scr = np.array(screenshot)
    scr_gray = cv2.cvtColor(scr, cv2.COLOR_RGB2GRAY)

    # Nur in der Region matchen (nicht Fullscreen)
    roi = scr_gray[T:T+H, L:L+W]
    res = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)

    present = max_val >= EGG_THRESHOLD
    now = time.time()

    if not present:
        _egg_seen_hits = 0
        # Abwesenheit tracken (Debounce)
        if egg_lock:
            if egg_absent_since is None:
                egg_absent_since = now
            elif now - egg_absent_since >= EGG_ABSENCE_RESET_SEC:
                egg_lock = False
                egg_absent_since = None
                print(f"🔄 Ei-Reset nach {EGG_ABSENCE_RESET_SEC}s Abwesenheit.")
        else:
            egg_absent_since = None
        print(f"❌ Kein Ei erkannt (ROI, score={max_val:.3f}).")
        return False

    # Sichtbar
    if egg_lock:
        # bereits abgearbeitet – erst warten, bis weg
        return False

    _egg_seen_hits += 1
    if _egg_seen_hits < EGG_REQUIRED_HITS:
        print(f"👀 Ei-Kandidat (score={max_val:.3f}) – warte Bestätigung… "
              f"({_egg_seen_hits}/{EGG_REQUIRED_HITS})")
        return False

    # Treffer bestätigt → Center des Treffers in globale Koordinaten rechnen
    tw, th = tpl.shape[::-1]
    cx = L + int(max_loc[0] + tw / 2)
    cy = T + int(max_loc[1] + th / 2)
    print(f"🥚 Ei bestätigt (score={max_val:.3f}) @ ({cx},{cy})")

    # Debug-Screenshots speichern
    if EGG_DEBUG_SAVE:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        scr_bgr = cv2.cvtColor(scr, cv2.COLOR_RGB2BGR)

        # ROI und Match markieren
        cv2.rectangle(scr_bgr, (L, T), (L+W, T+H), (0, 255, 0), 2)  # ROI
        cv2.rectangle(scr_bgr,
                      (cx - tw//2, cy - th//2),
                      (cx + tw//2, cy + th//2),
                      (255, 0, 0), 2)  # Match-Box

        out1 = os.path.join(EGG_DEBUG_DIR, f"{ts}_egg_match_{max_val:.3f}.png")
        out2 = os.path.join(EGG_DEBUG_DIR, f"{ts}_egg_roi_{W}x{H}.png")

        cv2.imwrite(out1, scr_bgr)
        cv2.imwrite(out2, cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR))

        print(f"💾 Debug gespeichert:\n   {out1}\n   {out2}")

    # Klick-Sequenz (Ei → Allianz → Zurück)
    try:
        run_egg_sequence(center=(cx, cy))
        egg_lock = True
        _egg_seen_hits = 0
    except Exception as e:
        print(f"⚠️ Fehler bei der Ei-Sequenz: {e}")
        return False

    return True

def open_bn_calibrator():
    """Mini-UI: Nach 4 Sekunden Cursor-Position einsammeln und relativ speichern."""
    # KEIN Vorab-Check mehr hier!
    m = _bn_load_clickmap()

    root = tk.Tk()
    root.title("Blutnacht – Koordinaten kalibrieren")
    root.geometry("540x260")

    tk.Label(root, text=(
        "So geht's:\n"
        "1) Klicke auf „X festlegen“ – nach OK hast du 4 Sekunden,\n"
        "   die Maus im Spiel über das weiße X zu bewegen.\n"
        "2) Dasselbe für den blauen Button unten.\n"
        "Die Punkte werden relativ zum Spielfenster gespeichert."
    ), justify="left").pack(padx=12, pady=10, anchor="w")

    status = tk.Label(root, text=f"Aktuell: X={m['x_close']} | Blau={m['blue_button']}")
    status.pack(padx=12, pady=6, anchor="w")

    def _capture(which, labeltext):
        root.withdraw()
        messagebox.showinfo("Aufnahme", f"Nach OK hast du 4 Sekunden.\nBewege die Maus im Spiel über {labeltext}.")
        time.sleep(4)

        # HIER erst Fenster suchen
        rect = get_game_client_rect()
        if not rect:
            messagebox.showerror("Kalibrieren", "Spiel-Fenster nicht gefunden. Bitte Spiel fokussieren und nochmal.")
            root.deiconify()
            return

        x, y = pyautogui.position()
        left, top, w, h = rect
        rx = round((x - left) / w, 4)
        ry = round((y - top) / h, 4)
        m[which] = [max(0.0, min(1.0, rx)), max(0.0, min(1.0, ry))]
        _bn_save_clickmap(m)
        status.config(text=f"Aktuell: X={m['x_close']} | Blau={m['blue_button']}")
        root.deiconify()

    btns = tk.Frame(root); btns.pack(pady=8)
    tk.Button(btns, text="X oben rechts festlegen", command=lambda: _capture("x_close","„X oben rechts“")).grid(row=0, column=0, padx=6)
    tk.Button(btns, text="Blauen Button festlegen", command=lambda: _capture("blue_button","„blauen Button unten“")).grid(row=0, column=1, padx=6)

    tk.Button(root, text="Testklicks jetzt ausführen",
              command=lambda: (bn_click_fixed("x_close"), time.sleep(0.3), bn_click_fixed("blue_button"))).pack(pady=6)
    tk.Button(root, text="Schließen", command=root.destroy).pack(pady=6)
    root.mainloop()





def open_broadcast_history():
    entries = iter_broadcast_logs()
    """Einfacher Viewer für gespeicherte Broadcasts + Export/Kopieren."""
    import tkinter.ttk as ttk
    from tkinter import filedialog

    root = tk.Tk()
    root.title("Broadcast-Verlauf")
    root.geometry("820x520")
    root.minsize(740, 460)

    top = tk.Frame(root, padx=12, pady=10); top.pack(fill="both", expand=True)

    cols = ("time","count","preview")
    tree = ttk.Treeview(top, columns=cols, show="headings", height=10)
    tree.heading("time", text="Zeit")
    tree.heading("count", text="# Empfänger")
    tree.heading("preview", text="Vorschau")
    tree.column("time", width=160, anchor="w")
    tree.column("count", width=100, anchor="center")
    tree.column("preview", width=440, anchor="w")

    yscroll = ttk.Scrollbar(top, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=yscroll.set)
    tree.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")

    # Details unten
    tk.Label(top, text="Ausgewählter Broadcast:").grid(row=1, column=0, sticky="w", pady=(10,2))
    txt = tk.Text(top, wrap="word", height=10, state="disabled")
    txt.grid(row=2, column=0, columnspan=2, sticky="nsew")

    # Buttons
    btnbar = tk.Frame(top); btnbar.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10,0))

   

    def copy_selected():
        sel = tree.selection()
        if not sel: return
        idx = int(tree.item(sel[0])["text"])
        entry = entries[idx]
        root.clipboard_clear()
        root.clipboard_append(entry.get("text",""))

    def export_txt():
        path = filedialog.asksaveasfilename(
            title="Export als TXT",
            defaultextension=".txt",
            filetypes=[("Textdatei","*.txt")]
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"Broadcast-Verlauf exportiert am {datetime.now():%Y-%m-%d %H:%M:%S}\n\n")
            for e in entries[::-1]:
                f.write(f"[{e.get('datetime_local','')}] ({e.get('count',0)} Empf.)\n")
                f.write(e.get("text","").rstrip()+"\n")
                f.write("-"*60+"\n")
        messagebox.showinfo("Export", "Export abgeschlossen.")

    tk.Button(btnbar, text="In Zwischenablage kopieren", command=copy_selected).pack(side="left", padx=6)
    tk.Button(btnbar, text="Als TXT exportieren…", command=export_txt).pack(side="left", padx=6)
    tk.Button(btnbar, text="Schließen", command=root.destroy).pack(side="left", padx=6)

    # Daten laden & Tabelle füllen
    for idx, e in enumerate(entries):
        preview_line = (e.get("text","").strip().splitlines() or [""])[0]
        if len(preview_line) > 80:
            preview_line = preview_line[:80] + "…"
        tree.insert("", "end", text=str(idx), values=(
            e.get("datetime_local",""),
            e.get("count", 0),
            preview_line
        ))

    # Auswahl-Handler
    def on_select(*_):
        sel = tree.selection()
        if not sel: return
        idx = int(tree.item(sel[0])["text"])
        e = entries[idx]
        txt.config(state="normal"); txt.delete("1.0","end")
        meta = f"[{e.get('datetime_local','')}] ({e.get('count',0)} Empfänger)\n"
        txt.insert("end", meta + e.get("text",""))
        txt.config(state="disabled")

    tree.bind("<<TreeviewSelect>>", on_select)

    # Grid config
    top.rowconfigure(0, weight=1)
    top.rowconfigure(2, weight=1)
    top.columnconfigure(0, weight=1)

    root.mainloop()





















def current_week_start_0400(now_dt=None):
    """
    Liefert den Start der aktuellen ZÄHLWOCHE: Montag 04:00.
    Falls jetzt noch vor Mo 04:00 ist, zählt das noch zur Vorwoche => dann der Montag 04:00 der Vorwoche.
    """
    if now_dt is None:
        now_dt = datetime.now()
    monday_this_week_0400 = (now_dt - timedelta(days=now_dt.weekday())).replace(hour=4, minute=0, second=0, microsecond=0)
    if now_dt < monday_this_week_0400:
        monday_this_week_0400 -= timedelta(days=7)
    return monday_this_week_0400

def last_completed_week_range(now_dt=None):
    """
    Zuletzt abgeschlossene Woche:
    start = Mo 04:00 (vor 7 Tagen relativ zum aktuellen Wochenstart),
    end   = Mo 04:00 (aktueller Wochenstart),
    report_time = end + 1 Minute (Mo 04:01)
    """
    if now_dt is None:
        now_dt = datetime.now()
    end = current_week_start_0400(now_dt)
    start = end - timedelta(days=7)
    report_time = end + timedelta(minutes=REPORT_POST_MINUTE_AFTER)
    return start, end, report_time




def two_hour_bin_label(h):
    a = (h // 2) * 2
    b = (a + 2) % 24
    return f"{a:02d}–{b:02d}"

def compute_weekly_stats(start_dt, end_dt):
    entries = load_logs_in_range(start_dt, end_dt)
    bagger = [e for e in entries if e.get("category") == "bagger"]
    drohne = [e for e in entries if e.get("category") == "drohne"]
    sammel = [e for e in entries if e.get("category") == "sammelstelle"]

    def weekday_de_short(dt):
        mapping = {0: "Mo", 1: "Di", 2: "Mi", 3: "Do", 4: "Fr", 5: "Sa", 6: "So"}
        return mapping[dt.weekday()]

    def summarize(events):
        cnt = len(events)
        wd_count = Counter()
        bin_count = Counter()
        for e in events:
            dt = datetime.fromtimestamp(e["timestamp"])
            wd_count[weekday_de_short(dt)] += 1
            bin_count[two_hour_bin_label(dt.hour)] += 1
        peak_day = "-"
        if wd_count:
            maxv = max(wd_count.values())
            order = ["Mo","Di","Mi","Do","Fr","Sa","So"]
            peak_days = [f"{d} ({wd_count[d]})" for d in order if wd_count.get(d,0)==maxv]
            peak_day = ", ".join(peak_days)
        peak_bin = "-"
        if bin_count:
            labels = [two_hour_bin_label(h) for h in range(0,24,2)]
            maxv = max(bin_count.values())
            peak_bins = [f"{lb} ({bin_count[lb]})" for lb in labels if bin_count.get(lb,0)==maxv]
            peak_bin = peak_bins[0]
        avg_per_day = round(cnt / 7.0, 2)
        return cnt, peak_day, avg_per_day, peak_bin

    b_cnt, b_peak_day, b_avg, b_peak_bin = summarize(bagger)
    d_cnt, d_peak_day, d_avg, d_peak_bin = summarize(drohne)

    # Sammelstellen: Breakdown pro Unterart (begriff)
    ress_counter = Counter()
    for e in sammel:
        res = e.get("begriff", "Unbekannt")
        ress_counter[res] += 1
    ress_list = sorted(ress_counter.items(), key=lambda x: (-x[1], x[0]))

    return {
        "bagger": {"count": b_cnt, "peak_day": b_peak_day, "avg_per_day": b_avg, "peak_time": b_peak_bin},
        "drohne": {"count": d_cnt, "peak_day": d_peak_day, "avg_per_day": d_avg, "peak_time": d_peak_bin},
        "sammel": {"total": sum(ress_counter.values()), "breakdown": ress_list}
    }

def format_weekly_report(stats, start_dt, end_dt, lang="de"):
    """
    Baut den Wochenreport-Text in der gewünschten Sprache.
    peak_day/peak_time bleiben wie berechnet, nur die Texte + Ressourcennamen werden lokalisiert.
    """
    rng = f"{start_dt:%d.%m} {start_dt:%H:%M} – {end_dt:%d.%m} {end_dt:%H:%M} (Mo→Mo)"
    b = stats["bagger"]; d = stats["drohne"]; s = stats["sammel"]

    # Ressourcennamen ggf. ins Englische mappen
    if s["breakdown"]:
        ress_txt = ", ".join([f"{_res_name_by_lang(name, lang)}×{anz}" for name, anz in s["breakdown"][:8]])
        if len(s["breakdown"]) > 8:
            ress_txt += ", …"
    else:
        ress_txt = "-"

    lines = [
        _tr(lang, "weekly_header", rng=rng),
        _tr(lang, "weekly_bagger", count=b['count'], avg=b['avg_per_day'],
            peak_day=b['peak_day'], peak_time=b['peak_time']),
        _tr(lang, "weekly_drone", count=d['count'], avg=d['avg_per_day'],
            peak_day=d['peak_day'], peak_time=d['peak_time']),
        _tr(lang, "weekly_sammel", total=s['total'], ress_txt=ress_txt),
    ]
    return "\n".join(lines)



def post_weekly_report_if_due():
    """
    Wenn der Report (Mo 04:01) fällig ist und noch nicht gepostet wurde,
    jetzt posten. Nachholen beim Start inklusive.
    """
    now_dt = datetime.now()
    start_dt, end_dt, report_time = last_completed_week_range(now_dt)

    key = f"{start_dt:%Y-%m-%d %H:%M:%S}|{end_dt:%Y-%m-%d %H:%M:%S}"
    if key in posted_report_runtime_cache:
        return

    if now_dt.timestamp() >= report_time.timestamp():
        if posted_report_exists_for_range(start_dt, end_dt):
            posted_report_runtime_cache.add(key)
            return

        stats = compute_weekly_stats(start_dt, end_dt)

        # Alle Sprachen bauen
        msg = {
            "de": format_weekly_report(stats, start_dt, end_dt, lang="de"),
            "en": format_weekly_report(stats, start_dt, end_dt, lang="en"),
            "ru": format_weekly_report(stats, start_dt, end_dt, lang="ru"),
            "ja": format_weekly_report(stats, start_dt, end_dt, lang="ja"),
            "ar": format_weekly_report(stats, start_dt, end_dt, lang="ar"),
        }
        try:
            sent = broadcast_localized(msg)
            print(f"📤 Wochenreport an {sent} Empfänger gesendet.")
        except Exception as e:
            print(f"⚠️ Wochenreport-Senden fehlgeschlagen: {e}")

        # Fürs Log eine DE-Referenz ablegen (einheitlich)
        log_event("report", msg["de"], extra={
            "range_start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "range_end": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "stats": stats
        })
        posted_report_runtime_cache.add(key)
        print("✅ Wochenreport gepostet.")




# === ERKENNUNG ===
def detect_bagger():
    global bagger_lock, bagger_absent_since

    print("🔍 Starte Bagger-Erkennung...")

    screenshot = pyautogui.screenshot()
    screenshot_np = np.array(screenshot)
    screen_gray = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2GRAY)

    template_path = resource_path("bagger_icon.png")
    template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
    # --- bei deinen Template-Pfaden ---
    


    if template is None:
        print(f"❌ Fehler: Template '{template_path}' konnte nicht geladen werden!")
        return False

    result = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    print(f"📊 Ähnlichkeit: {max_val:.4f}")

    now = time.time()
    present = max_val >= THRESHOLD

    # --- Symbol aktuell NICHT sichtbar ---
    if not present:
        if bagger_lock:
            # Start/weiterführen des Abwesenheits-Timers
            if bagger_absent_since is None:
                bagger_absent_since = now
            elif now - bagger_absent_since >= BAGGER_ABSENCE_RESET_SEC:
                # lange genug weg -> Lock lösen
                bagger_lock = False
                bagger_absent_since = None
                print(f"🔄 Bagger-Reset nach {BAGGER_ABSENCE_RESET_SEC}s Abwesenheit.")
        else:
            bagger_absent_since = None  # sauber halten
        print("❌ Kein Bagger erkannt.")
        return False

    # --- Symbol ist sichtbar ---
    bagger_absent_since = None  # Abwesenheit zurücksetzen

    # Wenn bereits gepostet und Symbol nie verschwunden -> kein Repost
    if bagger_lock:
        print("⏸️ Bagger noch da (Lock aktiv) → kein Repost.")
        return False

    # Hier nur beim Übergang 'weg' -> 'da': EINMAL posten
    print("✅ Bagger erkannt!")

    try:
        gray = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2GRAY)
        _, thresh = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY)
        text = pytesseract.image_to_string(thresh, lang='eng+deu')

        print("🔍 OCR-Scan auf 'Testflugstörung':")
        print(text)

        # einfacher OCR-Check für Drohne vs Bagger
        text_clean = text.lower()
        text_clean = re.sub(r'[^a-zäöüß]', ' ', text_clean)
        words = text_clean.split()
        drohnen_treffer = get_close_matches("testflugstörung", words, n=1, cutoff=0.8)

        if drohnen_treffer:
            category = "drohne"
            send_alert("drone_alert")
            log_event(category, _tr("de", "drone_alert"))  # im Log deutsch als Referenz
        else:
            category = "bagger"
            send_alert("bagger_alert")
            log_event(category, _tr("de", "bagger_alert"))


        for _ in range(6):
            winsound.Beep(2000, 500)
            time.sleep(0.2)

       

        # Lock setzen: solange Symbol weiter sichtbar ist, kein weiterer Post
        bagger_lock = True

    except Exception as e:
        print(f"⚠️ Fehler beim OCR/Senden: {e}")

    # True zurück -> dein next_bagger_check wird wie gehabt gesetzt
    return True


def detect_ressourcen():
    global gepostete_ressourcen

    print(f"🔍 OCR: Suche nach: {', '.join(SUCHBEGRIFFE.values())}")

    screenshot = pyautogui.screenshot()
    screenshot_np = np.array(screenshot)

    height = screenshot_np.shape[0]
    bottom_crop = screenshot_np[int(height * 0.85):, :]

    cv2.imwrite("screenshot_bottom.png", cv2.cvtColor(bottom_crop, cv2.COLOR_RGB2BGR))

    try:
        gray = cv2.cvtColor(bottom_crop, cv2.COLOR_RGB2GRAY)
        _, thresh = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY)
        text = pytesseract.image_to_string(thresh, lang='eng')

        print("\n========== OCR-ERGEBNIS ==========")
        print(text)
        print("========== ENDE OCR ==========\n")

        text = re.sub(r'(L[vy]\.?\s*\d+)\s+(?=\1)', '', text, flags=re.IGNORECASE)

    except Exception as e:
        print(f"⚠️ OCR-Fehler: {e}")
        return False

    # WICHTIG: nur 1–2 Ziffern zulassen (kein 994), Rest filtern wir zusätzlich per Bereichscheck 1–10
    pattern = r"(?:L[vt]\.?\s*)?(\d{1,2})\s+(" + "|".join(SUCHBEGRIFFE.keys()) + r")"
    matches = re.finditer(pattern, text, re.IGNORECASE)

    now = time.time()
    gepostete_ressourcen = {
        k: t for k, t in gepostete_ressourcen.items() if now - t < 7200
    }

    for match in matches:
        lv_str = match.group(1)
        begriff_raw = match.group(2).lower()
        begriff = SUCHBEGRIFFE.get(begriff_raw, begriff_raw)

        # --- LEVEL-FILTER 1–10 ---
        try:
            lv_val = int(lv_str)
        except ValueError:
            print(f"↩️ Verworfen (kein gültiges Level): '{lv_str}' {begriff}")
            continue
        if not (1 <= lv_val <= 10):
            print(f"↩️ Verworfen (Level außerhalb 1–10): {lv_val} {begriff}")
            continue
        lv = f"Lv. {lv_val}"
        # --------------------------

        key = (begriff.lower(), lv)

        if key in gepostete_ressourcen:
            print(f"ℹ️ Bereits gepostet in den letzten 2 Stunden: {key}")
            continue

        satz = f"{lv} {begriff}"
        print(f"✅ Neuer Fund: {key} -> {satz}")
        gepostete_ressourcen[key] = now

        try:
            send_alert("resource_hint", lv=lv, res=begriff)
            log_event("sammelstelle", _tr("de", "resource_hint", lv=lv, res=begriff),
                extra={"lv": lv, "begriff": begriff})


        except Exception as e:
            print(f"⚠️ Fehler beim Senden: {e}")

        return True

    print("❌ Kein relevanter Satz gefunden.")
    return False

# --- Blutnacht-Popup-Autoklicker --------------------------------------------

# Pfade zu deinen Template-Bildern
BN_TPL_CLOSE_X   = resource_path("bn_close_x.png")
BN_TPL_BLUE_BTN  = resource_path("bn_blue_btn.png")
# --- Blutnacht: Template-Modus (zeitunabhängig) ---
BN_BY_TEMPLATE_ENABLED = False   # <- per Default an; kannst du auch per Tray umschalten, wenn du willst
_bn_lock = False
_bn_absent_since = None
BN_ABSENCE_RESET_SEC = 2.0

# Stabilität: erst klicken, wenn 2 Scans hintereinander Treffer
BN_REQUIRED_HITS = 2
_bn_seen_hits = 0

# Extra-Schutz: nach einem Klick mindestens X Sekunden warten
BN_CLICK_COOLDOWN_SEC = 8
_bn_last_click = 0.0

# feste Zeiten
BN_TIMES_X_ONLY = [(6,32), (14,32), (22,32)]
BN_TIMES_BOTH   = [(7,2),  (15,2),  (23,2)]
BN_TIMES = BN_TIMES_X_ONLY + BN_TIMES_BOTH  # für Fensterbestimmung


# wie „nah an der Zeit“ wir aggressiv suchen (in Minuten)
BN_FOCUS_WINDOW_MIN = 1
# wie oft scannen (Sekunden)
BN_SCAN_INTERVAL_NORMAL  = 15     # außerhalb des Zeitfensters
BN_SCAN_INTERVAL_FOCUSED = 1.5    # innerhalb des Zeitfensters (engmaschiger)
_next_bn_scan = 0.0               # Laufzeit-Timer für das Scan-Intervall

# <<< NEU: Autoclose standardmäßig aus + "einmal pro Slot" merken >>>
BN_AUTOCLOSE_ENABLED = False
EGG_AUTOCLOSE_ENABLED = False

_bn_last_reset_date = None



def _is_within_minutes(now_dt, target_h, target_m, window_min):
    """True, wenn now_dt innerhalb ±window_min um target_h:target_m liegt."""
    t = now_dt.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
    delta = abs((now_dt - t).total_seconds())
    return delta <= window_min * 60

def _in_focus_window(now_dt):
    return any(_is_within_minutes(now_dt, h, m, BN_FOCUS_WINDOW_MIN) for (h, m) in BN_TIMES)

def _locate_center_on_screen(template_path, confidence=0.86, region=None, grayscale=True):
    """Wrapper um pyautogui.locateCenterOnScreen mit sinnvollen Defaults."""
    try:
        pt = pyautogui.locateCenterOnScreen(
            template_path,
            confidence=confidence,
            region=region,
            grayscale=grayscale
        )
        return pt  # (x, y) oder None
    except Exception:
        return None

def _bn_search_region(key: str, pad_rel=0.16):
    """
    Liefert eine Such-Region um den kalibrierten Punkt 'key'
    (key = 'x_close' oder 'blue_button').
    pad_rel ist die Breite/Höhe relativ zum Spielfenster (0.16 = 16%).
    """
    rect = get_game_client_rect()
    if not rect:
        return None
    left, top, w, h = rect

    m = _bn_load_clickmap()
    rx, ry = m.get(key, DEFAULT_BN_CLICKMAP.get(key, [0.5, 0.5]))
    cx = int(left + rx * w)
    cy = int(top  + ry * h)

    rw = int(max(40, pad_rel * w))
    rh = int(max(40, pad_rel * h))

    L = max(left, cx - rw // 2)
    T = max(top,  cy - rh // 2)
    R = min(left + w, L + rw)
    B = min(top  + h, T + rh)

    return (L, T, R - L, B - T)

# neue festen Punkte fürs Ei-Workflow
DEFAULT_BN_CLICKMAP.update({
    "egg_target":   [0.85, 0.18],  # Wo das Ei erscheint (nur fürs Testen/Fallback)
    "egg_alliance": [0.12, 0.92],  # Allianz-Chat
    "egg_back":     [0.06, 0.06],  # Zurück-Button
})

# Golden Egg (OpenCV-Erkennung – wie Bagger)
EGG_THRESHOLD = cfg["thresholds"]["egg"]
egg_lock = False
egg_absent_since = None
EGG_ABSENCE_RESET_SEC = 2.5
next_egg_check = 0.0

# --- Egg: Debug & Debounce ---
EGG_REQUIRED_HITS = 2       # 2 Scans nacheinander nötig
_egg_seen_hits = 0          # Laufzeit-Zähler

EGG_DEBUG_SAVE = True
EGG_DEBUG_DIR = os.path.join(APP_DIR, "egg_debug")
os.makedirs(EGG_DEBUG_DIR, exist_ok=True)

def bloodnight_autoclose_tick_tpl():
    """
    Sucht per Template um die kalibrierten Punkte:
      - bn_close_x.png im Bereich um 'x_close'
      - bn_blue_btn.png im Bereich um 'blue_button'
    Klickt pro Sichtung genau 1x, dann Debounce, bis das Popup sichtbar weg war.
    """
    global _bn_lock, _bn_absent_since, _bn_seen_hits, _bn_last_click

    if not BN_BY_TEMPLATE_ENABLED:
        return

    now = time.time()
    # Cooldown nach letztem Klick
    if (now - _bn_last_click) < BN_CLICK_COOLDOWN_SEC:
        return

    # Regionen vorbereiten
    region_x   = _bn_search_region("x_close", pad_rel=0.16)
    region_btn = _bn_search_region("blue_button", pad_rel=0.16)
    if not region_x and not region_btn:
        return

    # Templates mit hoher Confidence suchen
    pt_x = _locate_center_on_screen(BN_TPL_CLOSE_X,  confidence=0.94, region=region_x,   grayscale=True) if region_x else None
    pt_b = _locate_center_on_screen(BN_TPL_BLUE_BTN, confidence=0.94, region=region_btn, grayscale=True) if region_btn else None

    # Nichts gesehen -> Abwesenheits-Timer für Debounce
    if pt_x is None and pt_b is None:
        _bn_seen_hits = 0
        if _bn_lock:
            if _bn_absent_since is None:
                _bn_absent_since = now
            elif now - _bn_absent_since >= BN_ABSENCE_RESET_SEC:
                _bn_lock = False
                _bn_absent_since = None
        else:
            _bn_absent_since = None
        return

    # Sichtbar
    _bn_absent_since = None
    _bn_seen_hits += 1

    # Bereits bedient? Erst warten bis weg
    if _bn_lock:
        return

    # Noch nicht stabil genug erkannt?
    if _bn_seen_hits < BN_REQUIRED_HITS:
        return

    # Jetzt klicken (höflich erst X, dann Button)
    _focus_game_window()
    did = False
    if pt_x is not None:
        did = bn_click_fixed("x_close", clicks=1) or did
        time.sleep(0.20)
    if pt_b is not None:
        did = bn_click_fixed("blue_button", clicks=1) or did

    if did:
        _bn_lock = True
        _bn_last_click = now
        _bn_seen_hits = 0

def bloodnight_autoclose_tick(now_dt=None):
    """
    Klicke NUR innerhalb des Zeitfensters (±BN_FOCUS_WINDOW_MIN) und pro Slot genau 1x.
    Außerhalb des Fensters wird NICHT geklickt.
    """
    global _next_bn_scan, _fired_slots, _bn_last_reset_date
    if now_dt is None:
        now_dt = datetime.now()

    now_ts = time.time()

    # Autoclose komplett AUS? -> nichts tun, nur später wieder prüfen
    if not BN_AUTOCLOSE_ENABLED:
        _next_bn_scan = now_ts + BN_SCAN_INTERVAL_NORMAL
        return

    # Intervall beachten
    if now_ts < _next_bn_scan:
        return

    # Tageswechsel -> gesetzte Slots zurücksetzen
    if _bn_last_reset_date != now_dt.date():
        _fired_slots.clear()
        _bn_last_reset_date = now_dt.date()

    # 1) Außerhalb des Fensters -> gar nichts tun
    if not _in_focus_window(now_dt):
        _next_bn_scan = now_ts + BN_SCAN_INTERVAL_NORMAL
        return

    # 2) Im Fenster: aktiven Slot ermitteln
    active = [(h, m) for (h, m) in BN_TIMES
              if _is_within_minutes(now_dt, h, m, BN_FOCUS_WINDOW_MIN)]
    if not active:
        _next_bn_scan = now_ts + BN_SCAN_INTERVAL_FOCUSED
        return

    h, m = active[0]
    key = f"{now_dt:%Y-%m-%d}|{h:02d}:{m:02d}"

    if key in _fired_slots:
        _next_bn_scan = now_ts + BN_SCAN_INTERVAL_FOCUSED
        return

    # --- ab hier: genau einmal pro Slot klicken ---
    ok = False
    if (h, m) in BN_TIMES_X_ONLY:
        # nur X
        ok = bn_click_fixed("x_close", clicks=1)
        if ok:
            print(f"BN {h:02d}:{m:02d} → nur X geklickt.")
    elif (h, m) in BN_TIMES_BOTH:
        # X, dann 2 Sekunden warten, dann blauer Button
        ok1 = bn_click_fixed("x_close", clicks=1)
        time.sleep(2.0)  # << genau 2 Sekunden
        ok2 = bn_click_fixed("blue_button", clicks=1)
        ok = (ok1 or ok2)
        if ok:
            print(f"BN {h:02d}:{m:02d} → X + (2s) Blau geklickt.")

    if ok:
        _fired_slots.add(key)            # Slot für heute als erledigt markieren
        _next_bn_scan = now_ts + 60      # 1 Minute Ruhe nach Erfolg
    else:
        _next_bn_scan = now_ts + BN_SCAN_INTERVAL_FOCUSED




def start_tray_icon():
    """System tray icon starten."""
    global tray_icon

    # Icon laden
    try:
        img = Image.open(resource_path("bagger_icon.png")).resize((32, 32), Image.LANCZOS)
    except Exception:
        from PIL import Image as PILImage, ImageDraw
        img = PILImage.new("RGBA", (32, 32), (255, 255, 255, 0))
        d = ImageDraw.Draw(img); d.ellipse((4,4,28,28), outline=(0,0,0,255), width=2)

    # Menü-Callbacks (wie bei dir)
    def _toggle_egg(icon, item):
        global EGG_AUTOCLOSE_ENABLED
        EGG_AUTOCLOSE_ENABLED = not EGG_AUTOCLOSE_ENABLED
        icon.update_menu()

    def _egg_test(icon, item):
        global ui_request; ui_request = "egg_test"

    def _open_egg_calib(icon, item):
        global ui_request; ui_request = "egg_calib"

    def _toggle_pause(icon, item):
        global paused; paused = not paused; icon.update_menu()

    def _toggle_bn(icon, item):
        global BN_AUTOCLOSE_ENABLED; BN_AUTOCLOSE_ENABLED = not BN_AUTOCLOSE_ENABLED; icon.update_menu()

    def _open_bn_calib(icon, item):
        global ui_request; ui_request = "bn_calib"

    def _show_info(icon, item):
        global ui_request; ui_request = "info"

    def _quit(icon, item):
        global running; running = False
        try: icon.stop()
        except Exception: pass

    def _open_recipients(icon, item):
        global ui_request; ui_request = "recipients"

    def _open_broadcast(icon, item):
        global ui_request; ui_request = "broadcast"

    def _pause_label(item):
        return _tr(cfg["language"], "tray_pause") if not paused else _tr(cfg["language"], "tray_resume")

    def _bn_label(item):
        return _tr(cfg["language"], "tray_bn_toggle_on") if BN_AUTOCLOSE_ENABLED else _tr(cfg["language"], "tray_bn_toggle_off")

    def _egg_label(item):
        return _tr(cfg["language"], "tray_egg_toggle_on") if EGG_AUTOCLOSE_ENABLED else _tr(cfg["language"], "tray_egg_toggle_off")

    def _open_lang(icon, item):
        tray_change_language()

    menu = Menu(
        MenuItem(_tr(cfg["language"], "tray_bn_calib"), _open_bn_calib),
        MenuItem(_bn_label, _toggle_bn),
        MenuItem(_tr(cfg["language"], "tray_egg_calib"), _open_egg_calib),
        MenuItem(_egg_label, _toggle_egg),
        MenuItem(_tr(cfg["language"], "tray_egg_test"), _egg_test),
        MenuItem(_tr(cfg["language"], "tray_recipients"), _open_recipients),
        MenuItem(_tr(cfg["language"], "tray_broadcast"), _open_broadcast),
        MenuItem(_tr(cfg["language"], "tray_broadcast_history"), open_broadcast_history),
        MenuItem(_tr(cfg["language"], "tray_language"), _open_lang),
        MenuItem(_pause_label, _toggle_pause),
        MenuItem(_tr(cfg["language"], "tray_info"), _show_info),
        MenuItem(_tr(cfg["language"], "tray_quit"), _quit),
    )

    tray_icon = pystray.Icon("LastWarBot", img, "LastWar Bot", menu)
    # wichtig: nicht blockieren
    tray_icon.run_detached()



# Auto-Reply-Worker starten (läuft, solange 'running' True ist)
if cfg.get("features", {}).get("poll_updates", True):
    threading.Thread(target=lambda: auto_reply_worker(lambda: running), daemon=True).start()
else:
    print("[TG] polling disabled on this instance (features.poll_updates = false)")



def choose_language_first_run():
    # nur wenn 'auto' → sonst in Ruhe lassen
    if cfg.get("language") != "auto":
        return
    root = tk.Tk(); root.withdraw()
    lang = simpledialog.askstring(
        _tr(cfg["language"], "lang_picker_title"),
        _tr(cfg["language"], "lang_picker_body") + "\n\n(en/de/ru/ja/ar)",
        parent=root
    )
    if not lang:
        lang = "en"
    cfg["language"] = normalize_lang(lang)
    save_cfg()
    root.destroy()

def tray_change_language():
    root = tk.Tk(); root.withdraw()
    lang = simpledialog.askstring(
        _tr(cfg["language"], "lang_picker_title"),
        _tr(cfg["language"], "lang_picker_body") + "\n\n(en/de/ru/ja/ar)",
        parent=root
    )
    root.destroy()
    if lang:
        cfg["language"] = normalize_lang(lang)
        save_cfg()
        restart_app()




# ----------------- Start-Infofenster -----------------
def show_startup_info():
    """
    Modernes Welcome-Fenster mit 1 OK-Button und Sprach-Dropdown oben rechts.
    """
    from Module.config import apply_ttk_theme, ACCENT, ACCENT_D, BG_WIN
    prefs_path = os.path.join(APP_DIR, "ui_prefs.json")

    # Prefs laden
    prefs = {}
    try:
        with open(prefs_path, "r", encoding="utf-8") as f:
            prefs = json.load(f)
    except Exception:
        pass
    if prefs.get("hide_welcome"):
        return

    root = tk.Tk()
    apply_ttk_theme(root)

        # Header (mit App-Icon + Titel + Sprachwahl mit Flaggen)
    header = tk.Frame(root, bg=ACCENT)
    header.pack(fill="x")

    # Icon links
    try:
        from PIL import Image, ImageTk
        img = Image.open(resource_path("bagger_icon.png")).resize((44, 44), Image.LANCZOS)
        icon = ImageTk.PhotoImage(img)
        tk.Label(header, image=icon, bg=ACCENT).pack(side="left", padx=14, pady=10)
        header._icon = icon  # Referenz halten
    except Exception:
        tk.Label(header, text="🚜", bg=ACCENT, fg="white", font=("Segoe UI", 18)).pack(side="left", padx=14, pady=10)

    # Titel
    tk.Label(header, text=_tr(cfg["language"], "welcome_header"),
             bg=ACCENT, fg="white", font=("Segoe UI", 16, "bold")).pack(side="left", pady=12)

        # Sprachwahl rechts (Flaggen + Text) – 5 Sprachen
    def _load_flag(rel):
        try:
            fimg = Image.open(resource_path(rel)).resize((20, 14), Image.LANCZOS)
            return ImageTk.PhotoImage(fimg)
        except Exception as e:
            print("[UI] Flaggenladefehler (welcome):", rel, e)
            return None

    FLAGS = {
        "en": _load_flag("Module/data/flag_en.png"),
        "de": _load_flag("Module/data/flag_de.png"),
        "ru": _load_flag("Module/data/flag_ru.png"),
        "ja": _load_flag("Module/data/flag_ja.png"),
        "ar": _load_flag("Module/data/flag_ar.png"),
    }

    cur = normalize_lang(cfg["language"])
    cur_text = f" {cur.upper()}"
    cur_img  = FLAGS.get(cur)

    def on_lang_change(code: str):
        cfg["language"] = code
        save_cfg()
        # sanft neu aufbauen (statt Full-Restart)
        try:
            root.destroy()
            show_startup_info()
            return
        except Exception:
            from Module.config import restart_app
            restart_app()

    lang_btn = tk.Menubutton(
        header,
        text=cur_text,
        image=cur_img, compound=("left" if cur_img else None),
        bg=ACCENT, fg="white",
        activebackground=ACCENT_D, activeforeground="white",
        relief="flat", font=("Segoe UI", 10, "bold")
    )
    lang_btn._flags = FLAGS  # keep references

    menu = tk.Menu(lang_btn, tearoff=False)
    for code in ("en","de","ru","ja","ar"):
        menu.add_radiobutton(
            label=f" {code.upper()}",
            image=FLAGS.get(code),
            compound="left",
            command=lambda c=code: on_lang_change(c)
        )
    lang_btn.configure(menu=menu)
    lang_btn.pack(side="right", padx=10, pady=8)



    # Window
    root.title(_tr(cfg["language"], "welcome_win_title"))
    root.geometry("820x560")
    root.minsize(740, 520)

    # Body (scrollbar)
    import tkinter.ttk as ttk
    outer = ttk.Frame(root, style="Card.TFrame"); outer.pack(fill="both", expand=True, padx=12, pady=12)

    txt = tk.Text(outer, wrap="word", relief="flat", bg="white")
    yscroll = ttk.Scrollbar(outer, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=yscroll.set)
    txt.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")
    outer.rowconfigure(0, weight=1)
    outer.columnconfigure(0, weight=1)

    INFO = _tr(cfg["language"], "welcome_text")
    txt.insert("end", INFO.strip() + "\n")
    txt.configure(state="disabled")

    # Footer (Checkbox + EINER OK-Button)
    footer = tk.Frame(root, bg=BG_WIN); footer.pack(fill="x", padx=12, pady=10)
    dont_var = tk.BooleanVar(value=False)
    chk = tk.Checkbutton(footer, text=_tr(cfg["language"], "welcome_dont_show"),
                         variable=dont_var, bg=BG_WIN)
    chk.pack(side="left")

    def close_ok():
        try:
            prefs["hide_welcome"] = bool(dont_var.get())
            tmp = prefs_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(prefs, f, ensure_ascii=False, indent=2)
            os.replace(tmp, prefs_path)
        except Exception:
            pass
        root.destroy()

    ok_btn = ttk.Button(footer, text=_tr(cfg["language"], "welcome_ok"),
                        style="Accent.TButton", command=close_ok)
    ok_btn.pack(side="right")

    root.mainloop()


# >>> Sprachwahl beim ersten Start
choose_language_first_run()

# >>> Willkommens-Hinweise (falls nicht deaktiviert)
show_startup_info()

# >>> Empfänger-UI zuerst (blockiert bis Start)
from Module.ui_recipients import open_recipients_ui_blocking_start
started = open_recipients_ui_blocking_start()
paused = not started  # nur wenn der Nutzer "Start monitoring" klickt, geht's los

# >>> Tray-Icon starten
start_tray_icon()

# >>> Startmeldung
try:
    from Module.telebot import _send_admin
    _send_admin("started ✔")
except Exception:
    pass

# === HAUPTSCHLEIFE ===
try:
    while running:
        # UI-Anfragen vom Tray NUR im Main-Thread öffnen/schließen
        if ui_request:
            req = ui_request
            ui_request = None  # sofort zurücksetzen

            if req == "recipients":
                was_paused = paused
                paused = True
                try:
                    open_recipients_ui()
                finally:
                    paused = was_paused

            elif req == "info":
                show_startup_info()  # schließt sauber mit X

            elif req == "bn_calib":
                was_paused = paused
                paused = True
                try:
                    open_bn_calibrator()
                finally:
                    paused = was_paused

            elif req == "egg_test":
                was_paused = paused
                paused = True
                try:
                    # Test: benutze die kalibrierte 'egg_target' Position,
                    # damit du ohne echtes Ei die ganze Sequenz prüfen kannst
                    run_egg_sequence(center=None)
                finally:
                    paused = was_paused

            elif req == "egg_calib":
                was_paused = paused
                paused = True
                try:
                    open_egg_calibrator()
                finally:
                    paused = was_paused

            elif req == "broadcast_history":
                was_paused = paused
                paused = True
                try:
                    open_broadcast_history()
                finally:
                    paused = was_paused

            elif req == "broadcast":
                was_paused = paused
                paused = True
                try:
                    open_broadcast_dialog()
                finally:
                    paused = was_paused

            time.sleep(0.1)
            continue


        if paused:
            time.sleep(0.3)
            continue

        now = time.time()

        if now >= next_bagger_check:
            if detect_bagger():
                next_bagger_check = now + 150

        if now >= next_ocr_check:
            if detect_ressourcen():
                next_ocr_check = now + 60
            else:
                next_ocr_check = now + 2

        # Ei-Erkennung wie Bagger getaktet
        if EGG_AUTOCLOSE_ENABLED and now >= next_egg_check:
            if detect_egg():
                next_egg_check = now + 90   # nach Erfolg etwas Ruhe
            else:
                next_egg_check = now + 2    # sonst in 2s erneut prüfen

        # Wochenreport prüfen
        try:
            post_weekly_report_if_due()
        except Exception as e:
            print(f"⚠️ Fehler beim Wochenreport: {e}")
# Blutnacht-Popups automatisch schließen
        try:
            bloodnight_autoclose_tick()
        except Exception as e:
            print(f"BN(TIME): Tick-Fehler: {e}")
    

        time.sleep(0.5)
finally:
    try:
        if tray_icon:
            tray_icon.stop()
    except Exception:
        pass
    sys.exit(0)