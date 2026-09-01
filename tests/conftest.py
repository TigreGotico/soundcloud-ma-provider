"""Shared fixtures for soundcloud_ma_provider tests.

``music_assistant`` (the server package, as opposed to ``music_assistant_models``)
is not published to PyPI and cannot be installed by pip/uv. Since
``soundcloud_ma_provider`` only needs one piece of it at import time --
``music_assistant.models.music_provider.MusicProvider`` -- a stub module that
matches the real API is injected into ``sys.modules`` before the provider
module is imported.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest


def _install_music_assistant_stubs() -> None:
    if "music_assistant" in sys.modules:
        return

    ma = types.ModuleType("music_assistant")
    ma_models = types.ModuleType("music_assistant.models")
    ma_models_music_provider = types.ModuleType("music_assistant.models.music_provider")

    class Provider:
        """Minimal stand-in for music_assistant.models.provider.Provider."""

        def __init__(self, mass, manifest, config, supported_features=None):
            self.mass = mass
            self.manifest = manifest
            self.config = config
            self._supported_features = supported_features or set()

        @property
        def supported_features(self):
            return self._supported_features

        @property
        def domain(self) -> str:
            return self.manifest.domain

        @property
        def instance_id(self) -> str:
            return self.config.instance_id

    class MusicProvider(Provider):
        """Minimal stand-in for music_assistant.models.music_provider.MusicProvider."""

    ma_models_music_provider.MusicProvider = MusicProvider

    sys.modules["music_assistant"] = ma
    sys.modules["music_assistant.models"] = ma_models
    sys.modules["music_assistant.models.music_provider"] = ma_models_music_provider


_install_music_assistant_stubs()

from music_assistant_models.config_entries import ProviderConfig  # noqa: E402
from music_assistant_models.enums import ProviderType  # noqa: E402
from music_assistant_models.provider import ProviderManifest  # noqa: E402

import soundcloud_ma_provider as scm  # noqa: E402


@pytest.fixture
def manifest() -> ProviderManifest:
    return ProviderManifest(
        type=ProviderType.MUSIC,
        domain="soundcloud_free",
        name="SoundCloud (no login)",
        description="test",
        codeowners=["@TigreGotico"],
    )


@pytest.fixture
def provider_config() -> ProviderConfig:
    return ProviderConfig(
        values={},
        type=ProviderType.MUSIC,
        domain="soundcloud_free",
        instance_id="soundcloud_free_1",
    )


@pytest.fixture
def mass() -> MagicMock:
    return MagicMock()


@pytest.fixture
def provider(mass, manifest, provider_config) -> scm.SoundCloudProvider:
    return scm.SoundCloudProvider(mass, manifest, provider_config, scm.SUPPORTED_FEATURES)
