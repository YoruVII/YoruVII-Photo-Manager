import time
import os
import json
import threading
import sys
import gc
import msvcrt
import psutil 
import datetime
import tkinter as tk
from tkinter import messagebox
import tkinter.font as tkfont
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from PIL import Image
import requests
import pystray
from pystray import MenuItem as item

# Start on low priotiy so if VRC needs to it can take YPM out back and cripple it

def set_low_priority():
    try:
        p = psutil.Process(os.getpid())
        p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass

# do the paths good so logo.ico works good
def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Settings and Log Management

SETTINGS_FILE = "yoruvii_photo_manager_settings.json"
SENT_LOG_FILE = "ypm_sent.log"
AUTO_PATH = os.path.join(os.path.expanduser("~"), "Pictures", "VRChat")

DEFAULT_SETTINGS = {
    "webhook_url": "",
    "watch_path": AUTO_PATH,
    "delay_ms": 100,
    "msg_format": "Photo taken by {author} in [{world}](<{url}>) <t:{ts}:R>{players}",
    "last_author": "User"
}

def check_log_size():
    """ Wipes the sent log if it exceeds 100MB to save disk space and scan time """
    if os.path.exists(SENT_LOG_FILE):
        if os.path.getsize(SENT_LOG_FILE) > 100 * 1024 * 1024:
            try: os.remove(SENT_LOG_FILE)
            except: pass

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return {**DEFAULT_SETTINGS, **json.load(f)}
        except: pass
    return DEFAULT_SETTINGS

def save_settings(data):
    """ Cleans up the path string and saves settings to disk """
    data["watch_path"] = data["watch_path"].strip('"').strip("'")
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=4)

# Photo Prossesing logic

class PhotoHandler(FileSystemEventHandler):
    def __init__(self, settings, session, start_time):
        self.settings = settings
        self.start_time = start_time
        self.session = session
        self.processed_files = {} 
        self.last_sizes = {} # Tracks file sizes so windows opening the fucking file that contains the images does not spam them all

    def is_already_sent(self, file_path):
        if not os.path.exists(SENT_LOG_FILE): return False
        unique_id = os.path.basename(file_path)[:32] 
        try:
            with open(SENT_LOG_FILE, "r", encoding="utf-8") as f:
                return unique_id in f.read()
        except: return False

    def on_any_event(self, event):
        if event.is_directory: return

        # Identify the path when things are moved/created
        path = event.dest_path if event.event_type == 'moved' else event.src_path
        
        if path and path.lower().endswith(('.png', '.jpg', '.jpeg')):
            
            # Kills the process if the file was created before the app was opened to prevent old photos from tripping it up
            try:
                if os.path.getctime(path) < self.start_time:
                    return 
            except:
                return

            # Kills the process if the photos is already in ypm_sent.log to prevent resending when vrc closes or vrcx renames the files
            if self.is_already_sent(path):
                return

            # Kills the process if Windows just "touched" the file without changing data like when you open the images path in file explorer
            try:
                current_size = os.path.getsize(path)
                if path in self.last_sizes and self.last_sizes[path] == current_size:
                    return 
                self.last_sizes[path] = current_size
            except:
                return

            # just a 5s window to prevent double-firing on the same path
            current_time = time.time()
            if path in self.processed_files:
                if current_time - self.processed_files[path] < 5:
                    return
            
            self.processed_files[path] = current_time
            
            # Start processing the image in a background thread
            threading.Thread(target=self.process_photo, args=(path,), daemon=True).start()

            # RAM Cleanup: Keep our size tracker cache from growing forever yippe
            if len(self.last_sizes) > 50:
                self.last_sizes.clear()

    # do this by year because vrc did not always have metadata so best to just check old photos from a last session and year is a good way to do that thare is a world whare this does not work but it is 3AM and I am struggleing
    def get_fallback_author(self):
        """ Scans all subfolders (YYYY-MM) for the oldest tagged photo of the year oof if you use this Jan 1 for the first time"""
        try:
            folder = self.settings.get("watch_path")
            files = []
            # Scan subdirectories
            for root, _, filenames in os.walk(folder):
                for f in filenames:
                    if f.lower().endswith(('.png', '.jpg')):
                        files.append(os.path.join(root, f))
            
            if not files: return "User"
            
            # Find the start of the current year
            year_start = datetime.datetime(datetime.datetime.now().year, 1, 1).timestamp()
            files.sort(key=os.path.getmtime) # Oldest first
            
            for f in files:
                # Skip files from previous years I feel like this is going to come back to bite me but whateva
                if os.path.getmtime(f) < year_start: continue
                try:
                    with Image.open(f) as img:
                        meta = img.info.get('Description', "")
                        if meta:
                            name = json.loads(meta).get('author', {}).get('displayName')
                            if name: return name
                except: continue
        except: pass
        return "User"

    def process_photo(self, file_path):
        """ Extracts metadata and handles the Discord upload with retries """
        # Let the file finish writing yippeeee
        time.sleep(int(self.settings.get("delay_ms", 1000)) / 1000.0)
        
        msg, raw_metadata = "", ""
        try:
            # Wait for VRChat to release the file lock and write metadata
            for _ in range(20):
                if not os.path.exists(file_path): return 
                try:
                    with Image.open(file_path) as img:
                        raw_metadata = img.info.get('Description', "")
                    if raw_metadata: break
                except:
                    time.sleep(0.1); continue
                time.sleep(0.1)

            ts = int(os.path.getctime(file_path)) 
            
            # Case 1: Metadata found (VRCX was active yay)
            if raw_metadata:
                data = json.loads(raw_metadata)
                players_str = ""
                author = data.get('author', {}).get('displayName', "User")
                
                # If we found the user, save it as our persistent fallback haha all your base is mine
                if author != "User" and author != self.settings.get("last_author"):
                    self.settings["last_author"] = author
                    save_settings(self.settings)

                world_data = data.get('world', {})
                world, w_id = world_data.get('name'), world_data.get('id')
                
                if author and world and w_id:
                    url = f"https://vrchat.com/home/world/{w_id}"
                    player_list = [p['displayName'] for p in data.get('players', [])]
                    if author in player_list: player_list.remove(author)
                    
                    # multiple players logic have with: usernames if you are not alone and nothing if you are a lonely bitch sorry very tired and hangry
                    players_str = "\nWith: " + ", ".join([f"`{p}`" for p in player_list]) if player_list else ""
                    msg = self.settings["msg_format"].format(author=author, world=world, url=url, players=players_str, ts=ts)
            
            # Case 2: No metadata (VRCX Closed) (Fuck you)
            if not msg:
                author = self.settings.get("last_author", "User")
                # If even the settings name is 'User', try the expensive folder-scan
                if author == "User":
                    found = self.get_fallback_author()
                    if found:
                        author = found
                        self.settings["last_author"] = author
                        save_settings(self.settings)
                
                msg = f"Photo taken by {author} <t:{ts}:R>" if author != "User" else f"Photo taken <t:{ts}:R>"

            gc.collect() # Balanced cleanup

            # For my shitass internet ugh
            if msg:
                # Try 5 times (total 1 min of downtime coverage)
                for attempt in range(5):
                    # Final check: did VRCX rename it while we were waiting on internet?
                    if self.is_already_sent(file_path): break
                    
                    try:
                        with open(file_path, 'rb') as f:
                            files = {'file': (os.path.basename(file_path), f, 'image/png')}
                            # 15s timeout prevents a dead pipe from hanging the thread forever
                            urls = [u.strip() for u in self.settings["webhook_url"].split(',')]
                            for webhook_url in urls:
                                if not webhook_url: continue # Skip empty strings
                                try:
                                    # We need to seek(0) if we are sending the same file object multiple times
                                    f.seek(0) 
                                    resp = self.session.post(webhook_url, data={'content': msg}, files=files, timeout=15)
                                    # Add your success logging here
                                except Exception:
                                    continue # Try the next hook if one fails
                            
                            if resp.status_code in [200, 204]:
                                # Success! Log only the timestamp-id to the disk log
                                unique_id = os.path.basename(file_path)[:32]
                                with open(SENT_LOG_FILE, "a", encoding="utf-8") as log:
                                    log.write(unique_id + "\n")
                                break # Exit retry loop
                    except (requests.exceptions.RequestException, Exception):
                        # Internet fucking sucks, wait 12 seconds and try again
                        time.sleep(12) 
                
                gc.collect() # Final cleanup
        except Exception as e: print(f"Error: {e}")

# The UI

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("YoruVII Photo Manager")
        self.root.geometry("500x550")
        self.start_time = time.time()
        
        set_low_priority()
        check_log_size()
        
        # Reuse connection to Discord for faster uploads/lower RAM (thiryetricly (I got to install mono's spelcheck softwhare again lmaoo))
        self.session = requests.Session()
        self.session.max_redirects = 1 # RAM safety
        self.session.trust_env = False   # RAM safety
        
        self.icon_path = get_resource_path("logo.ico")
        if os.path.exists(self.icon_path):
            try: self.root.iconbitmap(self.icon_path)
            except: pass

        self.settings = load_settings()
        self.observer, self.tray_icon = None, None

        # Colors and Epic Styling
        self.BG_COLOR, self.FIELD_COLOR = "#29303A", "#37424F"   
        self.TEXT_COLOR, self.ACCENT_COLOR = "#7A8099", "#741211"  

        self.root.configure(bg=self.BG_COLOR)
        self.custom_font = tkfont.Font(family="Aptos", size=15)
        self.header_font = tkfont.Font(family="Aptos", size=15, weight="bold")

        self.create_widgets()
        self.setup_tray() 

        # if settings are set just go to the trey
        if self.settings["webhook_url"] and self.settings["watch_path"]:
            self.root.after(200, self.apply_and_hide)

    def create_widgets(self):
        def add_label(text):
            lbl = tk.Label(self.root, text=text, bg=self.BG_COLOR, fg=self.TEXT_COLOR, font=self.header_font)
            lbl.pack(pady=(15, 0))

        def add_entry(val):
            ent = tk.Entry(self.root, width=60, bg=self.FIELD_COLOR, fg=self.TEXT_COLOR, insertbackground="white", font=self.custom_font, relief="flat", bd=8)
            ent.pack(padx=25, pady=5); ent.insert(0, val)
            return ent

        add_label("Discord Webhook URL"); self.ent_webhook = add_entry(self.settings["webhook_url"])
        add_label("VRChat Photo Path"); self.ent_path = add_entry(self.settings["watch_path"])
        add_label("Post Delay (ms)"); self.ent_delay = add_entry(self.settings["delay_ms"])
        add_label("VRCX Message Format")
        self.txt_format = tk.Text(self.root, height=4, width=60, bg=self.FIELD_COLOR, fg=self.TEXT_COLOR, insertbackground="white", font=self.custom_font, relief="flat", bd=8)
        self.txt_format.pack(padx=25, pady=5); self.txt_format.insert("1.0", self.settings["msg_format"])

        self.btn_save = tk.Button(self.root, text="Save & Hide to Tray", bg=self.ACCENT_COLOR, fg="white", font=self.header_font, relief="flat", command=self.apply_and_hide, cursor="hand2", padx=30, pady=12)
        self.btn_save.pack(pady=25)
        self.root.protocol('WM_DELETE_WINDOW', self.minimize_to_tray)

    def apply_and_hide(self):
        # Update settings from UI
        self.settings.update({
            "webhook_url": self.ent_webhook.get(),
            "watch_path": self.ent_path.get(),
            "delay_ms": self.ent_delay.get(),
            "msg_format": self.txt_format.get("1.0", "end-1c")
        })
        save_settings(self.settings)
        
        # Stop the old observer if it exists
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=1)
        
        # Create the Observer object FIRST fuken dumbass
        watch_path = self.settings["watch_path"]
        if os.path.exists(watch_path):
            self.observer = Observer() # This creates the object so it isn't 'None'
            
            # call .schedule
            self.observer.schedule(
                PhotoHandler(self.settings, self.session, self.start_time), 
                watch_path, 
                recursive=True
            )
            
            self.observer.daemon = True 
            self.observer.start()
            self.minimize_to_tray()
        else:
            messagebox.showerror("Error", f"Path not found:\n{watch_path}")

    def setup_tray(self):
        icon_img = Image.open(self.icon_path) if os.path.exists(self.icon_path) else Image.new('RGB', (64, 64), (116, 18, 17))
        def on_clicked(icon, item): self.root.after(0, self.show_window)
        menu = (item('Show Settings', on_clicked, default=True), item('Exit YPM', self.quit_app))
        self.tray_icon = pystray.Icon("YoruVIIPhotoManager", icon_img, "YoruVII Photo Manager", menu)
        self.tray_icon.action = on_clicked
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def minimize_to_tray(self): self.root.withdraw()
    def show_window(self):
        self.root.deiconify(); self.root.lift()
        self.root.attributes('-topmost', True); self.root.attributes('-topmost', False)

    def quit_app(self):
        """ Clean shutdown of the watcher and tray """
        if self.observer: self.observer.stop()
        if self.tray_icon: self.tray_icon.stop()
        os._exit(0) 

if __name__ == "__main__":
    # Keep the application from haveing two open
    lock_file_path = "yoruvii_Photo_manager.lock"
    try:
        lock_file = open(lock_file_path, 'w')
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        root = tk.Tk(); app = App(root); root.mainloop()
    except:
        error_window = tk.Tk(); error_window.withdraw() 
        messagebox.showinfo("YoruVII Photo Manager", "Already running you FUCKING RAT Check the tray if its not thare I fucked it up sorry.")
        error_window.destroy(); os._exit(0)


# To Build: pyinstaller --noconsole --onefile --clean --add-data "logo.ico;." --icon=logo.ico --exclude-module tkinter.test --exclude-module test --exclude-module numpy --exclude-module matplotlib -n "YoruVII Photo Manager" YoruVII_Photo_Manager.py