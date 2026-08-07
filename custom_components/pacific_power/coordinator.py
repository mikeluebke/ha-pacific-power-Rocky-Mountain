"""DataUpdateCoordinator for Pacific Power energy data."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, UnitOfEnergy
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    AccountInfo,
    DailyUsage,
    PacificPowerApi,
    PacificPowerApiError,
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

UPDATE_INTERVAL = timedelta(hours=12)
OVERLAP_DAYS = 30
INITIAL_HISTORY_DAYS = 365

_STAT_ID_RE = re.compile(r"[^a-z0-9_]")

type PacificPowerConfigEntry = ConfigEntry[PacificPowerCoordinator]


@dataclass
class PacificPowerData:
    """Data returned by the coordinator."""

    account: AccountInfo
    last_data_received: datetime | None
    last_updated: datetime


def _slugify(value: str) -> str:
    return _STAT_ID_RE.sub("_", value.lower()).strip("_")


def _make_stat_id(account: AccountInfo) -> str:
    slug = _slugify(f"{account.customer_idn}_{account.account_sequence}")
    return f"{DOMAIN}:{slug}_energy_consumption"


class PacificPowerCoordinator(DataUpdateCoordinator[dict[str, PacificPowerData]]):
    """Fetches daily energy data and inserts HA statistics."""

    config_entry: PacificPowerConfigEntry

    def __init__(self, hass: Any, entry: PacificPowerConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=UPDATE_INTERVAL
        )
        self._entry = entry
        self._account = AccountInfo(
            customer_idn=entry.data[CONF_CUSTOMER_IDN],
            account_sequence=entry.data[CONF_ACCOUNT_SEQUENCE],
            agreement_sequence=entry.data[CONF_AGREEMENT_SEQUENCE],
            address=entry.data[CONF_SERVICE_ADDRESS],
        )

    async def _async_update_data(
        self,
    ) -> dict[str, PacificPowerData]:
        api = PacificPowerApi(
            username=self._entry.data[CONF_USERNAME],
            password=self._entry.data[CONF_PASSWORD],
        )
        try:
            await api.async_start()
            await api.async_login()

            user = await api.async_get_user_info()
            await api.async_get_accounts(user.get("webUserId", ""))

            last_data_ts = await self._fetch_and_insert(api)
        except PacificPowerAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except PacificPowerConnectionError as err:
            raise UpdateFailed(str(err)) from err
        except PacificPowerApiError as err:
            raise UpdateFailed(str(err)) from err
        finally:
            await api.async_stop()

        now = datetime.now(UTC)
        key = f"{self._account.customer_idn}_{self._account.account_sequence}"
        return {
            key: PacificPowerData(
                account=self._account,
                last_data_received=last_data_ts,
                last_updated=now,
            )
        }

    async def _fetch_and_insert(self, api: PacificPowerApi) -> datetime | None:
        stat_id = _make_stat_id(self._account)

        last_stats = await self.hass.async_add_executor_job(
            get_last_statistics, self.hass, 1, stat_id, False, {"sum", "start"}
        )

        now = datetime.now(UTC)
        if last_stats and stat_id in last_stats:
            last_stat = last_stats[stat_id][0]
            last_ts = datetime.fromtimestamp(last_stat["start"], tz=UTC)
            start = last_ts - timedelta(days=OVERLAP_DAYS)
            last_sum = last_stat.get("sum", 0.0) or 0.0
        else:
            start = now - timedelta(days=INITIAL_HISTORY_DAYS)
            last_sum = 0.0
            last_ts = None

        all_readings: list[DailyUsage] = []
        cursor = start.replace(day=1)
        while cursor <= now:
            month_end = (cursor.replace(day=28) + timedelta(days=4)).replace(
                day=1
            ) - timedelta(days=1)
            if month_end > now:
                month_end = now
            readings = await api.async_get_daily_usage(
                self._account, cursor, month_end
            )
            all_readings.extend(readings)
            cursor = month_end + timedelta(days=1)

        if not all_readings:
            _LOGGER.debug("No daily usage data returned")
            return None

        last_start_ts = last_ts.timestamp() if last_ts else 0.0
        new_readings = [
            r
            for r in all_readings
            if datetime.strptime(r.date, "%Y-%m-%d")
            .replace(tzinfo=UTC)
            .timestamp()
            > last_start_ts
            and r.kwh > 0
        ]
        if not new_readings:
            _LOGGER.debug("No new readings since last import")
            return None

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"Pacific Power {self._account.address}",
            source=DOMAIN,
            statistic_id=stat_id,
            unit_class="energy",
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )

        running_sum = last_sum
        statistics: list[StatisticData] = []
        for reading in new_readings:
            start_dt = datetime.strptime(reading.date, "%Y-%m-%d").replace(
                tzinfo=UTC
            )
            running_sum += reading.kwh
            statistics.append(
                StatisticData(
                    start=start_dt,
                    state=reading.kwh,
                    sum=running_sum,
                )
            )

        async_add_external_statistics(self.hass, metadata, statistics)
        _LOGGER.debug("Inserted %d statistics for %s", len(statistics), stat_id)

        last_reading = new_readings[-1]
        return datetime.strptime(last_reading.date, "%Y-%m-%d").replace(
            tzinfo=UTC
        )
