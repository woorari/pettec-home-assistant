"""PetTec (Snoop Cube) integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import (
    CONF_COUNTRY_CODE,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PHONE_CODE,
    DEFAULT_COUNTRY_CODE,
    DEFAULT_PHONE_CODE,
    DOMAIN,
)
from .meari_api import MeariApiError, MeariAuthError, MeariClient, MeariSessionBumpedError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BUTTON]


@dataclass
class PettecData:
    client: MeariClient
    feeders: list[dict]  # raw device dicts from get_device_list


type PettecConfigEntry = ConfigEntry[PettecData]


async def async_setup_entry(hass: HomeAssistant, entry: PettecConfigEntry) -> bool:
    """Login, discover feeders, store on entry, forward to button platform."""
    # Dedicated aiohttp session — isolates our auth state from HA's shared
    # session (which carries cookies/state from other integrations and seems
    # to interfere with Meari's per-token session tracking).
    import aiohttp
    http = async_create_clientsession(
        hass,
        cookie_jar=aiohttp.DummyCookieJar(),
        headers={"User-Agent": "PettecHA/0.1"},
    )
    client = MeariClient(
        http=http,
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        country_code=entry.data.get(CONF_COUNTRY_CODE, DEFAULT_COUNTRY_CODE),
        phone_code=entry.data.get(CONF_PHONE_CODE, DEFAULT_PHONE_CODE),
    )
    try:
        await client.login()
        feeders = await client.list_feeders_with_retry()
    except MeariAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except MeariSessionBumpedError as err:
        # The Meari cloud invalidated our token. Either another login on
        # the same account happened, or the request didn't sign cleanly.
        # Surface as not-ready so HA retries on a backoff.
        raise ConfigEntryNotReady(
            "Meari session was invalidated. HA will retry."
        ) from err
    except MeariApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    _LOGGER.info("PetTec setup: found %d feeder(s)", len(feeders))
    entry.runtime_data = PettecData(client=client, feeders=feeders)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PettecConfigEntry) -> bool:
    """Unload platforms."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
