# 🧠 Bid Document Extraction Automation (Python + Playwright)

This project automates the extraction of Bid and Award Notice documents from the PhilGEPS system.  
It uses **Playwright** for browser automation and **PyInstaller** to package the script into a standalone `.exe` file.

------------------------------------------------------

## 🚀 Features
- Automatically logs into PhilGEPS and navigates to bid details
- Saves **Bid and Award Notice Abstracts** as PDFs
- Extracts **Bid Supplements** and **Associated Documents**
- Handles **non-electronic** documents gracefully
- Can be built as a portable `.exe` file (no Python needed on target machine)

------------------------------------------------------

## 🧩 Prerequisites

### 1. Install Python
Download and install **Python 3.10+** from:  
👉 [https://www.python.org/downloads/](https://www.python.org/downloads/)

Make sure to tick:
> ✅ "Add Python to PATH"
>

------------------------------------------------------

### 2. Install Dependencies
Clone this repository first:
```bash
git clone https://github.com/arjaymarinas/philgeps-bid-docs-automation.git
cd <your-repo>
pip install -r requirements.txt
playwright install chromium
```
------------------------------------------------------

### 3. Database Connection
``` python
DB_CONFIG = {
    "server": "YOUR_SERVER_NAME",
    "database": "YOUR_DATABASE_NAME",
    "username": "YOUR_USERNAME",
    "password": "YOUR_PASSWORD",
    "driver": "{ODBC Driver 17 for SQL Server}"
}
```
- Make sure you have ODBC Driver 17 for SQL Server installed.
- If not, download it here:
- 👉 https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server

------------------------------------------------------

### 4. Verify installation
``` bash
python extract_bid_docs.py
```
- If successful, you should see logs like:.
```bash
INFO - Using Chromium from: .../ms-playwright/chromium-1187/chrome-win/chrome.exe
INFO - Connected to SQL Server
You’ll be prompted for:
PhilGEPS username
PhilGEPS password
RefID (bid reference number)
To exit, just press Enter when asked for a RefID.
```

------------------------------------------------------

### 5. Output: All generated PDFs are saved inside:
ExtractedBidDocs/
   ├── 7793173/
   │   ├── bid_notice_abstract.pdf
   │   ├── Associated Components/
   │   ├── Bid Supplements/
   │   ├── Award/
   │   └── IMPORTANT-NOTES.txt

------------------------------------------------------

### 6. Copy "ms-playwright" folder 
- From C:\Users\<your-user>\AppData\Local\ and copy the "ms-playwright" and paste it to your local repository's root folder
- Your repo's root folder will now look like this:
Your-repo-folder/
   ├── ms-playwright
   │   ├── <subdirectory>
   │   ├── <subdirectory>
   │   ├── <subdirectory>
   │   ├── ****
   ├── extract_bid_docs.py
   ├── README.md
   ├── requirements.txt

------------------------------------------------------

### 7. Building the Standalone .exe
- This project supports building a standalone executable (no dependencies needed on the target machine).
``` bash
pip install pyinstaller
```

- Run this full command (copy & paste):
```
pyinstaller --onefile ^
--add-data "ms-playwright;ms-playwright" ^
--hidden-import playwright.sync_api ^
--hidden-import playwright._impl._connection ^
--hidden-import playwright._impl._driver ^
--hidden-import playwright._impl._transport ^
--collect-submodules playwright ^
--collect-data playwright ^
extract_bid_docs_training_v2.py
```

------------------------------------------------------

### 8. Run the .exe
- After the build completes, you’ll find the .exe file inside the dist folder:
``` dist/extract_bid_docs_training_v2.exe ```
- You can now share this single .exe file with your colleagues — no need to install Python or Playwright or any other dependencies manually.


### TROUBLESHOOTING

| Issue                                                  | Cause                              | Solution                                                               |
| ------------------------------------------------------ | ---------------------------------- | ---------------------------------------------------------------------- |
| ❌ `Executable doesn't exist at ... headless_shell.exe` | Chromium not bundled               | Make sure you’ve run `playwright install chromium` **before** building |
| ⚠️ `Failed to connect: ...`                            | Wrong SQL credentials              | Double-check your `DB_CONFIG` values                                   |
| ⚠️ No PDFs generated                                   | Page didn’t load fully             | Increase timeout in `page.goto(..., timeout=60000)`                    |
| ⚠️ "Login failed"                                      | Wrong username/password            | Re-enter credentials when prompted                                     |
| ⚠️ Big .exe size                                       | PyInstaller packs all dependencies | Install UPX and use `--upx-dir` to compress                            |

------------------------------------------------------

🧑‍💻 Author
Developed and maintained by Arjay Mariñas
📍 PhilGEPS – Electronic Government Procurement Operations Division

------------------------------------------------------

License
This project is licensed under the MIT License — you’re free to use and modify it with attribution.

