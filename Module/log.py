# Alert_modular/log.py
import os, json, time
from datetime import datetime
from glob import glob

# Log-Verzeichnis neben EXE / im Arbeitsordner
LOG_DIR = os.path.join(os.path.abspath("."), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

def _log_path_for_ts(ts: float) -> str:
    dt = datetime.fromtimestamp(ts)
    return os.path.join(LOG_DIR, f"meldungen_{dt:%Y-%m}.json")

def read_json_list(path: str):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _write_json_list(path: str, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def log_event(category: str, text: str, extra: dict | None = None):
    """
    category: 'bagger' | 'drohne' | 'sammelstelle' | 'report' | 'broadcast'
    text:     gesendeter Text (Referenz; i. d. R. DE)
    extra:    optionales Dict (z.B. {'lv': 'Lv. 3', 'begriff': 'Eisen'})
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
    data = read_json_list(path)
    data.append(item)
    _write_json_list(path, data)

def load_logs_in_range(start_dt: datetime, end_dt: datetime):
    """
    Alle Monatsdateien im Bereich durchsuchen und Einträge filtern (start <= ts < end).
    """
    months = set([(start_dt.year, start_dt.month), (end_dt.year, end_dt.month)])
    files = []
    for y, m in months:
        files.extend(glob(os.path.join(LOG_DIR, f"meldungen_{y:04d}-{m:02d}.json")))
    entries = []
    for path in set(files):
        for item in read_json_list(path):
            ts = item.get("timestamp")
            if ts is None:
                continue
            dt = datetime.fromtimestamp(ts)
            if start_dt <= dt < end_dt:
                entries.append(item)
    return entries

def posted_report_exists_for_range(start_dt: datetime, end_dt: datetime) -> bool:
    """
    Prüft, ob für GENAU dieses Zeitfenster (start/end) bereits ein Report geloggt wurde.
    Wir prüfen über gespeicherte 'range_start'/'range_end' im Log.
    """
    target_start = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    target_end   = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    for path in glob(os.path.join(LOG_DIR, "meldungen_*.json")):
        for e in read_json_list(path):
            if e.get("category") == "report" \
               and e.get("range_start") == target_start \
               and e.get("range_end") == target_end:
                return True
    return False

def iter_broadcast_logs():
    """
    Liest alle Broadcast-Logs aus /logs und liefert neu→alt sortierte Einträge.
    (Nützlich für eine spätere Broadcast-History-UI.)
    """
    entries = []
    for path in glob(os.path.join(LOG_DIR, "meldungen_*.json")):
        for item in read_json_list(path):
            if item.get("category") == "broadcast":
                entries.append(item)
    entries.sort(key=lambda e: e.get("timestamp", 0), reverse=True)
    return entries
