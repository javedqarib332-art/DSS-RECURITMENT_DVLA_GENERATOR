import os
import re
import time
import random
import logging
import threading
import pandas as pd
import gspread
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DVLA_ROBOT")

# --- FLASK CONFIG ---
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- ORIGINAL CONFIG (AS PROVIDED) ---
JSON_PATH = r"C:\Users\Muhammad Qarib\Downloads\credentials.jason.json"
SHEET_URL = "https://docs.google.com/spreadsheets/d/1vO4Hs0FYu58dqzA-3MMr_Hpj10M-9RRsG5j0ZOxs1Yo/edit"
DOWNLOAD_BASE = os.path.join(os.path.expanduser("~"), "Downloads", "DVLA for DSS-RECRUITMENT")
os.makedirs(DOWNLOAD_BASE, exist_ok=True)


# --- ORIGINAL FUNCTIONS (STRICTLY UNCHANGED) ---
def retry(func, retries=3):
    for i in range(retries):
        try:
            return func()
        except Exception as e:
            if i == retries - 1:
                raise e
            time.sleep(random.uniform(2, 4))


class DVLARobot:
    def __init__(self, context):
        self.context = context

    def human_delay(self):
        time.sleep(random.uniform(1.5, 3.5))

    def solve_phase_1(self, page, pichla_code):
        logger.info("📡 Phase 1: Detecting Fresh Code...")
        try:
            page.wait_for_selector("#tab_ShareCode", timeout=15000)
            page.click("#tab_ShareCode", force=True)
            self.human_delay()
            gen_btn = page.locator("button:has-text('Get a code'), button:has-text('Get another code')").first
            gen_btn.click(force=True)
            logger.info("🔘 Button Clicked. Scanning for text...")
            page.wait_for_timeout(3000)
        except Exception as e:
            logger.error(f"❌ UI Navigation Fail: {e}")
            return None
        for i in range(20):
            page.wait_for_timeout(1000)
            raw_body = page.inner_text("body")
            clean_body = re.sub(r'\s+', '', raw_body)
            match = re.search(r'Yourcheckcodeis([A-Za-z0-9]{8})', clean_body, re.IGNORECASE)
            if match:
                detected = match.group(1)
                if detected != pichla_code:
                    if any(c.isdigit() for c in detected) and len(detected) == 8:
                        if detected.upper() not in ['VIEWNOW', 'POSTCODE', 'CONTINUE']:
                            logger.info(f"✅ FRESH CODE SECURED: {detected}")
                            return detected
            backup_matches = re.findall(r'\b[A-Za-z0-9]{8}\b', raw_body.replace(" ", ""))
            for bm in backup_matches:
                if bm != pichla_code and any(c.isdigit() for c in bm):
                    if bm.upper() not in ['VIEWNOW', 'POSTCODE', 'CONTINUE']:
                        return bm
        return None

    def solve_phase_2(self, row, code):
        logger.info(f"🏗️ Phase 2: Validating {row['Driver Name']}...")
        p2 = self.context.new_page()
        try:
            lic_suffix = str(row['licence number']).strip()[-8:].upper()
            retry(lambda: p2.goto(
                "https://www.viewdrivingrecord.service.gov.uk/lang/en/driving-record/validate",
                wait_until="networkidle"
            ))
            self.human_delay()
            p2.wait_for_selector("#wizard_check_driving_licence_enter_details_driving_licence_number")
            p2.fill("#wizard_check_driving_licence_enter_details_driving_licence_number", lic_suffix)
            self.human_delay()
            p2.fill("#wizard_check_driving_licence_enter_details_check_code", code)
            self.human_delay()
            p2.click("button[name='button']")
            save_sel = "a:has-text('Save or print this licence')"
            p2.wait_for_selector(save_sel, timeout=20000)
            with p2.expect_download() as download_info:
                p2.click(save_sel, force=True)
            filename = f"DVLA_{row['Driver Name'].replace(' ', '_')}.pdf"
            download_info.value.save_as(os.path.join(DOWNLOAD_BASE, filename))
            logger.info(f"🎯 PDF SAVED: {filename}")
            return True
        except Exception as e:
            logger.error(f"🚨 Phase 2 Error: {e}")
            return False
        finally:
            p2.close()


# --- WEB INTEGRATION WRAPPER ---
def run_automation(names_input, log_callback):
    try:
        creds = Credentials.from_service_account_file(
            JSON_PATH,
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        )
        client = gspread.authorize(creds).open_by_url(SHEET_URL).sheet1
        df = pd.DataFrame(client.get_all_records()).fillna('')
        log_callback(f"📊 Sheet Synced: {len(df)} records found.")
    except Exception as e:
        log_callback(f"CRITICAL: Sheet Access Denied: {e}")
        return [], []

    names = [q.strip() for q in names_input.split(",")]
    targets = df[df['Driver Name'].apply(
        lambda x: any(name.lower() in x.lower() for name in names))].to_dict('records')

    if not targets:
        log_callback("⚠️ No driver found with those names.")
        return [], []

    failed_drivers = []
    success_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        last_code_memory = ""
        for row in targets:
            log_callback(f"🚀 Processing: {row['Driver Name']}")
            context = browser.new_context(
                accept_downloads=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                locale="en-GB",
                timezone_id="Europe/London"
            )
            bot = DVLARobot(context)
            p1 = context.new_page()
            p1.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            try:
                retry(lambda: p1.goto("https://www.viewdrivingrecord.service.gov.uk/driving-record/licence-number"))
                bot.human_delay()
                p1.fill("#wizard_view_driving_licence_enter_details_driving_licence_number", str(row['licence number']))
                p1.fill("#wizard_view_driving_licence_enter_details_national_insurance_number", str(row['NIN Number']))
                p1.fill("#wizard_view_driving_licence_enter_details_post_code", str(row['Post code']))
                p1.locator("input[type='checkbox']").check()
                bot.human_delay()
                p1.click("#view-now")
                current_code = bot.solve_phase_1(p1, last_code_memory)
                if current_code:
                    last_code_memory = current_code
                    success = bot.solve_phase_2(row, current_code)
                    if success:
                        success_count += 1
                        log_callback(f"✅ Success: {row['Driver Name']}")
                    else:
                        failed_drivers.append(row['Driver Name'])
                else:
                    failed_drivers.append(row['Driver Name'])
            finally:
                p1.close()
                context.close()
            time.sleep(random.uniform(2, 5))
        browser.close()
    return success_count, failed_drivers


# --- UI HTML TEMPLATE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"><title>DSS-RECRUITMENT DVLA GENERATOR</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        body { font-family: 'Inter', sans-serif; background-color: #0f172a; color: #f1f5f9; }
        .glass { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255,255,255,0.1); }
        .log-stream { font-family: 'Fira Code', monospace; scrollbar-width: thin; }
    </style>
</head>
<body class="min-h-screen p-4 md:p-10">
    <div class="max-w-6xl mx-auto">
        <header class="flex justify-between items-center mb-10 border-b border-slate-700 pb-6">
            <div>
                <h1 class="text-3xl font-bold tracking-tight text-white">DSS-RECRUITMENT <span class="text-blue-500">DVLA GENERATOR</span></h1>
                <p class="text-slate-400">Developed by <span class="text-blue-400 font-semibold">QARIB JAVED</span></p>
            </div>
            <div id="status" class="px-4 py-1 rounded-full bg-slate-800 text-xs font-bold uppercase tracking-widest text-slate-400">Standby</div>
        </header>

        <div class="grid grid-cols-1 lg:grid-cols-12 gap-8">
            <div class="lg:col-span-4 space-y-6">
                <div class="glass p-6 rounded-2xl shadow-2xl">
                    <label class="block text-sm font-medium text-slate-300 mb-3">Target Driver Names</label>
                    <textarea id="names" rows="6" class="w-full bg-slate-900/50 border border-slate-700 rounded-xl p-4 text-white focus:ring-2 focus:ring-blue-500 outline-none transition" placeholder="John Doe, Jane Smith..."></textarea>
                    <div class="grid grid-cols-2 gap-3 mt-4">
                        <button id="startBtn" class="bg-blue-600 hover:bg-blue-500 text-white font-bold py-3 rounded-xl transition shadow-lg shadow-blue-900/20">START</button>
                        <button id="clearBtn" class="bg-slate-800 hover:bg-slate-700 text-slate-300 py-3 rounded-xl transition">CLEAR</button>
                    </div>
                </div>
            </div>

            <div class="lg:col-span-8 space-y-6">
                <div class="glass p-6 rounded-2xl h-[400px] flex flex-col">
                    <div class="flex justify-between items-center mb-4">
                        <h3 class="text-xs font-bold uppercase text-slate-500 tracking-widest">Live System Output</h3>
                        <span id="loader" class="hidden animate-pulse text-blue-500 text-xs font-bold">ENGINE RUNNING...</span>
                    </div>
                    <div id="logs" class="log-stream flex-grow overflow-y-auto bg-black/40 p-4 rounded-xl text-sm text-blue-300 border border-white/5 space-y-1">
                        <div>> System initialized. Awaiting driver list...</div>
                    </div>
                </div>

                <div id="summary" class="hidden glass p-6 rounded-2xl border-l-4 border-emerald-500 animate-in fade-in slide-in-from-bottom-4 duration-700">
                    <h4 class="text-lg font-bold mb-4">Processing Summary</h4>
                    <div class="grid grid-cols-2 gap-4 mb-4">
                        <div class="bg-emerald-500/10 p-4 rounded-xl border border-emerald-500/20">
                            <p class="text-xs text-emerald-500 uppercase font-bold">Successful</p>
                            <p id="successCount" class="text-3xl font-black">0</p>
                        </div>
                        <div class="bg-rose-500/10 p-4 rounded-xl border border-rose-500/20">
                            <p class="text-xs text-rose-500 uppercase font-bold">Rejected</p>
                            <p id="failCount" class="text-3xl font-black">0</p>
                        </div>
                    </div>
                    <div id="failList" class="space-y-2"></div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const socket = io();
        const startBtn = document.getElementById('startBtn');
        const logs = document.getElementById('logs');
        const status = document.getElementById('status');
        const loader = document.getElementById('loader');

        startBtn.onclick = () => {
            const val = document.getElementById('names').value;
            if(!val) return alert("Please enter at least one name.");

            socket.emit('trigger_process', { names: val });
            startBtn.disabled = true;
            startBtn.classList.add('opacity-50');
            status.innerText = "Processing";
            status.className = "px-4 py-1 rounded-full bg-blue-500 text-xs font-bold uppercase tracking-widest text-white";
            loader.classList.remove('hidden');
            document.getElementById('summary').classList.add('hidden');
        };

        socket.on('update_log', (data) => {
            const div = document.createElement('div');
            div.innerHTML = `<span class="text-slate-600">[${new Date().toLocaleTimeString()}]</span> ${data.msg}`;
            logs.appendChild(div);
            logs.scrollTop = logs.scrollHeight;
        });

        socket.on('complete', (data) => {
            startBtn.disabled = false;
            startBtn.classList.remove('opacity-50');
            loader.classList.add('hidden');
            status.innerText = "Finished";
            status.className = "px-4 py-1 rounded-full bg-emerald-600 text-xs font-bold uppercase tracking-widest text-white";

            document.getElementById('summary').classList.remove('hidden');
            document.getElementById('successCount').innerText = data.success;
            document.getElementById('failCount').innerText = data.failed.length;

            const list = document.getElementById('failList');
            list.innerHTML = "";
            data.failed.forEach(name => {
                list.innerHTML += `<div class="text-xs p-3 bg-rose-500/5 border border-rose-500/20 rounded-lg text-rose-300">
                    <strong>❌ ${name}</strong>: The website rejected the provided details.
                </div>`;
            });
        });

        document.getElementById('clearBtn').onclick = () => document.getElementById('names').value = "";
    </script>
</body>
</html>
"""


# --- ROUTES & SOCKETS ---
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@socketio.on('trigger_process')
def handle_automation(data):
    names = data.get('names', '')

    def log_bridge(message):
        socketio.emit('update_log', {'msg': message})

    def run_thread():
        success, failed = run_automation(names, log_bridge)
        socketio.emit('complete', {'success': success, 'failed': failed})

    threading.Thread(target=run_thread).start()


if __name__ == '__main__':
    print(">>> DSS-RECRUITMENT DVLA GENERATOR BY QARIB JAVED")
    print(">>> System launching at http://127.0.0.1:5000")
    # allow_unsafe_werkzeug=True add kiya gaya hai
    socketio.run(app, port=5000, debug=False, allow_unsafe_werkzeug=True)
