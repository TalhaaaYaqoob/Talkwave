"""WebRTC-related helpers (ICE server configuration, etc.)."""

from api.services.webrtc.ice_config import (
    get_ice_servers_for_aiortc,
    get_ice_servers_for_client,
)

__all__ = ["get_ice_servers_for_aiortc", "get_ice_servers_for_client"]
