"""DataUpdateCoordinator for Pacific Power Green Button data."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
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
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    AccountInfo,
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
from .espi import FLOW_FORWARD, FLOW_REVERSE, MeterReadingData, parse_green_button_xml

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(hours=12)
OVERLAP_DAYS = 30

STAT_ID_RE = re.compile(r"[^a-z0-9_]")

type PacificPowerConfigEntry = ConfigEntry[PacificPowerCoordinator]


@dataclass
class PacificPowerData:
    """Data returned by the coordinator."""

    account: AccountInfo
    last_data_received: datetime | None
    last_updated: datetime


def _slugify_stat_id(value: str) -> str:
    """Sanitize a string for use in a statistic_id."""
    return STAT_ID_RE.sub("_", value.lower()).strip("_")


def _make_statistic_id(account: AccountInfo, suffix: str) -> str:
    """Build a statistic_id from account info."""
    slug = _slugify_stat_id(
        f"{account.customer_idn}_{account.account_sequence}"
    )
    return f"{DOMAIN}:{slug}_{suffix}"


class PacificPowerCoordinator(DataUpdateCoordinator[dict[str, PacificPowerData]]):
    """Coordinator that fetches Green Button data and inserts statistics."""

    config_entry: PacificPowerConfigEntry

    def __init__(
        self,
        hass: Any,
        entry: PacificPowerConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self._entry = entry
        self._api: PacificPowerApi | None = None
        self._account = AccountInfo(
            customer_idn=entry.data[CONF_CUSTOMER_IDN],
            account_sequence=entry.data[CONF_ACCOUNT_SEQUENCE],
            agreement_sequence=entry.data[CONF_AGREEMENT_SEQUENCE],
            address=entry.data[CONF_SERVICE_ADDRESS],
        )

    def _create_api(self) -> PacificPowerApi:
        """Create a fresh API client with a new session."""
        session = async_create_clientsession(
            self.hass,
            cookie_jar=aiohttp.CookieJar(unsafe=True),
        )
        return PacificPowerApi(
            session=session,
            username=self._entry.data[CONF_USERNAME],
            password=self._entry.data[CONF_PASSWORD],
        )

    async def _async_update_data(
        self,
    ) -> dict[str, PacificPowerData]:
        """Fetch Green Button data and insert statistics."""
        self._api = self._create_api()

        try:
            await self._api.async_login()
        except PacificPowerAuthError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except PacificPowerConnectionError as err:
            raise UpdateFailed(f"Connection failed: {err}") from err

        try:
            last_data_ts = await self._fetch_and_insert_statistics()
        except PacificPowerApiError as err:
            raise UpdateFailed(f"Data fetch failed: {err}") from err

        now = datetime.now(UTC)
        key = f"{self._account.customer_idn}_{self._account.account_sequence}"
        return {
            key: PacificPowerData(
                account=self._account,
                last_data_received=last_data_ts,
                last_updated=now,
            )
        }

    async def _fetch_and_insert_statistics(self) -> datetime | None:
        """Fetch Green Button XML, parse it, and insert into HA statistics."""
        assert self._api is not None

        consumption_stat_id = _make_statistic_id(
            self._account, "energy_consumption"
        )

        last_stats = await self.hass.async_add_executor_job(
            get_last_statistics, self.hass, 1, consumption_stat_id, False, {"sum"}
        )

        months = 12
        if last_stats and consumption_stat_id in last_stats:
            last_stat = last_stats[consumption_stat_id][0]
            last_ts = datetime.fromtimestamp(last_stat["start"], tz=UTC)
            overlap_start = last_ts - timedelta(days=OVERLAP_DAYS)
            now = datetime.now(UTC)
            months_diff = (now.year - overlap_start.year) * 12 + (
                now.month - overlap_start.month
            )
            months = max(2, months_diff + 1)

        try:
            xml_data = await self._api.async_get_green_button_data(
                self._account, months=months
            )
        except PacificPowerApiError:
            _LOGGER.debug("Green Button download returned no data")
            return None

        if not xml_data or not xml_data.strip():
            _LOGGER.debug("Empty Green Button response")
            return None

        data = parse_green_button_xml(xml_data)
        if not data.usage_points:
            _LOGGER.debug("No usage points in Green Button data")
            return None

        latest_ts: datetime | None = None

        for up in data.usage_points:
            for mr in up.meter_readings:
                if not mr.readings:
                    continue

                flow = mr.reading_type.flow_direction
                if flow == FLOW_FORWARD:
                    suffix = "energy_consumption"
                elif flow == FLOW_REVERSE:
                    suffix = "energy_returned"
                else:
                    suffix = "energy_consumption"

                ts = await self._async_insert_meter_reading_stats(mr, suffix)
                if ts and (latest_ts is None or ts > latest_ts):
                    latest_ts = ts

        return latest_ts

    async def _async_insert_meter_reading_stats(
        self,
        mr: MeterReadingData,
        suffix: str,
    ) -> datetime | None:
        """Insert statistics for a single meter reading series."""
        stat_id = _make_statistic_id(self._account, suffix)

        name_suffix = "Consumption" if "consumption" in suffix else "Returned"
        name = f"Pacific Power {self._account.address} {name_suffix}"

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=name,
            source=DOMAIN,
            statistic_id=stat_id,
            unit_class="energy",
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )

        last_stats = await self.hass.async_add_executor_job(
            get_last_statistics, self.hass, 1, stat_id, False, {"sum", "start"}
        )

        last_sum = 0.0
        last_start: float = 0.0
        if last_stats and stat_id in last_stats:
            last_stat = last_stats[stat_id][0]
            last_sum = last_stat.get("sum", 0.0) or 0.0
            last_start = last_stat.get("start", 0.0) or 0.0

        readings_after_last = [
            r for r in mr.readings if r.start > last_start
        ]

        if not readings_after_last:
            _LOGGER.debug(
                "No new readings for %s (last_start=%s)", stat_id, last_start
            )
            return None

        running_sum = last_sum
        statistics: list[StatisticData] = []

        for reading in readings_after_last:
            start_dt = datetime.fromtimestamp(reading.start, tz=UTC)
            start_dt = start_dt.replace(minute=0, second=0, microsecond=0)

            running_sum += reading.value_kwh
            statistics.append(
                StatisticData(
                    start=start_dt,
                    state=reading.value_kwh,
                    sum=running_sum,
                )
            )

        if statistics:
            async_add_external_statistics(self.hass, metadata, statistics)
            _LOGGER.debug(
                "Inserted %d statistics for %s", len(statistics), stat_id
            )

        latest_reading = readings_after_last[-1]
        return datetime.fromtimestamp(latest_reading.start, tz=UTC)
