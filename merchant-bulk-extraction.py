import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import sv_ttk
from playwright.sync_api import sync_playwright
import os, shutil, pyodbc, logging, sys, threading, getpass
import queue
from queue import Empty
import time
import traceback
import re
from tkinter import filedialog

log_buffer = []
last_log_time = time.time()

completed_counter = 1
counter_lock = threading.Lock()
folder_lock = threading.Lock()

browser_context = None
page = None

# -------------------------------
# APP CONFIG
# -------------------------------
DB_CONFIG = {
    "server": "13.76.134.173",
    "database": "GEPSDB",
    "username": "gepsdb",
    "password": "$dmd123",
    "driver": "{ODBC Driver 17 for SQL Server}"
}

GEPS_URL = {
    "login_url": "https://notices.philgeps.gov.ph/GEPSNONPILOT/log-in.aspx",
    "bid_notice_url": "https://notices.philgeps.gov.ph/GEPSNONPILOT/Tender/PrintableBidNoticeAbstractUI.aspx",
    "award_notice_url": "https://notices.philgeps.gov.ph/GEPSNONPILOT/Tender/printableAwardNoticeAbstractUI.aspx",
    "assoc_comp_url": "https://notices.philgeps.gov.ph/GEPSNONPILOT/Tender/ViewNonElectronicAssocCompUI.aspx",
    "bid_sup_url": "https://notices.philgeps.gov.ph/GEPSNONPILOT/Tender/BidSupplementViewUI.aspx",
    "bid_sup_item_url": "https://notices.philgeps.gov.ph/GEPSNONPILOT/Tender/ViewNonElectronicAssocCompUI.aspx"
}

# -------------------------------
# LOGGING
# -------------------------------


if getattr(sys, 'frozen', False):
    # Running as a frozen EXE (release build)
    logging.basicConfig(filename='app.log', level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s')
else:
    # Running as a .py script (dev mode)
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s')
# -------------------------------
# PATH SETUP
# -------------------------------
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

OUTPUT_DIR = None
selected_root_folder = None

from tkinter import filedialog

def select_output_folder():
    global OUTPUT_DIR, selected_root_folder

    folder = filedialog.askdirectory(
        title="Select Destination Folder"
    )

    if not folder:
        return  # user cancelled

    OUTPUT_DIR = os.path.abspath(folder)
    selected_root_folder = OUTPUT_DIR

    log_message(f"📁 Output folder selected: {OUTPUT_DIR}")

def resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

BROWSER_PATH = resource_path("ms-playwright/chromium-1187/chrome-win/chrome.exe")

# -------------------------------
# DB CONNECTION
# -------------------------------
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
        #logging.info("Connected to SQL Server ✅")
        return conn
    except Exception as e:
        logging.error(f"Database connection failed: {e}")
        return None

# ----------------------------------
# FILE HELPERS
# ----------------------------------
def create_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
        # log_message(f"Created folder: {path}")
    except Exception as e:
        logging.warning(f"⚠️ Failed to create folder {path}: {e}")
    return path

def sanitize_path(path):
    # Only sanitize destination parts, not drive letters
    return re.sub(r'[<>:"/\\|?*]', "_", path)

def copy_files(src_files, dest_folder, refid_folder):
    create_folder(dest_folder)
    
    for f in src_files:
        if os.path.exists(f):
            try:
                # Keep the source as is (don't sanitize!)
                abs_src = os.path.abspath(f)

                # Only sanitize destination
                safe_dest = os.path.abspath(dest_folder)

                # Add \\?\ prefix for long path support (Windows only)
                if os.name == "nt":
                    abs_src = f"\\\\?\\{abs_src}"
                    safe_dest = f"\\\\?\\{safe_dest}"

                shutil.copy(abs_src, safe_dest)

            except Exception as e:
                logging.error(f"Failed to copy {f} → {dest_folder}: {e}")
                with open(os.path.join(refid_folder, "IMPORTANT-NOTES.txt"), "a", encoding="utf-8") as file:
                    file.write(f"Failed to copy {f}: {e}\n")

        else:
            with open(os.path.join(refid_folder, "IMPORTANT-NOTES.txt"), "a", encoding="utf-8") as file:
                file.write(f"File not found: {f}. Unable to copy to destination folder: {dest_folder}\n")

# -------------------------------
# LOG BOX HANDLER
# -------------------------------
def log_message(msg):
    global last_log_time
    log_buffer.append(msg)
    
    # schedule flush in main thread
    if 'root' in globals():  # ensure root exists
        root.after(0, flush_logs)
    
    # update last_log_time for throttling (optional)
    last_log_time = time.time()

def flush_logs():
    if not log_buffer:
        return
    
    # If GUI isn't ready yet, skip
    if 'log_box' not in globals():
        log_buffer.clear()
        return

    log_box.configure(state="normal")
    for msg in log_buffer:
        log_box.insert(tk.END, f"{msg}\n")
    log_box.configure(state="disabled")
    log_box.see(tk.END)
    log_buffer.clear()


# -------------------------------
# EXTRACTION LOGIC
# -------------------------------

task_queue = queue.Queue()
pdf_task_queue = queue.Queue()

def run_extraction():
    
    merchant_org_id = merchant_org_var.get().strip()
    year = year_var.get()
    status = status_var.get()
    include_bid_notice=include_bid_notice_var.get()
    include_assoc = include_assoc_var.get()
    include_supp = include_supp_var.get()
    include_award_notice=include_award_notice_var.get()
    include_award = include_award_var.get()

    if not OUTPUT_DIR:
        messagebox.showwarning(
            "Destination Required",
            "Please select a folder destination before running extraction."
        )
        run_button.config(state="normal")
        return

    # Show the progress bar
    #progress.pack(pady=5)
    #progress.start(10)  # speed; smaller = faster animation

    # Disable the Run button while processing
    run_button.config(state="disabled")

    if not merchant_org_id:
        messagebox.showwarning("Missing Input", "Please enter a Merchant Org ID.")
        return
    
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("SELECT OrgName FROM M_Organization WHERE OrgID = ?", merchant_org_id)
    merchant_name = cursor.fetchone()

    conn.close()
    
    log_message(f"🔍 Fetching data for Merchant {merchant_name.OrgName}, Year {year}, Status {status}")
    threading.Thread(
        target=fetch_refids_thread,
        args=(merchant_org_id, status, year, include_bid_notice, include_assoc, include_supp, include_award_notice, include_award),
        daemon=True
    ).start()

def login_philgeps(user_data_dir, stop_event):
    global browser_context, page

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser_context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=True,
            executable_path=BROWSER_PATH
        )
        page = browser_context.new_page()
        page.goto(GEPS_URL["login_url"], timeout=32000)
        page.wait_for_load_state("networkidle")

        # Auto-login...
        if "log-in" in page.url.lower():
            log_message("Logging in. Please wait...")
            page.fill('input[name="userName"]', user_credentials["username"])
            page.fill('input[id="password"]', user_credentials["password"])
            page.click('input[id="btnLogin"]', timeout=32000)
            page.wait_for_load_state("networkidle")

            if "log-in" in page.url.lower():
                log_message("❌ Login failed! Check credentials.")
                browser_context.close()
                return

            # Wait for a known post-login element (change selector as needed)
            #page.wait_for_selector('span[id="ctl01_nameLBL"]', timeout=60000)

            log_message("✅ Login successful.")
            root.after(0, lambda: run_button.config(state="normal"))

        while not stop_event.is_set():
            try:
                task_type, args = pdf_task_queue.get(timeout=1)
                if task_type == "save_pdf":
                    save_page_as_pdf(page, *args)
                elif task_type == "logout":
                    #log_message("Logging out...")
                    page.goto("https://notices.philgeps.gov.ph/GEPSNONPILOT/LogoutRedirect.aspx", wait_until="load")
                    log_message("✅ Logged out successfully.")
                    break
                pdf_task_queue.task_done()
            except Empty:
                # no task right now → just continue quietly
                continue
            except Exception as e:
                logging.error(f"Playwright worker task failed: {e}\n{traceback.format_exc()}")
                time.sleep(1)

        # when stop_event is set
        try:
            browser_context.close()
        except:
            pass

def playwright_thread(page, stop_worker):
    while not stop_worker.is_set():
        try:
            task_type, args = pdf_task_queue.get(timeout=1)
            if task_type == "save_pdf":
                save_page_as_pdf(page, *args)
            pdf_task_queue.task_done()
        except Empty:
            continue
        except Exception as e:
            logging.error(f"Worker task failed: {e}")
        

def fetch_refids_thread(merchant_org_id, status, year, include_bid_notice, include_assoc, include_supp, include_award_notice, include_award):
    conn = connect_db()
    cursor = conn.cursor()
  
    cursor.execute("""
        SELECT DISTINCT t.RefID, t.TenderStatus FROM M_Tender t
        LEFT JOIN M_Award a ON t.RefID = a.RefID
        LEFT JOIN D_AwardAwardee aa ON a.AwardID=aa.AwardID
        LEFT JOIN M_Organization o ON aa.AwardeeID = o.OrgID
        WHERE o.OrgID = ? AND aa.AwardDate LIKE ?
        AND (t.TenderStatus LIKE '%awarded%' OR t.TenderStatus LIKE '%closed%')
        AND a.AwardStatusid IN ('2','3','6')
    """, (merchant_org_id, f"%{year}%"))

    bids = cursor.fetchall()

    log_message(f"✅ Found {len(bids)} record(s). Extracting files...")

    #if not include_bid_notice:
        #log_message("Skipping bid notice abstract (option not selected).")
    
    #if not include_assoc:
        #log_message("Skipping associated docs (option not selected).")
    
    #if not include_supp:
        #log_message("Skipping bid supplements (option not selected).")
    
    #if not include_award_notice:
        #log_message("Skipping award notice abstract (option not selected).")
    
    #if not include_award:
        #log_message("Skipping award documents (option not selected).")

    for idx, row in enumerate(bids, start=1):
        refid = row.RefID
        tender_status = row.TenderStatus
        #log_message(f"[{idx}/{len(bids)}] Queuing Bid Ref. No. {refid}...")
        task_queue.put((refid, tender_status, include_bid_notice, include_assoc, include_supp, include_award_notice, include_award, idx, len(bids)))

    conn.close()

    # wait for all tasks to finish
    def monitor_queue():
        global completed_counter
        if task_queue.unfinished_tasks == 0 and pdf_task_queue.unfinished_tasks == 0:
            log_message(f"Extraction Complete!")
            completed_counter = 1
            root.after(0, lambda: [
                #progress.stop(),
                #progress.pack_forget(),
                run_button.config(state="normal"),
                messagebox.showinfo("Extraction Complete", "✅ Data extraction is finished successfully!")
            ])
        else:
            root.after(500, monitor_queue)  # check again after 0.5s

    monitor_queue()
    
def process_queue():
    try:
        refid, tender_status, include_bid_notice, include_assoc, include_supp, include_award_notice, include_award, idx, len_bids = task_queue.get_nowait()

        def worker():
            try:
                process_refid(refid, tender_status, include_bid_notice, include_assoc, include_supp, include_award_notice, include_award, idx, len_bids)
            finally:
                task_queue.task_done()  # mark task complete even if error occurs

        threading.Thread(target=worker, daemon=True).start()

    except Empty:
        pass

    root.after(500, process_queue)

# ----------------------------------
# PROCESS REFID
# ----------------------------------
def process_refid(refid, tender_status, include_bid_notice, include_assoc, include_supp, include_award_notice, include_award, idx, len_bids):
    # create a local DB connection for thread-safety
    conn = connect_db()

    if not conn:
        log_message(f"DB connection failed for RefID {refid}. Skipping.")
        return

    global completed_counter

    #log_message(f"Processing Bid Ref. No. {refid}.")

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(1) FROM M_Tender WHERE refid = ?", refid)
        exists = cursor.fetchone()[0]

        refid_folder = create_folder(os.path.join(OUTPUT_DIR, str(refid)))

        if include_bid_notice:
            # enqueue PDF tasks on the GLOBAL pdf_task_queue (do NOT shadow it)
            pdf_task_queue.put(("save_pdf", (refid, '0', '0', '0', refid_folder, 'bid_notice')))
            #log_message(f"Enqueued bid_notice PDF task for RefID {refid}.")

        if include_assoc:
            # Associated Components
            cursor.execute("""
                SELECT DocID, DocName, RefID, IsElectronic, DocPhyName
                FROM M_Document
                WHERE RefID = ?
                AND bidsuppid IS NULL
                AND (DocPhyName LIKE '%TenderDoc%')
            """, refid)

            bid_docs = cursor.fetchall()
            #log_message(f"Found {len(bid_docs)} Associated Component(s).")

            if bid_docs:
                assoc_folder = os.path.join(refid_folder, "Associated Components")
                for row in bid_docs:
                    if row.IsElectronic == 1:
                        file_path = rf"Z:\GEPS_Files\Tender\{row.DocPhyName}"
                        copy_files([file_path], assoc_folder, refid_folder)
            else:
                cursor.execute("""
                    SELECT DocID, DocName, RefID, IsElectronic, DocPhyName
                    FROM M_Document
                    WHERE RefID = ?
                    AND bidsuppid IS NULL
                    AND IsElectronic = 0
                """, refid)

                ne_bid_docs = cursor.fetchall()

                if ne_bid_docs:
                    assoc_folder = os.path.join(refid_folder, "Associated Components")
                    for row in ne_bid_docs:
                        #log_message(f"Non-electronic doc {row.DocID}: saving as PDF...")
                        pdf_task_queue.put(("save_pdf", (refid, row.DocID, '0', row.DocName, assoc_folder, 'assoc_comp')))
                        #log_message(f"Enqueued assoc_comp PDF for DocID {row.DocID}.")

        # Bid supplements
        if include_supp:
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
            #log_message(f"Found {len(bid_supplements)} item(s) under Bid Supplement. Downloading file(s)...")

            if bid_supplements:
                sup_folder = os.path.join(refid_folder, "Bid Supplements")
                for row in bid_supplements:
                    if row.DocPhyName:  # checks if not NULL/empty
                        file_path = os.path.join(r"Z:\GEPS_Files\BidSupp", row.DocPhyName)
                        copy_files([file_path], sup_folder, refid_folder)
                    else:
                        #log_message(f"Non-electronic doc {row.BidSuppID}: saving as PDF...")
                        pdf_task_queue.put(("save_pdf", (refid, row.DocID, row.BidSuppID, row.DocName, sup_folder, 'bid_sup')))
                        #log_message(f"Enqueued bid_sup PDF for BidSuppID {row.BidSuppID}.")

                        if all([row.CollectionContact, row.CollectionContactID, row.CollectionPoint, row.SpecialInstruction]):
                            #log_message(f"Non-electronic. Saving attachment of doc {row.BidSuppID} as PDF...")
                            pdf_task_queue.put(("save_pdf", (refid, row.DocID, row.BidSuppID, row.DocName, sup_folder, 'bid_sup_item')))
                            #log_message(f"Enqueued bid_sup_item PDF for BidSuppID {row.BidSuppID}.")

                            # Check if any field contains a Google Drive link
                            if ("https://drive.google.com/" in str(row.Description)) or ("https://drive.google.com/" in str(row.Remarks)):
                                link = row.Description if "https://drive.google.com/" in str(row.Description) else row.Remarks
                                msg = (
                                    f"Bid Supplement No. {row.BidSuppID} contains files stored in Google Drive.\n"
                                    f"Please manually follow this link to download all available files:\n{link}\n"
                                )
                                with open(os.path.join(refid_folder, "IMPORTANT-NOTES.txt"), "a", encoding="utf-8") as file:
                                    file.write(f"{msg}\n")
                                #log_message(f"Google Drive link found for Bid Supplement {row.BidSuppID}. Added to IMPORTANT-NOTES.txt.")
                #log_message("Finished processing bid supplements.")
            #else:
                #log_message("No bid supplements uploaded. Skipping...")

        # Awards (same pattern)
        if include_award:
            if tender_status in ("Closed", "Awarded"):
                cursor.execute("SELECT AwardID FROM M_Award WHERE RefID = ?", refid)
                awards = cursor.fetchall()
                if awards:
                    award_folder = os.path.join(refid_folder, "Award")
                    create_folder(award_folder)
                    for award in awards:
                        award_id = award[0]
                        sub_folder = os.path.join(award_folder, str(award_id))
                        create_folder(sub_folder)

                        cursor.execute("""
                            SELECT rf.ServerFileName, rf.ServerPath
                            FROM R4_AwardNotice_AwardDoc ad
                            JOIN R3_File rf ON ad.FileID = rf.FileID
                            WHERE AwardID = ?
                        """, award_id)

                        award_item_files = cursor.fetchall()
                        
                        #log_message(f"Found {len(award_item_files)} file(s) under AwardID {award_id}. Downloading file(s)...")

                        for file_row in award_item_files:
                            server_file, server_path = file_row
                            file_path = os.path.join(r"Z:\Fileserver\R3FileServer", server_path, server_file)
                            copy_files([file_path], sub_folder, refid_folder)  # copy into award subfolder
                        
                        #log_message("Finished processing award documents.")
            #else:
                #if row:
                    #log_message(f'Bid status is "{row[0]}". Skipping award processing...')
                #else:
                    #log_message("No tender row found; skipping award processing.")

        # Awards (same pattern)
        if include_award_notice:
            if tender_status in ("Closed", "Awarded"):
                cursor.execute("SELECT AwardID FROM M_Award WHERE RefID = ?", refid)
                awards = cursor.fetchall()
                if awards:
                    award_folder = os.path.join(refid_folder, "Award")
                    create_folder(award_folder)
                    for award in awards:
                        award_id = award[0]
                        sub_folder = os.path.join(award_folder, str(award_id))
                        create_folder(sub_folder)
                        
                        pdf_task_queue.put(("save_pdf", (award_id, '0', '0', '0', sub_folder, 'award_notice')))
                            #log_message(f"Enqu eued award_notice PDF for AwardID {award_id}.")
                        
                        #log_message("Finished processing award documents.")
            #else:
                #if row:
                    #log_message(f'Bid status is "{row[0]}". Skipping award processing...')
                #else:
                    #log_message("No tender row found; skipping award processing.")

        with counter_lock:
            sequence = completed_counter
            completed_counter += 1

        log_message(f"[{sequence}/{len_bids}] Completed processing RefID {refid}.")
        if sequence == len_bids:
            log_message("All RefIDs processed successfully. Finalizing tasks...")
        root.after(100, flush_logs)
    
    except Exception as e:
        logging.exception(f"Error processing RefID {refid}: {e}")
        log_message(f"❌ Error processing RefID {refid}: {e}")
        with open(os.path.join(refid_folder, "IMPORTANT-NOTES.txt"), "a", encoding="utf-8") as file:
            traceback.print_exc(file=file)
    finally:
        try:
            conn.close()
        except:
            pass
# ----------------------------------
# SAVE PAGE AS PDF (Reuses Same Page)
# ----------------------------------
def save_page_as_pdf(page, refid, docid, bidsupid, docname, output_dir, type):
    pdf_path = ""

    try:
        if type == 'bid_notice':
            pdf_path = os.path.join(output_dir, f"{type}_abstract.pdf")
            target_url = f"{GEPS_URL['bid_notice_url']}?refid={refid}"
        elif type == 'award_notice':
            pdf_path = os.path.join(output_dir, f"{type}_abstract.pdf")
            target_url = f"{GEPS_URL['award_notice_url']}?awardID={refid}"
        elif type == 'assoc_comp':
            pdf_path = os.path.join(output_dir, f"{docid}.pdf")
            target_url = (
                f"{GEPS_URL['assoc_comp_url']}"
                f"?directFrom=&refId={refid}&DocId={docid}"
                f"&PageFrom=&OrgName=&OrgID=0"
                f"&linkFrom=&PreviousPageFrom=ViewBidNoticeAssocCompUI"
            )
        elif type == 'bid_sup':
            pdf_path = os.path.join(output_dir, f"{bidsupid}.pdf")
            target_url = (
                f"{GEPS_URL['bid_sup_url']}"
                f"?refId={refid}&bidSuppID={bidsupid}"
                f"&directFrom=BidAbstract"
            )
        else:
            pdf_path = os.path.join(output_dir, f"{bidsupid}_{docid}.pdf")

            target_url = (
                f"{GEPS_URL['bid_sup_item_url']}"
                f"?refId={refid}&DocId={docid}&directFrom=BidAbstract&BidSupplID={bidsupid}"
            )

        #log_message(f"Navigating to {target_url}")
        page.goto(target_url, timeout=32000)
        page.wait_for_load_state("networkidle")

        # If still redirected to login, report error
        if "log-in" in page.url.lower():
            msg = (f"Session Expired: Saving PDF failed for {target_url}. Page was redirected to the login page.")
            logging.error(msg)

            refid_dir = os.path.join(OUTPUT_DIR, str(refid))
            os.makedirs(refid_dir, exist_ok=True)

            with open(os.path.join(refid_dir, "IMPORTANT-NOTES.txt"), "a", encoding="utf-8") as file:
                file.write(msg + "\n")

        if type not in ('bid_notice', 'award_notice'):
            try:
                page.wait_for_selector('span[id="ctl01_nameLBL"]', timeout=32000)
                # Then safely remove it
                page.evaluate("""
                    () => {
                        const element = document.querySelector('span[id="ctl01_nameLBL"]');
                        if (element) element.remove();
                    }
                """)
                #logging.info("Removed admin name from page before saving PDF.")
            except:
                logging.info("Admin name element not found, skipping removal.")

        # Save the PDF
        page.wait_for_load_state("networkidle", timeout=32000)
        page.pdf(path=pdf_path, format="A4", print_background=True)
        #log_message(f"Saved PDF: {pdf_path}")

    except Exception as e:
        refid_dir = os.path.join(OUTPUT_DIR, str(refid))
        logging.error(f"Failed to save PDF for RefID {refid}: {e}")
        os.makedirs(refid_dir, exist_ok=True) 
        with open(os.path.join(refid_dir, "IMPORTANT-NOTES.txt"), "a", encoding="utf-8") as file:
            file.write(f"Failed to save PDF for RefID {refid}: {e}\n")

# -------------------------------
# LOGIN POPUP (Tkinter)
# -------------------------------
def login_window():
    def submit_login():
        global user_credentials
        user_credentials = {
            "username": username_var.get().strip(),
            "password": password_var.get().strip()
        }
        if not user_credentials["username"] or not user_credentials["password"]:
            messagebox.showwarning("Missing Info", "Please enter both username and password.")
            return
        login_win.destroy()

    login_win = tk.Tk()
    login_win.title("PhilGEPS Login")
    login_win.geometry("400x250")
    login_win.resizable(False, False)

    # Title
    ttk.Label(login_win, text="PhilGEPS Login", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=2, pady=15)

    # Variables
    username_var = tk.StringVar()
    password_var = tk.StringVar()

    # Username
    ttk.Label(login_win, text="Username:").grid(row=1, column=0, sticky="e", padx=10, pady=8)
    ttk.Entry(login_win, textvariable=username_var, width=30).grid(row=1, column=1, sticky="w", padx=10, pady=8)

    # Password
    ttk.Label(login_win, text="Password:").grid(row=2, column=0, sticky="e", padx=10, pady=8)
    ttk.Entry(login_win, textvariable=password_var, show="*", width=30).grid(row=2, column=1, sticky="w", padx=10, pady=8)

    # Login button
    ttk.Button(login_win, text="Login", command=submit_login).grid(row=3, column=0, columnspan=2, pady=20)

    # Center alignment
    login_win.grid_columnconfigure(0, weight=1)
    login_win.grid_columnconfigure(1, weight=1)
    
    login_win.mainloop()

# -------------------------------
# LOGOUT HANDLER
# -------------------------------
import requests

def logout_and_exit(root):
    global stop_worker

    log_message("🚪 Logging out... please wait.")
    try:
        # 1️⃣ Signal the worker to log out through Playwright
        pdf_task_queue.put(("logout", []))

        # 2️⃣ Give it a moment to complete
        time.sleep(2)

        # 3️⃣ Stop the worker thread
        stop_worker.set()

        # 4️⃣ Optional: remove local session data
        user_data_dir = os.path.join(os.path.expanduser("~"), "PhilGEPS_Session")
        if os.path.exists(user_data_dir):
            shutil.rmtree(user_data_dir, ignore_errors=True)
            log_message("🗑️ Local session data removed.")
    except Exception as e:
        logging.error(f"Logout failed: {e}")
    finally:
        log_message("✅ Logged out successfully. Exiting app.")
        try:
            root.destroy()
        except:
            os._exit(0)

def on_close():
    if messagebox.askokcancel("Exit", "Are you sure you want to close the app?"):
        threading.Thread(target=logout_and_exit, args=(root,), daemon=True).start()

# -------------------------------
# GUI
# -------------------------------
def open_main_window(conn, page):
    global merchant_org_var, year_var, status_var, log_box, include_assoc_var, include_supp_var, include_award_var, include_award_notice_var, include_bid_notice_var, run_button, progress

    title_label = ttk.Label(root, text="PhilGEPS BID Document Extraction Tool", font=("Segoe UI", 14, "bold"))
    title_label.pack(pady=10)

    merchant_frame = ttk.Frame(root)
    merchant_frame.pack(pady=5, padx=20, fill="x")
    ttk.Label(merchant_frame, text="Merchant Org ID:").pack(side="left", padx=5)
    merchant_org_var = tk.StringVar()
    ttk.Entry(merchant_frame, textvariable=merchant_org_var, width=40).pack(side="left", padx=5)
    ttk.Button(merchant_frame, text="📂 Select Folder", command=select_output_folder).pack(side="left", padx=5)

    filter_frame = ttk.LabelFrame(root, text="Filters")
    filter_frame.pack(fill="x", padx=20, pady=10)
    status_var = tk.StringVar(value="Awarded")
    year_var = tk.StringVar(value="2025")
    ttk.Label(filter_frame, text="Status:").grid(row=0, column=0, padx=10, pady=5)
    ttk.Combobox(filter_frame, values="Awarded", textvariable=status_var, state="readonly", width=15).grid(row=0, column=1, padx=10, pady=5)
    ttk.Label(filter_frame, text="Year:").grid(row=0, column=2, padx=10, pady=5)
    ttk.Combobox(filter_frame, textvariable=year_var, values=[str(y) for y in range(2015, 2026)], state="readonly", width=10).grid(row=0, column=3, padx=10, pady=5)

    doc_frame = ttk.LabelFrame(root, text="Document Types")
    doc_frame.pack(fill="x", padx=20, pady=5)

    include_bid_notice_var = tk.BooleanVar(value=True)
    include_assoc_var = tk.BooleanVar(value=True)
    include_supp_var = tk.BooleanVar(value=True)
    include_award_notice_var = tk.BooleanVar(value=True)
    include_award_var = tk.BooleanVar(value=True)

    ttk.Checkbutton(doc_frame, text="Bid Notice", variable=include_bid_notice_var).grid(row=0, column=0, sticky="w", padx=10, pady=3)
    ttk.Checkbutton(doc_frame, text="Associated Docs", variable=include_assoc_var).grid(row=0, column=1, sticky="w", padx=10, pady=3)
    ttk.Checkbutton(doc_frame, text="Bid Supplements", variable=include_supp_var).grid(row=0, column=2, sticky="w", padx=10, pady=3)
    ttk.Checkbutton(doc_frame, text="Award Notice", variable=include_award_notice_var).grid(row=0, column=3, sticky="w", padx=10, pady=3)
    ttk.Checkbutton(doc_frame, text="Award Docs", variable=include_award_var).grid(row=0, column=4, sticky="w", padx=10, pady=3)

    run_button = ttk.Button(root, text="🚀 Run Extraction", command=run_extraction, state="disabled")
    run_button.pack(pady=10)
 
    #progress = ttk.Progressbar(root, orient="horizontal", mode="indeterminate", length=250)
    #progress.pack(pady=5)
    #progress.pack_forget()  # hide it initially

    log_frame = ttk.LabelFrame(root, text="Logs")
    log_frame.pack(fill="both", expand=True, padx=20, pady=10)
    log_box = scrolledtext.ScrolledText(log_frame, height=18, wrap=tk.WORD, state="disabled", font=("Consolas", 9))
    log_box.pack(fill="both", expand=True)

    ttk.Label(root, text="PhilGEPS EGPOD", font=("Segoe UI", 8, "italic")).pack(pady=5)
    root.title("PhilGEPSBidDocsExtractor_v1")

# -------------------------------
# MAIN
# -------------------------------
if __name__ == "__main__":
    # don't create a single conn to be shared — threads will open their own when needed
    # conn = connect_db()  # remove sharing across threads

    user_credentials = {}
    login_window()  # waits until user submits

    USER_DATA_DIR = os.path.join(os.path.expanduser("~"), "PhilGEPS_Session")
    os.makedirs(USER_DATA_DIR, exist_ok=True)

    stop_worker = threading.Event()
    worker = threading.Thread(target=login_philgeps, args=(USER_DATA_DIR, stop_worker), daemon=True)
    worker.start()

    # start GUI (root) in main thread
    root = tk.Tk()
    
    open_main_window(None, None)  # adjust your open_main_window signature if needed

    root.protocol("WM_DELETE_WINDOW", on_close)

    # process_queue should create new threads that call process_refid(refid, ...)
    # make sure process_queue uses the new process_refid signature (no conn argument)
    process_queue()

    root.mainloop()

    # when exiting:
    stop_worker.set()
    worker.join(timeout=5)
