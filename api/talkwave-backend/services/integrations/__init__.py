"""
Integrations module.
Provides OAuth connections and tool execution for external services.
"""

from api.services.integrations.composio_service import (
    composio_service,
    database_service,
    ComposioService,
    DatabaseService,
    COMPOSIO_APPS,
    COMPOSIO_CATEGORIES,
)

from api.services.integrations.nango import (
    nango_service,
    NangoService,
)

__all__ = [
    # Composio
    "composio_service",
    "database_service",
    "ComposioService",
    "DatabaseService",
    "COMPOSIO_APPS",
    "COMPOSIO_CATEGORIES",
    # Nango (legacy)
    "nango_service",
    "NangoService",
]

