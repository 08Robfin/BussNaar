#!/usr/bin/env python3
# BussNaar — Norsk bussavgang-tracker

import sys, subprocess, json, threading, time, webbrowser
from pathlib import Path
from datetime import datetime
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

if sys.platform == "win32":
    import ctypes
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except: pass

# ── Bootstrap ─────────────────────────────────────────────────────────────────
def ensure_packages():
    import tkinter as tk
    root = tk.Tk()
    root.overrideredirect(True)
    root.configure(bg="#ffffff")
    root.geometry("340x160")
    root.eval('tk::PlaceWindow . center')
    root.attributes('-alpha', 0)
    tk.Label(root, text="BussNaar", font=("Segoe UI", 28, "bold"),
             fg="#00c47a", bg="#ffffff").pack(pady=(36, 6))
    status = tk.Label(root, text="Laster...", font=("Segoe UI", 11),
                      fg="#bbbbbb", bg="#ffffff")
    status.pack()
    def fade(a=0.0):
        if a < 1.0:
            root.attributes('-alpha', a); root.after(16, lambda: fade(a+0.07))
        else: root.attributes('-alpha', 1.0)
    fade(); root.update()
    reqs = [('requests','requests'),('customtkinter','customtkinter'),
            ('pystray','pystray'),('PIL','Pillow')]
    missing = [pip for imp,pip in reqs
               if subprocess.call([sys.executable,'-c',f'import {imp}'],
                                  stderr=subprocess.DEVNULL) != 0]
    if missing:
        status.config(text="Installerer avhengigheter..."); root.update()
        subprocess.run([sys.executable,'-m','pip','install','-q']+missing, check=True)
    root.destroy()

if not getattr(sys, 'frozen', False):
    ensure_packages()

import requests
import customtkinter as ctk
from pystray import Icon, Menu, MenuItem
from PIL import Image, ImageDraw, ImageFont

# ── Design tokens ─────────────────────────────────────────────────────────────
ACCENT        = "#00c47a"
ACCENT_HOVER  = "#00a866"
ACCENT_LIGHT  = "#edf9f4"
ACCENT_BORDER = "#b3ead1"
BG            = "#f7f8fa"
SURFACE       = "#ffffff"
CARD          = "#ffffff"
BORDER        = "#ebebeb"
TEXT          = "#111111"
TEXT2         = "#9a9a9a"
TEXT3         = "#c4c4c4"
RED           = "#e53935"
FONT          = "Segoe UI"
RADIUS        = 12

ctk.set_appearance_mode("light")

# ── OS helpers ─────────────────────────────────────────────────────────────────
def apply_rounded_corners(win):
    """Ask Windows 11 DWM to round this window's corners."""
    if sys.platform != "win32": return
    try:
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        if not hwnd: hwnd = win.winfo_id()
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        val = ctypes.c_int(2)          # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(val), ctypes.sizeof(val))
    except: pass

# ── Animation helpers ──────────────────────────────────────────────────────────
def fade_in(win, steps=20, delay=10):
    win.attributes('-alpha', 0.0)
    def _tick(a):
        if a >= 1.0: win.attributes('-alpha', 1.0); return
        win.attributes('-alpha', round(a, 2))
        win.after(delay, lambda: _tick(a + 1.0/steps))
    win.after(10, lambda: _tick(0.0))


def animate_dots(label, base, stop_flag):
    frames = [base+"   ", base+".  ", base+".. ", base+"..."]
    idx = [0]
    def _tick():
        if stop_flag[0]: return
        label.configure(text=frames[idx[0] % 4]); idx[0] += 1
        label.after(380, _tick)
    _tick()


def interpolate_color(s, e, t):
    def h2r(h): return tuple(int(h.lstrip('#')[i:i+2],16) for i in (0,2,4))
    sr,er = h2r(s),h2r(e)
    r = tuple(int(sr[i]+(er[i]-sr[i])*t) for i in range(3))
    return f"#{r[0]:02x}{r[1]:02x}{r[2]:02x}"


def hover_animate(widget, from_col, to_col, key="fg_color", steps=8, delay=14):
    state = [0, None]
    def _run():
        if state[1]: widget.after_cancel(state[1])
        t = max(0.0, min(1.0, state[0]/steps))
        widget.configure(**{key: interpolate_color(from_col, to_col, t)})
        if 0 < state[0] < steps:
            state[0] += 1; state[1] = widget.after(delay, _run)
        elif state[0] <= 0:
            widget.configure(**{key: from_col})
    def on_enter(_): state[0] = max(state[0],1); _run()
    def on_leave(_):
        def _rev():
            if state[1]: widget.after_cancel(state[1])
            widget.configure(**{key: interpolate_color(from_col, to_col, state[0]/steps)})
            if state[0] > 0: state[0] -= 1; state[1] = widget.after(delay, _rev)
            else: widget.configure(**{key: from_col})
        _rev()
    widget.bind("<Enter>", on_enter)
    widget.bind("<Leave>", on_leave)

# ── Shared UI helpers ──────────────────────────────────────────────────────────
def _center(win, w, h):
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")


def _drag_bind(widget, win):
    def start(e): win._dx, win._dy = e.x, e.y
    def move(e): win.geometry(
        f"+{win.winfo_x()+(e.x-win._dx)}+{win.winfo_y()+(e.y-win._dy)}")
    widget.bind("<Button-1>", start)
    widget.bind("<B1-Motion>", move)


def _title_bar(win, text, on_close):
    bar = ctk.CTkFrame(win, height=50, fg_color=SURFACE, corner_radius=0)
    bar.pack(fill="x"); bar.pack_propagate(False)
    ctk.CTkFrame(win, height=1, fg_color=BORDER, corner_radius=0).pack(fill="x")

    left = ctk.CTkFrame(bar, fg_color="transparent")
    left.pack(side="left", fill="y", padx=18)
    dot = ctk.CTkLabel(left, text="●", font=(FONT,9), text_color=ACCENT, fg_color="transparent")
    dot.pack(side="left", padx=(0,7))
    lbl = ctk.CTkLabel(left, text=text, font=(FONT,13,"bold"), text_color=TEXT, fg_color="transparent")
    lbl.pack(side="left")

    ctk.CTkButton(bar, text="✕", width=50, height=50, fg_color="transparent",
                  hover_color="#ffeaea", text_color=TEXT2, font=(FONT,13),
                  corner_radius=0, command=on_close).pack(side="right")
    for w in [bar, dot, lbl, left]: _drag_bind(w, win)


# ── API ────────────────────────────────────────────────────────────────────────
class EnturAPI:
    HEADERS = {"ET-Client-Name":"student_vennesla-bussnaar_app","User-Agent":"Mozilla/5.0"}

    @staticmethod
    def search(query):
        try:
            r = requests.get("https://api.entur.io/geocoder/v1/autocomplete",
                             params={"text":query,"lang":"no"},
                             headers=EnturAPI.HEADERS, timeout=5, verify=False)
            r.raise_for_status(); results=[]
            for f in r.json().get('features',[]):
                props=f.get('properties',{}); fid=str(f.get('id',props.get('id','')))
                fname=props.get('name',props.get('label','Ukjent'))
                loc=props.get('locality',props.get('county',''))
                name=f"{fname}, {loc}" if loc else fname
                if 'NSR:StopPlace' in fid and not any(x['id']==fid for x in results):
                    results.append({'id':fid,'name':name})
            return results
        except Exception as e: return [{'id':'ERROR','name':f"Feil: {e}"}]

    @staticmethod
    def get_lines_for_stop(stop_id):
        try:
            q=(f'{{stopPlace(id:"{stop_id}"){{estimatedCalls(timeRange:86400,numberOfDepartures:100)'
               f'{{destinationDisplay{{frontText}}serviceJourney{{journeyPattern{{line{{publicCode}}}}}}}}}}}}')
            r=requests.post("https://api.entur.io/journey-planner/v3/graphql",
                            json={"query":q},headers=EnturAPI.HEADERS,timeout=5,verify=False)
            unique={}
            for d in r.json().get('data',{}).get('stopPlace',{}).get('estimatedCalls',[]):
                line=d.get('serviceJourney',{}).get('journeyPattern',{}).get('line',{}).get('publicCode','?')
                dest=d.get('destinationDisplay',{}).get('frontText','?'); k=f"{line}_{dest}"
                if k not in unique: unique[k]={"line":line,"dest":dest}
            return sorted(unique.values(),key=lambda x:(x['line'],x['dest']))
        except: return []

    @staticmethod
    def get_next_bus(stop_id, line_code, target_dest):
        try:
            q=(f'{{stopPlace(id:"{stop_id}"){{estimatedCalls(timeRange:86400,numberOfDepartures:150)'
               f'{{expectedDepartureTime realtime destinationDisplay{{frontText}}'
               f'serviceJourney{{journeyPattern{{line{{publicCode}}}}}}}}}}}}')
            r=requests.post("https://api.entur.io/journey-planner/v3/graphql",
                            json={"query":q},headers=EnturAPI.HEADERS,timeout=5,verify=False)
            deps=[]
            for call in r.json().get('data',{}).get('stopPlace',{}).get('estimatedCalls',[]):
                dest=call.get('destinationDisplay',{}).get('frontText','?')
                l_code=call.get('serviceJourney',{}).get('journeyPattern',{}).get('line',{}).get('publicCode','?')
                if (dest.strip().lower()!=target_dest.strip().lower() or
                        l_code.strip().lower()!=line_code.strip().lower()): continue
                dt=datetime.fromisoformat(call.get('expectedDepartureTime','').replace('Z','+00:00'))
                clock=dt.astimezone().strftime('%H:%M')
                mins=(dt-datetime.now(dt.tzinfo)).total_seconds()/60
                if mins>=0:
                    deps.append({'line':l_code,'dest':dest,'mins':int(mins),'time':clock,
                                 'realtime':call.get('realtime',False)})
            return sorted(deps,key=lambda x:x['mins'])[:5]
        except: return []


# ── Departure Board ────────────────────────────────────────────────────────────
class DepartureBoard(ctk.CTkToplevel):
    W, H = 390, 570

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.configure(fg_color=BG)
        self.geometry(f"{self.W}x{self.H}")
        _center(self, self.W, self.H)
        fade_in(self)
        self.after(50, lambda: apply_rounded_corners(self))

        route = app.config.get('route',{}).get('name','Avganger')
        _title_bar(self, route, self.destroy)

        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=ACCENT_BORDER)
        self._scroll.pack(fill="both", expand=True, padx=16, pady=12)

        ctk.CTkFrame(self, height=1, fg_color=BORDER, corner_radius=0).pack(fill="x")

        # ── Settings row ──
        settings = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=44)
        settings.pack(fill="x")
        settings.pack_propagate(False)

        ctk.CTkLabel(settings, text="Start ved oppstart",
                     font=(FONT, 12), text_color=TEXT2,
                     fg_color="transparent").pack(side="left", padx=16)

        self._startup_switch = ctk.CTkSwitch(
            settings, text="", width=36, height=18,
            fg_color=BORDER, progress_color=ACCENT,
            button_color=SURFACE, button_hover_color=SURFACE,
            command=self._toggle_startup)
        self._startup_switch.pack(side="right", padx=16)
        if app.is_startup_enabled():
            self._startup_switch.select()

        ctk.CTkFrame(self, height=1, fg_color=BORDER, corner_radius=0).pack(fill="x")
        ctk.CTkButton(self, text="Se bussene live på kart  →",
                      font=(FONT,12), fg_color=SURFACE, hover_color=ACCENT_LIGHT,
                      text_color=TEXT2, height=44, corner_radius=0,
                      command=self._open_map).pack(fill="x")
        self._refresh()

    def _toggle_startup(self):
        self.app._toggle_startup(None, None)

    def _open_map(self):
        webbrowser.open(f"https://entur.no/kart/stoppested?id={self.app.config['route']['stop_id']}")

    def _refresh(self):
        for w in self._scroll.winfo_children(): w.destroy()
        deps = self.app.current_deps
        if deps is None:
            lbl = ctk.CTkLabel(self._scroll, text="Henter avganger",
                               font=(FONT,13), text_color=TEXT3, fg_color="transparent")
            lbl.pack(pady=60)
            flag = [False]
            animate_dots(lbl, "Henter avganger", flag)
            self.after(800, lambda: (flag.__setitem__(0,True), self._refresh()))
            return
        if not deps:
            ctk.CTkLabel(self._scroll, text="Ingen avganger funnet",
                         font=(FONT,13), text_color=RED, fg_color="transparent").pack(pady=60)
            return
        for i, d in enumerate(deps): self._card(d, i)

    def _card(self, d, index):
        is_live = d['realtime']
        color   = ACCENT if is_live else TEXT3
        bg_badge= ACCENT_LIGHT if is_live else "#f0f0f0"

        card = ctk.CTkFrame(self._scroll, fg_color=SURFACE, corner_radius=RADIUS,
                            border_width=1, border_color=BORDER)
        card.pack(fill="x", pady=5)
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(card, text=d['line'], font=(FONT,13,"bold"),
                     text_color=ACCENT if is_live else TEXT2,
                     fg_color=bg_badge, corner_radius=8,
                     width=44, height=44).grid(row=0,column=0,rowspan=2,padx=(14,10),pady=14)

        dest = d['dest'] if len(d['dest'])<=22 else d['dest'][:20]+"…"
        ctk.CTkLabel(card, text=dest, font=(FONT,14,"bold"),
                     text_color=TEXT, anchor="w", fg_color="transparent").grid(
            row=0,column=1,sticky="sw",pady=(14,1))

        tag = ("● Live" if is_live else "○ Rutetid")
        ctk.CTkLabel(card, text=tag, font=(FONT,11),
                     text_color=color, anchor="w", fg_color="transparent").grid(
            row=1,column=1,sticky="nw",pady=(0,14))

        right = ctk.CTkFrame(card, fg_color="transparent")
        right.grid(row=0,column=2,rowspan=2,padx=(0,16))
        ctk.CTkLabel(right, text=str(d['mins']), font=(FONT,30,"bold"),
                     text_color=ACCENT if is_live else TEXT,
                     fg_color="transparent").pack(anchor="e")
        ctk.CTkLabel(right, text=f"min · {d['time']}", font=(FONT,10),
                     text_color=TEXT2, fg_color="transparent").pack(anchor="e")

        hover_animate(card, SURFACE, ACCENT_LIGHT, "fg_color")


# ── Setup Wizard ───────────────────────────────────────────────────────────────
class SetupWizard(ctk.CTkToplevel):
    W, H    = 440, 580
    _PAD_X  = 30
    _PAD_Y  = 24
    _BAR_H  = 51   # title bar (50) + separator (1)

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.configure(fg_color=SURFACE)
        self.geometry(f"{self.W}x{self.H}")
        _center(self, self.W, self.H)
        fade_in(self)
        self.after(50, lambda: apply_rounded_corners(self))

        self._cfg, self._all_lines, self._timer = {}, [], None

        _title_bar(self, "BussNaar — Oppsett", self._close)
        self._body = ctk.CTkFrame(self, fg_color="transparent")
        self._body.pack(fill="both", expand=True,
                        padx=self._PAD_X, pady=self._PAD_Y)
        self._step1()

    def _close(self):
        self.destroy()
        if not self.app.is_config_valid(): self.app.quit()

    def _clear(self):
        for w in self._body.winfo_children(): w.destroy()

    def _transition(self, next_fn):
        next_fn()

    # ── Shared widget builders ────────────────────────────────────────────────
    def _heading(self, title, sub=None):
        ctk.CTkLabel(self._body, text=title, font=(FONT,22,"bold"),
                     text_color=TEXT, anchor="w", fg_color="transparent").pack(
            anchor="w", pady=(4,2))
        if sub:
            ctk.CTkLabel(self._body, text=sub, font=(FONT,13),
                         text_color=ACCENT, anchor="w", fg_color="transparent").pack(
                anchor="w", pady=(0,16))

    def _primary_btn(self, text, cmd):
        return ctk.CTkButton(self._body, text=text, font=(FONT,14,"bold"),
                             fg_color=ACCENT, hover_color=ACCENT_HOVER,
                             text_color="#ffffff", height=50, corner_radius=RADIUS,
                             command=cmd)

    def _mk_entry(self, placeholder):
        return ctk.CTkEntry(self._body, placeholder_text=placeholder,
                            font=(FONT,14), height=48, corner_radius=10,
                            fg_color=BG, border_color=BORDER, border_width=1,
                            text_color=TEXT, placeholder_text_color=TEXT3)

    # ── Steps ─────────────────────────────────────────────────────────────────
    def _step1(self):
        self._clear()
        ctk.CTkLabel(self._body, text="", fg_color="transparent").pack(expand=True)
        ctk.CTkLabel(self._body, text="BussNaar", font=(FONT,40,"bold"),
                     text_color=ACCENT, fg_color="transparent").pack()
        ctk.CTkLabel(self._body, text="Din personlige bussavgang-tracker.",
                     font=(FONT,14), text_color=TEXT2, fg_color="transparent").pack(pady=(6,0))
        ctk.CTkLabel(self._body, text="", fg_color="transparent").pack(expand=True)
        self._primary_btn("Kom i gang  →", lambda: self._transition(self._step2)).pack(
            fill="x", pady=(0,4))

    def _step2(self):
        self._clear()
        self._heading("Hvor drar du fra?", "Skriv inn navn på holdeplass")
        self._stop_entry = self._mk_entry("F.eks. Rådhuset...")
        self._stop_entry.pack(fill="x", pady=(0,10))
        self._stop_entry.bind("<KeyRelease>", self._debounce)
        self._stop_entry.focus()
        self._results = ctk.CTkScrollableFrame(self._body, fg_color="transparent",
                                               scrollbar_button_color=BORDER,
                                               scrollbar_button_hover_color=ACCENT_BORDER)
        self._results.pack(fill="both", expand=True)

    def _debounce(self, _=None):
        if self._timer: self.after_cancel(self._timer)
        self._timer = self.after(300, self._do_search)

    def _do_search(self):
        q = self._stop_entry.get().strip()
        for w in self._results.winfo_children(): w.destroy()
        if len(q) < 2: return
        flag = [False]
        lbl = ctk.CTkLabel(self._results, text="Søker", font=(FONT,13),
                           text_color=TEXT3, fg_color="transparent")
        lbl.pack(pady=20)
        animate_dots(lbl, "Søker", flag)
        def fetch():
            res = EnturAPI.search(q); flag[0] = True
            self.after(0, lambda: self._show_stops(res))
        threading.Thread(target=fetch, daemon=True).start()

    def _show_stops(self, results):
        for w in self._results.winfo_children(): w.destroy()
        if not results:
            ctk.CTkLabel(self._results, text="Ingen treff.", font=(FONT,13),
                         text_color=RED, fg_color="transparent").pack(pady=20); return
        if results[0]['id']=='ERROR':
            ctk.CTkLabel(self._results, text=results[0]['name'], font=(FONT,12),
                         text_color=RED, wraplength=360, fg_color="transparent").pack(pady=20); return
        for s in results[:10]:
            ctk.CTkButton(self._results, text=s['name'],
                          fg_color=BG, hover_color=ACCENT_LIGHT,
                          text_color=TEXT, height=44, corner_radius=10,
                          anchor="w", font=(FONT,13), border_width=1, border_color=BORDER,
                          command=lambda stop=s: self._transition(lambda: self._step3(stop))
                          ).pack(fill="x", pady=3)

    def _step3(self, stop):
        self._cfg['stop_id'], self._cfg['stop_name'] = stop['id'], stop['name']
        self._clear()
        self._heading("Henter ruter", stop['name'])
        flag = [False]
        lbl = ctk.CTkLabel(self._body, text="Henter ruter", font=(FONT,13),
                           text_color=TEXT3, fg_color="transparent")
        lbl.pack(pady=60)
        animate_dots(lbl, "Henter ruter", flag)
        def fetch():
            lines = EnturAPI.get_lines_for_stop(stop['id']); flag[0] = True
            self.after(0, lambda: self._show_lines(lines))
        threading.Thread(target=fetch, daemon=True).start()

    def _show_lines(self, lines):
        self._clear(); self._all_lines = lines
        self._heading("Hvilken buss?", self._cfg['stop_name'])
        self._line_search = self._mk_entry("Filtrer linjer...")
        self._line_search.pack(fill="x", pady=(0,10))
        self._line_search.bind("<KeyRelease>", self._filter_lines)
        self._lines_frame = ctk.CTkScrollableFrame(self._body, fg_color="transparent",
                                                   scrollbar_button_color=BORDER,
                                                   scrollbar_button_hover_color=ACCENT_BORDER)
        self._lines_frame.pack(fill="both", expand=True)
        self._filter_lines()

    def _filter_lines(self, _=None):
        q = self._line_search.get().strip().lower()
        for w in self._lines_frame.winfo_children(): w.destroy()
        filtered = [l for l in self._all_lines
                    if q in l['line'].lower() or q in l['dest'].lower()]
        if not filtered:
            ctk.CTkLabel(self._lines_frame, text="Ingen ruter funnet.", font=(FONT,13),
                         text_color=RED, fg_color="transparent").pack(pady=20); return
        for l in filtered:
            row = ctk.CTkFrame(self._lines_frame, fg_color=BG, corner_radius=10,
                               border_width=1, border_color=BORDER)
            row.pack(fill="x", pady=3)
            badge = ctk.CTkLabel(row, text=l['line'], font=(FONT,12,"bold"),
                                 text_color=ACCENT, fg_color=ACCENT_LIGHT,
                                 corner_radius=7, width=36, height=36)
            badge.pack(side="left", padx=10, pady=9)
            dest_lbl = ctk.CTkLabel(row, text=l['dest'], font=(FONT,13),
                                    text_color=TEXT, fg_color="transparent", anchor="w")
            dest_lbl.pack(side="left", padx=4, fill="x", expand=True)
            def _click(x=l): self._transition(lambda: self._step4(x))
            for widget in [row, badge, dest_lbl]:
                widget.bind("<Button-1>", lambda e, fn=_click: fn())
            hover_animate(row, BG, ACCENT_LIGHT, "fg_color")

    def _step4(self, line_data):
        self._cfg['line'], self._cfg['dest'] = line_data['line'], line_data['dest']
        self._clear()
        self._heading("Gi ruten et navn", f"Buss {line_data['line']} → {line_data['dest']}")
        ctk.CTkLabel(self._body, text="Navn på ruten:", font=(FONT,12),
                     text_color=TEXT2, anchor="w", fg_color="transparent").pack(
            anchor="w", pady=(10,4))
        self._name_entry = self._mk_entry('F.eks. "Hjem fra skolen"')
        self._name_entry.pack(fill="x")
        self._name_entry.focus()
        self._name_entry.bind("<Return>", lambda _: self._finish())
        self._primary_btn("Lagre og start", self._finish).pack(
            fill="x", side="bottom", pady=(20,4))

    def _finish(self):
        name = self._name_entry.get().strip()
        if not name: return
        self.app.config['route'] = {"name":name,"stop_id":self._cfg['stop_id'],
                                    "line":self._cfg['line'],"dest":self._cfg['dest']}
        self.app.save_config(); self.app.trigger_refresh()
        self.app.open_board(); self.destroy()


# ── App Controller ─────────────────────────────────────────────────────────────
class AppController:
    def __init__(self):
        self.conf_path = Path.home() / "BussNaar" / "config.json"
        self.conf_path.parent.mkdir(exist_ok=True)
        try: self.config = json.load(open(self.conf_path)) if self.conf_path.exists() else {}
        except: self.config = {}
        self.current_deps = None
        self.running = True
        self.root = ctk.CTk(); self.root.withdraw()
        self.tray = None; self._setup_tray()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        if not self.is_config_valid(): self.root.after(400, self.open_wizard)
        else: self.trigger_refresh(); self.root.after(600, self.open_board)
        self.root.mainloop()

    def is_config_valid(self):
        return (isinstance(self.config,dict) and 'route' in self.config
                and 'dest' in self.config['route'])

    def open_wizard(self): SetupWizard(self.root, self)
    def open_board(self):
        if self.is_config_valid(): DepartureBoard(self.root, self)

    def save_config(self):
        with open(self.conf_path,'w') as f: json.dump(self.config,f)

    # ── Startup helpers ───────────────────────────────────────────────────────
    _REG_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
    _REG_NAME = "BussNaar"

    def _startup_cmd(self):
        if getattr(sys, 'frozen', False):
            return f'"{sys.executable}"'
        return f'"{sys.executable}" "{Path(__file__).resolve()}"'

    def is_startup_enabled(self):
        if sys.platform != "win32": return False
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._REG_KEY, 0, winreg.KEY_READ)
            winreg.QueryValueEx(key, self._REG_NAME)
            winreg.CloseKey(key)
            return True
        except: return False

    def _toggle_startup(self, icon, item):
        if sys.platform != "win32": return
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._REG_KEY, 0, winreg.KEY_SET_VALUE)
        if self.is_startup_enabled():
            try: winreg.DeleteValue(key, self._REG_NAME)
            except: pass
        else:
            winreg.SetValueEx(key, self._REG_NAME, 0, winreg.REG_SZ, self._startup_cmd())
        winreg.CloseKey(key)

    def _setup_tray(self):
        menu = Menu(
            MenuItem("Vis avganger",       lambda i,it: self.root.after(0,self.open_board), default=True),
            MenuItem("Endre rute",         lambda i,it: self.root.after(0,self.open_wizard)),
            MenuItem("Start ved oppstart", self._toggle_startup,
                     checked=lambda item: self.is_startup_enabled()),
            MenuItem("Avslutt",            self.quit))
        self.tray = Icon("BussNaar", self._draw_icon("…"), menu=menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _draw_icon(self, text):
        SIZE, R = 64, 14
        img = Image.new('RGBA', (SIZE, SIZE), (0,0,0,0))
        d   = ImageDraw.Draw(img)
        # Rounded rectangle background
        d.rounded_rectangle([0,0,SIZE-1,SIZE-1], radius=R, fill="#00c47a")
        # Load font
        try:    font = ImageFont.truetype("segoeuib.ttf", 42)
        except: font = ImageFont.load_default()
        # Center text precisely
        bb = d.textbbox((0,0), text, font=font)
        tw, th = bb[2]-bb[0], bb[3]-bb[1]
        tx = (SIZE - tw) / 2 - bb[0]
        ty = (SIZE - th) / 2 - bb[1]
        d.text((tx, ty), text, fill="white", font=font)
        # Flatten to RGB for pystray
        bg = Image.new('RGB', (SIZE,SIZE), (240,240,240))
        bg.paste(img, mask=img.split()[3])
        return bg

    def trigger_refresh(self):
        self.current_deps = None
        threading.Thread(target=self._fetch, daemon=True).start()

    def _poll_loop(self):
        while self.running: time.sleep(30); self._fetch()

    def _fetch(self, *_):
        if not self.is_config_valid(): return
        r = self.config['route']
        self.current_deps = EnturAPI.get_next_bus(r['stop_id'],r['line'],r['dest'])
        if self.current_deps:
            nb = self.current_deps[0]
            self.tray.icon  = self._draw_icon(str(nb['mins']))
            self.tray.title = f"{r['name']} — {nb['line']} → {nb['dest']} om {nb['mins']} min"
        else:
            self.tray.icon  = self._draw_icon("-")
            self.tray.title = "Ingen avganger funnet."

    def quit(self, *_):
        self.running = False
        if self.tray: self.tray.stop()
        self.root.quit()


if __name__ == "__main__":
    AppController()
