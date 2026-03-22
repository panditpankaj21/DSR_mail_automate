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

# How long to wait (seconds) for a page/tab to load before giving up
PAGE_LOAD_TIMEOUT    = 30000   # 30 seconds in milliseconds (Playwright uses ms)
TAB_LOAD_TIMEOUT     = 15000   # 15 seconds for tab content to appear
ELEMENT_WAIT_TIMEOUT = 10000   # 10 seconds to find an element

# ── Chrome Profile Path ───────────────────────────────────────
# This is where Chrome stores YOUR cookies, sessions, login state.
# Playwright will use this so it inherits your Chalk login.
#
# We auto-detect based on OS. You can override manually if needed.

def get_chrome_profile_path() -> str:
    system = platform.system()

    if system == "Windows":
        # Default Chrome profile on Windows
        return os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Google", "Chrome", "User Data"
        )
    elif system == "Darwin":
        # Default Chrome profile on Mac
        return os.path.expanduser(
            "~/Library/Application Support/Google/Chrome"
        )
    elif system == "Linux":
        # Default Chrome profile on Linux
        return os.path.expanduser(
            "~/.config/google-chrome"
        )
    else:
        raise RuntimeError(f"Unsupported OS: {system}")

CHROME_PROFILE_PATH = get_chrome_profile_path()

# Which Chrome profile to use (Default is the main one)
# If you use multiple Chrome profiles, change this to "Profile 1", "Profile 2" etc.
CHROME_PROFILE_NAME = "Profile 2"

# ── Tab Names on Chalk Page ───────────────────────────────────
# These are the exact tab labels we click on the Chalk page
SUMMARY_TAB_TEXT          = "Summary"
EXECUTION_SUMMARY_TAB_TEXT = "Execution Summary"

# ── Output Settings ───────────────────────────────────────────
OUTPUT_DIR = "output"

# ── Logging ───────────────────────────────────────────────────
LOG_DIR  = "logs"
LOG_FILE = "chalk_scraper.log"