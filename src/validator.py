# ─────────────────────────────────────────────────────────────
# validator.py  —  URL and input validation
# ─────────────────────────────────────────────────────────────

import re
from urllib.parse import urlparse
from src.config import CHALK_BASE_DOMAIN, MAX_URLS


class ValidationError(Exception):
    """Raised when a URL or input fails validation."""
    pass


def extract_page_id(url: str) -> str | None:
    """
    Extracts the Confluence page ID from a Chalk URL.

    Example URL:
      https://chalk.charter.com/spaces/SEIOTCH/pages/3247430367/SAX1V1K_v5.4.0-ENG4
                                                      ^^^^^^^^^^
                                                      This is the page ID

    Returns the page ID string, or None if not found.
    """
    # Match the numeric page ID in the URL path
    match = re.search(r'/pages/(\d+)', url)
    if match:
        return match.group(1)
    return None


def validate_single_url(url: str) -> str:
    """
    Validates a single Chalk URL. Returns cleaned URL or raises ValidationError.

    Checks:
    1. Not empty
    2. Starts with http:// or https://
    3. Is from chalk.charter.com domain
    4. Contains a numeric page ID in the path
    """
    url = url.strip()

    # Check 1 — not empty
    if not url:
        raise ValidationError("URL cannot be empty.")

    # Check 2 — must have http/https scheme
    if not url.startswith(("http://", "https://")):
        # Try adding https:// and see if it works
        url = "https://" + url

    # Check 3 — must be chalk.charter.com
    parsed = urlparse(url)
    if CHALK_BASE_DOMAIN not in parsed.netloc:
        raise ValidationError(
            f"Invalid domain '{parsed.netloc}'. URL must be from {CHALK_BASE_DOMAIN}"
        )

    # Check 4 — must have a page ID
    page_id = extract_page_id(url)
    if not page_id:
        raise ValidationError(
            f"Cannot find page ID in URL. "
            f"Expected format: https://chalk.charter.com/spaces/SPACE/pages/PAGE_ID/title"
        )

    return url


def validate_all_urls(raw_urls: list[str]) -> tuple[list[str], list[str]]:
    """
    Validates a list of URLs.

    Returns:
        valid_urls   — list of clean, validated URLs
        errors       — list of error messages for invalid ones

    Also handles:
    - Removes duplicates (keeps first occurrence)
    - Enforces MAX_URLS limit
    - Skips blank lines
    """
    valid_urls   = []
    errors       = []
    seen_page_ids = set()  # to detect duplicates

    # Filter out completely blank entries first
    raw_urls = [u for u in raw_urls if u.strip()]

    # Check max URL count
    if len(raw_urls) > MAX_URLS:
        errors.append(
            f"Too many URLs provided ({len(raw_urls)}). Maximum allowed is {MAX_URLS}."
        )
        # Still process the first MAX_URLS ones
        raw_urls = raw_urls[:MAX_URLS]

    for i, url in enumerate(raw_urls, start=1):
        try:
            clean_url = validate_single_url(url)
            page_id   = extract_page_id(clean_url)

            # Check for duplicates
            if page_id in seen_page_ids:
                errors.append(f"URL {i}: Duplicate page ID '{page_id}' — skipping.")
                continue

            seen_page_ids.add(page_id)
            valid_urls.append(clean_url)

        except ValidationError as e:
            errors.append(f"URL {i} ('{url[:60]}...' if len(url)>60 else url): {e}")

    return valid_urls, errors


def get_page_title_from_url(url: str) -> str:
    """
    Extracts a human-readable title from the URL for display purposes.

    https://chalk.charter.com/spaces/SEIOTCH/pages/3247430367/SAX1V1K_v5.4.0-ENG4
    → "SAX1V1K_v5.4.0-ENG4"
    """
    parts = url.rstrip("/").split("/")
    if len(parts) >= 1:
        # Last part of URL is usually the page title slug
        title = parts[-1]
        # Replace hyphens/underscores with spaces for display
        return title.replace("-", " ").replace("_", " ")
    return url