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

# Detect folder where the script/exe is located
if getattr(sys, 'frozen', False):  
    # If running as a compiled .exe
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # If running as a .py script
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Then put your subfolder there
BASE_DIR = os.path.join(BASE_DIR, "ExtractedBidDocs")

# Make sure it exists
os.makedirs(BASE_DIR, exist_ok=True)

# ----------------------------------
# LOGGING FORMAT
# ----------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

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
# FILE 
# ----------------------------------
def create_folder(path):
    if not os.path.exists(path):
        os.makedirs(path)
        logging.info(f"Created folder: {path}")
    return path

def copy_files(src_files, dest_folder):
    create_folder(dest_folder)
    for f in src_files:
        if os.path.exists(f):
            shutil.copy(f, dest_folder)
            logging.info(f"Copied {f} → {dest_folder}")
        else:
            logging.warning(f"File not found: {f}")

# ----------------------------------
# MAIN LOGIC
# ----------------------------------
def process_refid(refid, conn):
    # Step 1: Check if refid exists
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(1) FROM M_Tender WHERE refid = ?", refid)
    exists = cursor.fetchone()[0]

    if not exists:
        logging.error(f"RefID {refid} not found. Try again.")
        return False
    else:
        logging.info(f"RefID {refid} found. Processing...")

        counter = 1
        
        # Step 2: Create folder with name as refid
        refid_folder = create_folder(os.path.join(BASE_DIR, str(refid)))

        with open(os.path.join(refid_folder, "please-read.txt"), "a") as file:
                file.write(f"{counter}. Download bid notice abstract." + "\n")

        # Step 3: Check uploaded bid docs
        cursor.execute("""
            SELECT DocID, DocName, RefID, IsElectronic, DocPhyName
            FROM M_Document
            WHERE RefID = ?
              AND bidsuppid IS NULL
              AND (DocPhyName LIKE 'TenderDoc%' OR Content LIKE '%Main Document%')
        """, refid)

        # Fetch results into a list
        bid_docs = cursor.fetchall()

        logging.info(f"Found {len(bid_docs)} item(s) under associated components. Downloading file(s)...")

        if len(bid_docs) > 0:
            assoc_folder = os.path.join(refid_folder, "Associated Components")

            # Loop through results to get file paths
            for row in bid_docs:
                if row.IsElectronic == 1:  # checks if the file if electronic/non-electronic
                    file_path = r"" + row.DocPhyName
                    copy_files([file_path], assoc_folder)
                else:
                    msg = f'Document Name "{row.DocName}" could not be downloaded. File is non-electronic.'
                    logging.info(msg)
                    
                    counter += 1
                    
                    with open(os.path.join(refid_folder, "please-read.txt"), "a") as file:
                        file.write(f"{counter}. {msg}" + "\n")
                
            logging.info("Finished processing associated components.")
        else:
            logging.info("No bid docs uploaded, skipping...")
            
        # Step 4: Check bid supplements
        cursor.execute("""
            SELECT bs.BidSuppID, bs.BidSuppTitle, bs.Description, 
                   d.DocName, d.DocPhyName, d.IsElectronic 
            FROM M_BidSupplement bs 
            LEFT JOIN M_Document d 
                ON bs.BidSuppID = d.BidSuppID 
            WHERE bs.RefID = ?
        """, refid)

        bid_supplements = cursor.fetchall()
        
        logging.info(f"Found {len(bid_supplements)} item(s) under Bid Supplement. Downloading file(s)...")
        
        if len(bid_supplements) > 0:
            supp_folder = os.path.join(refid_folder, "Bid Supplements")

            for row in bid_supplements:
                if row.DocPhyName:  # checks if not NULL/empty
                    file_path = os.path.join(r"Z:\GEPS_Files\BidSupp", row.DocPhyName)
                    copy_files([file_path], supp_folder)
                else:
                    msg = f"Bid Supplement No. {row.BidSuppID} could not be downloaded. File is non-electronic." 
                    logging.info(msg)
                    
                    counter += 1
                    
                    with open(os.path.join(refid_folder, "please-read.txt"), "a") as file:
                        file.write(f"{counter}. {msg}" + "\n")

            logging.info("Finished processing bid supplements.")
        else:
            logging.info("No bid supplements uploaded")
            
        # Step 5: Check bid status
        cursor.execute("SELECT TenderStatus FROM M_Tender WHERE RefID = ?", refid)
        row = cursor.fetchone()

        if row:  # record exists
            bid_status = row[0]  # first column
            if bid_status not in ("Closed", "Awarded"):
                logging.info(f'Bid status is "{bid_status}". Skipping award processing...')
            else:
                cursor.execute("SELECT AwardID FROM M_Award WHERE RefID = ?", refid)
                award_items = cursor.fetchall()
                
                logging.info(f"Found {len(award_items)} awarded item(s)...")
                
                if len(award_items) > 0:
                    award_folder = os.path.join(refid_folder, "Award")
                    create_folder(award_folder)   # ensure base "Award" folder exists

                    for award in award_items:
                        award_id = award[0]  # since pyodbc returns tuples
                        item_folder = os.path.join(award_folder, str(award_id))
                        #create_folder(item_folder)  # ✅ create per-item folder
                        
                        counter += 1
                        
                        with open(os.path.join(refid_folder, "please-read.txt"), "a") as file:
                            file.write(f"{counter}. Download award notice abstract for AwardID {award_id}." + "\n")

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
                            copy_files([file_path], item_folder)  # copy into award subfolder
                        
                        logging.info("Finished processing award documents.")
                        
        logging.info('All required documents have been processed successfully. Please review the details in please-read.txt for any actions needed.')
        
        return True

# ----------------------------------
# RUN
# ----------------------------------
if __name__ == "__main__":
    conn = connect_db()
    if conn:
        while True:
            refid_input = input("Enter RefID (or press Enter to exit): ").strip()
            if not refid_input:  # empty input = exit
                logging.info("Exiting program.")
                break

            success = process_refid(refid_input, conn)
            if success:
                continue
            else:
                continue

        conn.close()