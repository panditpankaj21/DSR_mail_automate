# ─────────────────────────────────────────────────────────────
# display.py  —  Show scraped data as clean tables in terminal
#
# Uses the `rich` library for beautiful terminal output.
# This is the "preview" step — shows all collected data
# before we send the email.
# ─────────────────────────────────────────────────────────────

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from rich.columns import Columns

from src.scraper import ChalkPageData

console = Console()


def display_all_results(results: list[ChalkPageData]):
    """
    Displays all scraped data in the terminal as formatted tables.
    One section per page URL.
    """
    console.print()
    console.print(Panel(
        f"[bold white]✅ Scraping Complete — {len(results)} page(s) processed[/bold white]",
        style="green",
        padding=(1, 4)
    ))
    console.print()

    success_count = sum(1 for r in results if r.scrape_success)
    fail_count    = len(results) - success_count

    console.print(f"  [green]✓ Successfully scraped:[/green] [bold]{success_count}[/bold]")
    if fail_count:
        console.print(f"  [red]✗ Failed:[/red] [bold]{fail_count}[/bold]")
    console.print()

    for i, data in enumerate(results, start=1):
        _display_single_page(i, len(results), data)

    # Final summary line
    console.print(Panel(
        "[bold]📋 Data collection complete. Ready to format email.[/bold]",
        style="blue",
        padding=(0, 4)
    ))


def _display_single_page(index: int, total: int, data: ChalkPageData):
    """Display scraped data for one page."""

    # ── Page Header ───────────────────────────────────────────
    console.print(Panel(
        f"[bold cyan]Page {index} of {total}:[/bold cyan]  [bold white]{data.page_title}[/bold white]\n"
        f"[dim]{data.url}[/dim]",
        style="cyan",
        padding=(0, 2)
    ))

    # ── Failed page ───────────────────────────────────────────
    if not data.scrape_success:
        console.print(f"  [bold red]❌ Scraping failed:[/bold red] {data.error_message}")
        console.print()
        return

    # ── SUMMARY TAB DATA ──────────────────────────────────────
    console.print("  [bold yellow]📄 SUMMARY TAB[/bold yellow]")
    console.print()

    s = data.summary

    summary_table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold white on dark_blue",
        padding=(0, 2),
        expand=False
    )
    summary_table.add_column("Field",  style="bold cyan",  width=30)
    summary_table.add_column("Value",  style="white",      width=50)

    # Add all summary fields as rows
    rows = [
        ("FW Version / Release",       s.fw_version           or "[dim]—[/dim]"),
        ("Status",                      _badge(s.status)                        ),
        ("On Schedule",                 _badge(s.on_schedule)                   ),
        ("Primary",                     s.primary              or "[dim]—[/dim]"),
        ("Testers",                     s.testers              or "[dim]—[/dim]"),
        ("PM",                          s.pm                   or "[dim]—[/dim]"),
        ("Start Date of Current Build", s.start_date           or "[dim]—[/dim]"),
        ("Completion Date",             s.completion_date      or "[dim]—[/dim]"),
        ("Release Dev Complete",        s.release_dev_complete or "[dim]—[/dim]"),
        ("Release Val Completion",      s.release_val_completion or "[dim]—[/dim]"),
        ("Release DLM Complete",        s.release_dlm_complete or "[dim]—[/dim]"),
        ("Type",                        s.type                 or "[dim]—[/dim]"),
        ("OSC Version",                 s.osc_version          or "[dim]—[/dim]"),
        ("Overall Summary",             s.overall_summary      or "[dim]—[/dim]"),
        ("CR Details",                  s.cr_details           or "[dim]—[/dim]"),
        ("HE",                          s.he                   or "[dim]—[/dim]"),
    ]

    for label, value in rows:
        summary_table.add_row(label, value)

    console.print(summary_table)
    console.print()

    # ── EXECUTION SUMMARY TAB DATA ────────────────────────────
    console.print("  [bold yellow]📊 EXECUTION SUMMARY TAB[/bold yellow]")
    console.print()

    if not data.execution_rows:
        console.print("  [dim]  No execution data found.[/dim]")
    else:
        exec_table = Table(
            box=box.SIMPLE_HEAD,
            show_header=True,
            header_style="bold white on dark_blue",
            padding=(0, 1),
        )

        exec_table.add_column("Execution Cycle",  style="bold cyan", width=30)
        exec_table.add_column("Total Planned",    justify="center",  width=14)
        exec_table.add_column("Total Executed",   justify="center",  width=14)
        exec_table.add_column("Passed",           justify="center",  width=10)
        exec_table.add_column("Passed %",         justify="center",  style="green",  width=10)
        exec_table.add_column("Failed",           justify="center",  width=10)
        exec_table.add_column("Failed %",         justify="center",  style="red",    width=10)
        exec_table.add_column("Blocked",          justify="center",  width=10)
        exec_table.add_column("Blocked %",        justify="center",  style="yellow", width=10)

        for row in data.execution_rows:
            exec_table.add_row(
                row.cycle,
                row.total_planned,
                row.total_executed,
                row.passed,
                row.passed_pct,
                row.failed,
                row.failed_pct,
                row.blocked,
                row.blocked_pct,
            )

        # Totals row
        t = data.execution_totals
        if t.total_planned or t.passed_pct:
            exec_table.add_section()
            exec_table.add_row(
                "[bold]TOTAL[/bold]",
                f"[bold]{t.total_planned}[/bold]",
                f"[bold]{t.total_executed}[/bold]",
                f"[bold]{t.passed}[/bold]",
                f"[bold green]{t.passed_pct}[/bold green]",
                f"[bold]{t.failed}[/bold]",
                f"[bold red]{t.failed_pct}[/bold red]",
                f"[bold]{t.blocked}[/bold]",
                f"[bold yellow]{t.blocked_pct}[/bold yellow]",
            )

        console.print(exec_table)

    console.print()
    console.rule(style="dim")
    console.print()


def _badge(value: str) -> str:
    """
    Colorize badge-like values.
    YES → green, NO → red, IN DEVTEST → blue, INPROGRESS → yellow
    """
    if not value:
        return "[dim]—[/dim]"

    v = value.upper().strip()

    if v in ("YES",):
        return f"[bold green]{value}[/bold green]"
    elif v in ("NO",):
        return f"[bold red]{value}[/bold red]"
    elif "DEVTEST" in v or "DEV TEST" in v:
        return f"[bold blue]{value}[/bold blue]"
    elif "INPROGRESS" in v or "IN PROGRESS" in v or "IN-PROGRESS" in v:
        return f"[bold yellow]{value}[/bold yellow]"
    elif "COMPLETE" in v or "DONE" in v:
        return f"[bold green]{value}[/bold green]"
    elif "TBD" in v:
        return f"[dim]{value}[/dim]"
    else:
        return value


def display_scraping_start(total_urls: int):
    """Show message when scraping begins."""
    console.print()
    console.print(Panel(
        f"[bold white]🔍 Starting scrape for {total_urls} URL(s)[/bold white]\n"
        f"[dim]Chrome will open automatically. Please do not click inside the browser.[/dim]",
        style="yellow",
        padding=(1, 4)
    ))
    console.print()


def display_progress(current: int, total: int, page_title: str):
    """Show progress for current page being scraped."""
    console.print(f"  [cyan]→[/cyan] [{current}/{total}] Scraping: [bold]{page_title}[/bold]...")


def display_failed_urls(errors: list[str]):
    """Show validation errors for bad URLs."""
    if not errors:
        return
    console.print()
    console.print("[bold red]⚠️  URL Validation Issues:[/bold red]")
    for err in errors:
        console.print(f"  [red]•[/red] {err}")
    console.print()