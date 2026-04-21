import os
import re
import time
import random
import logging
import pandas as pd
import gspread
import streamlit as st
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DVLA_ROBOT")

# --- CONFIG ---
# Hugging Face par file ka naam wahi rakhein jo upload ki hai
JSON_PATH = "credentials.json" 
SHEET_URL = "https://docs.google.com/spreadsheets/d/1vO4Hs0FYu58dqzA-3MMr_Hpj10M-9RRsG5j0ZOxs1Yo/edit"
DOWNLOAD_BASE = "downloads"
os.makedirs(DOWNLOAD_BASE, exist_ok=True)

# Playwright installation command for Hugging Face
if 'playwright_installed' not in st.session_state:
    os.system("playwright install chromium")
    st.session_state['playwright_installed'] = True

# ==========================================================
# --- ORIGINAL FUNCTIONS (STRICTLY UNCHANGED) ---
# ==========================================================
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
        return 0, []

    names = [q.strip() for q in names_input.split(",")]
    targets = df[df['Driver Name'].apply(lambda x: any(n.lower() in x.lower() for n in names))].to_dict('records')

    if not targets:
        log_callback("⚠️ No driver found.")
        return 0, []

    failed_drivers = []
    success_count = 0

    with sync_playwright() as p:
        # Hugging Face par hamesha headless=True hota hai
        browser = p.chromium.launch(headless=True) 
        
        last_code_memory = ""
        for row in targets:
            log_callback(f"🚀 Processing: {row['Driver Name']}")
            context = browser.new_context(
                accept_downloads=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...",
                viewport={"width": 1366, "height": 768}
            )
            bot = DVLARobot(context)
            p1 = context.new_page()
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
                    if bot.solve_phase_2(row, current_code):
                        success_count += 1
                        log_callback(f"✅ Success: {row['Driver Name']}")
                    else:
                        failed_drivers.append(row['Driver Name'])
                else:
                    failed_drivers.append(row['Driver Name'])
            finally:
                p1.close()
                context.close()
        browser.close()
    return success_count, failed_drivers

# --- STREAMLIT UI ---
st.set_page_config(page_title="DSS DVLA", layout="wide")
st.title("DSS-RECRUITMENT DVLA GENERATOR")

names_in = st.text_area("Enter names", height=150)
if st.button("START"):
    log_area = st.empty()
    all_logs = []
    def upd(m):
        all_logs.append(f"> {m}")
        log_area.code("\n".join(all_logs))
    
    s, f = run_automation(names_in, upd)
    st.success(f"Done! Success: {s}")
