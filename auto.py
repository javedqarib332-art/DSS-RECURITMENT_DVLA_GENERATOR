from playwright.sync_api import sync_playwright
import os
import base64

# --- Details ---
LICENSE = "SUTA9811269S99HZ"
NIN = "SZ418208A"
POSTCODE = "LU1 5NF"
LICENSE_LAST8 = LICENSE[-8:]


def run():
    with sync_playwright() as p:
        print("🚀 DVLA Full-Auto Agent Starting...")

        # Browser launch
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()

        # --- TAB 1: Login & Get Code ---
        page1 = context.new_page()
        try:
            print("📥 Tab 1: Logging in and generating code...")
            page1.goto("https://www.viewdrivingrecord.service.gov.uk/driving-record/licence-number")
            page1.fill("#wizard_view_driving_licence_enter_details_driving_licence_number", LICENSE)
            page1.fill("#wizard_view_driving_licence_enter_details_national_insurance_number", NIN)
            page1.fill("#wizard_view_driving_licence_enter_details_post_code", POSTCODE)
            page1.check("#wizard_view_driving_licence_enter_details_data_sharing_confirmation")
            page1.click("#view-now")

            # Share Code generate karne ka process
            page1.wait_for_selector("#share-licence-tab")
            page1.click("#share-licence-tab")
            page1.click("#get-a-code")

            # Code extract karna
            page1.wait_for_selector(".share-code-value")
            share_code = page1.inner_text(".share-code-value").strip()
            print(f"✅ Code Generated: {share_code}")

            # --- TAB 2: Validation & Auto-Fill ---
            print("🌐 Tab 2: Navigating to Validation page...")
            page2 = context.new_page()
            page2.goto("https://www.viewdrivingrecord.service.gov.uk/lang/en/driving-record/validate")

            # Last 8 digits fill karna (Pehle box mein)
            print(f"✍️ Filling last 8 digits: {LICENSE_LAST8}")
            page2.fill("#wizard_check_driving_licence_validate_details_last_eight_characters_driving_licence_number",
                       LICENSE_LAST8)

            # Share code fill karna
            page2.fill("#wizard_check_driving_licence_validate_details_share_code", share_code)

            # Click Check
            page2.click("#check-licence")

            # Wait for summary to load (Green boxes)
            print("⏳ Waiting for summary page to load...")
            page2.wait_for_selector(".driving-licence-summary", timeout=15000)

            # Extra wait taake images/style load ho jayein
            page2.wait_for_load_state("networkidle")

            # --- PDF Capture ---
            print("📄 Generating high-quality PDF...")
            save_path = os.path.join(os.getcwd(), f"{LICENSE_LAST8}_Auto_Summary.pdf")

            cdp_session = context.new_cdp_session(page2)
            pdf_data = cdp_session.send("Page.printToPDF", {
                "printBackground": True,
                "preferCSSPageSize": True,
                "displayHeaderFooter": False,
                "scale": 1  # 100% scale for clarity
            })

            with open(save_path, "wb") as f:
                f.write(base64.b64decode(pdf_data["data"]))

            print("\n" + "=" * 40)
            print(f"🔥 MISSION SUCCESS! File saved: {save_path}")
            print("=" * 40)

        except Exception as e:
            print(f"\n❌ Error: {e}")

        finally:
            print("\nBrowser 5 seconds mein band ho jayega...")
            page1.wait_for_timeout(5000)
            browser.close()


if __name__ == "__main__":
    run()