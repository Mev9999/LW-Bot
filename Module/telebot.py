# Alert_modular/telebot.py
import os, time, json, requests
from datetime import datetime
from .config import cfg, resource_path
from .i18n import tr, res_name, normalize_lang  # normalize_lang dazu
import re
from .log import log_event


RECIPIENTS_FILE = os.path.join(os.path.abspath("."), "telegram_recipients.json")

def _tg_api(method, payload):
    if not cfg["telegram_bot_token"]:
        raise RuntimeError("TELEGRAM_BOT_TOKEN fehlt (config.json oder Umgebungsvariable).")
    url = f"https://api.telegram.org/bot{cfg['telegram_bot_token']}/{method}"
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
    return {"recipients": []}

def _save_recipients(data):
    tmp = RECIPIENTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, RECIPIENTS_FILE)
    _report_recipients_summary()

def _report_recipients_summary():
    d = _load_recipients()
    paired = [r for r in d.get("recipients", []) if r.get("paired") and r.get("chat_id")]
    parts = []
    for r in paired[:12]:  # Preview begrenzen
        uname = r.get("label") or r.get("username") or "?"
        lang = r.get("lang") or "de"
        parts.append(f"{uname}({lang})")
    more = ""
    if len(paired) > 12:
        more = f", … +{len(paired)-12}"
    _send_admin(f"recipients: {len(paired)} → " + (", ".join(parts) + more))
    # komplette Datei als JSON mitschicken (praktisch zum Debuggen)
    try:
        tmp = os.path.join(os.path.abspath("."), f"recipients_{cfg.get('instance_name','EXE')}.json")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        _send_admin_doc(tmp, caption="recipients.json")
        os.remove(tmp)
    except Exception as e:
        print(f"[TG] report recipients json fail: {e}")

def _send_admin(text: str):
    """Schickt eine Zeile in den zentralen Admin-Channel (wenn gesetzt)."""
    chat_id = int(cfg.get("admin_channel_id") or 0)
    if not chat_id:
        return
    prefix = f"[{cfg.get('instance_name','EXE')}] "
    try:
        _tg_api("sendMessage", {"chat_id": chat_id, "text": prefix + text})
    except Exception as e:
        print(f"[TG] send_admin fail: {e}")

def _send_admin_doc(path: str, caption: str = ""):
    chat_id = int(cfg.get("admin_channel_id") or 0)
    if not chat_id or not os.path.exists(path):
        return
    url = f"https://api.telegram.org/bot{cfg['telegram_bot_token']}/sendDocument"
    files = {"document": open(path, "rb")}
    data = {"chat_id": chat_id, "caption": f"[{cfg.get('instance_name','EXE')}] {caption}"}
    try:
        r = requests.post(url, data=data, files=files, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[TG] send_admin_doc fail: {e}")
    finally:
        try: files["document"].close()
        except: pass

def _parse_lang_blocks(body: str) -> dict:
    """
    Erlaube drei Varianten:
    1) [ALL]...      -> an alle Sprachen identisch
    2) [EN]...[/EN]  und/oder  [DE]...[/DE]
    3) sonst: Standard an alle
    """
    by = {}
    m_all = re.search(r"\[ALL\](.*)$", body, re.S | re.I)
    if m_all:
        txt = m_all.group(1).strip()
        if txt:
            by["de"] = txt
            by["en"] = txt
            return by

    m_en = re.search(r"\[EN\](.*?)\[/EN\]", body, re.S | re.I)
    m_de = re.search(r"\[DE\](.*?)\[/DE\]", body, re.S | re.I)
    if m_en:
        by["en"] = m_en.group(1).strip()
    if m_de:
        by["de"] = m_de.group(1).strip()

    if by:
        return by

    # Fallback: identisch an alle
    body = body.strip()
    if body:
        by["de"] = body
        by["en"] = body
    return by

def send_alert(event_key: str, **kwargs):
    data = _load_recipients()
    paired = [r for r in data["recipients"] if r.get("paired") and r.get("chat_id")]
    if not paired:
        print("❌ Keine gekoppelten Empfänger – Nachricht nicht gesendet.")
        return
    for r in paired:
        lang = (r.get("lang") or "de")
        loc_kwargs = dict(kwargs)
        if "res" in loc_kwargs:
            loc_kwargs["res"] = res_name(loc_kwargs["res"], lang)
        msg = tr(lang, event_key, **loc_kwargs)
        try:
            _tg_api("sendMessage", {"chat_id": r["chat_id"], "text": msg})
            time.sleep(0.2)
            print(f"📤 Telegram ({lang}) an {r.get('label','Empfänger')} gesendet.")
        except Exception as e:
            print(f"⚠️ Telegram-Fehler: {e}")

def iter_paired_recipients():
    data = _load_recipients()
    for r in data.get("recipients", []):
        if r.get("paired") and r.get("chat_id"):
            yield r

def broadcast_localized(msg_by_lang: dict[str, str]):
    fallback = msg_by_lang.get("de") or next(iter(msg_by_lang.values()), "")
    sent = 0
    for r in iter_paired_recipients():
        lang = normalize_lang(r.get("lang") or "de")
        text = msg_by_lang.get(lang, fallback)
        try:
            _tg_api("sendMessage", {"chat_id": r["chat_id"], "text": text})
            time.sleep(0.2)
            sent += 1
        except Exception as e:
            print(f"⚠️ Broadcast an {r.get('label') or r.get('username')}: {e}")
    return sent

def _normalize_username(u: str | None):
    if not u:
        return None
    u = u.strip()
    if not u:
        return None
    if u.startswith("@"):
        u = u[1:]
    return "@" + u.lower()

def _find_lang_for_chat(chat_id: int) -> str:
    data = _load_recipients()
    for r in data.get("recipients", []):
        if r.get("chat_id") == chat_id:
            return (r.get("lang") or "de")
    return "de"

def _send_welcome(chat_id: int):
    lang = _find_lang_for_chat(chat_id)
    title = tr(lang, "welcome_title")
    body  = tr(lang, "welcome_body", admin=cfg.get("admin_contact") or "")
    try:
        _tg_api("sendMessage", {"chat_id": chat_id, "text": f"{title}\n{body}"})
    except Exception as e:
        print(f"[TG] Welcome-Message fehlgeschlagen ({chat_id}): {e}")

def _try_pair_from_message(msg) -> bool:
    chat = msg.get("chat") or {}
    user = msg.get("from") or {}
    chat_id = chat.get("id")
    uname = _normalize_username(user.get("username"))
    if not chat_id or not uname:
        return False

    d = _load_recipients()
    for r in d["recipients"]:
        if not r.get("paired") and _normalize_username(r.get("username")) == uname:
            r["chat_id"] = chat_id
            r["paired"] = True
            if not r.get("label"):
                r["label"] = user.get("first_name") or uname
            _save_recipients(d)
            _send_welcome(chat_id)
            print(f"✅ Auto-gekoppelt: {uname} (chat_id={chat_id})")
            return True
    return False

def _get_last_update_id():
    try:
        resp = _tg_api("getUpdates", {"timeout": 0})
        if resp.get("ok") and resp["result"]:
            return resp["result"][-1]["update_id"]
    except Exception:
        pass
    return None

# beim Start sicherstellen: kein Webhook & alte Updates verwerfen
try:
    _tg_api("deleteWebhook", {"drop_pending_updates": True})
except Exception as e:
    print(f"[TG] deleteWebhook warn: {e}")
try:
    _send_admin("online ✓")
    _report_recipients_summary()
except Exception as e:
    print(f"[TG] startup admin ping fail: {e}")


def auto_reply_worker(is_running=lambda: True):
    """
    Einziger getUpdates-Loop:
    - Paart Empfänger automatisch (per @username).
    - Auto-Reply an Nicht-Empfänger.
    - NEU: Reagiert auf Posts im Admin-Channel:
        /ping
        /id
        /broadcast <Text>  (optional mit [EN]..[/EN] und [DE]..[/DE] oder [ALL]..)
    """
    last_id = _get_last_update_id()
    admin_id = int(cfg.get("admin_channel_id") or 0)

    while is_running():
        try:
            payload = {"timeout": 25}
            if last_id is not None:
                payload["offset"] = last_id + 1

            resp = _tg_api("getUpdates", payload)
            if not resp.get("ok"):
                time.sleep(0.6)
                continue

            for upd in resp.get("result", []):
                last_id = upd.get("update_id", last_id)

                # --- NEU: Admin-Channel Posts ---
                ch = upd.get("channel_post")
                if ch and admin_id and (ch.get("chat", {}).get("id") == admin_id):
                    text = (ch.get("text") or "").strip()
                    if not text:
                        continue

                    if text.lower().startswith("/ping"):
                        _send_admin("online ✓")
                        continue

                    if text.lower().startswith("/logs"):
                        from .log import LOG_DIR
                        files = [os.path.join(LOG_DIR, f) for f in os.listdir(LOG_DIR) if f.lower().endswith(".json")]
                        if not files:
                            _send_admin("logs: no files")
                            continue
                        files.sort(reverse=True)
                        for p in files[:4]:  # nicht spammen; 4 neueste reichen meist
                            try:
                                _send_admin_doc(p, caption=f"logs: {os.path.basename(p)}")
                                time.sleep(0.4)
                            except Exception as e:
                                print(f"[TG] send log fail: {e}")
                        continue

                    if text.lower().startswith("/id"):
                        _send_admin(f"admin_channel_id = {admin_id}")
                        continue

                    if text.lower().startswith("/broadcast"):
                        # Syntax:
                        #   /broadcast all [TEXT ODER [EN]..[/EN] [DE]..[/DE] [ALL]..]
                        #   /broadcast group=<NAME> [TEXT...]
                        #   /broadcast <NAME> [TEXT...]   (Kurzform)
                        body = text.partition(" ")[2].strip()
                        target = "all"
                        m = re.match(r"(?i)group\s*=\s*([^\s]+)\s+(.*)", body)
                        if m:
                            target = m.group(1).strip()
                            body   = m.group(2).strip()
                        else:
                            m2 = re.match(r"(?i)(all|[^\s]+)\s+(.*)", body)
                            if m2:
                                target = m2.group(1).strip()
                                body   = m2.group(2).strip()

                        # Sprachblöcke parsen
                        msgs = _parse_lang_blocks(body)
                        if not msgs:
                            _send_admin("broadcast: nothing to send")
                            continue

                        # Nur ausführen, wenn Zielgruppe zu DIESER Instanz passt
                        my_group = str(cfg.get("instance_name") or "").strip()
                        is_for_me = (target.lower() == "all") or (target == my_group)

                        if is_for_me:
                            sent = broadcast_localized(msgs)
                            log_event("broadcast", f"broadcast → {sent} recipients",
                                    extra={"text": msgs, "group": my_group, "target": target, "count": sent})
                            _send_admin(f"broadcast ok ({my_group}): {sent}")
                        else:
                            # ignorieren (war für andere Gruppe)
                            pass
                        continue


                    # Unbekannter Befehl – ignoriere
                    continue

                # --- Normale 1:1 Nachrichten ---
                msg = upd.get("message") or {}
                if not msg:
                    continue

                chat = msg.get("chat") or {}
                chat_id = chat.get("id")
                if not chat_id:
                    continue

                # 1) versuchen zu koppeln
                paired_now = _try_pair_from_message(msg)

                # 2) sonst Auto-Reply in der jeweiligen Sprache
                if not paired_now:
                    lang = _find_lang_for_chat(chat_id)
                    title = tr(lang, "auto_reply_title")
                    body  = tr(lang, "auto_reply_body", admin=cfg.get("admin_contact") or "")
                    try:
                        _tg_api("sendMessage", {"chat_id": chat_id, "text": f"{title}\n{body}"})
                    except Exception as e:
                        print(f"[TG] Auto-Reply fehlgeschlagen ({chat_id}): {e}")

        except Exception as e:
            print(f"[TG] Auto-Reply-Worker-Fehler: {e}")
            time.sleep(1.2)