"""Arisu device for Home Assistant integration."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Any, Optional

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import ArisuApiClient
from .exceptions import ArisuAuthError, ArisuConnectionError, ArisuDataError
from ..const import DOMAIN, LOGGER, TZ_ASIA_SEOUL


class ArisuDevice:
    """Arisu (Seoul Water Works) device representation."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        customer_number: str,
        customer_name: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize Arisu device."""
        self.hass: HomeAssistant = hass
        self.entry_id: str = entry_id
        self.customer_number: str = customer_number
        self.customer_name: str = customer_name
        self.session: aiohttp.ClientSession = session
        self.api_client: ArisuApiClient = ArisuApiClient(self.session)

        self._name: str = f"아리수 ({customer_number})"
        self._unique_id: str = f"arisu_{entry_id}"
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
            manufacturer="서울특별시 상수도사업본부",
            model="아리수",
            configuration_url="https://arisu.seoul.go.kr",
        )

    @property
    def available(self) -> bool:
        """Return if device is available."""
        return self._available

    async def async_update(self) -> None:
        """Fetch data from Arisu API."""
        try:
            # Get water bill data
            bill_data = await self.api_client.async_get_water_bill_data(
                self.customer_number, self.customer_name
            )

            if not bill_data.get("success"):
                raise ArisuAuthError("Failed to retrieve water bill data")

            self.data = {
                "bill_data": bill_data,
                "last_updated": datetime.now(TZ_ASIA_SEOUL).isoformat(),
            }

            self._available = True
            self._last_update_success = datetime.now(TZ_ASIA_SEOUL)
            LOGGER.debug(f"Arisu data updated successfully for {self.customer_number}")

        except (ArisuAuthError, ArisuConnectionError, ArisuDataError) as err:
            self._available = False
            LOGGER.error(
                f"Error updating Arisu data for {self.customer_number}: {err}"
            )
            raise UpdateFailed(f"Error communicating with Arisu API: {err}") from err

        except Exception as err:
            self._available = False
            LOGGER.error(
                f"Unexpected error updating Arisu data for {self.customer_number}: {err}"
            )
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def async_close_session(self) -> None:
        """Close the aiohttp session."""
        if self.session:
            try:
                await self.session.close()
            except Exception as e:
                LOGGER.debug(f"Error closing session: {e}")
            finally:
                self.session = None
