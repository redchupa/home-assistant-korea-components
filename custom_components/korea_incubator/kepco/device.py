"""KEPCO device for Home Assistant integration."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Any, Optional, Union

import aiohttp
from curl_cffi import AsyncSession
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import KepcoApiClient
from .exceptions import KepcoAuthError
from ..const import DOMAIN, LOGGER


class KepcoDevice:
    """KEPCO device representation."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        username: str,
        password: str,
        session: Union[aiohttp.ClientSession, AsyncSession],
    ) -> None:
        """Initialize KEPCO device."""
        self.hass: HomeAssistant = hass
        self.entry_id: str = entry_id
        self.username: str = username
        self.password: str = password
        self.session: Union[aiohttp.ClientSession, AsyncSession] = session
        self.api_client: KepcoApiClient = KepcoApiClient(self.session)
        self.api_client.set_credentials(username, password)

        self._name: str = f"한전 ({username})"
        self._unique_id: str = f"kepco_{username}"
        self._available: bool = True
        self.data: Dict[str, Any] = {}
        self._last_update_success: Optional[datetime] = None

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return self._unique_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._unique_id)},
            name=self._name,
            manufacturer="한국전력공사",
            model="KEPCO",
            configuration_url="https://pp.kepco.co.kr",
        )

    @property
    def available(self) -> bool:
        """Return if device is available."""
        return self._available

    async def async_update(self) -> None:
        """Fetch data from KEPCO API."""
        try:
            recent_usage = await self.api_client.async_get_recent_usage()
            usage_info = await self.api_client.async_get_usage_info()
            self.data = {
                "recent_usage": recent_usage,
                "usage_info": usage_info,
            }
            self._available = True
            self._last_update_success = datetime.now()
            LOGGER.debug(f"KEPCO data updated successfully for {self.username}")
        except KepcoAuthError as err:
            self._available = False
            LOGGER.error(
                f"Authentication error updating KEPCO data for {self.username}: {err}"
            )
            raise UpdateFailed(f"Authentication error: {err}")
        except Exception as err:
            self._available = False
            LOGGER.error(f"Error updating KEPCO data for {self.username}: {err}")
            raise UpdateFailed(f"Error communicating with KEPCO API: {err}")

    def get_current_usage(self) -> Optional[Any]:
        """현재 사용량 조회"""
        try:
            return self.data.get("recent_usage", {}).get("result", {}).get("F_AP_QT")
        except (KeyError, AttributeError):
            return None

    def get_last_month_bill(self) -> Optional[Any]:
        """지난달 요금 조회"""
        try:
            return (
                self.data.get("usage_info", {}).get("result", {}).get("BILL_LAST_MONTH")
            )
        except (KeyError, AttributeError):
            return None

    def get_predicted_bill(self) -> Optional[Any]:
        """예상 요금 조회"""
        try:
            return (
                self.data.get("usage_info", {})
                .get("result", {})
                .get("PREDICT_TOTAL_CHARGE_REV")
            )
        except (KeyError, AttributeError):
            return None

    async def async_close_session(self) -> None:
        """Close the session."""
        if self.session:
            if isinstance(self.session, aiohttp.ClientSession):
                if not self.session.closed:
                    await self.session.close()
            elif isinstance(self.session, AsyncSession):
                await self.session.close()
            self.session = None
