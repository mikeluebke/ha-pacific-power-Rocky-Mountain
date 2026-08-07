"""Pacific Power API client using Playwright for browser automation.

The Pacific Power portal encrypts API request bodies and signs them with
a session-derived key (X-WCSSS-Content-Signature header). Rather than
reverse-engineering the crypto from minified Angular JS, we use a headless
browser to execute the portal's own JavaScript.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)

from .const import BASE_URL

_LOGGER = logging.getLogger(__name__)

LOGIN_TIMEOUT = 60000
NAV_TIMEOUT = 30000
API_TIMEOUT = 60000

GREEN_BUTTON_JS = """
async ({customerIDN, accountSequence, agreementSequence, startDate, endDate, numberOfMonths, graphWindow, address}) => {
    const body = {
        getGreenButtonDataRequestBody: {
            agreement: { customerIDN, accountSequence, agreementSequence },
            dateRange: { startDate, endDate, numberOfMonths: String(numberOfMonths) },
            graphDetails: { graphWindow, address }
        }
    };
    const response = await fetch("/api/energy-usage/getGreenButtonData", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json, text/plain, */*" },
        credentials: "same-origin",
        body: JSON.stringify(body)
    });
    if (!response.ok) {
        return { error: `HTTP ${response.status}`, status: response.status };
    }
    const data = await response.json();
    if (data.getGreenButtonDataResponseBody) {
        return { xml: data.getGreenButtonDataResponseBody.xmlPayload || JSON.stringify(data) };
    }
    const text = JSON.stringify(data);
    if (text.includes("IntervalReading")) {
        return { xml: text };
    }
    return { error: "Unexpected response format", body: text.substring(0, 500) };
}
"""


class PacificPowerApiError(Exception):
    """Base exception for Pacific Power API errors."""


class PacificPowerAuthError(PacificPowerApiError):
    """Authentication failed."""


class PacificPowerConnectionError(PacificPowerApiError):
    """Connection to Pacific Power failed."""


@dataclass
class AccountInfo:
    """Pacific Power account information."""

    customer_idn: str
    account_sequence: str
    agreement_sequence: str
    address: str


class PacificPowerApi:
    """Client for Pacific Power's portal using Playwright browser automation."""

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def async_start(self) -> None:
        """Launch the browser."""
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        except Exception as err:
            raise PacificPowerConnectionError(
                f"Failed to launch browser: {err}"
            ) from err

    async def async_stop(self) -> None:
        """Close the browser and clean up."""
        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    async def async_login(self) -> None:
        """Log in to the Pacific Power portal via the browser."""
        if not self._browser:
            await self.async_start()

        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()

        try:
            await self._page.goto(
                f"{BASE_URL}/secure/my-account/energy-usage",
                wait_until="networkidle",
                timeout=LOGIN_TIMEOUT,
            )
        except Exception as err:
            raise PacificPowerConnectionError(
                "Failed to load Pacific Power portal"
            ) from err

        if "login.csapps.pacificpower.net" in self._page.url:
            await self._handle_b2c_login()
        elif "/idm/login" in self._page.url:
            raise PacificPowerAuthError("Unexpected login page format")

    async def _handle_b2c_login(self) -> None:
        """Fill and submit the Azure AD B2C login form."""
        page = self._page
        assert page is not None

        try:
            await page.wait_for_selector("#signInName", timeout=NAV_TIMEOUT)
        except Exception as err:
            raise PacificPowerAuthError(
                "Login form did not load"
            ) from err

        await page.fill("#signInName", self._username)
        await page.fill("#password", self._password)
        await page.click("#next")

        try:
            await page.wait_for_url(
                f"{BASE_URL}/**", timeout=LOGIN_TIMEOUT
            )
        except Exception:
            current = page.url
            if "login.csapps.pacificpower.net" in current:
                error_el = await page.query_selector(".error, .errorMessage, #errorMessage")
                if error_el:
                    error_text = await error_el.text_content()
                    raise PacificPowerAuthError(
                        f"Login failed: {error_text}"
                    )
                raise PacificPowerAuthError("Login failed — credentials may be invalid")
            raise PacificPowerConnectionError("Login timed out")

        await page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT)

    async def async_get_green_button_data(
        self,
        account: AccountInfo,
        months: int = 12,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> str:
        """Download Green Button XML data via the portal's Angular app."""
        page = self._page
        if not page:
            raise PacificPowerApiError("Not logged in")

        now = datetime.now()
        if end_date is None:
            end_date = now
        if start_date is None:
            from dateutil.relativedelta import relativedelta
            start_date = now - relativedelta(months=months)

        params = {
            "customerIDN": account.customer_idn,
            "accountSequence": account.account_sequence,
            "agreementSequence": account.agreement_sequence,
            "startDate": start_date.strftime("%m/%d/%Y"),
            "endDate": end_date.strftime("%m/%d/%Y"),
            "numberOfMonths": str(months),
            "graphWindow": "daily",
            "address": account.address,
        }

        if "/secure/" not in page.url:
            try:
                await page.goto(
                    f"{BASE_URL}/secure/my-account/energy-usage",
                    wait_until="networkidle",
                    timeout=NAV_TIMEOUT,
                )
            except Exception as err:
                raise PacificPowerConnectionError(
                    "Failed to navigate to energy usage page"
                ) from err

        try:
            result = await page.evaluate(GREEN_BUTTON_JS, params)
        except Exception as err:
            raise PacificPowerApiError(
                f"Green Button API call failed: {err}"
            ) from err

        if not result:
            raise PacificPowerApiError("Green Button API returned empty result")

        if "error" in result:
            status = result.get("status", "")
            if status == 401:
                raise PacificPowerAuthError("Session expired during data fetch")
            raise PacificPowerApiError(
                f"Green Button API error: {result['error']}"
            )

        xml = result.get("xml", "")
        if not xml:
            raise PacificPowerApiError("Green Button response contained no XML data")

        if not ("IntervalReading" in xml or "<?xml" in xml or "<feed" in xml):
            raise PacificPowerApiError("Response does not contain valid Green Button XML")

        return xml
