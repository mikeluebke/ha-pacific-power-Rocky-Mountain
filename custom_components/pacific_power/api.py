"""Pacific Power API client for Azure AD B2C authentication and Green Button data."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime

import aiohttp

from .const import (
    BASE_URL,
    B2C_CLIENT_ID,
    B2C_LOGIN_URL,
    B2C_POLICY,
    GREEN_BUTTON_PATH,
    OAUTH_INIT_PATH,
)

_LOGGER = logging.getLogger(__name__)

SETTINGS_RE = re.compile(r"var\s+SETTINGS\s*=\s*(\{.*?\})\s*;", re.DOTALL)
CSRF_META_RE = re.compile(
    r'<meta\s+name=["\']_csrf["\']\s+content=["\']([^"\']+)["\']', re.IGNORECASE
)
CSRF_INPUT_RE = re.compile(
    r'<input[^>]+name=["\']_csrf["\']\s+value=["\']([^"\']+)["\']', re.IGNORECASE
)
XSRF_COOKIE = "XSRF-TOKEN"


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
    """Client for Pacific Power's portal."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._csrf_token: str | None = None

    async def async_login(self) -> None:
        """Authenticate via Azure AD B2C and establish a session."""
        try:
            b2c_html = await self._initiate_oauth()
            settings = self._extract_settings(b2c_html)
            await self._submit_credentials(settings)
            await self._confirm_signin(settings)
        except PacificPowerApiError:
            raise
        except aiohttp.ClientError as err:
            raise PacificPowerConnectionError(
                "Failed to connect to Pacific Power"
            ) from err

    async def _initiate_oauth(self) -> str:
        """Start the OAuth flow and return the B2C login page HTML."""
        url = f"{BASE_URL}{OAUTH_INIT_PATH}"
        async with self._session.get(
            url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            if resp.status != 200:
                raise PacificPowerConnectionError(
                    f"OAuth initiation returned status {resp.status}"
                )
            return await resp.text()

    def _extract_settings(self, html: str) -> dict:
        """Extract the SETTINGS object from the B2C login page."""
        match = SETTINGS_RE.search(html)
        if not match:
            raise PacificPowerAuthError(
                "Could not find SETTINGS on login page — portal may have changed"
            )
        raw = match.group(1)
        raw = re.sub(r",\s*}", "}", raw)
        raw = re.sub(r",\s*]", "]", raw)
        try:
            settings = json.loads(raw)
        except json.JSONDecodeError:
            trans_id = re.search(r'"transId"\s*:\s*"([^"]+)"', raw)
            csrf = re.search(r'"csrf"\s*:\s*"([^"]+)"', raw)
            if not trans_id or not csrf:
                raise PacificPowerAuthError(
                    "Could not parse SETTINGS from login page"
                )
            settings = {"transId": trans_id.group(1), "csrf": csrf.group(1)}
        if "transId" not in settings or "csrf" not in settings:
            raise PacificPowerAuthError("SETTINGS missing transId or csrf")
        return settings

    async def _submit_credentials(self, settings: dict) -> None:
        """POST credentials to the B2C SelfAsserted endpoint."""
        trans_id = settings["transId"]
        csrf = settings["csrf"]
        url = (
            f"{B2C_LOGIN_URL}/{B2C_POLICY.lower()}/SelfAsserted"
            f"?tx={trans_id}&p={B2C_POLICY}"
        )
        data = {
            "request_type": "RESPONSE",
            "signInName": self._username,
            "password": self._password,
        }
        headers = {
            "X-CSRF-TOKEN": csrf,
            "X-Requested-With": "XMLHttpRequest",
        }
        async with self._session.post(
            url,
            data=data,
            headers=headers,
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            body = await resp.text()
            if resp.status == 200 and '"status":"200"' in body:
                return
            if "INVALID_CREDENTIALS" in body or resp.status == 401:
                raise PacificPowerAuthError("Invalid username or password")
            if resp.status != 200:
                raise PacificPowerAuthError(
                    f"Credential submission returned status {resp.status}"
                )
            raise PacificPowerAuthError("Unexpected response during credential submission")

    async def _confirm_signin(self, settings: dict) -> None:
        """Confirm the B2C sign-in and follow redirects to establish session."""
        trans_id = settings["transId"]
        csrf = settings["csrf"]
        url = (
            f"{B2C_LOGIN_URL}/{B2C_POLICY.lower()}"
            f"/api/CombinedSigninAndSignup/confirmed"
            f"?csrf_token={csrf}&tx={trans_id}&p={B2C_POLICY}"
        )
        async with self._session.get(
            url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            if resp.status != 200:
                raise PacificPowerAuthError(
                    f"Sign-in confirmation returned status {resp.status}"
                )
            self._extract_csrf_from_cookies()

    def _extract_csrf_from_cookies(self) -> None:
        """Extract CSRF token from session cookies."""
        for cookie in self._session.cookie_jar:
            if cookie.key == XSRF_COOKIE:
                self._csrf_token = cookie.value
                return
        _LOGGER.debug("XSRF-TOKEN cookie not found, will try page extraction")

    async def _ensure_csrf(self) -> str:
        """Ensure we have a CSRF token, fetching from portal page if needed."""
        if self._csrf_token:
            return self._csrf_token

        async with self._session.get(
            f"{BASE_URL}/secure/my-account/dashboard",
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            html = await resp.text()

        match = CSRF_META_RE.search(html) or CSRF_INPUT_RE.search(html)
        if match:
            self._csrf_token = match.group(1)
            return self._csrf_token

        self._extract_csrf_from_cookies()
        if self._csrf_token:
            return self._csrf_token

        raise PacificPowerApiError("Could not obtain CSRF token")

    async def async_get_accounts(self) -> list[AccountInfo]:
        """Discover account information from the energy usage page."""
        try:
            async with self._session.get(
                f"{BASE_URL}/secure/energy-usage",
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("Energy usage page returned status %s", resp.status)
                    return []
                html = await resp.text()

            return self._parse_accounts(html)
        except aiohttp.ClientError:
            _LOGGER.debug("Failed to fetch energy usage page for account discovery")
            return []

    def _parse_accounts(self, html: str) -> list[AccountInfo]:
        """Extract account details from the energy usage page HTML."""
        accounts: list[AccountInfo] = []

        customer_idn_match = re.search(
            r'customerIDN["\']?\s*[:=]\s*["\']?(\d+)', html
        )
        account_seq_match = re.search(
            r'accountSequence["\']?\s*[:=]\s*["\']?(\d+)', html
        )
        agreement_seq_match = re.search(
            r'agreementSequence["\']?\s*[:=]\s*["\']?(\d+)', html
        )
        address_match = re.search(
            r'address["\']?\s*[:=]\s*["\']([^"\']+)["\']', html
        )

        if customer_idn_match and account_seq_match:
            accounts.append(
                AccountInfo(
                    customer_idn=customer_idn_match.group(1),
                    account_sequence=account_seq_match.group(1),
                    agreement_sequence=(
                        agreement_seq_match.group(1) if agreement_seq_match else "1"
                    ),
                    address=address_match.group(1) if address_match else "Unknown",
                )
            )

        if not accounts:
            _LOGGER.debug("Could not auto-discover account details from page")

        return accounts

    async def async_get_green_button_data(
        self,
        account: AccountInfo,
        months: int = 12,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> str:
        """Download Green Button XML data for an account."""
        csrf = await self._ensure_csrf()

        now = datetime.now()
        if end_date is None:
            end_date = now
        if start_date is None:
            start_date = now.replace(
                year=now.year - (months // 12),
                month=max(1, now.month - (months % 12)),
            )

        form_data = {
            "numberOfMonths": str(months),
            "customerIDN": account.customer_idn,
            "accountSequence": account.account_sequence,
            "agreementSequence": account.agreement_sequence,
            "address": account.address,
            "graphWindow": "daily",
            "startDate": start_date.strftime("%m/%d/%Y"),
            "endDate": end_date.strftime("%m/%d/%Y"),
            "filename": f"PacificPower_GreenButton_{now.strftime('%m%d%Y')}.xml",
            "_csrf": csrf,
        }

        try:
            async with self._session.post(
                f"{BASE_URL}{GREEN_BUTTON_PATH}",
                data=form_data,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    raise PacificPowerApiError(
                        f"Green Button download returned status {resp.status}"
                    )
                body = await resp.text()
        except aiohttp.ClientError as err:
            raise PacificPowerConnectionError(
                "Failed to download Green Button data"
            ) from err

        if not body or not body.strip():
            raise PacificPowerApiError("Green Button download returned empty response")

        if body.strip().startswith("<?xml") or body.strip().startswith("<feed"):
            return body

        try:
            payload = json.loads(body)
            if "xmlPayload" in payload:
                return payload["xmlPayload"]
        except (json.JSONDecodeError, KeyError):
            pass

        if "<" in body and "IntervalReading" in body:
            return body

        raise PacificPowerApiError("Unexpected response format from Green Button download")
