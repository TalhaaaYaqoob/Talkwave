"""WebSocket broadcaster for streaming transcripts and activity to connected clients.

This module provides a global registry of WebSocket connections that allows
the pipecat pipeline to broadcast transcript updates and activity logs to
connected web clients in real-time.
"""

import asyncio
from typing import Dict, Optional
from fastapi import WebSocket
from loguru import logger


class WebSocketBroadcaster:
    """Manages WebSocket connections for broadcasting pipeline events to clients.

    Register/unregister acquire the lock. Send methods take a snapshot reference
    of the dict first (dict.get is atomic in CPython) so they never iterate a
    mutating structure, avoiding race conditions without holding the lock on
    every send.
    """

    def __init__(self):
        self._connections: Dict[int, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def register(self, workflow_run_id: int, websocket: WebSocket):
        async with self._lock:
            self._connections[workflow_run_id] = websocket
            logger.debug(f"Registered WebSocket for workflow_run_id: {workflow_run_id}")

    async def unregister(self, workflow_run_id: int):
        async with self._lock:
            self._connections.pop(workflow_run_id, None)
            logger.debug(f"Unregistered WebSocket for workflow_run_id: {workflow_run_id}")

    def get_connection(self, workflow_run_id: int) -> Optional[WebSocket]:
        return self._connections.get(workflow_run_id)

    async def _safe_send(self, workflow_run_id: int, payload: dict):
        """Send JSON to the connected client, swallowing errors."""
        import os
        ws = self._connections.get(workflow_run_id)
        if ws:
            try:
                await ws.send_json(payload)
                msg_type = payload.get("type", "?")
                logger.debug(
                    f"[Broadcaster] SENT {msg_type} to run_id={workflow_run_id} | "
                    f"pid={os.getpid()}"
                )
            except Exception as e:
                logger.warning(f"[Broadcaster] SEND FAILED run_id={workflow_run_id}: {e}")
        else:
            msg_type = payload.get("type", "?")
            logger.warning(
                f"[Broadcaster] DROPPED {msg_type} for run_id={workflow_run_id} — "
                f"no WebSocket registered in pid={os.getpid()} | "
                f"registered_ids={list(self._connections.keys())}"
            )

    async def send_transcript(self, workflow_run_id: int, role: str, content: str):
        await self._safe_send(workflow_run_id, {
            "type": "transcript",
            "payload": {"role": role, "content": content},
        })

    async def send_transcript_interim(
        self, workflow_run_id: int, role: str, content: str, is_final: bool = False
    ):
        await self._safe_send(workflow_run_id, {
            "type": "transcript_interim",
            "payload": {"role": role, "content": content, "is_final": is_final},
        })

    async def send_activity(
        self,
        workflow_run_id: int,
        activity_type: str,
        message: str,
        details: Optional[str] = None,
    ):
        await self._safe_send(workflow_run_id, {
            "type": "activity",
            "payload": {
                "activity_type": activity_type,
                "activity_message": message,
                "details": details,
            },
        })

    async def send_node_transition(
        self,
        workflow_run_id: int,
        from_node: Optional[str],
        to_node: str,
    ):
        await self._safe_send(workflow_run_id, {
            "type": "node_transition",
            "payload": {"from_node": from_node, "to_node": to_node},
        })

    async def send_tool_call(self, workflow_run_id: int, tool_name: str):
        await self._safe_send(workflow_run_id, {
            "type": "tool_call",
            "payload": {"tool_name": tool_name},
        })

    async def send_action_result(
        self,
        workflow_run_id: int,
        action_id: str,
        action_type: str,
        success: bool,
        message: str,
        friendly_message: str = "",
        solution: str = "",
    ):
        await self._safe_send(workflow_run_id, {
            "type": "action_result",
            "payload": {
                "action_id": action_id,
                "action_type": action_type,
                "success": success,
                "message": message,
                "friendly_message": friendly_message,
                "solution": solution,
            },
        })


# Global singleton instance
websocket_broadcaster = WebSocketBroadcaster()

