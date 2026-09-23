"""OmniRSS 外掛開發 SDK (OmniRSS Plugin SDK).

This package provides standard Data Transfer Objects (DTOs), base plugin classes,
and contextual utilities for developing OmniRSS plugins.
"""

from omnirss.sdk.models import (
    ArticleDTO,
    FeedDTO,
    MediaManifestDTO,
    PluginManifest,
    PluginType,
)
from omnirss.sdk.base_plugin import (
    BasePlugin,
    BaseSourcePlugin,
    BaseProcessorPlugin,
    BaseActionPlugin,
)
from omnirss.sdk.context import PluginContext

__all__ = [
    "ArticleDTO",
    "FeedDTO",
    "MediaManifestDTO",
    "PluginManifest",
    "PluginType",
    "BasePlugin",
    "BaseSourcePlugin",
    "BaseProcessorPlugin",
    "BaseActionPlugin",
    "PluginContext",
]
