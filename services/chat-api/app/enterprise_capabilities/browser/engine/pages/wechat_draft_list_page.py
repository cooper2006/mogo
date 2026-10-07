from __future__ import annotations
from app.infrastructure.observability.config import log_print

from playwright.async_api import Page


class WeChatDraftListPage:
    def __init__(self, page: Page) -> None:
        self.page = page

    async def find_draft(self, title: str) -> bool:
        loc = self.page.get_by_text(title).first
        try:
            await loc.wait_for(state="visible", timeout=5000)
            return True
        except Exception as exc:
            log_print(f"[enterprise_capabilities.browser.engine.pages.wechat_draft_list_page] silent exception caught: {exc}", flush=True)
            return False
