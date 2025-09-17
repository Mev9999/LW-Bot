# Module/i18n.py
import json, os
from .config import resource_path

def _load_json(rel: str):
    p = resource_path(rel)
    if not os.path.exists(p):
        raise FileNotFoundError(f"I18N/Resource-Datei fehlt: {p}")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

# bekannte Sprachen
AVAILABLE_LANGS = ("de", "en", "ar", "ja", "ru")

# ---- zuerst normalize_lang definieren (wird unten beim Preload benutzt)
def normalize_lang(s: str) -> str:
    if not s:
        return "en"
    s = s.strip().lower()
    if s.startswith("de"): return "de"
    if s.startswith("en"): return "en"
    if s.startswith("ar"): return "ar"
    if s.startswith("ja") or s.startswith("jp"): return "ja"
    if s.startswith("ru"): return "ru"
    return "en"

# Lazy-Cache
_LANG_CACHE: dict[str, dict] = {}

def _ensure_lang(lang_code: str):
    code = normalize_lang(lang_code)
    if code in _LANG_CACHE:
        return
    filename = f"Module/data/i18n.{code}.json"
    try:
        _LANG_CACHE[code] = _load_json(filename)
    except Exception:
        # Fallback: EN muss existieren
        if "en" not in _LANG_CACHE:
            _LANG_CACHE["en"] = _load_json("Module/data/i18n.en.json")
        _LANG_CACHE[code] = _LANG_CACHE["en"]

# Ressourcen-Map laden
_RES_MAP = _load_json("Module/data/resource_map.json")

# Optionaler Preload (häufig genutzt)
for _base in ("en", "de"):
    try:
        _ensure_lang(_base)
    except Exception:
        pass

def tr(lang: str, key: str, **kwargs) -> str:
    _ensure_lang(lang)
    L = _LANG_CACHE.get(normalize_lang(lang), _LANG_CACHE.get("en", {}))
    template = L.get(key)
    if template is None:
        _ensure_lang("en")
        template = _LANG_CACHE["en"].get(key, key)
    try:
        return template.format(**kwargs)
    except Exception:
        return template

def res_name(name: str, lang: str) -> str:
    return _RES_MAP.get(name, name) if normalize_lang(lang) == "en" else name

def res_name_by_lang(name: str, lang: str) -> str:
    return res_name(name, lang)

def lang_display(code: str) -> str:
    m = {"de": "DE", "en": "EN", "ar": "AR", "ja": "JA", "ru": "RU"}
    return m.get(normalize_lang(code), "EN")
