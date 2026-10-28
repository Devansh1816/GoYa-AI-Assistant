import os
import sys
import threading
import time
import subprocess
import webbrowser
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
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
    """Core command processor shared by web UI and background wake-word"""
    cmd = cmd.lower().strip()
    if not cmd:
        return "Empty command received"

    # System Control Commands
    if "search youtube for" in cmd or "youtube search" in cmd:
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

    elif "volume up" in cmd:
        pyautogui.press("volumeup", presses=5)
        return "Increased volume"

    elif "volume down" in cmd:
        pyautogui.press("volumedown", presses=5)
        return "Decreased volume"

    elif "screenshot" in cmd:
        pyautogui.screenshot("screenshot.png")
        return "Screenshot saved"

    # Live News Search
    search_context = ""
    news_keywords = ["news", "latest", "today", "current", "weather", "score", "who won", "update", "price"]
    if any(k in cmd for k in news_keywords):
        headlines = fetch_live_news(cmd)
        if headlines:
            search_context = f"LIVE GOOGLE NEWS HEADLINES:\n{headlines}"

    # Groq AI Query
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
    """Background listener with process check & anti-duplicate execution locks"""
    global LAST_TRIGGER_TIME, IS_PROCESSING
    recognizer = sr.Recognizer()
    fs = 16000
    seconds = 3.5

    print("👂 Background OS Wake-Word Listener Active ('Hey GoYa')...")

    while True:
        try:
            # Skip listening while executing a command to prevent double triggers
            if IS_PROCESSING:
                time.sleep(1)
                continue

            audio_np = sd.rec(int(seconds * fs), samplerate=fs, channels=1, dtype='int16')
            sd.wait()

            audio_bytes = audio_np.tobytes()
            audio_data = sr.AudioData(audio_bytes, fs, 2)

            try:
                text = recognizer.recognize_google(audio_data).lower().strip()
                if text:
                    print(f"🎙️ Background Heard: {text}")

                if any(w in text for w in ["goya", "hey goya", "hi goya", "ok goya"]):
                    current_time = time.time()
                    if current_time - LAST_TRIGGER_TIME < 6.0:
                        continue
                    
                    IS_PROCESSING = True
                    LAST_TRIGGER_TIME = current_time
                    print("⚡ 'Hey GoYa' Triggered!")
                    
                    clean_cmd = text
                    for wake_phrase in ["hey goya", "hi goya", "ok goya", "goya"]:
                        clean_cmd = clean_cmd.replace(wake_phrase, "")
                    clean_cmd = clean_cmd.strip()

                    open_goya_window()

                    if clean_cmd:
                        print(f"⚡ Executing Spoken Command: '{clean_cmd}'")
                        time.sleep(0.5)
                        result_msg = process_command_text(clean_cmd)
                        print(f"🤖 Action Result: {result_msg}")

                    time.sleep(2)  # Wait 2 seconds before resuming microphone listener
                    IS_PROCESSING = False

            except sr.UnknownValueError:
                pass
            except sr.RequestError:
                pass
            
            time.sleep(0.3)
        except Exception as e:
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