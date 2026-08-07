"""Config flow for Pacific Power integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

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

CONF_ACCOUNT_NUMBER = "account_number"

ACCOUNT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ACCOUNT_NUMBER): str,
        vol.Required(CONF_AGREEMENT_SEQUENCE, default="001"): str,
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

            api = PacificPowerApi(self._username, self._password)

            try:
                await api.async_start()
                await api.async_login()
            except PacificPowerAuthError:
                errors["base"] = "invalid_auth"
            except PacificPowerConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during login")
                errors["base"] = "unknown"
            else:
                return await self.async_step_account()
            finally:
                await api.async_stop()

        return self.async_show_form(
            step_id="user",
            data_schema=CREDENTIALS_SCHEMA,
            errors=errors,
        )

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle account details entry."""
        if user_input is not None:
            account_number = user_input[CONF_ACCOUNT_NUMBER].strip()
            if "-" in account_number:
                parts = account_number.split("-", 1)
                customer_idn = parts[0]
                account_seq = parts[1]
            else:
                customer_idn = account_number[:8]
                account_seq = account_number[8:] or "001"

            unique_id = f"{customer_idn}_{account_seq}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"Pacific Power ({user_input[CONF_SERVICE_ADDRESS]})",
                data={
                    CONF_USERNAME: self._username,
                    CONF_PASSWORD: self._password,
                    CONF_CUSTOMER_IDN: customer_idn,
                    CONF_ACCOUNT_SEQUENCE: account_seq,
                    CONF_AGREEMENT_SEQUENCE: user_input[CONF_AGREEMENT_SEQUENCE],
                    CONF_SERVICE_ADDRESS: user_input[CONF_SERVICE_ADDRESS],
                },
            )

        return self.async_show_form(
            step_id="account",
            data_schema=ACCOUNT_SCHEMA,
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
            api = PacificPowerApi(
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )

            try:
                await api.async_start()
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
            finally:
                await api.async_stop()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=CREDENTIALS_SCHEMA,
            errors=errors,
        )
