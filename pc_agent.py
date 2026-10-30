import os
import sys
import threading
import time
import subprocess
import webbrowser
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import shutil
import ctypes
from pathlib import Path
import psutil
import pyautogui
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import sounddevice as sd
import numpy as np
import speech_recognition as sr

# ⚠️ PASTE YOUR GROQ API KEY HERE (starts with gsk_...)
GROQ_API_KEY = "YOUR_GROQ_API_KEY_HERE"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
CORS(app)

# Anti-duplicate state locks
LAST_TRIGGER_TIME = 0
IS_PROCESSING = False

def open_goya_window():
    """Brings GoYa to front ONLY if not already running to prevent duplicate windows"""
    try:
        is_running = False
        for proc in psutil.process_iter(['cmdline']):
            try:
                cmdline = proc.info.get('cmdline')
                if cmdline and any("127.0.0.1:5000" in str(arg) for arg in cmdline):
                    is_running = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        if not is_running:
            print("📱 Opening GoYa App Window...")
            os.system("start chrome --app=http://127.0.0.1:5000")
        else:
            print("ℹ️ GoYa App Window is already open. Skipping duplicate window.")
    except Exception as e:
        print(f"⚠️ Error opening app window: {e}")

def fetch_live_news(query):
    """Guaranteed live news fetcher via Google News RSS Feed"""
    try:
        clean_query = query.lower().replace("today news", "").replace("live news", "").replace("latest news", "").replace("news", "").strip()
        if not clean_query:
            url = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
        else:
            encoded_q = urllib.parse.quote(clean_query)
            url = f"https://news.google.com/rss/search?q={encoded_q}&hl=en-IN&gl=IN&ceid=IN:en"
            
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=5) as response:
            xml_data = response.read()
            
        root = ET.fromstring(xml_data)
        items = root.findall('.//item')
        headlines = []
        for item in items[:5]:
            title_elem = item.find('title')
            if title_elem is not None and title_elem.text:
                headlines.append(f"- {title_elem.text}")
                
        return "\n".join(headlines)
    except Exception as e:
        print(f"⚠️ Live news fetch error: {e}")
        return ""

def process_command_text(cmd):
    """Core command processor for System Automation & AI"""
    cmd = cmd.lower().strip()
    if not cmd:
        return "Empty command received"

    # ================= 1. POWER & WORKSTATION CONTROL =================
    if "shutdown pc" in cmd or "turn off pc" in cmd or "shutdown system" in cmd:
        os.system("shutdown /s /t 10")
        return "Shutting down PC in 10 seconds. Save your work!"

    elif "restart pc" in cmd or "reboot pc" in cmd:
        os.system("shutdown /r /t 10")
        return "Restarting PC in 10 seconds."

    elif "lock pc" in cmd or "lock screen" in cmd:
        ctypes.windll.user32.LockWorkStation()
        return "Workstation locked."

    elif "sleep pc" in cmd or "put pc to sleep" in cmd:
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
        return "Putting PC to sleep."

    # ================= 2. WORKSPACE & WINDOW MANAGEMENT =================
    elif "show desktop" in cmd or "minimize all" in cmd:
        pyautogui.hotkey('win', 'd')
        return "Showing desktop."

    elif "close app" in cmd or "close window" in cmd:
        pyautogui.hotkey('alt', 'f4')
        return "Closed active window."

    elif "open file explorer" in cmd or "open my computer" in cmd:
        os.system("explorer")
        return "Opened File Explorer."

    elif "open downloads" in cmd:
        downloads_path = str(Path.home() / "Downloads")
        os.system(f'explorer "{downloads_path}"')
        return "Opened Downloads folder."

    # ================= 3. AUTOMATIC DOWNLOADS FILE CLEANUP =================
    elif "organize downloads" in cmd or "clean downloads" in cmd or "clean my downloads" in cmd:
        downloads_dir = Path.home() / "Downloads"
        folders = {
            "Images": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".ico"],
            "Documents": [".pdf", ".docx", ".txt", ".xlsx", ".pptx", ".csv"],
            "Installers": [".exe", ".msi"],
            "Archives": [".zip", ".rar", ".7z"],
            "Videos": [".mp4", ".mkv", ".avi"]
        }
        moved_count = 0
        for item in downloads_dir.iterdir():
            if item.is_file():
                ext = item.suffix.lower()
                for folder, extensions in folders.items():
                    if ext in extensions:
                        target_dir = downloads_dir / folder
                        target_dir.mkdir(exist_ok=True)
                        try:
                            shutil.move(str(item), str(target_dir / item.name))
                            moved_count += 1
                        except Exception:
                            pass
                        break
        return f"Organized {moved_count} files into sorted folders inside Downloads!"

    # ================= 4. APP LAUNCH & WEB SEARCH =================
    elif "search youtube for" in cmd or "youtube search" in cmd:
        query = cmd.replace("search youtube for", "").replace("youtube search", "").strip()
        encoded = urllib.parse.quote(query)
        webbrowser.open(f"https://www.youtube.com/results?search_query={encoded}")
        return f"Opened YouTube search for '{query}'"

    elif "search google for" in cmd or "search web for" in cmd:
        query = cmd.replace("search google for", "").replace("search web for", "").strip()
        encoded = urllib.parse.quote(query)
        webbrowser.open(f"https://www.google.com/search?q={encoded}")
        return f"Searching web for '{query}'"

    elif "open website" in cmd or "open site" in cmd or "open url" in cmd:
        url = cmd.replace("open website", "").replace("open site", "").replace("open url", "").strip()
        if not url.startswith("http"):
            url = "https://" + url
        webbrowser.open(url)
        return f"Opening {url}"

    elif "open" in cmd or "launch" in cmd or "start" in cmd:
        app_target = cmd.replace("open", "").replace("launch", "").replace("start", "").strip()
        if "chrome" in app_target:
            os.system("start chrome")
        elif "notepad" in app_target:
            os.system("start notepad")
        elif "calculator" in app_target or "calc" in app_target:
            os.system("calc")
        else:
            os.system(f"start {app_target}")
        return f"Launched {app_target}"

    # ================= 5. SYSTEM HARDWARE CONTROLS =================
    elif "volume up" in cmd:
        pyautogui.press("volumeup", presses=5)
        return "Increased volume"

    elif "volume down" in cmd:
        pyautogui.press("volumedown", presses=5)
        return "Decreased volume"

    elif "mute" in cmd or "unmute" in cmd:
        pyautogui.press("volumemute")
        return "Toggled volume mute."

    elif "play" in cmd or "pause" in cmd:
        pyautogui.press("playpause")
        return "Toggled media playback."

    elif "screenshot" in cmd:
        try:
            ps_script = (
                "[Reflection.Assembly]::LoadWithPartialName('System.Drawing') | Out-Null; "
                "[Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                "$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
                "$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height; "
                "$graphics = [System.Drawing.Graphics]::FromImage($bmp); "
                "$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size); "
                "$bmp.Save('screenshot.png'); "
                "$graphics.Dispose(); "
                "$bmp.Dispose();"
            )
            subprocess.run(["powershell", "-Command", ps_script], check=True)
            return "Screenshot saved as screenshot.png"
        except Exception as err:
            return f"Screenshot error: {err}"

    # ================= 6. LIVE GOOGLE NEWS SEARCH =================
    search_context = ""
    news_keywords = ["news", "latest", "today", "current", "weather", "score", "who won", "update", "price"]
    if any(k in cmd for k in news_keywords):
        headlines = fetch_live_news(cmd)
        if headlines:
            search_context = f"LIVE GOOGLE NEWS HEADLINES:\n{headlines}"

    # ================= 7. GROQ AI FALLBACK =================
    clean_key = GROQ_API_KEY.strip()
    if not clean_key or clean_key == "YOUR_GROQ_API_KEY_HERE":
        return "Groq API key missing in pc_agent.py!"

    from groq import Groq
    client = Groq(api_key=clean_key)
    all_models = [m.id for m in client.models.list().data]
    chat_models = [
        m for m in all_models 
        if any(tag in m.lower() for tag in ['llama', 'mixtral', 'gemma', 'qwen', 'deepseek'])
        and 'whisper' not in m.lower() and 'guard' not in m.lower()
    ]

    if not chat_models:
        chat_models = [m for m in all_models if 'whisper' not in m.lower()]

    if search_context:
        prompt = f"{search_context}\n\nUSER QUESTION: {cmd}\nSummarize 2-3 of these current headlines directly for the user."
        system_msg = "You are GoYa, a voice assistant like Siri. Summarize the live news headlines clearly in 2 short sentences."
    else:
        prompt = cmd
        system_msg = "You are GoYa, a voice assistant like Siri. Give a clear, direct answer in 1 to 2 short sentences."

    for model_name in chat_models:
        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=150
            )
            return completion.choices[0].message.content
        except Exception:
            continue

    return "Could not process request with Groq AI."
def background_wake_word_listener():
    """Private listener: Ignores personal talk & opens GoYa app on wake word"""
    global LAST_TRIGGER_TIME, IS_PROCESSING
    
    time.sleep(3)
    
    recognizer = sr.Recognizer()
    fs = 16000
    seconds = 3.5
    
    # Auto-detect USB Headset device index in sounddevice
    usb_idx = None
    try:
        devices = sd.query_devices()
        for idx, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                name = dev['name'].lower()
                if any(term in name for term in ['usb', 'headset', 'mic']):
                    usb_idx = idx
                    print(f"--> Listener bound to device [{idx}]: {dev['name']}")
                    break
    except Exception:
        pass

    print("🎙️ GoYa Private Listener Active (Ignoring background talk until 'Hey GoYa')...")

    # List of wake words including common speech recognition variations
    wake_words = ["hey goya", "goya", "hi goya", "ok goya", "go ya", "a gaya", "aagaya"]

    while True:
        try:
            if IS_PROCESSING:
                time.sleep(1)
                continue

            # Record audio slice silently
            if usb_idx is not None:
                audio_np = sd.rec(int(seconds * fs), samplerate=fs, channels=1, dtype='int16', device=usb_idx)
            else:
                audio_np = sd.rec(int(seconds * fs), samplerate=fs, channels=1, dtype='int16')
            
            sd.wait()

            audio_bytes = audio_np.tobytes()
            audio_data = sr.AudioData(audio_bytes, fs, 2)

            # Transcribe speech silently
            try:
                text = recognizer.recognize_google(audio_data).lower().strip()
            except sr.UnknownValueError:
                continue  # Ignore unrecognized noise quietly

            # PRIVACY FILTER: Immediately drop any speech that DOES NOT contain the wake word
            if not any(w in text for w in wake_words):
                continue

            # Wake word matched!
            current_time = time.time()
            if current_time - LAST_TRIGGER_TIME < 3.0:
                continue

            IS_PROCESSING = True
            LAST_TRIGGER_TIME = current_time

            print(f"🚀 Wake word detected: '{text}'")

            # Extract any follow-up command
            clean_cmd = text
            for w in wake_words:
                clean_cmd = clean_cmd.replace(w, "")
            clean_cmd = clean_cmd.strip()

            if clean_cmd:
                print(f"⚡ Executing command: '{clean_cmd}'")
                execute_command_internal(clean_cmd)
            else:
                # If you just say "Hey GoYa", automatically bring up the GoYa app window!
                print("🌐 Opening GoYa App Window...")
                os.system("start chrome.exe --app=http://localhost:5000")

            IS_PROCESSING = False

        except Exception:
            IS_PROCESSING = False
            time.sleep(1)
@app.route('/')
def home():
    html_path = os.path.join(BASE_DIR, 'index.html')
    if os.path.exists(html_path):
        return send_file(html_path)
    return f"index.html file not found at {html_path}", 404

@app.route('/api/telemetry', methods=['GET'])
def telemetry():
    return jsonify({
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage('/').percent
    })

@app.route('/api/execute', methods=['POST'])
def execute():
    try:
        data = request.json or {}
        cmd = data.get("command", "").lower().strip()
        msg = process_command_text(cmd)
        return jsonify({"status": "success", "message": msg})
    except Exception as global_err:
        return jsonify({"status": "error", "message": str(global_err)}), 500

if __name__ == '__main__':
    listener_thread = threading.Thread(target=background_wake_word_listener, daemon=True)
    listener_thread.start()

    print("🚀 GoYa Server running on http://127.0.0.1:5000")
    app.run(port=5000, debug=False)