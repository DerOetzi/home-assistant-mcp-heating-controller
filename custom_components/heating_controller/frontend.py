"""Serve the Lovelace card that ships with this integration.

The card lives in the integration repo rather than a separate HACS plugin
repo so that card and integration can never drift apart in version. See
docs/card-design.md.
"""

from __future__ import annotations

import os

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

CARD_FILENAME = "heating-controller-card.js"
STATIC_URL_PATH = f"/{DOMAIN}_frontend"
CARD_URL = f"{STATIC_URL_PATH}/{CARD_FILENAME}"

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")
_CARD_PATH = os.path.join(_FRONTEND_DIR, CARD_FILENAME)
_REGISTERED_KEY = f"{DOMAIN}_frontend_registered"


async def async_setup(hass: HomeAssistant) -> None:
    """Register the card once, no matter how many rooms are configured."""
    if hass.data.get(_REGISTERED_KEY):
        return
    hass.data[_REGISTERED_KEY] = True

    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL_PATH, _FRONTEND_DIR)]
    )
    add_extra_js_url(hass, CARD_URL)
