# ─────────────────────────────────────────────────────────────
# scraper.py  —  Selenium-based Chalk scraper
#
# WHY SELENIUM:
#   Playwright needs 'greenlet' which needs C++ compiler on Python 3.13+
#   Selenium uses pre-built wheels — works on ANY Python version, zero compilation
#
# WHAT THIS DOES:
#   1. Opens Chrome using YOUR existing profile (already logged into Chalk)
#   2. For each URL — navigates to page
#   3. Clicks "Summary" tab → scrapes all fields
#   4. Clicks "Execution Summary" tab → scrapes the table
#   5. Returns structured data
# ─────────────────────────────────────────────────────────────

import re
import logging
import time
from dataclasses import dataclass, field
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
)
from selenium.webdriver.common.action_chains import ActionChains

from src.config import (
    CHROME_PROFILE_PATH,
    CHROME_PROFILE_NAME,
    PAGE_LOAD_TIMEOUT,
    ELEMENT_WAIT_TIMEOUT,
    SUMMARY_TAB_TEXT,
    EXECUTION_SUMMARY_TAB_TEXT,
)
from src.validator import extract_page_id, get_page_title_from_url

log = logging.getLogger("scraper")


# ─────────────────────────────────────────────────────────────
# DATA MODELS
# ─────────────────────────────────────────────────────────────

@dataclass
class ExecutionRow:
    """One row in the Execution Summary table."""
    cycle:          str = ""
    total_planned:  str = ""
    total_executed: str = ""
    passed:         str = ""
    passed_pct:     str = ""
    failed:         str = ""
    failed_pct:     str = ""
    blocked:        str = ""
    blocked_pct:    str = ""


@dataclass
class SummaryData:
    """All fields from the Summary tab."""
    primary:                  str = ""
    fw_version:               str = ""
    start_date:               str = ""
    completion_date:          str = ""
    release_dev_complete:     str = ""
    release_val_completion:   str = ""
    release_dlm_complete:     str = ""
    type:                     str = ""
    on_schedule:              str = ""
    cr_details:               str = ""
    status:                   str = ""
    osc_version:              str = ""
    overall_summary:          str = ""
    he:                       str = ""
    testers:                  str = ""
    pm:                       str = ""


@dataclass
class ChalkPageData:
    """Complete scraped data for one Chalk page URL."""
    url:              str  = ""
    page_id:          str  = ""
    page_title:       str  = ""
    scrape_success:   bool = False
    error_message:    str  = ""

    summary:          SummaryData  = field(default_factory=SummaryData)
    execution_rows:   list         = field(default_factory=list)
    execution_totals: ExecutionRow = field(default_factory=ExecutionRow)


# ─────────────────────────────────────────────────────────────
# SELENIUM SCRAPER CLASS
# ─────────────────────────────────────────────────────────────

class ChalkScraper:

    def __init__(self):
        self.driver = None

    def __enter__(self):
        """
        Open Chrome with the user's existing profile.

        KEY POINT:
        We pass --user-data-dir pointing to YOUR Chrome profile folder.
        This means Chrome opens with ALL your existing cookies and sessions.
        Chalk sees you as already logged in — no credentials needed.

        Chrome must be fully closed before this runs.
        Two Chrome instances cannot share the same profile folder.
        """
        log.info("🚀 Starting Chrome with your existing profile...")
        log.info(f"   Profile path: {CHROME_PROFILE_PATH}")

        options = Options()

        # ── Use YOUR existing Chrome profile ─────────────────
        options.add_argument(f"--user-data-dir={CHROME_PROFILE_PATH}")
        options.add_argument(f"--profile-directory={CHROME_PROFILE_NAME}")

        # ── Prevent Chalk detecting automation ───────────────
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # ── Other stability options ───────────────────────────
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-notifications")
        options.add_argument("--start-maximized")

        # ── headless=False — show the browser so user can see progress
        # Set to True if you want it to run in background silently
        # options.add_argument("--headless=new")

        # ── selenium-manager auto-downloads the right chromedriver ──
        # No need to manually download chromedriver — Selenium 4.6+ handles it
        self.driver = webdriver.Chrome(options=options)

        # Tell Chrome to not show "Chrome is being controlled by automated software" bar
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
        )

        # Set page load timeout
        self.driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT // 1000)  # convert ms to seconds

        log.info("✅ Chrome opened with your profile. Chalk session should be active.")
        return self

    def __exit__(self, *args):
        """Close the browser cleanly."""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
        log.info("🔒 Browser closed.")

    # ──────────────────────────────────────────────────────────
    # PUBLIC — scrape all URLs
    # ──────────────────────────────────────────────────────────

    def scrape_all(self, urls: list, progress_callback=None) -> list:
        """
        Scrapes all provided URLs one by one.
        Returns list of ChalkPageData objects.
        """
        results = []

        for i, url in enumerate(urls, start=1):
            page_title = get_page_title_from_url(url)
            log.info(f"\n[{i}/{len(urls)}] Scraping: {page_title}")

            if progress_callback:
                progress_callback(i, len(urls), page_title)

            data = self._scrape_single_page(url)
            results.append(data)

            # Polite pause between pages
            if i < len(urls):
                time.sleep(1.5)

        return results

    # ──────────────────────────────────────────────────────────
    # PRIVATE — scrape one page
    # ──────────────────────────────────────────────────────────

    def _scrape_single_page(self, url: str) -> ChalkPageData:
        """Navigate to one Chalk page and scrape both tabs."""
        data            = ChalkPageData()
        data.url        = url
        data.page_id    = extract_page_id(url) or ""
        data.page_title = get_page_title_from_url(url)

        try:
            # ── Navigate to the page ──────────────────────────
            log.info(f"  → Navigating to page...")
            self.driver.get(url)

            # ── Check if redirected to login ──────────────────
            if self._is_login_page():
                data.error_message = (
                    "Redirected to login page. "
                    "Please make sure you are logged into Chalk in Chrome "
                    "and Chrome is fully closed before running this tool."
                )
                log.error(f"  ❌ {data.error_message}")
                return data

            # ── Wait for page to load ─────────────────────────
            log.info(f"  → Waiting for page content...")
            self._wait_for_page_ready()

            # ── SCRAPE SUMMARY TAB ────────────────────────────
            log.info(f"  → Scraping Summary tab...")
            data.summary = self._scrape_summary_tab()

            # ── SCRAPE EXECUTION SUMMARY TAB ──────────────────
            log.info(f"  → Scraping Execution Summary tab...")
            rows, totals          = self._scrape_execution_tab()
            data.execution_rows   = rows
            data.execution_totals = totals

            data.scrape_success = True
            log.info(f"  ✅ Done: {data.page_title}")

        except TimeoutException:
            data.error_message = (
                f"Page timed out after {PAGE_LOAD_TIMEOUT // 1000}s. "
                "Check VPN connection."
            )
            log.error(f"  ❌ {data.error_message}")

        except WebDriverException as e:
            data.error_message = f"Browser error: {str(e)[:200]}"
            log.error(f"  ❌ {data.error_message}")

        except Exception as e:
            data.error_message = f"Unexpected error: {str(e)[:200]}"
            log.error(f"  ❌ Error: {e}", exc_info=True)

        return data

    # ──────────────────────────────────────────────────────────
    # WAIT FOR PAGE READY
    # ──────────────────────────────────────────────────────────

    def _wait_for_page_ready(self):
        """
        Wait for the Confluence page to fully load.
        Tries multiple strategies since Confluence can be slow.
        """
        wait = WebDriverWait(self.driver, ELEMENT_WAIT_TIMEOUT // 1000)

        # Strategy 1 — wait for tab elements to appear
        tab_selectors = [
            "ul.tabs-menu",
            "[data-testid='tabs']",
            ".tab-nav",
            "a.tabs-menu-item",
            "[role='tab']",
        ]

        for selector in tab_selectors:
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                log.info(f"     ✓ Page ready (found: {selector})")
                return
            except TimeoutException:
                continue

        # Strategy 2 — just wait for body content
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#main-content, #content, .wiki-content")))
            log.info("     ✓ Page ready (found main content)")
        except TimeoutException:
            # Last resort — just wait 3 seconds
            log.warning("     ⚠️  Could not detect page ready state — waiting 3s...")
            time.sleep(3)

    # ──────────────────────────────────────────────────────────
    # SUMMARY TAB
    # ──────────────────────────────────────────────────────────

    def _scrape_summary_tab(self) -> SummaryData:
        """Click Summary tab and extract all fields."""
        summary = SummaryData()

        try:
            # Click the Summary tab
            self._click_tab(SUMMARY_TAB_TEXT)

            # Wait for content to render after tab click
            time.sleep(2)

            # Parse current page HTML
            soup = BeautifulSoup(self.driver.page_source, "html.parser")

            # Extract each field by its label
            summary.fw_version             = self._find_field(soup, ["FW Version / Release", "FW Version", "Firmware Version"])
            summary.start_date             = self._find_field(soup, ["Start Date of Current Build", "Start Date"])
            summary.completion_date        = self._find_field(soup, ["Completion Date of Current Build", "Completion Date"])
            summary.release_dev_complete   = self._find_field(soup, ["Release Dev Complete"])
            summary.release_val_completion = self._find_field(soup, ["Release Val Completion", "Release Val Complete"])
            summary.release_dlm_complete   = self._find_field(soup, ["Release DLM Complete"])
            summary.type                   = self._find_field(soup, ["Type"])
            summary.on_schedule            = self._find_field(soup, ["On Schedule"])
            summary.cr_details             = self._find_field(soup, ["CR Details"])
            summary.status                 = self._find_field(soup, ["Status"])
            summary.osc_version            = self._find_field(soup, ["OSC Version"])
            summary.overall_summary        = self._find_field(soup, ["Overall Summary"])
            summary.he                     = self._find_field(soup, ["HE"])
            summary.primary                = self._find_field(soup, ["Primary"])
            summary.testers                = self._find_field(soup, ["Testers"])
            summary.pm                     = self._find_field(soup, ["PM"])

        except Exception as e:
            log.warning(f"  ⚠️  Error scraping Summary tab: {e}")

        return summary

    # ──────────────────────────────────────────────────────────
    # EXECUTION SUMMARY TAB
    # ──────────────────────────────────────────────────────────

    def _scrape_execution_tab(self) -> tuple:
        """Click Execution Summary tab and extract the table."""
        rows   = []
        totals = ExecutionRow()

        try:
            # Click the tab
            self._click_tab(EXECUTION_SUMMARY_TAB_TEXT)

            # Wait for table to render
            time.sleep(2)

            # Parse HTML
            soup  = BeautifulSoup(self.driver.page_source, "html.parser")
            table = self._find_execution_table(soup)

            if not table:
                log.warning("  ⚠️  Could not find Execution Summary table.")
                return rows, totals

            all_trs = table.find_all("tr")

            for tr in all_trs:
                cells      = tr.find_all(["td", "th"])
                if len(cells) < 2:
                    continue

                cell_texts = [self._clean(c.get_text()) for c in cells]

                # Skip header row
                if any(h in cell_texts[0].lower() for h in ["execution cycle", "cycle", "test cycle"]):
                    continue

                # Detect totals row — first cell is empty or bold
                first_cell = cells[0]
                is_total   = (
                    cell_texts[0].strip() == "" or
                    "total" in cell_texts[0].lower() or
                    first_cell.find(["strong", "b"]) is not None
                )

                row = self._parse_execution_row(cell_texts)

                if is_total and cell_texts[0].strip() == "":
                    totals = row
                else:
                    rows.append(row)

        except Exception as e:
            log.warning(f"  ⚠️  Error scraping Execution Summary tab: {e}")

        return rows, totals

    # ──────────────────────────────────────────────────────────
    # CLICK TAB HELPER
    # ──────────────────────────────────────────────────────────

    def _click_tab(self, tab_text: str):
        """
        Click a tab by its visible text.
        Tries multiple selector strategies for Confluence compatibility.
        """
        wait = WebDriverWait(self.driver, ELEMENT_WAIT_TIMEOUT // 1000)

        # All strategies to find and click a tab
        strategies = [
            # XPath — find any element whose text exactly matches
            (By.XPATH, f"//*[normalize-space(text())='{tab_text}']"),
            # XPath — partial match (handles extra whitespace)
            (By.XPATH, f"//*[contains(text(),'{tab_text}')]"),
            # CSS — anchor inside tab list
            (By.CSS_SELECTOR, f"ul.tabs-menu a"),
            # Role-based
            (By.XPATH, f"//*[@role='tab' and contains(text(),'{tab_text}')]"),
        ]

        for by, selector in strategies:
            try:
                if by == By.CSS_SELECTOR and "ul.tabs-menu" in selector:
                    # Special case — find the right tab from the list
                    tabs = self.driver.find_elements(by, selector)
                    for tab in tabs:
                        if tab_text.lower() in tab.text.lower():
                            self.driver.execute_script("arguments[0].click();", tab)
                            time.sleep(1.5)
                            log.info(f"     ✓ Clicked tab: '{tab_text}'")
                            return
                else:
                    elements = self.driver.find_elements(by, selector)
                    for el in elements:
                        if tab_text.lower() in el.text.lower():
                            # Scroll into view then click
                            self.driver.execute_script("arguments[0].scrollIntoView(true);", el)
                            time.sleep(0.3)
                            self.driver.execute_script("arguments[0].click();", el)
                            time.sleep(1.5)
                            log.info(f"     ✓ Clicked tab: '{tab_text}'")
                            return
            except Exception:
                continue

        log.warning(f"     ⚠️  Could not click tab '{tab_text}' — may not exist on this page.")

    # ──────────────────────────────────────────────────────────
    # FIELD EXTRACTION HELPER
    # ──────────────────────────────────────────────────────────

    def _find_field(self, soup: BeautifulSoup, label_variants: list) -> str:
        """
        Finds a field value by searching for its label in the HTML.

        Confluence renders fields as table rows:
          <tr>
            <td>FW Version / Release</td>   ← label
            <td>5.4.0</td>                  ← value  ← we want this
          </tr>
        """
        for label in label_variants:
            for cell in soup.find_all(["td", "th", "div", "span", "p"]):
                cell_text = self._clean(cell.get_text())

                # Match label (case-insensitive, short enough to be a label not content)
                if label.lower() in cell_text.lower() and len(cell_text) < 100:

                    # Try direct sibling first
                    sibling = cell.find_next_sibling(["td", "th"])
                    if sibling:
                        val = self._clean(sibling.get_text())
                        if val:
                            return val

                    # Try next cell in same row
                    parent_row = cell.find_parent("tr")
                    if parent_row:
                        cells_in_row = parent_row.find_all(["td", "th"])
                        for i, c in enumerate(cells_in_row):
                            if label.lower() in self._clean(c.get_text()).lower():
                                if i + 1 < len(cells_in_row):
                                    val = self._clean(cells_in_row[i + 1].get_text())
                                    if val:
                                        return val

        return ""

    # ──────────────────────────────────────────────────────────
    # OTHER HELPERS
    # ──────────────────────────────────────────────────────────

    def _find_execution_table(self, soup: BeautifulSoup):
        """Find the execution summary table by looking for known keywords."""
        for table in soup.find_all("table"):
            text = table.get_text().lower()
            if any(kw in text for kw in ["execution cycle", "sanity", "total planned", "total executed"]):
                return table
        return None

    def _parse_execution_row(self, cells: list) -> ExecutionRow:
        """Map cell list to ExecutionRow dataclass by position."""
        row = ExecutionRow()
        if len(cells) > 0: row.cycle          = cells[0]
        if len(cells) > 1: row.total_planned  = cells[1]
        if len(cells) > 2: row.total_executed = cells[2]
        if len(cells) > 3: row.passed         = cells[3]
        if len(cells) > 4: row.passed_pct     = cells[4]
        if len(cells) > 5: row.failed         = cells[5]
        if len(cells) > 6: row.failed_pct     = cells[6]
        if len(cells) > 7: row.blocked        = cells[7]
        if len(cells) > 8: row.blocked_pct    = cells[8]
        return row

    def _is_login_page(self) -> bool:
        """Check if we landed on a login page instead of the Chalk page."""
        url   = self.driver.current_url.lower()
        title = self.driver.title.lower()
        return (
            "login"        in url   or
            "signin"       in url   or
            "authenticate" in url   or
            "log in"       in title or
            "sign in"      in title
        )

    def _clean(self, text: str) -> str:
        """Clean and normalize whitespace in extracted text."""
        if not text:
            return ""
        return re.sub(r'\s+', ' ', text).strip()
