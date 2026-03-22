# ─────────────────────────────────────────────────────────────
# main.py  —  Chalk Scraper Tool — Main Entry Point
#
# HOW TO RUN:
#   1. pip install -r requirements.txt
#   2. playwright install chromium
#   3. python main.py
#
# PREREQUISITES FOR USER:
#   ✅ Logged into chalk.charter.com in Google Chrome
#   ✅ VPN is connected
#   ✅ Google Chrome is fully closed
# ─────────────────────────────────────────────────────────────

import sys
import logging
import os
from pathlib import Path

# Make sure src/ is importable
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich import box
from rich.table import Table

from src.config    import MAX_URLS, LOG_DIR, LOG_FILE
from src.validator import validate_all_urls
from src.scraper   import ChalkScraper
from src.display   import (
    display_all_results,
    display_scraping_start,
    display_progress,
    display_failed_urls,
)

console = Console()


# ─────────────────────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────────────────────

def setup_logging():
    Path(LOG_DIR).mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(f"{LOG_DIR}/{LOG_FILE}", encoding="utf-8"),
            # Not logging to console — rich handles console output
        ]
    )


# ─────────────────────────────────────────────────────────────
# STEP 1 — Welcome screen + prerequisite checklist
# ─────────────────────────────────────────────────────────────

def show_welcome():
    console.print()
    console.print(Panel(
        "[bold white]Chalk Data Collector[/bold white]\n"
        "[dim]Scrapes Summary & Execution Summary from Chalk pages[/dim]",
        style="bold blue",
        padding=(1, 6)
    ))
    console.print()

    # Show prerequisite checklist
    console.print("[bold yellow]Before continuing, please confirm:[/bold yellow]")
    console.print()

    checklist = [
        ("1", "You are logged into [bold]chalk.charter.com[/bold] in Google Chrome"),
        ("2", "Your [bold]VPN is connected[/bold]"),
        ("3", "Google Chrome is [bold]fully closed[/bold] (not just minimized)"),
    ]

    for num, item in checklist:
        console.print(f"  [cyan]{num}.[/cyan] {item}")

    console.print()

    # Ask user to confirm all 3
    confirmed = Confirm.ask(
        "  [bold]Have you confirmed all 3 points above?[/bold]",
        default=False
    )

    if not confirmed:
        console.print()
        console.print(Panel(
            "[yellow]Please complete the prerequisites and run the tool again.[/yellow]\n\n"
            "• Login to Chalk:  https://chalk.charter.com\n"
            "• Connect VPN\n"
            "• Close Chrome fully",
            title="Action Required",
            style="yellow"
        ))
        sys.exit(0)

    console.print()
    console.print("[green]✅ Prerequisites confirmed. Let's continue.[/green]")
    console.print()


# ─────────────────────────────────────────────────────────────
# STEP 2 — Collect URLs from user
# ─────────────────────────────────────────────────────────────

def collect_urls() -> list[str]:
    console.print(Panel(
        f"[bold white]Enter Chalk page URLs[/bold white]\n"
        f"[dim]Enter one URL per line. Maximum {MAX_URLS} URLs.\n"
        f"Type [bold]DONE[/bold] on a new line when finished.[/dim]\n\n"
        f"[dim]Example:\n"
        f"  https://chalk.charter.com/spaces/SEIOTCH/pages/3247430367/SAX1V1K_v5.4.0-ENG4[/dim]",
        style="blue",
        padding=(1, 2)
    ))

    raw_urls = []
    url_num  = 1

    while url_num <= MAX_URLS:
        try:
            entry = console.input(f"  [cyan]URL {url_num:02d}[/cyan] → ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Cancelled.[/yellow]")
            sys.exit(0)

        # User signals they are done
        if entry.upper() in ("DONE", "D", ""):
            if url_num == 1:
                console.print("[red]  Please enter at least one URL.[/red]")
                continue
            break

        raw_urls.append(entry)
        url_num += 1

        if url_num > MAX_URLS:
            console.print(f"\n  [yellow]Maximum of {MAX_URLS} URLs reached.[/yellow]")
            break

    return raw_urls


# ─────────────────────────────────────────────────────────────
# STEP 3 — Validate URLs and show summary to user
# ─────────────────────────────────────────────────────────────

def validate_and_confirm(raw_urls: list[str]) -> list[str]:
    console.print()
    console.print("[dim]Validating URLs...[/dim]")

    valid_urls, errors = validate_all_urls(raw_urls)

    # Show any validation errors
    display_failed_urls(errors)

    if not valid_urls:
        console.print("[bold red]No valid URLs to process. Please run the tool again.[/bold red]")
        sys.exit(0)

    # Show validated URLs as a confirmation table
    console.print(f"[bold green]✅ {len(valid_urls)} valid URL(s) ready to scrape:[/bold green]")
    console.print()

    confirm_table = Table(box=box.SIMPLE, padding=(0, 2), show_header=True, header_style="bold")
    confirm_table.add_column("#",    width=4,  justify="right")
    confirm_table.add_column("URL",  style="cyan")

    for i, url in enumerate(valid_urls, 1):
        confirm_table.add_row(str(i), url)

    console.print(confirm_table)
    console.print()

    # Final confirmation before opening browser
    proceed = Confirm.ask(
        "[bold]Proceed with scraping these URLs?[/bold]",
        default=True
    )

    if not proceed:
        console.print("[yellow]Scraping cancelled.[/yellow]")
        sys.exit(0)

    return valid_urls


# ─────────────────────────────────────────────────────────────
# STEP 4 — Run the scraper
# ─────────────────────────────────────────────────────────────

def run_scraping(valid_urls: list[str]):
    display_scraping_start(len(valid_urls))

    results = []

    try:
        with ChalkScraper() as scraper:
            results = scraper.scrape_all(
                urls=valid_urls,
                progress_callback=display_progress
            )

    except Exception as e:
        console.print()
        console.print(Panel(
            f"[bold red]❌ Scraping failed:[/bold red] {str(e)}\n\n"
            f"[dim]Common causes:\n"
            f"• Chrome is still open — please close it fully\n"
            f"• Chrome profile path not found\n"
            f"• VPN disconnected during scraping[/dim]",
            title="Error",
            style="red"
        ))
        logging.error(f"Scraping failed: {e}", exc_info=True)
        sys.exit(1)

    return results


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    setup_logging()

    # Step 1 — Welcome + prerequisite check
    show_welcome()

    # Step 2 — Collect URLs from user
    raw_urls = collect_urls()

    # Step 3 — Validate + confirm
    valid_urls = validate_and_confirm(raw_urls)

    # Step 4 — Scrape
    results = run_scraping(valid_urls)

    # Step 5 — Display all collected data
    display_all_results(results)

    # Step 6 — Done (email sending will be added in Part 2)
    console.print()
    console.print(Panel(
        "[bold green]✅ Part 1 Complete![/bold green]\n\n"
        "[white]All Chalk data has been collected and displayed above.\n"
        "Email sending (Part 2) will be added next.[/white]",
        style="green",
        padding=(1, 4)
    ))
    console.print()


if __name__ == "__main__":
    main()