"""Make the repo's custom_components importable and discoverable by HA's loader."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant

REPO_ROOT = Path(__file__).parent.parent

# REPO_ROOT lets `import custom_components` resolve to this repo's directory
# (HA's loader does exactly that to discover custom integrations);
# REPO_ROOT/custom_components lets pure-logic tests `import heating_controller`
# directly without going through the `custom_components` namespace package.
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "custom_components"))

pytest_plugins = "pytest_homeassistant_custom_component"

# pytest-homeassistant-custom-component is auto-loaded as a pytest11 plugin
# before this conftest runs, which already imports `custom_components` as a
# namespace package pointing only at its own (empty) testing_config dir. The
# sys.path insert above doesn't retroactively affect an already-imported
# namespace package's __path__, so extend it explicitly here.
import custom_components  # noqa: E402

if str(REPO_ROOT / "custom_components") not in custom_components.__path__:
    custom_components.__path__.append(str(REPO_ROOT / "custom_components"))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    hass: HomeAssistant, enable_custom_integrations: None
):
    yield
