# ─────────────────────────────────────────────────────────────
# scraper.py  —  Selenium-based Chalk scraper
#
# HOW IT WORKS:
#   VPN connected = Chalk pages open directly, no login needed (SSO)
#   Chrome opens → goes straight to each URL → scrapes data
#   No login, no credentials, no manual steps during scraping
# ─────────────────────────────────────────────────────────────

import re
import logging
import time
from dataclasses import dataclass, field
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from src.config import (
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
    url:              str  = ""
    page_id:          str  = ""
    page_title:       str  = ""
    scrape_success:   bool = False
    error_message:    str  = ""
    summary:          SummaryData  = field(default_factory=SummaryData)
    execution_rows:   list         = field(default_factory=list)
    execution_totals: ExecutionRow = field(default_factory=ExecutionRow)


# ─────────────────────────────────────────────────────────────
# SCRAPER
# ─────────────────────────────────────────────────────────────

class ChalkScraper:

    def __init__(self):
        self.driver = None

    def __enter__(self):
        """
        Opens Chrome and goes directly to URLs.
        VPN must be connected — Chalk opens without any login via SSO.
        No profile needed, no credentials, no manual steps.
        """
        log.info("Opening Chrome browser...")

        options = Options()

        # Suppress noisy Chrome internal log lines (DevTools, TensorFlow etc)
        options.add_argument("--log-level=3")
        options.add_argument("--silent")
        options.add_experimental_option(
            "excludeSwitches", ["enable-automation", "enable-logging"]
        )
        options.add_experimental_option("useAutomationExtension", False)

        # Prevent site detecting automation
        options.add_argument("--disable-blink-features=AutomationControlled")

        # General stability
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-infobars")
        options.add_argument("--start-maximized")

        # Selenium 4.6+ auto-downloads correct chromedriver automatically
        self.driver = webdriver.Chrome(options=options)

        # Hide webdriver property from the website
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
        )

        self.driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT // 1000)

        log.info("Chrome opened successfully.")
        return self

    def __exit__(self, *args):
        """Close browser cleanly when done."""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
        log.info("Browser closed.")

    # ──────────────────────────────────────────────────────────
    # PUBLIC — scrape all URLs
    # ──────────────────────────────────────────────────────────

    def scrape_all(self, urls: list, progress_callback=None) -> list:
        """Scrape all URLs one by one. Returns list of ChalkPageData."""
        results = []

        log.info(f"$$$$ Starting to scrape {len(urls)} pages...")

        for i, url in enumerate(urls, start=1):
            page_title = get_page_title_from_url(url)
            log.info(f"\n[{i}/{len(urls)}] Scraping: {page_title}")

            if progress_callback:
                progress_callback(i, len(urls), page_title)

            data = self._scrape_single_page(url)
            results.append(data)

            # Small pause between pages
            if i < len(urls):
                time.sleep(1.5)

        return results

    # ──────────────────────────────────────────────────────────
    # PRIVATE — single page
    # ──────────────────────────────────────────────────────────

    def _scrape_single_page(self, url: str) -> ChalkPageData:
        """Open one Chalk URL and scrape Summary + Execution Summary tabs."""
        data            = ChalkPageData()
        data.url        = url
        data.page_id    = extract_page_id(url) or ""
        data.page_title = get_page_title_from_url(url)

        try:
            # ── Go to the URL ─────────────────────────────────
            log.info(f"  Opening: {url}")
            self.driver.get(url)

            # ── Check if VPN is not connected (can't reach page) ──
            if self._is_unreachable():
                data.error_message = (
                    "Cannot reach Chalk page. "
                    "Please check VPN is connected and try again."
                )
                log.error(f"  ERROR: {data.error_message}")
                return data

            # ── Check if login page appeared (session issue) ──
            if self._is_login_page():
                data.error_message = (
                    "Login page appeared. "
                    "VPN may not be connected or SSO session expired."
                )
                log.error(f"  ERROR: {data.error_message}")
                return data

            # ── Wait for page content to load ─────────────────
            log.info(f"  Waiting for page to load...")
            self._wait_for_page_ready()

            # ── Scrape Summary tab ────────────────────────────
            log.info(f"  Scraping Summary tab...")
            data.summary = self._scrape_summary_tab()

            # ── Scrape Execution Summary tab ──────────────────
            log.info(f"  Scraping Execution Summary tab...")
            rows, totals          = self._scrape_execution_tab()
            data.execution_rows   = rows
            data.execution_totals = totals

            data.scrape_success = True
            log.info(f"  Done: {data.page_title}")

        except TimeoutException:
            data.error_message = (
                f"Page timed out after {PAGE_LOAD_TIMEOUT // 1000}s. "
                "VPN may be disconnected or page is very slow."
            )
            log.error(f"  TIMEOUT: {data.error_message}")

        except WebDriverException as e:
            data.error_message = f"Browser error: {str(e)[:200]}"
            log.error(f"  BROWSER ERROR: {data.error_message}")

        except Exception as e:
            data.error_message = f"Unexpected error: {str(e)[:200]}"
            log.error(f"  ERROR: {e}", exc_info=True)

        return data

    # ──────────────────────────────────────────────────────────
    # WAIT FOR PAGE READY
    # ──────────────────────────────────────────────────────────

    def _wait_for_page_ready(self):
        """Wait for Confluence tabs or main content to appear."""
        wait = WebDriverWait(self.driver, ELEMENT_WAIT_TIMEOUT // 1000)

        # Try Confluence-specific tab selectors first
        for selector in ["ul.tabs-menu", "a.tabs-menu-item", "[role='tab']", ".tab-nav"]:
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                log.info(f"     Page ready (tabs found: {selector})")
                return
            except TimeoutException:
                continue

        # Fall back to main content area
        try:
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "#main-content, #content, .wiki-content, .confluence-content")
            ))
            log.info("     Page ready (main content found)")
        except TimeoutException:
            log.warning("     Page state unknown — waiting 4 seconds...")
            time.sleep(4)

    # ──────────────────────────────────────────────────────────
    # SUMMARY TAB
    # ──────────────────────────────────────────────────────────

    def _scrape_summary_tab(self) -> SummaryData:
        """Click Summary tab and extract all key fields."""
        summary = SummaryData()
        try:
            self._click_tab(SUMMARY_TAB_TEXT)
            time.sleep(2)   # wait for tab content to render
            soup = BeautifulSoup(self.driver.page_source, "html.parser")

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
            log.warning(f"  Error scraping Summary tab: {e}")
        return summary

    # ──────────────────────────────────────────────────────────
    # EXECUTION SUMMARY TAB
    # ──────────────────────────────────────────────────────────

    def _scrape_execution_tab(self) -> tuple:
        """Click Execution Summary tab and extract the results table."""
        rows   = []
        totals = ExecutionRow()
        try:
            self._click_tab(EXECUTION_SUMMARY_TAB_TEXT)
            time.sleep(2)
            soup  = BeautifulSoup(self.driver.page_source, "html.parser")
            table = self._find_execution_table(soup)

            if not table:
                log.warning("  Could not find Execution Summary table on this page.")
                return rows, totals

            for tr in table.find_all("tr"):
                cells = tr.find_all(["td", "th"])
                if len(cells) < 2:
                    continue

                cell_texts = [self._clean(c.get_text()) for c in cells]

                # Skip header row
                if any(h in cell_texts[0].lower() for h in ["execution cycle", "cycle", "test cycle"]):
                    continue

                # Detect totals row — first cell empty or says "total"
                first_cell = cells[0]
                is_total = (
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
            log.warning(f"  Error scraping Execution Summary tab: {e}")
        return rows, totals

    # ──────────────────────────────────────────────────────────
    # CLICK TAB HELPER
    # ──────────────────────────────────────────────────────────

    def _click_tab(self, tab_text: str):
        """
        Find and click a tab by its visible text.
        Uses JavaScript click to avoid any interception issues.
        """
        strategies = [
            (By.XPATH,        f"//*[normalize-space(text())='{tab_text}']"),
            (By.XPATH,        f"//*[contains(text(),'{tab_text}')]"),
            (By.XPATH,        f"//*[@role='tab' and contains(text(),'{tab_text}')]"),
            (By.CSS_SELECTOR, "ul.tabs-menu a"),
            (By.CSS_SELECTOR, "a.tabs-menu-item"),
        ]

        for by, selector in strategies:
            try:
                elements = self.driver.find_elements(by, selector)
                for el in elements:
                    if tab_text.lower() in el.text.lower():
                        self.driver.execute_script("arguments[0].scrollIntoView(true);", el)
                        time.sleep(0.3)
                        self.driver.execute_script("arguments[0].click();", el)
                        time.sleep(1.5)
                        log.info(f"     Clicked tab: '{tab_text}'")
                        return
            except Exception:
                continue

        log.warning(f"     Could not click tab '{tab_text}' — may not exist on this page.")

    # ──────────────────────────────────────────────────────────
    # FIELD EXTRACTION HELPERS
    # ──────────────────────────────────────────────────────────

    def _find_field(self, soup: BeautifulSoup, label_variants: list) -> str:
        """
        Find value next to a label in Confluence's table layout.
        Tries all label name variants since field names can differ slightly.
        """
        for label in label_variants:
            for cell in soup.find_all(["td", "th", "div", "span", "p"]):
                cell_text = self._clean(cell.get_text())

                if label.lower() in cell_text.lower() and len(cell_text) < 100:
                    # Try direct sibling cell
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

    def _find_execution_table(self, soup: BeautifulSoup):
        """Find execution results table by looking for known column names."""
        for table in soup.find_all("table"):
            text = table.get_text().lower()
            if any(kw in text for kw in ["execution cycle", "sanity", "total planned", "total executed"]):
                return table
        return None

    def _parse_execution_row(self, cells: list) -> ExecutionRow:
        """Map list of cell texts to ExecutionRow by column position."""
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
        """Check if we landed on a login page — means VPN/SSO issue."""
        url   = self.driver.current_url.lower()
        title = self.driver.title.lower()
        return (
            "login"        in url   or
            "signin"       in url   or
            "authenticate" in url   or
            "log in"       in title or
            "sign in"      in title
        )

    def _is_unreachable(self) -> bool:
        """Check if the page failed to load — usually means VPN is off."""
        try:
            title = self.driver.title.lower()
            source = self.driver.page_source.lower()
            return (
                "err_name_not_resolved"  in source or
                "err_connection_refused" in source or
                "this site can't be reached" in source or
                "unable to connect" in title
            )
        except Exception:
            return False

    def _clean(self, text: str) -> str:
        """Normalize whitespace in extracted text."""
        if not text:
            return ""
        return re.sub(r'\s+', ' ', text).strip()
