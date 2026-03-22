# ─────────────────────────────────────────────────────────────
# scraper.py  —  Core Playwright scraping logic
#
# WHAT THIS DOES:
#   1. Opens Chrome using YOUR existing profile (already logged into Chalk)
#   2. For each URL — navigates to page
#   3. Clicks "Summary" tab → scrapes all fields
#   4. Clicks "Execution Summary" tab → scrapes the table
#   5. Returns structured data
# ─────────────────────────────────────────────────────────────

import logging
import time
from dataclasses import dataclass, field
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeout

from src.config import (
    CHROME_PROFILE_PATH,
    CHROME_PROFILE_NAME,
    PAGE_LOAD_TIMEOUT,
    TAB_LOAD_TIMEOUT,
    ELEMENT_WAIT_TIMEOUT,
    SUMMARY_TAB_TEXT,
    EXECUTION_SUMMARY_TAB_TEXT,
)
from src.validator import extract_page_id, get_page_title_from_url

log = logging.getLogger("scraper")


# ─────────────────────────────────────────────────────────────
# DATA MODELS
# These dataclasses define exactly what we collect per page
# ─────────────────────────────────────────────────────────────

@dataclass
class ExecutionRow:
    """One row in the Execution Summary table."""
    cycle:          str = ""   # e.g. "Sanity Dual Stack"
    total_planned:  str = ""   # e.g. "114"
    total_executed: str = ""   # e.g. "114"
    passed:         str = ""   # e.g. "113"
    passed_pct:     str = ""   # e.g. "99%"
    failed:         str = ""   # e.g. "1"
    failed_pct:     str = ""   # e.g. "1%"
    blocked:        str = ""   # e.g. "0"
    blocked_pct:    str = ""   # e.g. "0%"


@dataclass
class SummaryData:
    """All fields from the Summary tab."""
    # Left column
    primary:                    str = ""   # @R, Mohandas @Aravapalli, Vamsi
    fw_version:                 str = ""   # 5.4.0
    start_date:                 str = ""   # 04 Mar 2026
    completion_date:            str = ""   # 25 Mar 2026
    release_dev_complete:       str = ""   # TBD
    release_val_completion:     str = ""   # TBD
    release_dlm_complete:       str = ""   # TBD
    type:                       str = ""   # None
    on_schedule:                str = ""   # YES / NO
    cr_details:                 str = ""
    status:                     str = ""   # IN DEVTEST
    osc_version:                str = ""   # OSC Version: 1.148.15-rc1-master
    overall_summary:            str = ""   # Pass: 95% | Fail: 2% | Blocked: 0%
    he:                         str = ""
    # Right column
    testers:                    str = ""
    pm:                         str = ""


@dataclass
class ChalkPageData:
    """Complete data for one Chalk page URL."""
    url:              str = ""
    page_id:          str = ""
    page_title:       str = ""
    scrape_success:   bool = False
    error_message:    str = ""

    summary:          SummaryData = field(default_factory=SummaryData)
    execution_rows:   list[ExecutionRow] = field(default_factory=list)
    execution_totals: ExecutionRow = field(default_factory=ExecutionRow)


# ─────────────────────────────────────────────────────────────
# SCRAPER CLASS
# ─────────────────────────────────────────────────────────────

class ChalkScraper:

    def __init__(self):
        self.playwright = None
        self.context    = None

    def __enter__(self):
        """Start Playwright and open Chrome with user's existing profile."""
        log.info("🚀 Starting Playwright with your Chrome profile...")
        log.info(f"   Profile path: {CHROME_PROFILE_PATH}")

        self.playwright = sync_playwright().start()

        # launch_persistent_context = use YOUR Chrome profile folder
        # This means all your cookies, sessions, logins are already there
        # Chalk will see you as already logged in
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir     = CHROME_PROFILE_PATH,
            channel           = "chrome",        # use installed Google Chrome (not Chromium)
            headless          = False,            # show the browser window so user can see progress
            args              = [
                f"--profile-directory={CHROME_PROFILE_NAME}",
                "--disable-blink-features=AutomationControlled",  # don't let site detect automation
                "--no-first-run",
                "--no-default-browser-check",
            ],
            slow_mo           = 500,             # slight delay so scraping looks natural
            viewport          = {"width": 1280, "height": 800},
        )

        log.info("✅ Chrome opened with your profile. Chalk session should be active.")
        return self

    def __exit__(self, *args):
        """Clean up — close browser and Playwright."""
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()
        log.info("🔒 Browser closed.")

    # ──────────────────────────────────────────────────────────
    # PUBLIC METHOD — scrape all URLs
    # ──────────────────────────────────────────────────────────

    def scrape_all(self, urls: list[str], progress_callback=None) -> list[ChalkPageData]:
        """
        Scrapes all provided URLs one by one.

        progress_callback: optional function(current, total, page_title) for UI updates
        Returns list of ChalkPageData (one per URL)
        """
        results = []

        for i, url in enumerate(urls, start=1):
            page_title = get_page_title_from_url(url)
            log.info(f"\n[{i}/{len(urls)}] Scraping: {page_title}")
            log.info(f"  URL: {url}")

            if progress_callback:
                progress_callback(i, len(urls), page_title)

            data = self._scrape_single_page(url)
            results.append(data)

            # Small pause between pages — be polite to the server
            if i < len(urls):
                time.sleep(1)

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

        page = self.context.new_page()

        try:
            # ── Navigate to the page ──────────────────────────
            log.info(f"  → Navigating to page...")
            page.goto(url, timeout=PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")

            # ── Check if we got redirected to login ───────────
            if self._is_login_page(page):
                data.error_message = (
                    "Redirected to login page. "
                    "Please make sure you are logged into Chalk in Chrome and Chrome is fully closed before running this tool."
                )
                log.error(f"  ❌ {data.error_message}")
                return data

            # ── Wait for page content to appear ──────────────
            log.info(f"  → Waiting for page to load...")
            try:
                page.wait_for_selector(".tabs-menu, [data-testid='tabs'], .tab-nav, ul.tabs", timeout=ELEMENT_WAIT_TIMEOUT)
            except PlaywrightTimeout:
                # Tabs might have different selector — try waiting for any content
                page.wait_for_load_state("networkidle", timeout=PAGE_LOAD_TIMEOUT)

            # ── SCRAPE SUMMARY TAB ────────────────────────────
            log.info(f"  → Scraping Summary tab...")
            data.summary = self._scrape_summary_tab(page)

            # ── SCRAPE EXECUTION SUMMARY TAB ──────────────────
            log.info(f"  → Scraping Execution Summary tab...")
            exec_rows, exec_totals = self._scrape_execution_tab(page)
            data.execution_rows   = exec_rows
            data.execution_totals = exec_totals

            data.scrape_success = True
            log.info(f"  ✅ Successfully scraped: {data.page_title}")

        except PlaywrightTimeout:
            data.error_message = f"Page timed out after {PAGE_LOAD_TIMEOUT//1000}s. Check VPN connection."
            log.error(f"  ❌ Timeout: {data.error_message}")

        except Exception as e:
            data.error_message = f"Unexpected error: {str(e)}"
            log.error(f"  ❌ Error scraping {url}: {e}", exc_info=True)

        finally:
            page.close()

        return data

    # ──────────────────────────────────────────────────────────
    # SUMMARY TAB SCRAPING
    # ──────────────────────────────────────────────────────────

    def _scrape_summary_tab(self, page: Page) -> SummaryData:
        """Click the Summary tab and extract all fields."""
        summary = SummaryData()

        try:
            # Click the Summary tab
            self._click_tab(page, SUMMARY_TAB_TEXT)

            # Wait a moment for content to render
            page.wait_for_timeout(2000)

            # Get the full page HTML after tab click
            html    = page.content()
            soup    = BeautifulSoup(html, "html.parser")

            # ── Extract fields by looking for label → value pairs ──
            # Confluence renders these as table rows or definition lists
            # We search for the label text and get the adjacent cell

            summary.fw_version           = self._find_field(soup, ["FW Version", "FW Version / Release", "Firmware Version"])
            summary.start_date           = self._find_field(soup, ["Start Date of Current Build", "Start Date"])
            summary.completion_date      = self._find_field(soup, ["Completion Date of Current Build", "Completion Date"])
            summary.release_dev_complete = self._find_field(soup, ["Release Dev Complete"])
            summary.release_val_completion = self._find_field(soup, ["Release Val Completion", "Release Val Complete"])
            summary.release_dlm_complete = self._find_field(soup, ["Release DLM Complete"])
            summary.type                 = self._find_field(soup, ["Type"])
            summary.on_schedule          = self._find_field(soup, ["On Schedule"])
            summary.cr_details           = self._find_field(soup, ["CR Details"])
            summary.status               = self._find_field(soup, ["Status"])
            summary.osc_version          = self._find_field(soup, ["OSC Version"])
            summary.overall_summary      = self._find_field(soup, ["Overall Summary"])
            summary.he                   = self._find_field(soup, ["HE"])
            summary.primary              = self._find_field(soup, ["Primary"])
            summary.testers              = self._find_field(soup, ["Testers"])
            summary.pm                   = self._find_field(soup, ["PM"])

        except Exception as e:
            log.warning(f"  ⚠️  Error scraping Summary tab: {e}")

        return summary

    # ──────────────────────────────────────────────────────────
    # EXECUTION SUMMARY TAB SCRAPING
    # ──────────────────────────────────────────────────────────

    def _scrape_execution_tab(self, page: Page) -> tuple[list[ExecutionRow], ExecutionRow]:
        """Click the Execution Summary tab and extract the table."""
        rows   = []
        totals = ExecutionRow()

        try:
            # Click the Execution Summary tab
            self._click_tab(page, EXECUTION_SUMMARY_TAB_TEXT)

            # Wait for table to appear
            page.wait_for_timeout(2000)

            # Get page HTML
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Find the Overall Summary table
            # It has headers: Execution Cycle, Total Planned, Total Executed, Passed, etc.
            table = self._find_execution_table(soup)

            if not table:
                log.warning("  ⚠️  Could not find Execution Summary table.")
                return rows, totals

            # Parse table rows
            all_rows = table.find_all("tr")

            for tr in all_rows:
                cells = tr.find_all(["td", "th"])
                if len(cells) < 2:
                    continue

                cell_texts = [self._clean_text(c.get_text()) for c in cells]

                # Skip header row
                if any(h in cell_texts[0].lower() for h in ["execution cycle", "cycle", "test cycle"]):
                    continue

                # Check if it's a total/summary row (bold, or first cell is empty/bold)
                first_cell = cells[0]
                is_total   = (
                    first_cell.find("strong") is not None or
                    first_cell.find("b") is not None or
                    cell_texts[0].strip() == "" or
                    "total" in cell_texts[0].lower()
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
    # HELPERS
    # ──────────────────────────────────────────────────────────

    def _click_tab(self, page: Page, tab_text: str):
        """
        Clicks a tab by its visible text label.
        Tries multiple selector strategies since Confluence can vary.
        """
        # Strategy 1: Find by exact text in tab navigation
        try:
            tab = page.locator(f"text='{tab_text}'").first
            tab.wait_for(timeout=ELEMENT_WAIT_TIMEOUT)
            tab.click()
            page.wait_for_timeout(1500)
            log.info(f"     ✓ Clicked tab: '{tab_text}' (strategy 1)")
            return
        except Exception:
            pass

        # Strategy 2: Look for tab in common Confluence tab selectors
        selectors = [
            f"li a:has-text('{tab_text}')",
            f"[role='tab']:has-text('{tab_text}')",
            f".tab-nav a:has-text('{tab_text}')",
            f"a.tabs-menu-item:has-text('{tab_text}')",
            f"span:has-text('{tab_text}')",
        ]

        for selector in selectors:
            try:
                el = page.locator(selector).first
                el.wait_for(timeout=3000)
                el.click()
                page.wait_for_timeout(1500)
                log.info(f"     ✓ Clicked tab: '{tab_text}' (selector: {selector})")
                return
            except Exception:
                continue

        log.warning(f"     ⚠️  Could not click tab '{tab_text}' — tab may not exist on this page.")

    def _find_field(self, soup: BeautifulSoup, label_variants: list[str]) -> str:
        """
        Finds a field value by searching for its label in the page HTML.

        Confluence renders fields as table rows:
          <tr>
            <td>FW Version / Release</td>   ← label cell
            <td>5.4.0</td>                  ← value cell
          </tr>

        Tries all label variants (since field names can differ slightly).
        """
        for label in label_variants:
            # Search all table cells and divs for the label text
            for cell in soup.find_all(["td", "th", "div", "span", "p"]):
                cell_text = self._clean_text(cell.get_text())
                if label.lower() in cell_text.lower() and len(cell_text) < 80:
                    # Found the label cell — now get the NEXT sibling cell (value)
                    value_cell = cell.find_next_sibling(["td", "th"])
                    if value_cell:
                        return self._clean_text(value_cell.get_text())

                    # Or try parent row's next cell
                    parent_row = cell.find_parent("tr")
                    if parent_row:
                        cells_in_row = parent_row.find_all(["td", "th"])
                        for i, c in enumerate(cells_in_row):
                            if label.lower() in self._clean_text(c.get_text()).lower():
                                # Return the next cell's text
                                if i + 1 < len(cells_in_row):
                                    return self._clean_text(cells_in_row[i + 1].get_text())

        return ""  # field not found

    def _find_execution_table(self, soup: BeautifulSoup):
        """
        Finds the Overall Summary execution table in the page.
        Looks for a table containing 'Execution Cycle' or 'Sanity' in headers.
        """
        for table in soup.find_all("table"):
            table_text = table.get_text().lower()
            if any(keyword in table_text for keyword in [
                "execution cycle", "sanity", "total planned", "total executed"
            ]):
                return table
        return None

    def _parse_execution_row(self, cells: list[str]) -> ExecutionRow:
        """Convert a list of cell text values into an ExecutionRow dataclass."""
        row = ExecutionRow()
        # Map cells by position (based on table structure in image)
        # Col: Execution Cycle | Total Planned | Total Executed | Passed | Passed% | Failed | Failed% | Blocked | Blocked%
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

    def _is_login_page(self, page: Page) -> bool:
        """Check if we got redirected to a login page instead of the Chalk page."""
        current_url = page.url.lower()
        page_title  = page.title().lower()
        return (
            "login" in current_url or
            "signin" in current_url or
            "authenticate" in current_url or
            "log in" in page_title or
            "sign in" in page_title
        )

    def _clean_text(self, text: str) -> str:
        """Strip and clean whitespace from extracted text."""
        if not text:
            return ""
        # Replace multiple whitespace/newlines with single space
        import re
        text = re.sub(r'\s+', ' ', text)
        return text.strip()