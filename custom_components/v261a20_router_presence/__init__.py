"""The Huawei OptiXstar v261a-20 Router Presence integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME, DEFAULT_SCAN_INTERVAL, DOMAIN
from .router_client import RouterClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.DEVICE_TRACKER]


class V261A20RouterPresenceCoordinator(DataUpdateCoordinator):
    """Coordinator that also tracks per-MAC last-seen timestamps.

    `self.data` holds every MAC ever seen for this entry, merged/updated on
    each poll (it never shrinks), so entity names/hostnames persist even if
    a device temporarily drops out of the router's response. `self.last_seen`
    holds the UTC timestamp each MAC was last reported "Online", which is
    what implements the `consider_home` grace period in device_tracker.py.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: RouterClient,
        consider_home: int,
    ) -> None:
        self.client = client
        self.consider_home = consider_home
        self.entry_id = entry.entry_id
        self.last_seen: dict[str, datetime] = {}
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _async_update_data(self) -> dict[str, dict]:
        try:
            devices = await self.hass.async_add_executor_job(self.client.get_devices)
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Error communicating with v261a-20 router: {err}") from err

        known = dict(self.data) if self.data else {}
        now = datetime.now(timezone.utc)

        for dev in devices:
            mac = dev.get("MacAddr", "").lower()
            if not mac:
                continue
            known[mac] = dev
            if dev.get("DevStatus", "").lower() == "online":
                self.last_seen[mac] = now

        return known

    def is_home(self, mac: str) -> bool:
        last = self.last_seen.get(mac)
        if last is None:
            return False
        return (datetime.now(timezone.utc) - last) < timedelta(seconds=self.consider_home)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the v261a-20 Router Presence integration from a config entry."""
    client = RouterClient(
        host=entry.data[CONF_HOST],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
    )

    consider_home = entry.options.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME)
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"OptiXstar v261a-20 ({entry.data[CONF_HOST]})",
        manufacturer="Huawei",
        model="OptiXstar v261a-20",
    )

    coordinator = V261A20RouterPresenceCoordinator(hass, entry, client, consider_home)
    coordinator.update_interval = timedelta(seconds=scan_interval)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options (scan_interval/consider_home) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
