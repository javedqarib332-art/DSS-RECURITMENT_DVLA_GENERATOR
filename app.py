import streamlit as st
import os
import re
import time
import random
import logging
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DVLA_ROBOT")

# --- UI CONFIG ---
st.set_page_config(page_title="DSS-RECRUITMENT DVLA", page_icon="🏎️", layout="wide")

# Custom CSS for Dark Premium Theme
st.markdown("""
    <style>
    .main { background-color: #0f172a; color: #f1f5f9; }
    .stButton>button {
        width: 100%; border-radius: 12px; height: 3em;
        background-color: #2563eb; color: white; border: none;
        font-weight: bold; transition: 0.3s;
    }
    .stButton>button:hover { background-color: #3b82f6; border: none; color: white; }
    .log-container {
        background-color: #00000066; border: 1px solid #334155;
        border-radius: 12px; padding: 15px; font-family: 'Fira Code', monospace;
        color: #60a5fa; height: 400px; overflow-y: auto;
    }
    .stats-card {
        background: rgba(30, 41, 59, 0.7); padding: 20px;
        border-radius: 15px; border: 1px solid rgba(255,255,255,0.1);
    }
    </style>
    """, unsafe_allow_html=True)

# --- CONFIG ---
SHEET_URL = "https://docs.google.com/spreadsheets/d/1vO4Hs0FYu58dqzA-3MMr_Hpj10M-9RRsG5j0ZOxs1Yo/edit"
DOWNLOAD_BASE = "downloads"
os.makedirs(DOWNLOAD_BASE, exist_ok=True)

# --- GOOGLE AUTH HELPER (FIXED FOR JWT ERROR) ---
def get_gspread_client():
    try:
        # Secrets se data uthayega aur dictionary banayega
        creds_info = dict(st.secrets["gcp_service_account"])
        
        # KEY FIX: Literal \n ko real newline character mein badalna
        if "private_key" in creds_info:
            creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        
        creds = Credentials.from_service_account_info(
            creds_info, 
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        )
        return gspread.authorize(creds).open_by_url(SHEET_URL).sheet1
    except Exception as e:
        st.error(f"Authentication Error: {e}")
        return None

# --- CORE CLASSES (UNCHANGED) ---
def retry(func, retries=3):
    for i in range(retries):
        try: return func()
        except Exception as e:
            if i == retries - 1: raise e
            time.sleep(random.uniform(2, 4))

class DVLARobot:
    def __init__(self, context):
        self.context = context

    def human_delay(self):
        time.sleep(random.uniform(1.5, 3.5))

    def solve_phase_1(self, page, pichla_code):
        try:
            page.wait_for_selector("#tab_ShareCode", timeout=15000)
            page.click("#tab_ShareCode", force=True)
            self.human_delay()
            gen_btn = page.locator("button:has-text('Get a code'), button:has-text('Get another code')").first
            gen_btn.click(force=True)
            page.wait_for_timeout(3000)
        except: return None
        
        for i in range(20):
            page.wait_for_timeout(1000)
            raw_body = page.inner_text("body")
            clean_body = re.sub(r'\s+', '', raw_body)
            match = re.search(r'Yourcheckcodeis([A-Za-z0-9]{8})', clean_body, re.IGNORECASE)
            if match:
                detected = match.group(1)
                if detected != pichla_code and any(c.isdigit() for c in detected):
                    if detected.upper() not in ['VIEWNOW', 'POSTCODE', 'CONTINUE']:
                        return detected
        return None

    def solve_phase_2(self, row, code):
        p2 = self.context.new_page()
        try:
            lic_suffix = str(row['licence number']).strip()[-8:].upper()
            retry(lambda: p2.goto("https://www.viewdrivingrecord.service.gov.uk/lang/en/driving-record/validate", wait_until="networkidle"))
            p2.fill("#wizard_check_driving_licence_enter_details_driving_licence_number", lic_suffix)
            p2.fill("#wizard_check_driving_licence_enter_details_check_code", code)
            p2.click("button[name='button']")
            save_sel = "a:has-text('Save or print this licence')"
            p2.wait_for_selector(save_sel, timeout=20000)
            with p2.expect_download() as download_info:
                p2.click(save_sel, force=True)
            filename = f"DVLA_{row['Driver Name'].replace(' ', '_')}.pdf"
            download_info.value.save_as(os.path.join(DOWNLOAD_BASE, filename))
            return True
        except: return False
        finally: p2.close()

# --- UI LAYOUT ---
st.markdown("""
    <div style='border-bottom: 1px solid #334155; padding-bottom: 10px; margin-bottom: 25px;'>
        <h1 style='color: white; margin-bottom: 0;'>DSS-RECRUITMENT <span style='color: #3b82f6;'>DVLA GENERATOR</span></h1>
        <p style='color: #94a3b8;'>Developed by <span style='color: #60a5fa; font-weight: bold;'>QARIB JAVED</span></p>
    </div>
""", unsafe_allow_html=True)

col1, col2 = st.columns([1, 2], gap="large")

with col1:
    st.markdown("### 📋 Configuration")
    names_input = st.text_area("Target Driver Names", placeholder="John Doe, Jane Smith...", height=200)
    headless_mode = st.toggle("Headless Mode (Silent Run)", value=True)
    start_btn = st.button("🚀 START ENGINE")

with col2:
    st.markdown("### 📡 Live System Output")
    log_placeholder = st.empty()
    if 'logs' not in st.session_state: st.session_state.logs = []

    def update_ui_logs(msg):
        st.session_state.logs.append(f"[{time.strftime('%H:%M:%S')}] > {msg}")
        log_html = f"<div class='log-container'>{'<br>'.join(st.session_state.logs[::-1])}</div>"
        log_placeholder.markdown(log_html, unsafe_allow_html=True)

# --- EXECUTION ---
if start_btn:
    if not names_input:
        st.error("Please enter names first!")
    else:
        client = get_gspread_client()
        if client:
            try:
                df = pd.DataFrame(client.get_all_records()).fillna('')
                update_ui_logs(f"📊 Sheet Synced: {len(df)} records found.")

                names = [q.strip() for q in names_input.split(",")]
                targets = df[df['Driver Name'].apply(lambda x: any(name.lower() in str(x).lower() for name in names))].to_dict('records')

                if not targets:
                    update_ui_logs("⚠️ No driver found with those names.")
                else:
                    success_count = 0
                    failed_drivers = []
                    progress_bar = st.progress(0)

                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=headless_mode)
                        last_code_memory = ""
                        
                        for idx, row in enumerate(targets):
                            update_ui_logs(f"Processing: {row['Driver Name']}")
                            context = browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 720})
                            bot = DVLARobot(context)
                            p1 = context.new_page()
                            
                            try:
                                p1.goto("https://www.viewdrivingrecord.service.gov.uk/driving-record/licence-number")
                                p1.fill("#wizard_view_driving_licence_enter_details_driving_licence_number", str(row['licence number']))
                                p1.fill("#wizard_view_driving_licence_enter_details_national_insurance_number", str(row['NIN Number']))
                                p1.fill("#wizard_view_driving_licence_enter_details_post_code", str(row['Post code']))
                                p1.locator("input[type='checkbox']").check()
                                p1.click("#view-now")
                                
                                current_code = bot.solve_phase_1(p1, last_code_memory)
                                if current_code:
                                    last_code_memory = current_code
                                    if bot.solve_phase_2(row, current_code):
                                        success_count += 1
                                        update_ui_logs(f"✅ Success: {row['Driver Name']}")
                                    else: failed_drivers.append(row['Driver Name'])
                                else:
                                    update_ui_logs(f"❌ Code failed for: {row['Driver Name']}")
                                    failed_drivers.append(row['Driver Name'])
                            except Exception as e:
                                update_ui_logs(f"🚨 Error with {row['Driver Name']}: {str(e)[:50]}...")
                                failed_drivers.append(row['Driver Name'])
                            finally:
                                p1.close()
                                context.close()
                            
                            progress_bar.progress((idx + 1) / len(targets))
                        browser.close()

                    # Final Summary
                    st.markdown("---")
                    s1, s2 = st.columns(2)
                    with s1:
                        st.markdown(f"<div class='stats-card' style='border-left: 5px solid #10b981;'><h4 style='color: #10b981; margin:0;'>SUCCESSFUL</h4><h2 style='color: white; margin:0;'>{success_count}</h2></div>", unsafe_allow_html=True)
                    with s2:
                        st.markdown(f"<div class='stats-card' style='border-left: 5px solid #ef4444;'><h4 style='color: #ef4444; margin:0;'>FAILED</h4><h2 style='color: white; margin:0;'>{len(failed_drivers)}</h2></div>", unsafe_allow_html=True)
                    
                    if failed_drivers:
                        st.warning(f"Rechecked names: {', '.join(failed_drivers)}")

            except Exception as e:
                st.error(f"Main Process Error: {e}")
