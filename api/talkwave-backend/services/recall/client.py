"""Recall.ai REST API client for meeting bot lifecycle management.

Handles creating bots, joining meetings, outputting audio, and managing
bot state across Zoom, Google Meet, and Microsoft Teams.

API Reference: https://docs.recall.ai/docs
"""

from __future__ import annotations

import base64
import os
from enum import Enum
from typing import Optional

import httpx
from loguru import logger
from pydantic import BaseModel


RECALL_API_REGION = os.getenv("RECALL_API_REGION", "ap-northeast-1")
RECALL_API_BASE = os.getenv(
    "RECALL_API_BASE_URL",
    f"https://{RECALL_API_REGION}.recall.ai/api/v1",
)

_SILENT_MP3_FRAME = b"\xff\xfb\x90\x04" + b"\x00" * 413
_SILENT_MP3_B64 = base64.b64encode(_SILENT_MP3_FRAME).decode()


class MeetingPlatform(str, Enum):
    ZOOM = "zoom"
    GOOGLE_MEET = "google_meet"
    MICROSOFT_TEAMS = "microsoft_teams"
    WEBEX = "webex"


class BotStatus(str, Enum):
    READY = "ready"
    JOINING_CALL = "joining_call"
    IN_WAITING_ROOM = "in_waiting_room"
    IN_CALL_NOT_RECORDING = "in_call_not_recording"
    IN_CALL_RECORDING = "in_call_recording"
    CALL_ENDED = "call_ended"
    FATAL = "fatal"
    ANALYSIS_DONE = "analysis_done"


class RecallBot(BaseModel):
    id: str
    meeting_url: str
    status: str
    video_url: Optional[str] = None
    platform: Optional[str] = None


class RecallClient:
    """Async client for Recall.ai's Meeting Bot API.

    Accepts an optional shared_client (httpx.AsyncClient) to use the
    global connection pool instead of creating a per-instance client.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = RECALL_API_BASE,
        shared_client: Optional[httpx.AsyncClient] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = shared_client
        self._owns_client = shared_client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": "application/json",
                },
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
                timeout=30.0,
            )
            self._owns_client = True
        return self._client

    async def close(self):
        if self._owns_client and self._client and not self._client.is_closed:
            await self._client.aclose()

    async def create_bot(
        self,
        meeting_url: str,
        bot_name: str = "TalkWave",
        output_media_url: Optional[str] = None,
        transcription_options: Optional[dict] = None,
        real_time_transcription: Optional[dict] = None,
        recording_mode: str = "speaker_view",
        automatic_leave: Optional[dict] = None,
    ) -> RecallBot:
        """Create a bot and send it to a meeting.

        Uses Recall.ai's v1 API.  The ``real_time_transcription`` helper is
        translated into ``recording_config.realtime_endpoints`` which is the
        field Recall's API actually expects.

        Args:
            meeting_url: The meeting URL (Zoom, Meet, Teams).
            bot_name: Display name for the bot in the meeting.
            output_media_url: URL of a webpage whose audio/video will be
                streamed into the meeting (for Output Media API).
            transcription_options: Config for Recall's built-in transcription.
            real_time_transcription: Legacy helper — ``destination_url`` will be
                added as a webhook realtime endpoint.
            recording_mode: 'speaker_view', 'gallery_view', or 'audio_only'.
            automatic_leave: Auto-leave config (e.g. when everyone else leaves).

        Returns:
            RecallBot with the created bot's ID and status.
        """
        client = await self._get_client()

        recording_config: dict = {
            "video_mixed_layout": recording_mode,
            "transcript": {
                "provider": {
                    "meeting_captions": {},
                },
            },
        }

        realtime_endpoints: list[dict] = []
        if real_time_transcription:
            dest_url = real_time_transcription.get("destination_url", "")
            if dest_url:
                realtime_endpoints.append({
                    "type": "webhook",
                    "url": dest_url,
                    "events": ["transcript.data"],
                })
        if realtime_endpoints:
            recording_config["realtime_endpoints"] = realtime_endpoints

        payload: dict = {
            "meeting_url": meeting_url,
            "bot_name": bot_name,
            "recording_config": recording_config,
            "automatic_audio_output": {
                "in_call_recording": {
                    "data": {
                        "kind": "mp3",
                        "b64_data": _SILENT_MP3_B64,
                    },
                },
            },
        }

        if output_media_url:
            payload["output_media"] = {"kind": "webpage", "config": {"url": output_media_url}}

        if automatic_leave:
            payload["automatic_leave"] = automatic_leave
        else:
            payload["automatic_leave"] = {
                "waiting_room_timeout": 300,
                "noone_joined_timeout": 300,
                "everyone_left_timeout": 30,
            }

        logger.info(f"[Recall] Creating bot for meeting: {meeting_url} as '{bot_name}'")
        logger.debug(f"[Recall] Payload: {payload}")
        resp = await client.post("/bot", json=payload)
        if resp.status_code >= 400:
            body = resp.text
            logger.error(
                f"[Recall] Bot creation failed: {resp.status_code} — {body}"
            )
            resp.raise_for_status()
        data = resp.json()

        bot = RecallBot(
            id=data["id"],
            meeting_url=meeting_url,
            status=data.get("status_changes", [{}])[-1].get("code", "unknown")
            if data.get("status_changes")
            else "created",
            platform=data.get("meeting_metadata", {}).get("platform"),
        )
        logger.info(f"[Recall] Bot created: id={bot.id}, platform={bot.platform}")
        return bot

    async def get_bot(self, bot_id: str) -> dict:
        """Retrieve current bot status and metadata."""
        client = await self._get_client()
        resp = await client.get(f"/bot/{bot_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_bot_status(self, bot_id: str) -> str:
        """Get the latest status code of a bot."""
        data = await self.get_bot(bot_id)
        changes = data.get("status_changes", [])
        return changes[-1]["code"] if changes else "unknown"

    async def leave_meeting(self, bot_id: str) -> bool:
        """Instruct the bot to leave the meeting."""
        client = await self._get_client()
        try:
            resp = await client.post(f"/bot/{bot_id}/leave_call")
            resp.raise_for_status()
            logger.info(f"[Recall] Bot {bot_id} leaving meeting")
            return True
        except httpx.HTTPStatusError as e:
            logger.warning(f"[Recall] Failed to leave meeting: {e}")
            return False

    async def send_audio(self, bot_id: str, audio_data: bytes) -> bool:
        """Send an audio clip (MP3) for the bot to play in the meeting.

        Uses the Output Audio endpoint with the required `kind` + `b64_data`
        payload format.
        """
        client = await self._get_client()
        b64_audio = base64.b64encode(audio_data).decode("utf-8")
        payload = {"kind": "mp3", "b64_data": b64_audio}

        try:
            resp = await client.post(f"/bot/{bot_id}/output_audio", json=payload)
            resp.raise_for_status()
            logger.debug(f"[Recall] Audio sent to bot {bot_id} ({len(audio_data)} bytes)")
            return True
        except httpx.HTTPStatusError as e:
            body = e.response.text if e.response else ""
            logger.error(
                f"[Recall] Failed to send audio to {bot_id}: "
                f"{e.response.status_code} — {body[:300]}"
            )
            return False

    async def get_transcript(self, bot_id: str) -> list[dict]:
        """Retrieve the full transcript for a completed meeting."""
        client = await self._get_client()
        resp = await client.get(f"/bot/{bot_id}/transcript")
        resp.raise_for_status()
        return resp.json()

    async def get_recording(self, bot_id: str) -> Optional[str]:
        """Get the recording download URL if available."""
        data = await self.get_bot(bot_id)
        return data.get("video_url")

    async def list_bots(
        self,
        meeting_url: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """List bots with optional filters."""
        client = await self._get_client()
        params: dict = {"limit": limit}
        if meeting_url:
            params["meeting_url"] = meeting_url
        if status:
            params["status"] = status

        resp = await client.get("/bot", params=params)
        resp.raise_for_status()
        return resp.json().get("results", [])

    async def delete_bot(self, bot_id: str) -> bool:
        """Delete a bot and its data."""
        client = await self._get_client()
        try:
            resp = await client.delete(f"/bot/{bot_id}")
            resp.raise_for_status()
            logger.info(f"[Recall] Bot {bot_id} deleted")
            return True
        except httpx.HTTPStatusError:
            return False
