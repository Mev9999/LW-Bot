# Module/config.py
import os, sys, json, uuid, socket
import tkinter as tk
import tkinter.ttk as ttk
import subprocess

# Farben zentral
ACCENT   = "#1E88E5"
ACCENT_D = "#1565C0"
BG_WIN   = "#F5F6F8"
BG_CARD  = "#FFFFFF"
FG       = "#1A1A1A"

def apply_ttk_theme(root: tk.Misc):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    # Grundfarben
    root.configure(bg=BG_WIN)
    style.configure(".", background=BG_WIN, foreground=FG)

    style.configure("Card.TFrame", background=BG_CARD)
    style.configure("TLabel", background=BG_CARD, foreground=FG)
    style.configure("TButton", padding=(10, 6))

    # Akzent-Button
    style.configure("Accent.TButton", foreground="white", background=ACCENT)
    style.map("Accent.TButton",
              background=[("active", ACCENT_D), ("pressed", ACCENT_D)])

def restart_app():
    """Neustart der aktuellen App."""
    exe = sys.executable
    args = [exe] + sys.argv
    try:
        if getattr(sys, "frozen", False):
            os.execv(exe, args)
        else:
            subprocess.Popen(args)
            os._exit(0)
    except Exception:
        os.execv(exe, args)
        
def _app_dir():
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")

APP_DIR = _app_dir()

def resource_path(relative_path: str):
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


CONFIG_FILE = os.path.join(APP_DIR, "config.json")

_DEFAULT_CFG = {
    "language": "de",
    "telegram_bot_token": "",
    "bot_username": "LastWar_admin_bot",
    "admin_contact": "@Mev_Bot_Admin89",
    "tesseract_cmd": r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    "tessdata_prefix": r"C:\Program Files\Tesseract-OCR\tessdata",
    "thresholds": {"bagger": 0.70, "egg": 0.90},
    # >>> NEU:
    "instance_name": "auto",           # eindeutiger Name dieser EXE
    "admin_channel_id": -1002990182932,              # Telegram-ID des Admin-Channels (negativ, z.B. -1001234567890)
    "features": {
        "bn_autoclose": False,
        "egg_autoclose": False,
        "poll_updates": True            # diese Instanz darf getUpdates long-pollen
    }
}

def _load_cfg():
    cfg = dict(_DEFAULT_CFG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user = json.load(f)
                if isinstance(user, dict):
                    # deep-merge für "features"
                    if "features" in user and isinstance(user["features"], dict):
                        cfg["features"].update(user["features"])
                        user = {k:v for k,v in user.items() if k != "features"}
                    cfg.update(user)
        except Exception:
            pass
    tok = os.environ.get("ALERT_MODULAR_TOKEN")
    if tok:
        cfg["telegram_bot_token"] = tok
    return cfg

cfg = _load_cfg()

# >>> NEU: Config persistieren
def save_cfg():
    try:
        cur = dict(_DEFAULT_CFG)
        # deep-merge features, dann überschreiben
        cur.update(cfg)
        if "features" in cfg and isinstance(cfg["features"], dict):
            cur["features"].update(cfg["features"])
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_FILE)
    except Exception as e:
        print(f"[CFG] save_cfg failed: {e}")

def _ensure_instance_name():
    import uuid
    import os, json
    # 1) Falls schon gesetzt (nicht "auto"): nichts tun
    iname = str(cfg.get("instance_name") or "").strip()
    if iname and iname.lower() != "auto":
        return

    # 2) Stabile Kurz-ID pro Installation (Datei im APP_DIR)
    iid_file = os.path.join(APP_DIR, "instance_id.txt")
    if os.path.exists(iid_file):
        with open(iid_file, "r", encoding="utf-8") as f:
            short = f.read().strip()
    else:
        short = uuid.uuid4().hex[:6]   # z.B. 'a1b2c3'
        with open(iid_file, "w", encoding="utf-8") as f:
            f.write(short)

    import socket
    host = socket.gethostname()
    new_name = f"{host}-{short}".replace(" ", "_")

    cfg["instance_name"] = new_name
    save_cfg()  # dauerhaft speichern

_ensure_instance_name()

def init_env():
    os.environ['TESSDATA_PREFIX'] = cfg["tessdata_prefix"]
    return cfg["tesseract_cmd"]


