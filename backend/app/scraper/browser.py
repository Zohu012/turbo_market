"""
Browser manager: wraps Playwright in either headless or CDP mode.

SCRAPER_MODE=headless  — launches Chromium headless with stealth patches (Docker/production)
SCRAPER_MODE=cdp       — connects to existing Chrome on CDP_URL (local dev)
"""
import logging
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Playwright

from app.config import settings

log = logging.getLogger(__name__)

BROWSER_PROFILE_DIR = Path(__file__).parent.parent.parent / "browser_profile"


class BrowserManager:
    """Holds a single Browser + BrowserContext for the lifetime of a Celery worker."""

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    def start(self):
        self._playwright = sync_playwright().start()
        if settings.scraper_mode == "cdp":
            self._browser = self._playwright.chromium.connect_over_cdp(settings.cdp_url)
            self._context = self._browser.contexts[0]
            # Reuse an existing turbo.az page or open new one
            self._page = next(
                (p for p in self._context.pages if "turbo.az" in p.url), None
            ) or self._context.new_page()
        else:
            # Headless with persistent profile for Cloudflare trust accumulation
            BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            self._context = self._playwright.chromium.launch_persistent_context(
                str(BROWSER_PROFILE_DIR),
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            self._apply_stealth(self._context)
            self._page = self._context.new_page()
        log.info(f"Browser started (mode={settings.scraper_mode})")
        return self

    def _apply_stealth(self, context: BrowserContext):
        try:
            from playwright_stealth import stealth_sync
            # Apply stealth to each new page opened in this context
            context.on("page", stealth_sync)
            # Also apply to existing pages
            for page in context.pages:
                stealth_sync(page)
        except ImportError:
            log.warning("playwright-stealth not installed; running without stealth patches")

    def get_page(self) -> Page:
        if self._page is None:
            raise RuntimeError("BrowserManager not started")
        return self._page

    def new_page(self) -> Page:
        if self._context is None:
            raise RuntimeError("BrowserManager not started")
        page = self._context.new_page()
        try:
            from playwright_stealth import stealth_sync
            stealth_sync(page)
        except ImportError:
            pass
        return page

    def close_page(self, page: Page):
        try:
            if page != self._page:
                page.close()
        except Exception:
            pass

    def stop(self):
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._page = self._context = self._browser = self._playwright = None
        log.info("Browser stopped")
