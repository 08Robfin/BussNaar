#!/usr/bin/env python3
# RUN THIS FILE TO START BUSSNAAR?

import sys, os, subprocess, json, threading, time, webbrowser
from pathlib import Path
from datetime import datetime
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. PRO-APP DPI SCALING ---
if sys.platform == "win32":
    import ctypes
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except: pass

# --- 2. BOOTSTRAP ---
def ensure_packages():
    import tkinter as tk
    splash = tk.Tk()
    splash.title("BussNaar?")
    splash.geometry("450x250")
    splash.configure(bg="#00a070")
    splash.eval('tk::PlaceWindow . center')
    splash.overrideredirect(True)
    tk.Label(splash, text="BussNaar?", font=("Segoe UI", 36, "bold"), fg="white", bg="#00a070").pack(pady=30)
    status = tk.Label(splash, text="Laster...", font=("Segoe UI", 12), fg="white", bg="#00a070")
    status.pack()
    splash.update()

    reqs = [('requests', 'requests'), ('customtkinter', 'customtkinter'), ('pystray', 'pystray'), ('PIL', 'Pillow')]
    missing = [pip for imp, pip in reqs if subprocess.call([sys.executable, '-c', f'import {imp}'], stderr=subprocess.DEVNULL) != 0]
    
    if missing:
        status.config(text="Installerer... ✨")
        splash.update()
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-q'] + missing, check=True)
    splash.destroy()

ensure_packages()

import requests
import customtkinter as ctk
from pystray import Icon, Menu, MenuItem
from PIL import Image, ImageDraw, ImageFont

AKT_GREEN = "#00a070"
AKT_HOVER = "#007a55"
BG_COLOR = "#f9f9f9"
ctk.set_appearance_mode("light")

# --- 3. API CLIENT ---
class EnturAPI:
    HEADERS = {"ET-Client-Name": "student_vennesla-bussnaar_app", "User-Agent": "Mozilla/5.0"}

    @staticmethod
    def search(query):
        try:
            r = requests.get("https://api.entur.io/geocoder/v1/autocomplete", params={"text": query, "lang": "no"}, headers=EnturAPI.HEADERS, timeout=5, verify=False)
            r.raise_for_status()
            results = []
            for f in r.json().get('features', []):
                props = f.get('properties', {})
                fid = str(f.get('id', props.get('id', '')))
                fname = props.get('name', props.get('label', 'Ukjent'))
                locality = props.get('locality', props.get('county', ''))
                display_name = f"{fname}, {locality}" if locality else fname
                
                if 'NSR:StopPlace' in fid and not any(x['id'] == fid for x in results):
                    results.append({'id': fid, 'name': display_name})
            return results
        except Exception as e:
            return [{'id': 'ERROR', 'name': f"Internett/API Feil: {e}"}]

    @staticmethod
    def get_lines_for_stop(stop_id):
        try:
            q = f'{{stopPlace(id: "{stop_id}") {{estimatedCalls(timeRange: 86400, numberOfDepartures: 100) {{destinationDisplay {{frontText}} serviceJourney {{journeyPattern {{line {{publicCode}}}}}}}}}}}}'
            r = requests.post("https://api.entur.io/journey-planner/v3/graphql", json={"query": q}, headers=EnturAPI.HEADERS, timeout=5, verify=False)
            unique_lines = {}
            for d in r.json().get('data', {}).get('stopPlace', {}).get('estimatedCalls', []):
                line = d.get('serviceJourney', {}).get('journeyPattern', {}).get('line', {}).get('publicCode', 'Ukjent')
                dest = d.get('destinationDisplay', {}).get('frontText', 'Ukjent')
                key = f"{line}_{dest}"
                if key not in unique_lines:
                    unique_lines[key] = {"line": line, "dest": dest}
            return sorted(list(unique_lines.values()), key=lambda x: (x['line'], x['dest']))
        except Exception: return []

    @staticmethod
    def get_next_bus(stop_id, line_code, target_dest):
        try:
            q = f'{{stopPlace(id: "{stop_id}") {{estimatedCalls(timeRange: 86400, numberOfDepartures: 150) {{expectedDepartureTime realtime destinationDisplay {{frontText}} serviceJourney {{journeyPattern {{line {{publicCode}}}}}}}}}}}}'
            r = requests.post("https://api.entur.io/journey-planner/v3/graphql", json={"query": q}, headers=EnturAPI.HEADERS, timeout=5, verify=False)
            deps = []
            
            for call in r.json().get('data', {}).get('stopPlace', {}).get('estimatedCalls', []):
                dest = call.get('destinationDisplay', {}).get('frontText', 'Ukjent')
                l_code = call.get('serviceJourney', {}).get('journeyPattern', {}).get('line', {}).get('publicCode', 'Ukjent')
                
                if dest.strip().lower() != target_dest.strip().lower() or l_code.strip().lower() != line_code.strip().lower(): 
                    continue

                dt = datetime.fromisoformat(call.get('expectedDepartureTime', '').replace('Z', '+00:00'))
                clock_time = dt.astimezone().strftime('%H:%M')
                mins = (dt - datetime.now(dt.tzinfo)).total_seconds() / 60
                
                if mins >= 0:
                    deps.append({
                        'line': l_code,
                        'dest': dest, 
                        'mins': int(mins), 
                        'time': clock_time,
                        'realtime': call.get('realtime', False)
                    })
            
            return sorted(deps, key=lambda x: x['mins'])[:5]
        except: return []

# --- 4. DEPARTURE BOARD POPUP ---
class DepartureBoard(ctk.CTkToplevel):
    def __init__(self, parent, app_controller):
        super().__init__(parent)
        self.app_controller = app_controller
        self.overrideredirect(True)
        self.geometry("350x550")
        self.configure(fg_color=BG_COLOR)
        self.attributes('-topmost', True)
        
        self.update_idletasks()
        self.geometry(f"+{(self.winfo_screenwidth()//2)-(350//2)}+{(self.winfo_screenheight()//2)-(550//2)}")

        self.build_custom_titlebar()
        
        # FIX 1: Byttet fra CTkScrollableFrame til CTkFrame
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=15, pady=(15, 0))

        self.map_btn = ctk.CTkButton(self, text="🗺️ Se bussene live på kart", font=("Segoe UI", 14, "bold"), fg_color="#e0e0e0", hover_color="#d0d0d0", text_color="#333", height=45, corner_radius=8, command=self.open_entur_map)
        self.map_btn.pack(fill="x", padx=15, pady=15)
        
        self.refresh()

    def build_custom_titlebar(self):
        self.title_bar = ctk.CTkFrame(self, height=40, fg_color="#ffffff", corner_radius=0)
        self.title_bar.pack(fill="x", side="top")
        route_name = self.app_controller.config.get('route', {}).get('name', 'Avganger')
        ctk.CTkLabel(self.title_bar, text=f"🚌 {route_name}", font=("Segoe UI", 14, "bold"), text_color="#333").pack(side="left", padx=15)
        self.close_btn = ctk.CTkButton(self.title_bar, text="✕", width=40, height=40, fg_color="transparent", hover_color="#ffe5e5", text_color="#333", font=("Arial", 16), corner_radius=0, command=self.destroy)
        self.close_btn.pack(side="right")
        self.title_bar.bind("<Button-1>", self.start_move)
        self.title_bar.bind("<B1-Motion>", self.do_move)

    def start_move(self, event):
        self.x, self.y = event.x, event.y

    def do_move(self, event):
        self.geometry(f"+{self.winfo_x() + (event.x - self.x)}+{self.winfo_y() + (event.y - self.y)}")

    def open_entur_map(self):
        # FIX 2: Riktig URL-struktur for Entur
        stop_id = self.app_controller.config['route']['stop_id']
        webbrowser.open(f"https://entur.no/kart/stoppested?id={stop_id}")

    def refresh(self):
        for w in self.container.winfo_children(): w.destroy()
        deps = self.app_controller.current_deps
        
        if deps is None:
            ctk.CTkLabel(self.container, text="Laster avganger... ⏳", font=("Segoe UI", 14), text_color="#888").pack(pady=40)
            self.after(1000, self.refresh)
            return
            
        if len(deps) == 0:
            ctk.CTkLabel(self.container, text="Ingen avganger funnet.", font=("Segoe UI", 14), text_color="#e74c3c").pack(pady=40)
            return

        for d in deps:
            card = ctk.CTkFrame(self.container, fg_color="#fff", corner_radius=8)
            card.pack(fill="x", pady=5)
            
            color = AKT_GREEN if d['realtime'] else "#888888"
            live_text = "📡 Live" if d['realtime'] else "Rutetid"
            
            right_frame = ctk.CTkFrame(card, fg_color="transparent")
            right_frame.pack(side="right", padx=15, pady=5)
            ctk.CTkLabel(right_frame, text=f"{d['mins']} min", font=("Segoe UI", 16, "bold"), text_color=color).pack(anchor="e")
            ctk.CTkLabel(right_frame, text=f"{live_text} • kl {d['time']}", font=("Segoe UI", 11, "bold"), text_color="#888").pack(anchor="e")

            ctk.CTkLabel(card, text=f"{d['line']}", font=("Segoe UI", 16, "bold"), text_color="white", fg_color=color, corner_radius=6, width=40, height=40).pack(side="left", padx=10, pady=10)
            
            short_dest = d['dest'] if len(d['dest']) <= 16 else d['dest'][:14] + "..."
            ctk.CTkLabel(card, text=short_dest, font=("Segoe UI", 14, "bold"), text_color="#333", anchor="w").pack(side="left", padx=5, fill="x", expand=True)

# --- 5. THE WIZARD ---
class ModernWizard(ctk.CTkToplevel):
    def __init__(self, parent, app_controller):
        super().__init__(parent)
        self.app_controller = app_controller
        self.overrideredirect(True)
        self.geometry("450x650")
        self.configure(fg_color=BG_COLOR)
        self.attributes('-topmost', True)
        
        self.update_idletasks()
        self.geometry(f"+{(self.winfo_screenwidth()//2)-(450//2)}+{(self.winfo_screenheight()//2)-(650//2)}")

        self.config_data = {}
        self.search_timer = None
        self.all_lines = []
        
        self.build_custom_titlebar()
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=30, pady=20)
        self.show_step_1()

    def build_custom_titlebar(self):
        self.title_bar = ctk.CTkFrame(self, height=45, fg_color="#ffffff", corner_radius=0)
        self.title_bar.pack(fill="x", side="top")
        ctk.CTkLabel(self.title_bar, text="🚌 BussNaar? Oppsett", font=("Segoe UI", 14, "bold"), text_color="#333").pack(side="left", padx=15)
        self.close_btn = ctk.CTkButton(self.title_bar, text="✕", width=45, height=45, fg_color="transparent", hover_color="#ffe5e5", text_color="#333", font=("Arial", 16), corner_radius=0, command=self.close_wizard)
        self.close_btn.pack(side="right")
        self.title_bar.bind("<Button-1>", self.start_move)
        self.title_bar.bind("<B1-Motion>", self.do_move)

    def start_move(self, event):
        self.x, self.y = event.x, event.y

    def do_move(self, event):
        self.geometry(f"+{self.winfo_x() + (event.x - self.x)}+{self.winfo_y() + (event.y - self.y)}")

    def close_wizard(self):
        self.destroy()
        if not self.app_controller.is_config_valid():
            self.app_controller.quit()

    def clear_container(self):
        for widget in self.container.winfo_children(): widget.destroy()

    def show_step_1(self):
        self.clear_container()
        ctk.CTkLabel(self.container, text="Velkommen", font=("Segoe UI", 32, "bold"), text_color="#111").pack(pady=(60, 10))
        ctk.CTkLabel(self.container, text="Finn din faste rute.", font=("Segoe UI", 16), text_color="#666").pack(pady=(0, 60))
        ctk.CTkButton(self.container, text="Start →", font=("Segoe UI", 16, "bold"), fg_color=AKT_GREEN, hover_color=AKT_HOVER, height=55, corner_radius=8, command=self.show_step_2).pack(fill="x", side="bottom", pady=40)

    def show_step_2(self):
        self.clear_container()
        ctk.CTkLabel(self.container, text="Hvor drar du fra?", font=("Segoe UI", 28, "bold"), text_color="#111").pack(pady=(20, 20))
        self.search_entry = ctk.CTkEntry(self.container, placeholder_text="F.eks. Rådhuset...", font=("Segoe UI", 16), height=50, corner_radius=8, fg_color="#fff")
        self.search_entry.pack(fill="x", pady=10)
        self.search_entry.bind("<KeyRelease>", self.trigger_search)
        self.results_frame = ctk.CTkScrollableFrame(self.container, fg_color="transparent")
        self.results_frame.pack(fill="both", expand=True, pady=10)

    def trigger_search(self, event):
        if self.search_timer: self.after_cancel(self.search_timer)
        self.search_timer = self.after(300, self.execute_search)

    def execute_search(self):
        query = self.search_entry.get().strip()
        for w in self.results_frame.winfo_children(): w.destroy()
        if len(query) < 2: return
        ctk.CTkLabel(self.results_frame, text="Søker... ⏳", font=("Segoe UI", 14), text_color="#888").pack(pady=30)
        def fetch():
            results = EnturAPI.search(query)
            self.after(0, lambda: self.render_results(results))
        threading.Thread(target=fetch, daemon=True).start()

    def render_results(self, results):
        for w in self.results_frame.winfo_children(): w.destroy()
        if not results:
            ctk.CTkLabel(self.results_frame, text="Ingen treff.", font=("Segoe UI", 14), text_color="#e74c3c").pack(pady=30)
            return
        if results[0]['id'] == 'ERROR':
            ctk.CTkLabel(self.results_frame, text=results[0]['name'], font=("Segoe UI", 12), text_color="#e74c3c", wraplength=350).pack(pady=30)
            return
        for s in results[:10]:
            btn = ctk.CTkButton(self.results_frame, text=f"{s['name']}", fg_color="#fff", text_color="#333", hover_color="#e0f2ec", height=45, corner_radius=8, anchor="w", font=("Segoe UI", 14), command=lambda stop=s: self.show_step_3(stop))
            btn.pack(fill="x", pady=4)

    def show_step_3(self, stop):
        self.config_data['stop_id'] = stop['id']
        self.config_data['stop_name'] = stop['name']
        self.clear_container()
        ctk.CTkLabel(self.container, text="Henter bussruter... ⏳", font=("Segoe UI", 16), text_color="#888").pack(pady=100)
        def fetch_lines():
            lines = EnturAPI.get_lines_for_stop(stop['id'])
            self.after(0, lambda: self.render_lines(lines))
        threading.Thread(target=fetch_lines, daemon=True).start()

    def render_lines(self, lines):
        self.clear_container()
        self.all_lines = lines
        ctk.CTkLabel(self.container, text="Hvilken buss?", font=("Segoe UI", 28, "bold"), text_color="#111").pack(pady=(10, 5))
        ctk.CTkLabel(self.container, text=f"Fra {self.config_data['stop_name']}", font=("Segoe UI", 12), text_color=AKT_GREEN).pack(pady=(0, 10))
        self.line_search = ctk.CTkEntry(self.container, placeholder_text="Søk linje (f.eks 15)...", font=("Segoe UI", 16), height=45, corner_radius=8, fg_color="#fff")
        self.line_search.pack(fill="x", pady=5)
        self.line_search.bind("<KeyRelease>", self.filter_lines)
        self.lines_frame = ctk.CTkScrollableFrame(self.container, fg_color="transparent")
        self.lines_frame.pack(fill="both", expand=True, pady=5)
        self.filter_lines()

    def filter_lines(self, event=None):
        q = self.line_search.get().strip().lower()
        for w in self.lines_frame.winfo_children(): w.destroy()
        filtered = [l for l in self.all_lines if q in l['line'].lower() or q in l['dest'].lower()]
        if not filtered:
            ctk.CTkLabel(self.lines_frame, text="Fant ingen ruter.", text_color="#e74c3c").pack(pady=20)
            return
        for l in filtered:
            btn = ctk.CTkButton(self.lines_frame, text=f"Buss {l['line']} ➔ {l['dest']}", fg_color="#fff", text_color="#333", hover_color="#e0f2ec", height=50, corner_radius=8, anchor="w", font=("Segoe UI", 14), command=lambda x=l: self.show_step_4(x))
            btn.pack(fill="x", pady=4)

    def show_step_4(self, line_data):
        self.config_data['line'] = line_data['line']
        self.config_data['dest'] = line_data['dest']
        self.clear_container()
        ctk.CTkLabel(self.container, text="Siste detaljer", font=("Segoe UI", 28, "bold"), text_color="#111").pack(pady=(40, 5))
        ctk.CTkLabel(self.container, text=f"Buss {line_data['line']} ➔ {line_data['dest']}", font=("Segoe UI", 16, "bold"), text_color=AKT_GREEN).pack(pady=(0, 30))
        ctk.CTkLabel(self.container, text="Ditt navn på ruten:", font=("Segoe UI", 14), text_color="#555").pack(anchor="w", pady=(20, 5))
        self.name_entry = ctk.CTkEntry(self.container, placeholder_text="F.eks. Hjem fra skolen", font=("Segoe UI", 16), height=50, corner_radius=8)
        self.name_entry.pack(fill="x", pady=5)
        ctk.CTkButton(self.container, text="Lagre & Start ✔️", font=("Segoe UI", 16, "bold"), fg_color=AKT_GREEN, hover_color=AKT_HOVER, height=55, corner_radius=8, command=self.finish).pack(fill="x", side="bottom", pady=40)

    def finish(self):
        name = self.name_entry.get().strip()
        if not name: return
        self.app_controller.config['route'] = {
            "name": name, "stop_id": self.config_data['stop_id'], 
            "line": self.config_data['line'], "dest": self.config_data['dest']
        }
        self.app_controller.save_config()
        self.app_controller.trigger_refresh()
        self.app_controller.open_board() 
        self.destroy()

# --- 6. MAIN APP CONTROLLER ---
class AppController:
    def __init__(self):
        self.conf_path = Path.home() / "BussNaar" / "config.json"
        self.conf_path.parent.mkdir(exist_ok=True)
        
        try: self.config = json.load(open(self.conf_path)) if self.conf_path.exists() else {}
        except: self.config = {}

        self.current_deps = None
        
        self.dummy_root = ctk.CTk()
        self.dummy_root.withdraw()
        self.tray = None
        self.setup_tray()
        
        self.running = True
        threading.Thread(target=self.loop, daemon=True).start()
        
        if not self.is_config_valid():
            self.dummy_root.after(500, self.open_wizard)
        else:
            self.trigger_refresh()
            self.dummy_root.after(1000, self.open_board) 
            
        self.dummy_root.mainloop()

    def is_config_valid(self):
        if not isinstance(self.config, dict): return False
        if 'route' not in self.config: return False
        if 'dest' not in self.config['route']: return False
        return True

    def open_wizard(self):
        ModernWizard(self.dummy_root, self)
        
    def open_board(self):
        if not self.is_config_valid(): return
        DepartureBoard(self.dummy_root, self)

    def save_config(self):
        with open(self.conf_path, 'w') as f: json.dump(self.config, f)

    def setup_tray(self):
        menu = Menu(
            MenuItem("Vis Avganger", lambda icon, item: self.dummy_root.after(0, self.open_board), default=True),
            MenuItem("Endre rute / Innstillinger", lambda icon, item: self.dummy_root.after(0, self.open_wizard)), 
            MenuItem("Avslutt", self.quit)
        )
        self.tray = Icon("BussNaar?", self.draw_icon("..."), menu=menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def draw_icon(self, text):
        img = Image.new('RGB', (64, 64), color=AKT_GREEN)
        d = ImageDraw.Draw(img)
        try: font = ImageFont.truetype("segoeuib.ttf", 34)
        except: font = ImageFont.load_default()
        bbox = d.textbbox((0, 0), text, font=font)
        d.text(((64 - (bbox[2] - bbox[0])) / 2, (64 - (bbox[3] - bbox[1])) / 2 - 4), text, fill="white", font=font)
        return img

    def trigger_refresh(self):
        self.current_deps = None
        threading.Thread(target=self.force_refresh, daemon=True).start()

    def loop(self):
        while self.running:
            time.sleep(30)
            self.force_refresh()

    def force_refresh(self, *args):
        if not self.is_config_valid(): return
        r = self.config['route']
        
        self.current_deps = EnturAPI.get_next_bus(r['stop_id'], r['line'], r['dest'])
        
        if self.current_deps:
            next_bus = self.current_deps[0]
            self.tray.icon = self.draw_icon(str(next_bus['mins']))
            self.tray.title = f"{r['name']}\nLinje {next_bus['line']} til {next_bus['dest']} går om {next_bus['mins']} min\nVenstreklikk for å se flere."
        else:
            self.tray.icon = self.draw_icon("-")
            self.tray.title = "Ingen avganger funnet for valgt rute akkurat nå."

    def quit(self, icon=None, item=None):
        self.running = False
        if self.tray: self.tray.stop()
        self.dummy_root.quit()

if __name__ == "__main__":
    AppController()