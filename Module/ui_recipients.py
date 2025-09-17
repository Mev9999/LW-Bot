# Module/ui_recipients.py
import time
import tkinter as tk
import tkinter.ttk as ttk
import os, sys 
from tkinter import messagebox, simpledialog

from .telebot import _load_recipients, _save_recipients, _tg_api
from .log import log_event
from .i18n import normalize_lang, tr
from PIL import Image, ImageTk
from .config import cfg, save_cfg, apply_ttk_theme, BG_WIN, BG_CARD, FG, ACCENT, ACCENT_D, resource_path
try:
    from .config import restart_app  # existiert evtl. nicht
except Exception:
    restart_app = None

def _refresh_tree(tree, data):
    tree.delete(*tree.get_children())
    for i, r in enumerate(data["recipients"]):
        lang = (r.get("lang") or "de")
        paired = "✅" if r.get("paired") and r.get("chat_id") else "—"
        tree.insert("", "end", iid=str(i), values=(
            r.get("label") or "",
            r.get("username") or "",
            lang,
            paired
        ))

def open_recipients_ui_blocking_start() -> bool:
    """
    Öffnet die Empfänger-UI modernisiert. Solange offen, pausiert Hauptlogik.
    Rückgabe True = Nutzer hat 'Start monitoring' geklickt.
    """
    data = _load_recipients()

    root = tk.Tk()
    root.title(tr(cfg["language"], "ui_recipients_title"))
    root.geometry("820x520")
    root.minsize(780, 480)
    try:
        from .config import apply_ttk_theme, BG_WIN, BG_CARD, FG, ACCENT
    except Exception:
        # falls import im Modul nicht vorhanden ist
        pass
    # Fallback: lokale simple Styles
    try:
        apply_ttk_theme(root)
        root.configure(bg=BG_WIN)
    except Exception:
        pass

    # Header mit Titel + Sprach-Dropdown
    header = tk.Frame(root, bg=ACCENT)
    header.pack(fill="x")
    tk.Label(header, text=tr(cfg["language"], "ui_recipients_title"),
            bg=ACCENT, fg="white", font=("Segoe UI", 14, "bold")).pack(side="left", padx=12, pady=10)
        # --- Sprachwahl (Flagge + Dropdown mit Flaggen) ---
        # --- Sprachwahl (Flagge + Dropdown mit Flaggen) ---
    def _load_flag(rel):
        try:
            img = Image.open(resource_path(rel)).resize((20, 14), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception as e:
            print("[UI] Flaggenladefehler:", rel, e)
            return None

    # load all 5 flags
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
        try:
            if callable(restart_app):
                restart_app()
                return
        except Exception:
            pass
        os.execv(sys.executable, [sys.executable] + sys.argv)

    lang_btn = tk.Menubutton(
        header,
        text=cur_text,
        image=cur_img, compound=("left" if cur_img else None),
        bg=ACCENT, fg="white",
        activebackground=ACCENT_D, activeforeground="white",
        relief="flat", font=("Segoe UI", 10, "bold")
    )
    # keep refs so GC doesn't drop them
    lang_btn._flags = FLAGS

    m = tk.Menu(lang_btn, tearoff=False)
    for code in ("en","de","ru","ja","ar"):
        m.add_radiobutton(
            label=f" {code.upper()}",
            image=FLAGS.get(code),
            compound="left",
            command=lambda c=code: on_lang_change(c)
        )
    lang_btn.configure(menu=m)
    lang_btn.pack(side="right", padx=10, pady=6)




    # Card-Container
    card = ttk.Frame(root, style="Card.TFrame")
    card.pack(fill="both", expand=True, padx=12, pady=12)

    # Tabelle
    cols = ("label","username","lang","paired")
    tree = ttk.Treeview(card, columns=cols, show="headings", height=14)
    headers = (
        tr(cfg["language"], "ui_cols_label"),
        tr(cfg["language"], "ui_cols_username"),
        tr(cfg["language"], "ui_cols_lang"),
        tr(cfg["language"], "ui_cols_paired"),
    )
    widths = (260, 260, 80, 80)
    for c, head, w in zip(cols, headers, widths):
        tree.heading(c, text=head)
        tree.column(c, width=w, anchor="w")
    tree.grid(row=0, column=0, sticky="nsew", padx=(10,0), pady=(10,8))

    yscroll = ttk.Scrollbar(card, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=yscroll.set)
    yscroll.grid(row=0, column=1, sticky="ns", pady=(10,8), padx=(0,10))

    card.rowconfigure(0, weight=1)
    card.columnconfigure(0, weight=1)

    _refresh_tree(tree, data)

    # Button-Bar (Add/Edit/Delete/Test)
    btnbar = ttk.Frame(card, style="Card.TFrame")
    btnbar.grid(row=1, column=0, columnspan=2, sticky="we", padx=10, pady=(0,10))

    def add_recipient():
        username = simpledialog.askstring(tr(cfg["language"], "ui_add_prompt_title"),
                                          tr(cfg["language"], "ui_add_prompt_body"),
                                          parent=root)
        if not username:
            return
        username = username.strip().lstrip("@")
        entry = {
            "username": username,
            "label": username,
            "lang": normalize_lang(cfg.get("language", "de")),
            "paired": False,
            "chat_id": None
        }

        data["recipients"].append(entry)
        _save_recipients(data)
        _refresh_tree(tree, data)

    def edit_selected():
        sel = tree.selection()
        if not sel:
            return
        i = int(sel[0])
        r = data["recipients"][i]

        top = tk.Toplevel(root)
        try:
            apply_ttk_theme(top); top.configure(bg=BG_WIN)
        except Exception:
            pass
        top.title(tr(cfg["language"], "ui_edit_title"))
        top.resizable(False, False)

        ttk.Label(top, text=tr(cfg["language"], "ui_cols_label")).grid(row=0, column=0, sticky="e", padx=6, pady=6)
        ttk.Label(top, text=tr(cfg["language"], "ui_cols_username")).grid(row=1, column=0, sticky="e", padx=6, pady=6)
        ttk.Label(top, text=tr(cfg["language"], "ui_cols_lang")).grid(row=2, column=0, sticky="e", padx=6, pady=6)
        ttk.Label(top, text=tr(cfg["language"], "ui_chat_id")).grid(row=3, column=0, sticky="e", padx=6, pady=6)

        e_label = ttk.Entry(top, width=36); e_label.insert(0, r.get("label","")); e_label.grid(row=0, column=1, padx=6, pady=6)
        e_user  = ttk.Entry(top, width=36); e_user.insert(0, r.get("username","")); e_user.grid(row=1, column=1, padx=6, pady=6)

        lang_var = tk.StringVar(value=r.get("lang","de"))
        lang_combo = ttk.Combobox(top, textvariable=lang_var, width=12, values=["de", "en", "ru", "ja", "ar"], state="readonly")

        lang_combo.grid(row=2, column=1, padx=6, pady=6, sticky="w")

        e_chat  = ttk.Entry(top, width=36)
        if r.get("chat_id"): e_chat.insert(0, str(r["chat_id"]))
        e_chat.grid(row=3, column=1, padx=6, pady=6)

        def save():
            r["label"] = e_label.get().strip() or r.get("label")
            r["username"] = e_user.get().strip().lstrip("@")
            r["lang"] = normalize_lang(lang_var.get())
            chat_raw = e_chat.get().strip()
            if chat_raw:
                try:
                    r["chat_id"] = int(chat_raw)
                    r["paired"] = True
                except Exception:
                    messagebox.showerror(tr(cfg["language"], "ui_error"),
                                         tr(cfg["language"], "ui_chat_id_must_number"))
                    return
            _save_recipients(data)
            _refresh_tree(tree, data)
            top.destroy()

        ttk.Button(top, text=tr(cfg["language"], "ui_save"), style="Accent.TButton", command=save)\
            .grid(row=4, column=0, columnspan=2, pady=10)

        top.grab_set(); top.wait_window()

    def delete_selected():
        sel = tree.selection()
        if not sel: return
        i = int(sel[0])
        r = data["recipients"][i]
        if messagebox.askyesno(tr(cfg["language"], "ui_delete_recipient"),
                               f"{r.get('label') or r.get('username')}?"):
            data["recipients"].pop(i)
            _save_recipients(data)
            _refresh_tree(tree, data)

    def test_message():
        sel = tree.selection()
        if not sel: return
        i = int(sel[0]); r = data["recipients"][i]
        if not (r.get("paired") and r.get("chat_id")):
            messagebox.showwarning(tr(cfg["language"], "ui_not_paired"),
                                   tr(cfg["language"], "ui_not_paired_body"))
            return
        try:
            _tg_api("sendMessage", {"chat_id": r["chat_id"], "text": "Test ✅"})
            messagebox.showinfo("OK", tr(cfg["language"], "ui_test_sent"))
        except Exception as e:
            messagebox.showerror(tr(cfg["language"], "ui_error"), str(e))

    ttk.Button(btnbar, text=tr(cfg["language"], "ui_add_recipient"), command=add_recipient).pack(side="left", padx=6)
    ttk.Button(btnbar, text=tr(cfg["language"], "ui_edit_recipient"), command=edit_selected).pack(side="left", padx=6)
    ttk.Button(btnbar, text=tr(cfg["language"], "ui_delete_recipient"), command=delete_selected).pack(side="left", padx=6)
    ttk.Button(btnbar, text=tr(cfg["language"], "ui_test_message"), command=test_message).pack(side="left", padx=6)

    # Start/Close
    ctl = ttk.Frame(root, style="Card.TFrame"); ctl.pack(fill="x", padx=12, pady=(0,12))
    started = {"val": False}
    def do_start():
        started["val"] = True
        root.destroy()
    ttk.Button(ctl, text="▶  " + tr(cfg["language"], "tray_resume"), style="Accent.TButton", command=do_start)\
        .pack(side="left", padx=(0,6))
    ttk.Button(ctl, text=tr(cfg["language"], "ui_close"), command=root.destroy).pack(side="right")

    root.mainloop()
    return started["val"]


# kompatible Wrapper (falls irgendwo noch die alte Funktion aufgerufen wird)
def open_recipients_ui():
    open_recipients_ui_blocking_start()

def open_broadcast_dialog():
    data = _load_recipients()
    paired = [r for r in data["recipients"] if r.get("paired") and r.get("chat_id")]

    root = tk.Tk()
    root.title(tr(cfg["language"], "ui_broadcast_title"))
    root.geometry("640x420")

    tk.Label(root, text=tr(cfg["language"], "ui_broadcast_pairs", n=len(paired))).pack(anchor="w", padx=10, pady=(10,0))
    txt = tk.Text(root, wrap="word", height=12)
    txt.pack(fill="both", expand=True, padx=10, pady=10)

    def send_now():
        text = txt.get("1.0","end").strip()
        if not text:
            messagebox.showwarning(tr(cfg["language"], "ui_empty_warn"),
                                   tr(cfg["language"], "ui_empty_warn_body"))
            return
        ok = 0
        for r in paired:
            try:
                _tg_api("sendMessage", {"chat_id": r["chat_id"], "text": text})
                time.sleep(0.2); ok += 1
            except Exception as e:
                print(f"Broadcast to {r.get('label')}: {e}")
        log_event("broadcast", text, extra={"count": ok})
        messagebox.showinfo(tr(cfg["language"], "ui_sent"),
                            tr(cfg["language"], "ui_sent_body", n=ok))
        root.destroy()

    btns = tk.Frame(root); btns.pack(pady=4)
    ttk.Button(btns, text=tr(cfg["language"], "ui_send"), command=send_now).pack(side="left", padx=6)
    ttk.Button(btns, text=tr(cfg["language"], "ui_cancel"), command=root.destroy).pack(side="left", padx=6)

    root.mainloop()
