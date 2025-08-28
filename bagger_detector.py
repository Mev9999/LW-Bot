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


# >>> FEST VERDRAHTET (dein Token & Bot-Name) <<<
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")


# === BAGGER-DEBOUNCE ===
bagger_lock = False          # True, wenn zuletzt ein Bagger gepostet wurde und Symbol weiterhin sichtbar ist
bagger_absent_since = None   # Zeitstempel, seit wann das Symbol weg ist (oder None)
BAGGER_ABSENCE_RESET_SEC = 3 # so lange muss das Symbol am Stück weg sein, bevor neu gepostet werden darf

running = True   # steuert die Hauptschleife
paused  = False  # Pause/Weiter vom Tray-Menü
tray_icon = None
ui_request = None  # "recipients" | "info" | None

# === EINSTELLUNGEN ===
THRESHOLD = 0.70
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
os.environ['TESSDATA_PREFIX'] = r'C:\Program Files\Tesseract-OCR\tessdata'

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

# === LOGGING ===
LOG_DIR = os.path.join(os.path.abspath("."), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

def _log_path_for_ts(ts):
    dt = datetime.fromtimestamp(ts)
    return os.path.join(LOG_DIR, f"meldungen_{dt:%Y-%m}.json")

def _read_json_list(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []  # Fallback bei korrupter Datei

def _write_json_list(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def log_event(category, text, extra=None):
    """
    category: 'bagger' | 'drohne' | 'sammelstelle' | 'report'
    text: gesendeter WhatsApp-Text
    extra: optionales Dict (z.B. {'lv': 'Lv. 3', 'begriff': 'Eisen'})
    """
    ts = time.time()
    dt = datetime.fromtimestamp(ts)
    item = {
        "timestamp": ts,
        "datetime_local": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "weekday": dt.strftime("%a"),
        "hour": dt.hour,
        "category": category,
        "text": text
    }
    if extra:
        item.update(extra)
    path = _log_path_for_ts(ts)
    data = _read_json_list(path)
    data.append(item)
    _write_json_list(path, data)

# === HELFER ===
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def _app_dir():
    # In EXE: neben die EXE schreiben; im Script: ins aktuelle Verzeichnis
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")

RECIPIENTS_FILE = os.path.join(_app_dir(), "telegram_recipients.json")

def _tg_api(method, payload):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN fehlt.")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    r = requests.post(url, json=payload, timeout=25)
    r.raise_for_status()
    return r.json()

def _load_recipients():
    if os.path.exists(RECIPIENTS_FILE):
        try:
            with open(RECIPIENTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"recipients": []}  # [{"label":"Max","username":"@max","pair_code":"123456","chat_id":123,"paired":true}]

def _save_recipients(data):
    tmp = RECIPIENTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, RECIPIENTS_FILE)

def _ensure_code(r):
    if not r.get("pair_code"):
        r["pair_code"] = "".join(random.choice(string.digits) for _ in range(6))

def _open_pair_link(r):
    code = r["pair_code"]
    link = f"https://t.me/{BOT_USERNAME}?start={code}"
    try:
        webbrowser.open(link)
    except Exception:
        pass
    return link

def _poll_pairing_once(pending_codes, last_update_id=None):
    """Holt Telegram-Updates und liefert Kopplungs-Ereignisse (code, chat_id, label)."""
    payload = {"timeout": 15}
    if last_update_id is not None:
        payload["offset"] = last_update_id + 1
    try:
        resp = _tg_api("getUpdates", payload)
    except Exception:
        time.sleep(1); return last_update_id, []
    if not resp.get("ok"):
        return last_update_id, []
    events = []
    for upd in resp["result"]:
        last_update_id = upd.get("update_id", last_update_id)
        msg = upd.get("message") or {}
        text = (msg.get("text") or "").strip()
        code = None
        if text.isdigit() and len(text) == 6:
            code = text
        elif text.startswith("/start") and len(text.split()) >= 2 and text.split()[1].isdigit():
            code = text.split()[1]
            # NEU: /start ohne Parameter → wenn genau EIN pending, nimm dessen Code
        if not code and text.strip() == "/start" and len(pending_codes) == 1:
            code = next(iter(pending_codes))
        if code and code in pending_codes:
            chat = msg.get("chat") or {}
            user = msg.get("from") or {}
            chat_id = chat.get("id")
            label = user.get("first_name") or chat.get("title") or "Empfänger"
            events.append((code, chat_id, label))
    return last_update_id, events

def setup_telegram_recipients_ui():
    """
    Schöne Verwaltungs-UI:
    • Empfänger in einer Tabelle (Name, @Username, Status, Chat-ID)
    • Hinzufügen / Entfernen / (Re)koppeln
    • Oben farbige Kopfzeile mit Bagger-Icon
    """
    data = _load_recipients()

    # --- Fenster & Farben ---
    root = tk.Tk()
    root.title("Bagger-Alarm – Telegram-Empfänger")
    root.geometry("900x600")
    root.minsize(820, 520)

    ACCENT   = "#1E88E5"
    ACCENT_D = "#1565C0"
    FG_LIGHT = "#FFFFFF"

    # --- Header mit Icon ---
    header = tk.Frame(root, bg=ACCENT)
    header.pack(fill="x")
    try:
        # Bild hübsch skalieren (Pillow ist bei dir installiert)
        from PIL import Image, ImageTk
        img = Image.open(resource_path("bagger_icon.png")).resize((44, 44), Image.LANCZOS)
        icon = ImageTk.PhotoImage(img)
        tk.Label(header, image=icon, bg=ACCENT).pack(side="left", padx=14, pady=10)
        header._icon = icon  # Referenz halten
    except Exception:
        tk.Label(header, text="🛠", bg=ACCENT, fg=FG_LIGHT, font=("Segoe UI", 18)).pack(side="left", padx=14, pady=10)

    tk.Label(
        header,
        text="Bagger-Alarm – Empfänger verwalten",
        bg=ACCENT, fg=FG_LIGHT, font=("Segoe UI", 16, "bold")
    ).pack(side="left", pady=12)

    # --- Inhalt (Tabelle + Log + Buttons) ---
    content = tk.Frame(root, padx=14, pady=14)
    content.pack(fill="both", expand=True)

    # ttk-Styles
    import tkinter.ttk as ttk
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
    style.configure("Accent.TButton", foreground="white")
    style.map("Accent.TButton", background=[("!disabled", ACCENT), ("active", ACCENT_D)])

    # Tabelle
    cols = ("label", "username", "status", "chat_id")
    tree = ttk.Treeview(content, columns=cols, show="headings", height=12)
    headings = {"label": "Name", "username": "@Username", "status": "Status", "chat_id": "Chat-ID"}
    widths   = {"label": 220, "username": 200, "status": 120, "chat_id": 160}

    for c in cols:
        tree.heading(c, text=headings[c])
        tree.column(c, width=widths[c], anchor="w", stretch=True)

    yscroll = ttk.Scrollbar(content, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=yscroll.set)

    tree.grid(row=0, column=0, columnspan=4, sticky="nsew")
    yscroll.grid(row=0, column=4, sticky="ns")

    # Log-Feld
    logtxt = tk.Text(content, height=7, state="disabled")
    logtxt.grid(row=1, column=0, columnspan=5, sticky="nsew", pady=(10, 0))

    def log(msg):
        logtxt.config(state="normal")
        logtxt.insert("end", msg + "\n")
        logtxt.see("end")
        logtxt.config(state="disabled")
        root.update_idletasks()

    # Buttons
    btnbar = tk.Frame(content)
    btnbar.grid(row=2, column=0, columnspan=5, sticky="ew", pady=(12, 0))

    def mkbtn(text, cmd, style_name="Accent.TButton", side="left"):
        b = ttk.Button(btnbar, text=text, command=cmd, style=style_name)
        b.pack(side=side, padx=(0, 8))
        return b

    # Hilfsfunktionen Tabelle
    def refresh():
        for row in tree.get_children():
            tree.delete(row)
        d = _load_recipients()
        data["recipients"] = d["recipients"]
        for idx, r in enumerate(data["recipients"]):
            label   = r.get("label") or ""
            uname   = r.get("username") or ""
            status  = "✅ gekoppelt" if r.get("paired") else "⏳ ausstehend"
            chat_id = r.get("chat_id") or ""
            tree.insert("", "end", iid=str(idx), values=(label, uname, status, chat_id))

    def selected_indices():
        return [int(i) for i in tree.selection()]

    # Aktionen
    def add_clicked():
        text = simpledialog.askstring("Empfänger hinzufügen", "Namen oder @usernames, KOMMA-getrennt:", parent=root)
        if not text:
            return
        parts = [p.strip() for p in text.split(",") if p.strip()]
        d = _load_recipients()
        added = []
        for p in parts:
            label, username = (p, None)
            if p.startswith("@"):
                label = p[1:]; username = p
            # Duplikate vermeiden
            if any(
                (username and r.get("username") == username) or
                (not username and r.get("label", "").lower() == label.lower())
                for r in d["recipients"]
            ):
                log(f"↪️ Bereits vorhanden: {p}")
                continue
            r = {"label": label}
            if username: r["username"] = username
            _ensure_code(r)
            d["recipients"].append(r)
            added.append(r)
            log(f"➕ Hinzugefügt: {p} (Code {r['pair_code']})")

        if not added:
            refresh(); return

        _save_recipients(d); refresh()

        # Links öffnen + auf Kopplung warten
        pending = {r["pair_code"]: r for r in added}
        for r in added:
            link = _open_pair_link(r)
            log(f"🔗 Link geöffnet: {r.get('label')} → {link}")

        log("⏳ Warte bis zu 3 Minuten auf Kopplung…")
        start = time.time(); last_id = None
        while time.time() - start < 180 and pending:
            last_id, evts = _poll_pairing_once(pending, last_update_id=last_id)
            changed = False
            for code, chat_id, _ in evts:
                rr = pending.pop(code, None)
                if rr and chat_id:
                    rr["chat_id"] = chat_id
                    rr["paired"]  = True
                    changed = True
                    log(f"✅ Gekoppelt: {rr.get('label')} (chat_id={chat_id})")
            if changed:
                _save_recipients(d); refresh()
            root.update(); time.sleep(0.4)

    def remove_clicked():
        idxs = selected_indices()
        if not idxs:
            messagebox.showinfo("Entfernen", "Bitte Empfänger in der Tabelle markieren.")
            return
        if not messagebox.askyesno("Bestätigen", "Ausgewählte Empfänger wirklich entfernen?"):
            return
        d = _load_recipients()
        for i in sorted(idxs, reverse=True):
            if 0 <= i < len(d["recipients"]):
                d["recipients"].pop(i)
        _save_recipients(d)
        log(f"🗑️ {len(idxs)} Empfänger entfernt.")
        refresh()

    def pair_clicked():
        idxs = selected_indices()
        if not idxs:
            messagebox.showinfo("Koppeln", "Bitte Empfänger in der Tabelle markieren.")
            return
        d = _load_recipients()
        to_pair = []
        for i in idxs:
            if 0 <= i < len(d["recipients"]):
                r = d["recipients"][i]
                r["paired"] = False
                r.pop("chat_id", None)
                _ensure_code(r)
                to_pair.append(r)
        if not to_pair:
            return
        _save_recipients(d); refresh()

        pending = {r["pair_code"]: r for r in to_pair}
        for r in to_pair:
            link = _open_pair_link(r)
            log(f"🔗 Link geöffnet: {r.get('label')} → {link}")

        log("⏳ Warte bis zu 3 Minuten auf Kopplung…")
        start = time.time(); last_id = None
        while time.time() - start < 180 and pending:
            last_id, evts = _poll_pairing_once(pending, last_update_id=last_id)
            changed = False
            for code, chat_id, _ in evts:
                rr = pending.pop(code, None)
                if rr and chat_id:
                    rr["chat_id"] = chat_id
                    rr["paired"]  = True
                    changed = True
                    log(f"✅ Gekoppelt: {rr.get('label')} (chat_id={chat_id})")
            if changed:
                _save_recipients(d); refresh()
            root.update(); time.sleep(0.4)

    def close_and_continue():
        root.destroy()

    # Buttons platzieren
    mkbtn("➕ Empfänger hinzufügen", add_clicked)
    mkbtn("🗑️ Entfernen", remove_clicked)
    mkbtn("🔗 (Re)koppeln", pair_clicked)
    ttk.Button(btnbar, text="▶ Programm starten", command=close_and_continue, style="Accent.TButton").pack(side="right")

    # Grid-Resizing
    content.rowconfigure(0, weight=1)
    content.rowconfigure(1, weight=1)
    content.columnconfigure(0, weight=1)

    refresh()
    root.mainloop()



def send_to_whatsapp(message: str):
    """Ersatz: Sendet per Telegram-Bot an alle gekoppelten Empfänger."""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN fehlt.")
        return
    data = _load_recipients()
    paired = [r for r in data["recipients"] if r.get("paired") and r.get("chat_id")]
    if not paired:
        print("❌ Keine gekoppelten Telegram-Empfänger – Nachricht nicht gesendet.")
        return
    dead = []
    for r in paired:
        try:
            _tg_api("sendMessage", {"chat_id": r["chat_id"], "text": message})
            print(f"📤 Telegram an {r.get('label','Empfänger')} gesendet.")
        except Exception as e:
            print(f"⚠️ Senden an {r} fehlgeschlagen: {e}")
            dead.append(r)
    if dead:
        for rr in data["recipients"]:
            if rr in dead:
                rr["paired"] = False
                rr.pop("chat_id", None)   # <<< wichtig: chat_id entfernen, damit Re-Kopplung klappt
    _save_recipients(data)


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

def load_logs_in_range(start_dt, end_dt):
    """Alle Monatsdateien im Bereich durchsuchen und Einträge filtern (start <= ts < end)."""
    months = set([(start_dt.year, start_dt.month), (end_dt.year, end_dt.month)])
    files = []
    for y, m in months:
        files.extend(glob(os.path.join(LOG_DIR, f"meldungen_{y:04d}-{m:02d}.json")))
    entries = []
    for path in set(files):
        for item in _read_json_list(path):
            ts = item.get("timestamp")
            if ts is None:
                continue
            dt = datetime.fromtimestamp(ts)
            if start_dt <= dt < end_dt:
                entries.append(item)
    return entries

def posted_report_exists_for_range(start_dt, end_dt):
    """
    Prüft, ob für genau dieses Zeitfenster (start/end) bereits ein Report geloggt wurde.
    Nicht per Timestamp window filtern (Report liegt nach dem Fenster), sondern über range_start/range_end.
    """
    target_start = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    target_end = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    for path in glob(os.path.join(LOG_DIR, "meldungen_*.json")):
        for e in _read_json_list(path):
            if e.get("category") == "report" \
               and e.get("range_start") == target_start \
               and e.get("range_end") == target_end:
                return True
    return False

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

def format_weekly_report(stats, start_dt, end_dt):
    rng = f"{start_dt:%d.%m} {start_dt:%H:%M} – {end_dt:%d.%m} {end_dt:%H:%M} (Mo→Mo)"
    b = stats["bagger"]; d = stats["drohne"]; s = stats["sammel"]

    # Sammelstellen kompakt (z. B. "Eisen×6, Öl×6, Gold×2")
    if s["breakdown"]:
        ress_txt = ", ".join([f"{name}×{anz}" for name, anz in s["breakdown"][:8]])
        if len(s["breakdown"]) > 8:
            ress_txt += ", …"
    else:
        ress_txt = "-"

    lines = [
        f"📊 Wochenstatistik {rng}",
        f"• 🚜 Bagger: {b['count']} | Ø/Tag: {b['avg_per_day']} | Peak-Tag: {b['peak_day']} | Peak-Zeit: {b['peak_time']}",
        f"• 🛸 Drohne: {d['count']} | Ø/Tag: {d['avg_per_day']} | Peak-Tag: {d['peak_day']} | Peak-Zeit: {d['peak_time']}",
        f"• 📍 Sammelstellen: {s['total']}  ({ress_txt})",
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
        msg = format_weekly_report(stats, start_dt, end_dt)
        send_to_whatsapp(msg)
        log_event("report", msg, extra={
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
        text = pytesseract.image_to_string(thresh, lang='eng')

        print("🔍 OCR-Scan auf 'Testflugstörung':")
        print(text)

        # einfacher OCR-Check für Drohne vs Bagger
        text_clean = text.lower()
        text_clean = re.sub(r'[^a-zäöüß]', ' ', text_clean)
        words = text_clean.split()
        drohnen_treffer = get_close_matches("testflugstörung", words, n=1, cutoff=0.8)

        if drohnen_treffer:
            message = "🚨 DROHNEN-ALARM: 🛸"
            category = "drohne"
        else:
            message = "🚨 BAGGER-ALARM: 🚜"
            category = "bagger"

        for _ in range(6):
            winsound.Beep(2000, 500)
            time.sleep(0.2)

        # Posten + Loggen
        send_to_whatsapp(message)
        log_event(category, message)

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
            message = f"📌 Hinweis: '{satz}'"
            send_to_whatsapp(message)

            # Alles aus der Ressourcenerkennung zählt als Sammelstelle (Unterart in 'begriff')
            log_event("sammelstelle", message, extra={"lv": lv, "begriff": begriff})

        except Exception as e:
            print(f"⚠️ Fehler beim Senden: {e}")

        return True

    print("❌ Kein relevanter Satz gefunden.")
    return False

def start_tray_icon():
    """Startet das Tray-Icon in einem eigenen Thread (Tk-Fenster nur via Main-Thread)."""
    def _run():
        global tray_icon  # Referenz merken

        # Icon laden
        try:
            img = Image.open(resource_path("bagger_icon.png")).resize((32, 32), Image.LANCZOS)
        except Exception:
            from PIL import Image as PILImage
            img = PILImage.new("RGBA", (32, 32), (255, 255, 255, 0))

        # Menü-Callbacks (ALLE auf globale Flags arbeiten)
        def _toggle_pause(icon, item):
            global paused
            paused = not paused
            icon.update_menu()

        def _open_recipients(icon, item):
            global ui_request
            ui_request = "recipients"

        def _show_info(icon, item):
            global ui_request
            ui_request = "info"

        def _quit(icon, item):
            global running
            running = False
            try:
                icon.stop()
            except Exception:
                pass

        def _pause_label(item):
            return "⏸️ Pause" if not paused else "▶️ Weiter"

        menu = Menu(
            MenuItem("Empfänger öffnen", _open_recipients),
            MenuItem(_pause_label, _toggle_pause),
            MenuItem("ℹ️ Hinweise", _show_info),
            MenuItem("Beenden", _quit)
        )

        tray_icon = pystray.Icon("LastWarBot", img, "LastWar Bot", menu)
        tray_icon.run()

    threading.Thread(target=_run, daemon=True).start()



# ----------------- Start-Infofenster -----------------
def show_startup_info():
    """
    Zeigt beim Programmstart Hinweise an (mit 'Nicht mehr anzeigen').
    """
    prefs_path = os.path.join(_app_dir(), "ui_prefs.json")

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
    root.lift()
    root.after(50, lambda: root.focus_force())
    root.attributes('-topmost', True)
    root.after(250, lambda: root.attributes('-topmost', False))

    root.title("Bagger-Alarm – Hinweise")
    root.geometry("780x560")
    root.minsize(700, 520)

    ACCENT   = "#1E88E5"
    ACCENT_D = "#1565C0"
    FG_LIGHT = "#FFFFFF"

    # Header
    header = tk.Frame(root, bg=ACCENT)
    header.pack(fill="x")
    try:
        from PIL import Image, ImageTk
        img = Image.open(resource_path("bagger_icon.png")).resize((44, 44), Image.LANCZOS)
        icon = ImageTk.PhotoImage(img)
        tk.Label(header, image=icon, bg=ACCENT).pack(side="left", padx=14, pady=10)
        header._icon = icon
    except Exception:
        tk.Label(header, text="🚜", bg=ACCENT, fg=FG_LIGHT, font=("Segoe UI", 18)).pack(side="left", padx=14, pady=10)

    tk.Label(header, text="Willkommen! So richtest du den Bagger-Alarm ein",
             bg=ACCENT, fg=FG_LIGHT, font=("Segoe UI", 16, "bold")).pack(side="left", pady=12)

    # Inhalt
    body = tk.Frame(root, padx=14, pady=14)
    body.pack(fill="both", expand=True)

    # Scrollbarer Text
    import tkinter.ttk as ttk
    txt = tk.Text(body, wrap="word")
    yscroll = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=yscroll.set)
    txt.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")

    INFO = f"""
🧩 Telegram koppeln
• Sende deinem Admin/Verwalter deinen Telegram-@Benutzernamen.
• Der Admin trägt dich im Programm unter „Empfänger hinzufügen“ ein.
• Öffne in Telegram den Bot @LastWar_admin_bot und tippe auf „Start“
  (alternativ bekommst du Link/QR – beides funktioniert).
• Sobald in der Liste „✅ gekoppelt“ steht, empfängst du Nachrichten.

🎮 Voraussetzungen im Spiel (auf dem PC, auf dem die EXE läuft)
• Du bist im Spiel eingeloggt.
• Der ALLIANZ-CHAT ist unten dauerhaft sichtbar.
• Der Bot funktioniert nur, wenn Chatleiste UND Bagger-Icon nicht verdeckt sind.

⚠️ Popups
• Saison-Popups (z. B. Stadteinnahmen, Blutnacht, …) können die Erkennung überdecken.
• Diese Popups bitte wegklicken – danach läuft der Bot wieder.
• In der Off-Season läuft der Bot durch, solange das Spiel läuft und der Allianz-Chat sichtbar ist.
• In einem Update wird daran gearbeitet, solche Popups automatisch zu schließen.

ℹ️ Sonstiges
• Es werden nur Sammelstellen der Stufen Lv. 1–10 gemeldet.
• Doppelte Meldungen (selbe Ressource + Level) werden für 2 Stunden unterdrückt.
• Der nächste Bagger oder die nächste Drohne kann erst 3 Sekunden nach verschwinden der vorherigen Bagger-Icons angezeigt werden.
• Es wird jede Woche am Montag um 04:01 eine Wochenauswertung über die Treffer in die Gruppe gepostet.
"""

    txt.insert("end", INFO.strip() + "\n")
    txt.configure(state="disabled")

    # Footer mit Buttons
    footer = tk.Frame(root, padx=14, pady=10)
    footer.pack(fill="x")

    dont_var = tk.BooleanVar(value=False)
    chk = tk.Checkbutton(footer, text="Nicht mehr anzeigen", variable=dont_var)
    chk.pack(side="left")

    def close_ok():
        # Prefs speichern
        try:
            prefs["hide_welcome"] = bool(dont_var.get())
            tmp = prefs_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(prefs, f, ensure_ascii=False, indent=2)
            os.replace(tmp, prefs_path)
        except Exception:
            pass
        root.destroy()

    ok = tk.Button(footer, text="OK, verstanden", bg=ACCENT, fg=FG_LIGHT,
                   activebackground=ACCENT_D, activeforeground=FG_LIGHT, command=close_ok)
    ok.pack(side="right", padx=4)

    root.rowconfigure(0, weight=1)
    body.rowconfigure(0, weight=1)
    body.columnconfigure(0, weight=1)

    root.mainloop()
# ----------------- /Start-Infofenster -----------------

# >>> Willkommens-Hinweise (falls nicht deaktiviert)
show_startup_info()

# >>> Tray-Icon starten
start_tray_icon()

# >>> Empfänger-UI (einmalig öffnen, danach läuft Bot im Tray)
setup_telegram_recipients_ui()

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
                    setup_telegram_recipients_ui()  # schließt sauber mit X
                finally:
                    paused = was_paused

            elif req == "info":
                show_startup_info()  # schließt sauber mit X

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

        # Wochenreport prüfen
        try:
            post_weekly_report_if_due()
        except Exception as e:
            print(f"⚠️ Fehler beim Wochenreport: {e}")

        time.sleep(0.5)
finally:
    try:
        if tray_icon:
            tray_icon.stop()
    except Exception:
        pass
    sys.exit(0)
