"""Device tracker platform for router-based MAC presence detection.

Configuration (configuration.yaml):

    device_tracker:
      - platform: router_presence
        host: 192.168.1.1
        username: Useradmin
        password: !secret router_password
        consider_home: 180

`consider_home` (seconds) is a core option HA applies automatically: a
tracked device stays "home" for this long after it last appears in
async_scan_devices(), so brief scan misses (wifi drop, router hiccup)
don't immediately flip someone to "away". 180s is a reasonable start;
raise it if your network is flaky.

To turn a MAC into a person's presence, add entries to
known_devices.yaml (auto-created after first run) or use
`track_new_devices: false` and register devices explicitly, then map
device_tracker.<name> entities to a `person:` entry in configuration.yaml.
"""
from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.device_tracker import (
    DOMAIN,
    PLATFORM_SCHEMA,
    DeviceScanner,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .router_client import RouterClient

_LOGGER = logging.getLogger(__name__)

MIN_SCAN_INTERVAL = timedelta(seconds=30)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
})


async def async_get_scanner(hass: HomeAssistant, config: ConfigType) -> "RouterDeviceScanner | None":
    conf = config[DOMAIN]
    scanner = RouterDeviceScanner(hass, conf)
    success = await scanner.async_init()
    return scanner if success else None


class RouterDeviceScanner(DeviceScanner):
    """Polls the router and reports which MACs are currently connected."""

    def __init__(self, hass: HomeAssistant, config: ConfigType) -> None:
        self.hass = hass
        self._client = RouterClient(
            host=config[CONF_HOST],
            username=config[CONF_USERNAME],
            password=config[CONF_PASSWORD],
        )
        # mac (lowercase) -> hostname
        self._devices: dict[str, str] = {}

    async def async_init(self) -> bool:
        """Validate we can actually log in before HA registers the scanner."""
        try:
            await self.hass.async_add_executor_job(self._client.get_devices)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Router presence: initial login/fetch failed: %s", err)
            return False
        return True

    async def async_scan_devices(self) -> list[str]:
        """Called by HA on the scan interval. Returns list of MACs seen as connected."""
        try:
            raw_devices = await self.hass.async_add_executor_job(self._client.get_devices)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Router presence: scan failed, keeping previous state: %s", err)
            return list(self._devices.keys())

        self._devices = {}
        for dev in raw_devices:
            mac = dev.get("MacAddr", "").lower()
            if not mac:
                continue
            # Only devices actively reporting "Online" count as present.
            if dev.get("DevStatus", "").lower() != "online":
                continue
            self._devices[mac] = dev.get("HostName") or mac

        return list(self._devices.keys())

    async def async_get_device_name(self, device: str) -> str | None:
        return self._devices.get(device.lower())
