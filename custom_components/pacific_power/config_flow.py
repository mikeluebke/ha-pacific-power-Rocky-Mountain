"""Config flow for Pacific Power integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    PacificPowerApi,
    PacificPowerAuthError,
    PacificPowerConnectionError,
)
from .const import (
    CONF_ACCOUNT_SEQUENCE,
    CONF_AGREEMENT_SEQUENCE,
    CONF_CUSTOMER_IDN,
    CONF_SERVICE_ADDRESS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

MANUAL_ACCOUNT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CUSTOMER_IDN): str,
        vol.Required(CONF_ACCOUNT_SEQUENCE, default="1"): str,
        vol.Required(CONF_AGREEMENT_SEQUENCE, default="1"): str,
        vol.Required(CONF_SERVICE_ADDRESS): str,
    }
)


class PacificPowerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Pacific Power."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._username: str = ""
        self._password: str = ""
        self._accounts: list[dict[str, str]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the credentials step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]

            session = async_create_clientsession(
                self.hass,
                cookie_jar=aiohttp.CookieJar(unsafe=True),
            )
            api = PacificPowerApi(session, self._username, self._password)

            try:
                await api.async_login()
            except PacificPowerAuthError:
                errors["base"] = "invalid_auth"
            except PacificPowerConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during login")
                errors["base"] = "unknown"
            else:
                accounts = await api.async_get_accounts()
                if len(accounts) == 1:
                    account = accounts[0]
                    unique_id = (
                        f"{account.customer_idn}_{account.account_sequence}"
                    )
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"Pacific Power ({account.address})",
                        data={
                            CONF_USERNAME: self._username,
                            CONF_PASSWORD: self._password,
                            CONF_CUSTOMER_IDN: account.customer_idn,
                            CONF_ACCOUNT_SEQUENCE: account.account_sequence,
                            CONF_AGREEMENT_SEQUENCE: account.agreement_sequence,
                            CONF_SERVICE_ADDRESS: account.address,
                        },
                    )

                if len(accounts) > 1:
                    self._accounts = [
                        {
                            CONF_CUSTOMER_IDN: a.customer_idn,
                            CONF_ACCOUNT_SEQUENCE: a.account_sequence,
                            CONF_AGREEMENT_SEQUENCE: a.agreement_sequence,
                            CONF_SERVICE_ADDRESS: a.address,
                        }
                        for a in accounts
                    ]
                    return await self.async_step_select_account()

                return await self.async_step_manual_account()

        return self.async_show_form(
            step_id="user",
            data_schema=CREDENTIALS_SCHEMA,
            errors=errors,
        )

    async def async_step_select_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle account selection for multi-account users."""
        if user_input is not None:
            selected = user_input["account"]
            for account in self._accounts:
                if account[CONF_SERVICE_ADDRESS] == selected:
                    unique_id = (
                        f"{account[CONF_CUSTOMER_IDN]}"
                        f"_{account[CONF_ACCOUNT_SEQUENCE]}"
                    )
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"Pacific Power ({account[CONF_SERVICE_ADDRESS]})",
                        data={
                            CONF_USERNAME: self._username,
                            CONF_PASSWORD: self._password,
                            **account,
                        },
                    )

        addresses = [a[CONF_SERVICE_ADDRESS] for a in self._accounts]
        return self.async_show_form(
            step_id="select_account",
            data_schema=vol.Schema(
                {vol.Required("account"): vol.In(addresses)}
            ),
        )

    async def async_step_manual_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual account entry when auto-discovery fails."""
        if user_input is not None:
            unique_id = (
                f"{user_input[CONF_CUSTOMER_IDN]}"
                f"_{user_input[CONF_ACCOUNT_SEQUENCE]}"
            )
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"Pacific Power ({user_input[CONF_SERVICE_ADDRESS]})",
                data={
                    CONF_USERNAME: self._username,
                    CONF_PASSWORD: self._password,
                    **user_input,
                },
            )

        return self.async_show_form(
            step_id="manual_account",
            data_schema=MANUAL_ACCOUNT_SCHEMA,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauth when credentials expire."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauth credential entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_create_clientsession(
                self.hass,
                cookie_jar=aiohttp.CookieJar(unsafe=True),
            )
            api = PacificPowerApi(
                session,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )

            try:
                await api.async_login()
            except PacificPowerAuthError:
                errors["base"] = "invalid_auth"
            except PacificPowerConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during reauth")
                errors["base"] = "unknown"
            else:
                entry = self.hass.config_entries.async_get_entry(
                    self.context["entry_id"]
                )
                if entry:
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={
                            **entry.data,
                            CONF_USERNAME: user_input[CONF_USERNAME],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=CREDENTIALS_SCHEMA,
            errors=errors,
        )
