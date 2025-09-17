# updater.py  (neben main.py ablegen)
import os, sys, json, re, zipfile, tempfile, shutil, subprocess
from urllib.request import urlopen, Request
from Module.version import APP_VERSION
print("Version:", APP_VERSION)


GITHUB_OWNER = "Mev9999"      # << anpassen
GITHUB_REPO  = "LW-Bot"       # << anpassen
ASSET_PREFIX = "AlertModular_Portable_"  # Release-Asset-Name muss so beginnen
EXE_NAME     = "AlertModular.exe"        # Name deiner EXE im Paket

def _app_dir():
    # Ordner, in dem die App gerade läuft (auch in onedir/onefile sinnvoll)
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def _read_local_version():
    for base in [sys.argv[0], _app_dir()]:
        path = os.path.join(os.path.dirname(base), "VERSION")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except: pass
    return "0.0.0"

def _ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3] or [0])

def _fetch_latest_release():
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    req = Request(url, headers={"User-Agent":"Updater"})
    with urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    tag = (data.get("tag_name") or data.get("name") or "").lstrip("v")
    asset = None
    for a in data.get("assets", []):
        n = a.get("name","")
        if n.startswith(ASSET_PREFIX) and n.endswith(".zip"):
            asset = a.get("browser_download_url")
            break
    return tag, asset

def _download(url, dst):
    req = Request(url, headers={"User-Agent":"Updater"})
    with urlopen(req, timeout=120) as r, open(dst, "wb") as f:
        shutil.copyfileobj(r, f)

def _extract_zip(zip_path, dest_dir):
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(dest_dir)

def check_and_offer_update(auto=False):
    local = _read_local_version()
    try:
        latest, url = _fetch_latest_release()
    except Exception:
        return  # offline/keine Releases

    if not url or _ver_tuple(latest) <= _ver_tuple(local):
        return

    print(f"Update verfügbar: {local} → {latest}")
    if not auto:
        try:
            ans = input("Jetzt laden & starten? (j/N): ").strip().lower()
        except Exception:
            ans = "n"
        if ans != "j":
            return

    appdir = _app_dir()
    upd_root = os.path.join(appdir, "updates")
    os.makedirs(upd_root, exist_ok=True)

    tmp_zip = os.path.join(tempfile.gettempdir(), f"{ASSET_PREFIX}{latest}.zip")
    try:
        print("Lade:", url)
        _download(url, tmp_zip)
        target_dir = os.path.join(upd_root, latest)
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir, ignore_errors=True)
        os.makedirs(target_dir, exist_ok=True)
        _extract_zip(tmp_zip, target_dir)
        # EXE suchen
        exe_path = os.path.join(target_dir, EXE_NAME)
        if not os.path.exists(exe_path):
            # Fallback: EXE irgendwo im entpackten Baum suchen
            for root, _, files in os.walk(target_dir):
                if EXE_NAME in files:
                    exe_path = os.path.join(root, EXE_NAME)
                    break
        if not os.path.exists(exe_path):
            raise RuntimeError("Neue EXE nicht gefunden nach dem Entpacken.")

        # neue Version starten & alte beenden
        subprocess.Popen([exe_path], cwd=os.path.dirname(exe_path), shell=False)
        os._exit(0)
    except Exception as e:
        print("Update-Fehler:", e)
    finally:
        try: os.remove(tmp_zip)
        except: pass
