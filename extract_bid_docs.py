from playwright.sync_api import sync_playwright
import os
import shutil
import pyodbc
import logging
import sys

# ----------------------------------
# CONFIGURATION
# ----------------------------------
DB_CONFIG = {
    "server": "",
    "database": "",
    "username": "",
    "password": "",
    "driver": "{ODBC Driver 17 for SQL Server}"
}

LOGIN_CONFIG = {
    "login_url": "https://notices.philgeps.gov.ph/GEPSNONPILOT/log-in.aspx",
    "bid_notice_url": "https://notices.philgeps.gov.ph/GEPSNONPILOT/Tender/PrintableBidNoticeAbstractUI.aspx",
    "award_notice_url": "https://notices.philgeps.gov.ph/GEPSNONPILOT/Tender/printableAwardNoticeAbstractUI.aspx", # for non-electronic
    "assoc_comp_url": "https://notices.philgeps.gov.ph/GEPSNONPILOT/Tender/ViewNonElectronicAssocCompUI.aspx", # for non-electronic
    "bid_sup_url": "https://notices.philgeps.gov.ph/GEPSNONPILOT/Tender/BidSupplementViewUI.aspx", # for non-electronic
    "bid_sup_item_url": "https://notices.philgeps.gov.ph/GEPSNONPILOT/Tender/ViewNonElectronicAssocCompUI.aspx"
}

# ----------------------------------
# LOGGING
# ----------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ----------------------------------
# BASE DIRECTORY
# ----------------------------------
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

OUTPUT_DIR = os.path.join(BASE_DIR, "ExtractedBidDocs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Handle path resolution for bundled resources (PyInstaller)
def resource_path(relative_path):
    """Get absolute path to resource, works for .py and bundled .exe."""
    if getattr(sys, 'frozen', False):  # Running as compiled .exe
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)
    
BROWSER_PATH = resource_path("ms-playwright/chromium-1187/chrome-win/chrome.exe")

# Check browser existence
if not os.path.exists(BROWSER_PATH):
    logging.error(f"Chromium not found at {BROWSER_PATH}")
else:
    logging.info(f"Using Chromium from: {BROWSER_PATH}")
    
# ----------------------------------
# DATABASE CONNECTION
# ----------------------------------
def connect_db():
    try:
        conn_str = (
            f"DRIVER={DB_CONFIG['driver']};"
            f"SERVER={DB_CONFIG['server']};"
            f"DATABASE={DB_CONFIG['database']};"
            f"UID={DB_CONFIG['username']};"
            f"PWD={DB_CONFIG['password']}"
        )
        conn = pyodbc.connect(conn_str)
        logging.info("Connected to SQL Server")
        return conn
    except Exception as e:
        logging.error(f"Failed to connect: {e}")
        return None

# ----------------------------------
# FILE HELPERS
# ----------------------------------
def create_folder(path):
    if not os.path.exists(path):
        os.makedirs(path)
        logging.info(f"Created folder: {path}")
    return path

def copy_files(src_files, dest_folder, refid_folder):
    create_folder(dest_folder)
    for f in src_files:
        if os.path.exists(f):
            shutil.copy(f, dest_folder)
            logging.info(f"Copied {f} → {dest_folder}")
        else:
            logging.warning(f"File not found: {f}")
            with open(os.path.join(refid_folder, "IMPORTANT-NOTES.txt"), "a", encoding="utf-8") as file:
                file.write(f"File not found: {f}. Unable to copy to destination folder: {dest_folder}\n")
            
# ----------------------------------
# PLAYWRIGHT: LOGIN
# ----------------------------------
def login(p):
    """Logs in once and keeps the same page active."""

    browser = p.chromium.launch_persistent_context(
        user_data_dir=os.path.join(BASE_DIR, "user_data"),
        headless=True,
        executable_path=BROWSER_PATH
    )
    page = browser.new_page()

    logging.info(f"Navigating to ({LOGIN_CONFIG['login_url']})...")
    page.goto(LOGIN_CONFIG["login_url"])
    page.wait_for_load_state("networkidle")

    import getpass
    username = input("Enter PhilGEPS username: ").strip()
    password = getpass.getpass("Enter PhilGEPS password: ")

    logging.info(f"Logging in...")

    # Fill in login credentials (using name locators for reliability)
    page.fill('input[name="userName"]', username)
    page.fill('input[id="password"]', password)
    page.click('input[id="btnLogin"]')

    page.wait_for_load_state("networkidle")

    # Verify login success
    if "log-in" in page.url.lower():
        logging.error("Login failed. Check credentials or login field selectors.")
        browser.close()
        sys.exit(1)

    logging.info("Login successful.")
    return browser, page  # return page for reuse

# ----------------------------------
# SAVE PAGE AS PDF (Reuses Same Page)
# ----------------------------------
def save_page_as_pdf(page, refid, docid, bidsupid, docname, output_dir, type):
    pdf_path = ""

    try:
        if type == 'bid_notice':
            pdf_path = os.path.join(output_dir, f"{type}_abstract.pdf")
            target_url = f"{LOGIN_CONFIG['bid_notice_url']}?refid={refid}"
        elif type == 'award_notice':
            pdf_path = os.path.join(output_dir, f"{type}_abstract.pdf")
            target_url = f"{LOGIN_CONFIG['award_notice_url']}?awardID={refid}"
        elif type == 'assoc_comp':
            pdf_path = os.path.join(output_dir, f"{docid}.pdf")
            target_url = (
                f"{LOGIN_CONFIG['assoc_comp_url']}"
                f"?directFrom=&refId={refid}&DocId={docid}"
                f"&PageFrom=&OrgName=&OrgID=0"
                f"&linkFrom=&PreviousPageFrom=ViewBidNoticeAssocCompUI"
            )
        elif type == 'bid_sup':
            pdf_path = os.path.join(output_dir, f"{bidsupid}.pdf")
            target_url = (
                f"{LOGIN_CONFIG['bid_sup_url']}"
                f"?refId={refid}&bidSuppID={bidsupid}"
                f"&directFrom=BidAbstract"
            )
        else:
            pdf_path = os.path.join(output_dir, f"{bidsupid}_{docid}_{docname}.pdf")

            target_url = (
                f"{LOGIN_CONFIG['bid_sup_item_url']}"
                f"?refId={refid}&DocId={docid}&directFrom=BidAbstract&BidSupplID={bidsupid}"
            )

        logging.info(f"Navigating to {target_url}")
        page.goto(target_url, timeout=60000)
        page.wait_for_load_state("networkidle")

        # If still redirected to login, report error
        if "log-in" in page.url.lower():
            logging.error(f"Session expired or invalid for RefID {refid}. Still on login page.")
            return

        try:
            page.wait_for_selector('span[id="ctl01_nameLBL"]', timeout=5000)
            # Then safely remove it
            page.evaluate("""
                () => {
                    const element = document.querySelector('span[id="ctl01_nameLBL"]');
                    if (element) element.remove();
                }
            """)
            logging.info("Removed admin name from page before saving PDF.")
        except:
            logging.info("Admin name element not found, skipping removal.")

        # Save the PDF
        page.pdf(path=pdf_path, format="A4", print_background=True)
        logging.info(f"Saved PDF: {pdf_path}")

    except Exception as e:
        logging.error(f"Failed to save PDF for RefID {refid}: {e}")

# ----------------------------------
# PROCESS REFID
# ----------------------------------
def process_refid(refid, conn, page):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(1) FROM M_Tender WHERE refid = ?", refid)
    exists = cursor.fetchone()[0]

    if not exists:
        logging.error(f"RefID {refid} not found.")
        return False

    logging.info(f"Processing RefID {refid}...")

    refid_folder = create_folder(os.path.join(OUTPUT_DIR, str(refid)))

    # Bid Notice
    save_page_as_pdf(page, refid, '0', '0', '0', refid_folder, 'bid_notice')

    # Associated Components
    cursor.execute("""
        SELECT DocID, DocName, RefID, IsElectronic, DocPhyName
        FROM M_Document
        WHERE RefID = ?
          AND bidsuppid IS NULL
          AND (DocPhyName LIKE '%TenderDoc%')
    """, refid)

    bid_docs = cursor.fetchall()
    logging.info(f"Found {len(bid_docs)} Associated Component(s).")

    if bid_docs:
        assoc_folder = os.path.join(refid_folder, "Associated Components")
        for row in bid_docs:
            if row.IsElectronic == 1:
                file_path = rf"Z:\GEPS_Files\Tender\{row.DocPhyName}"
                copy_files([file_path], assoc_folder, refid_folder)
            else:
                logging.info(f"Non-electronic doc {row.DocID}: saving as PDF...")
                save_page_as_pdf(page, refid, row.DocID, '0', row.DocName, assoc_folder, 'assoc_comp')
    else:
        logging.info("No bid docs uploaded, skipping...")

# Step 4: Check bid supplements
    cursor.execute("""
        SELECT d.DocID, bs.BidSuppID, bs.BidSuppTitle, bs.Description, bs.Remarks, bs.CollectionContactID,
                bs.CollectionContact, bs.CollectionPoint, bs.SpecialInstruction,
                d.DocName, d.DocPhyName, d.IsElectronic 
        FROM M_BidSupplement bs 
        LEFT JOIN M_Document d 
            ON bs.BidSuppID = d.BidSuppID 
        WHERE bs.RefID = ?
    """, refid)

    bid_supplements = cursor.fetchall()
    
    logging.info(f"Found {len(bid_supplements)} item(s) under Bid Supplement. Downloading file(s)...")
    
    if bid_supplements:
        sup_folder = os.path.join(refid_folder, "Bid Supplements")
        for row in bid_supplements:
            if row.DocPhyName:  # checks if not NULL/empty
                file_path = os.path.join(r"Z:\GEPS_Files\BidSupp", row.DocPhyName)
                copy_files([file_path], sup_folder, refid_folder)
            else:
                logging.info(f"Non-electronic doc {row.BidSuppID}: saving as PDF...")
                save_page_as_pdf(page, refid, row.DocID, row.BidSuppID, row.DocName, sup_folder, 'bid_sup')

                if  all([row.CollectionContact, row.CollectionContactID, row.CollectionPoint, row.SpecialInstruction]):
                    logging.info(f"Non-electronic. Saving attachment of doc {row.BidSuppID} as PDF...")
                    save_page_as_pdf(page, refid, row.DocID, row.BidSuppID, row.DocName, sup_folder, 'bid_sup_item')
                    
                    # Check if any field contains a Google Drive link
                    if ("https://drive.google.com/" in str(row.Description)) or ("https://drive.google.com/" in str(row.Remarks)):
                        link = row.Description if "https://drive.google.com/" in str(row.Description) else row.Remarks
                        msg = (
                            f"Bid Supplement No. {row.BidSuppID} contains files stored in Google Drive.\n"
                            f"Please manually follow this link to download all available files:\n{link}\n"
                        )
                        with open(os.path.join(refid_folder, "IMPORTANT-NOTES.txt"), "a", encoding="utf-8") as file:
                            file.write(f"{msg}\n")
                            logging.info(f"Google Drive link found for Bid Supplement {row.BidSuppID}. Added to IMPORTANT-NOTES.txt.")

        logging.info("Finished processing bid supplements.")
    else:
        logging.info("No bid supplements uploaded. Skipping...")

    # Award Notice
    cursor.execute("SELECT TenderStatus FROM M_Tender WHERE RefID = ?", refid)
    row = cursor.fetchone()
    if row and row[0] in ("Closed", "Awarded"):
        cursor.execute("SELECT AwardID FROM M_Award WHERE RefID = ?", refid)
        awards = cursor.fetchall()
        if awards:
            award_folder = os.path.join(refid_folder, "Award")
            create_folder(award_folder)
            for award in awards:
                award_id = award[0]
                sub_folder = os.path.join(award_folder, str(award_id))
                create_folder(sub_folder)
                save_page_as_pdf(page, award_id, '0', '0', '0', sub_folder, 'award_notice')

                cursor.execute("""
                    SELECT rf.ServerFileName, rf.ServerPath
                    FROM R4_AwardNotice_AwardDoc ad
                    JOIN R3_File rf ON ad.FileID = rf.FileID
                    WHERE AwardID = ?
                """, award_id)

                award_item_files = cursor.fetchall()
                
                logging.info(f"Found {len(award_item_files)} file(s) under AwardID {award_id}. Downloading file(s)...")

                for file_row in award_item_files:
                    server_file, server_path = file_row
                    file_path = os.path.join(r"Z:\Fileserver\R3FileServer", server_path, server_file)
                    copy_files([file_path], sub_folder, refid_folder)  # copy into award subfolder
                
                logging.info("Finished processing award documents.")
    else:
        logging.info(f'Bid status is "{row[0]}". Skipping award processing...')

    logging.info(f"Completed processing RefID {refid}.")
    return True

# ----------------------------------
# MAIN
# ----------------------------------
if __name__ == "__main__":

    conn = connect_db()
    if not conn:
        sys.exit(1)

    with sync_playwright() as p:
        browser, page = login(p)

        while True:
            refid_input = input("Enter RefID (or press Enter to exit): ").strip()
            if not refid_input:
                try:
                    page.goto("https://notices.philgeps.gov.ph/GEPSNONPILOT/LogoutRedirect.aspx")
                    page.wait_for_load_state("networkidle")
                    logging.info("Logout successful.")
                except Exception as e:
                    logging.warning(f"Unable to log out: {e}")
                
                logging.info("Exiting program.")
                break

            process_refid(refid_input, conn, page)

        browser.close()
        conn.close()
