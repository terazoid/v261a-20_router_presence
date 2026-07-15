"""Device tracker platform for the Huawei OptiXstar v261a-20 Router Presence integration.

Each MAC address seen by the router becomes a `device_tracker.*` entity.
Entities are created dynamically as new MACs show up in coordinator data,
so you don't need to pre-declare devices anywhere.

Presence uses a `consider_home` grace period (configurable via the
integration's Options): a device stays "home" for that many seconds after
it was last reported online, even if a poll misses it (e.g. phone wifi
radio sleeping).
"""
from __future__ import annotations

from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import V261A20RouterPresenceCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: V261A20RouterPresenceCoordinator = hass.data[DOMAIN][entry.entry_id]
    tracked_macs: set[str] = set()

    @callback
    def _add_new_entities() -> None:
        new_entities = [
            RouterScannerEntity(coordinator, mac)
            for mac in coordinator.data
            if mac not in tracked_macs
        ]
        if new_entities:
            tracked_macs.update(e.mac_address for e in new_entities)
            async_add_entities(new_entities)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


class RouterScannerEntity(CoordinatorEntity, ScannerEntity):
    """Represents a single MAC address tracked via the v261a-20 router."""

    _attr_should_poll = False

    def __init__(self, coordinator: V261A20RouterPresenceCoordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = mac

    @property
    def source_type(self) -> SourceType:
        return SourceType.ROUTER

    @property
    def mac_address(self) -> str:
        return self._mac

    @property
    def is_connected(self) -> bool:
        return self.coordinator.is_home(self._mac)

    @property
    def hostname(self) -> str | None:
        dev = self.coordinator.data.get(self._mac)
        return dev.get("HostName") if dev else None

    @property
    def name(self) -> str:
        dev = self.coordinator.data.get(self._mac)
        if dev and dev.get("HostName"):
            return dev["HostName"]
        return self._mac

    @property
    def device_info(self) -> DeviceInfo:
        dev = self.coordinator.data.get(self._mac) or {}
        return DeviceInfo(
            identifiers={(DOMAIN, self._mac)},
            connections={("mac", self._mac)},
            name=dev.get("HostName") or self._mac,
            via_device=(DOMAIN, self.coordinator.entry_id),
        )
