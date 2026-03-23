# ─────────────────────────────────────────────────────────────
# config.py  —  All configuration for Chalk Scraper Tool
# ─────────────────────────────────────────────────────────────

import os
import platform

# ── Chalk Settings ────────────────────────────────────────────
CHALK_BASE_DOMAIN = "chalk.charter.com"
CHALK_BASE_URL    = f"https://{CHALK_BASE_DOMAIN}"

# Maximum URLs user can provide
MAX_URLS = 10

# Timeouts (in milliseconds — divided by 1000 when passed to Selenium)
PAGE_LOAD_TIMEOUT    = 30000   # 30 seconds — how long to wait for a page to load
ELEMENT_WAIT_TIMEOUT = 10000   # 10 seconds — how long to wait for an element

# ── Chrome Profile Path ───────────────────────────────────────
# Selenium opens Chrome pointing to YOUR profile folder.
# This means your Chalk login session is already there — no login needed.
# Chrome must be fully closed before running the tool.

def get_chrome_profile_path() -> str:
    system = platform.system()
    if system == "Windows":
        return os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Google", "Chrome", "User Data"
        )
    elif system == "Darwin":  # Mac
        return os.path.expanduser("~/Library/Application Support/Google/Chrome")
    elif system == "Linux":
        return os.path.expanduser("~/.config/google-chrome")
    else:
        raise RuntimeError(f"Unsupported OS: {system}")

CHROME_PROFILE_PATH = get_chrome_profile_path()

# Which Chrome profile to use
# "Default" is the main profile. If you use multiple Chrome profiles,
# change to "Profile 1", "Profile 2" etc.
CHROME_PROFILE_NAME = "Default"

# ── Tab Names on Chalk Page ───────────────────────────────────
SUMMARY_TAB_TEXT           = "Summary"
EXECUTION_SUMMARY_TAB_TEXT = "Execution Summary"

# ── Output / Logging ─────────────────────────────────────────
OUTPUT_DIR = "output"
LOG_DIR    = "logs"
LOG_FILE   = "chalk_scraper.log"
