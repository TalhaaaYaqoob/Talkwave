"""Meeting agent pipeline -- orchestrates Recall.ai bot, STT, LLM, TTS, and wake word detection.

This is the main entry point for running a meeting agent session. It:
  1. Creates a Recall.ai bot and joins the meeting
  2. Streams meeting audio through Deepgram for real-time transcription
  3. Monitors transcripts for wake word triggers
  4. When triggered, builds context from the meeting and queries the LLM
  5. Sends TTS audio response back to the meeting via Recall
  6. On meeting end, generates post-meeting summary
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

from loguru import logger

from api.constants import MEETING_BOT_POLL_INTERVAL_SECONDS
from api.services.meeting.concurrency import (
    acquire_response_slot,
    release_response_slot,
)
from api.services.meeting.connection_pool import pool_manager
from api.services.meeting.context_manager import MeetingContextManager
from api.services.meeting.post_meeting import MeetingSummary, PostMeetingProcessor
from api.services.meeting.wake_word import WakeWordDetector
from api.services.recall.client import RecallClient


class MeetingAgentPipeline:
    """Manages the full lifecycle of a meeting agent session."""

    def __init__(
        self,
        recall_api_key: str,
        meeting_url: str,
        agent_name: str = "TalkWave",
        wake_words: Optional[list[str]] = None,
        knowledge_base_id: Optional[int] = None,
        workflow_id: Optional[int] = None,
        user_id: Optional[int] = None,
        organization_id: Optional[int] = None,
        llm_model: str = "gpt-4o",
        llm_api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ):
        self.meeting_url = meeting_url
        self.agent_name = agent_name
        self.knowledge_base_id = knowledge_base_id
        self.workflow_id = workflow_id
        self.user_id = user_id
        self.organization_id = organization_id
        self.llm_model = llm_model
        self.llm_api_key = llm_api_key or os.getenv("OPENAI_API_KEY", "")
        self._recall_api_key = recall_api_key

        self.system_prompt = system_prompt or (
            f"You are {agent_name}, an AI assistant participating in a meeting. "
            f"When someone addresses you, respond helpfully and concisely. "
            f"You have access to the meeting context, participant information, "
            f"and any knowledge base documents provided. "
            f"Keep responses under 3 sentences unless asked for detail. "
            f"Be professional, clear, and add value to the conversation."
        )

        self.recall_client = RecallClient(api_key=recall_api_key)
        self._recall_pool_initialized = False
        from api.services.meeting.auto_join import _expand_wake_words

        expanded = _expand_wake_words(wake_words or [], agent_name)
        self.wake_detector = WakeWordDetector(wake_words=expanded)
        logger.info(f"[MeetingPipeline] Initial wake words: {expanded}")
        self.context_manager = MeetingContextManager()
        self.post_processor = PostMeetingProcessor(
            llm_api_key=self.llm_api_key, llm_model=self.llm_model
        )

        self._bot_id: Optional[str] = None
        self._running = False
        self._session_id: Optional[str] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._transcript_drain_task: Optional[asyncio.Task] = None
        self._on_transcript_callback = None
        self._on_agent_response_callback = None
        self._on_status_change_callback = None
        self._active_response_tasks: set[asyncio.Task] = set()
        self._responding = False
        self._interrupted = False
        self._pending_wake_task: Optional[asyncio.Task] = None

    @property
    def bot_id(self) -> Optional[str]:
        return self._bot_id

    @property
    def is_running(self) -> bool:
        return self._running

    def on_transcript(self, callback):
        """Register callback for real-time transcript updates."""
        self._on_transcript_callback = callback

    def on_agent_response(self, callback):
        """Register callback when the agent speaks."""
        self._on_agent_response_callback = callback

    def on_status_change(self, callback):
        """Register callback for bot status changes."""
        self._on_status_change_callback = callback

    async def _load_workflow_wake_words(self):
        """Load wake words from workflow's meetingTrigger node as a fallback."""
        if not self.workflow_id:
            return
        try:
            from api.db import db_client
            wf = await db_client.get_workflow(self.workflow_id)
            if wf and wf.workflow_definition_with_fallback:
                for node in wf.workflow_definition_with_fallback.get("nodes", []):
                    if node.get("type") == "meetingTrigger":
                        ww = (
                            node.get("data", {})
                            .get("trigger_config", {})
                            .get("wake_words", [])
                        )
                        added = []
                        for w in ww:
                            w_lower = w.lower().strip()
                            if w_lower and w_lower not in self.wake_detector.wake_words:
                                self.wake_detector.add_wake_word(w_lower)
                                added.append(w_lower)
                        if added:
                            logger.info(
                                f"[MeetingPipeline] Added wake words from workflow "
                                f"{self.workflow_id}: {added}"
                            )
                        logger.info(
                            f"[MeetingPipeline] Final wake words: "
                            f"{self.wake_detector.wake_words}"
                        )
                        break
        except Exception as e:
            logger.warning(
                f"[MeetingPipeline] Could not load workflow wake words: {e}"
            )

    @staticmethod
    async def pre_warm_pools():
        """Pre-initialize HTTP connection pools to avoid cold-start latency."""
        try:
            await pool_manager.openai()
            await pool_manager.deepgram()
            logger.debug("[MeetingPipeline] Connection pools pre-warmed")
        except Exception as e:
            logger.debug(f"[MeetingPipeline] Pool pre-warm skipped: {e}")

    async def start(self) -> str:
        """Create the Recall bot and join the meeting.

        Returns:
            The Recall bot ID.
        """
        logger.info(
            f"[MeetingPipeline] Starting for meeting: {self.meeting_url} "
            f"as '{self.agent_name}'"
        )

        await self._load_workflow_wake_words()
        await self.pre_warm_pools()

        if not self._recall_pool_initialized:
            try:
                shared = await pool_manager.recall(self._recall_api_key)
                self.recall_client = RecallClient(
                    api_key=self._recall_api_key, shared_client=shared
                )
                self._recall_pool_initialized = True
            except Exception:
                logger.debug("[MeetingPipeline] Using per-instance Recall client")

        from api.constants import BACKEND_API_ENDPOINT

        webhook_url = f"{BACKEND_API_ENDPOINT}/api/v1/meeting-agent/webhook/transcript"

        bot = await self.recall_client.create_bot(
            meeting_url=self.meeting_url,
            bot_name=self.agent_name,
            real_time_transcription={
                "partial_transcripts": False,
                "destination_url": webhook_url,
            },
            automatic_leave={
                "waiting_room_timeout": 300,
                "noone_joined_timeout": 300,
                "everyone_left_timeout": 30,
            },
        )

        self._bot_id = bot.id
        self._running = True

        self._poll_task = asyncio.create_task(self._poll_bot_status())
        self._transcript_drain_task = asyncio.create_task(self._drain_transcript_queue())

        logger.info(f"[MeetingPipeline] Bot created: {self._bot_id}")
        return self._bot_id

    async def stop(self):
        """Leave the meeting and clean up all resources."""
        self._running = False

        for t in (self._poll_task, self._transcript_drain_task):
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

        for task in list(self._active_response_tasks):
            task.cancel()
        if self._active_response_tasks:
            await asyncio.gather(*self._active_response_tasks, return_exceptions=True)

        if self._bot_id:
            await self.recall_client.leave_meeting(self._bot_id)

        await self.recall_client.close()
        logger.info(f"[MeetingPipeline] Stopped for bot {self._bot_id}")

    async def handle_transcript_webhook(self, data: dict):
        """Process a real-time transcript webhook from Recall.ai."""
        event_type = data.get("event", "")
        inner = data.get("data", {})

        if not inner:
            logger.debug("[MeetingPipeline] Webhook: empty data payload")
            return

        utterance = inner.get("data", {})
        if not utterance:
            logger.debug(
                f"[MeetingPipeline] Webhook: no inner data. event={event_type} "
                f"keys={list(inner.keys())}"
            )
            return

        participant = utterance.get("participant", {})
        speaker = participant.get("name") or "Unknown"
        speaker_id = str(participant.get("id", speaker))

        words = utterance.get("words", [])
        if isinstance(words, list):
            text = " ".join(w.get("text", "") for w in words if isinstance(w, dict))
        elif isinstance(words, str):
            text = words
        else:
            text = ""

        if not text.strip():
            logger.debug(
                f"[MeetingPipeline] Webhook: empty text. event={event_type} "
                f"utterance_keys={list(utterance.keys())}"
            )
            return

        is_bot_speech = (
            speaker_id == "0"
            or participant.get("platform") == "unknown"
            or (speaker == "Unknown" and participant.get("is_host") is None)
        )

        is_final = event_type == "transcript.data"
        logger.info(
            f"[MeetingPipeline] Transcript: speaker={speaker} final={is_final} "
            f"bot_echo={is_bot_speech} text='{text[:120]}'"
        )

        self.context_manager.add_utterance(
            text=text,
            speaker_id=speaker_id,
            speaker_name=speaker,
            is_final=is_final,
        )

        if self._on_transcript_callback:
            await self._on_transcript_callback({
                "type": "transcript",
                "speaker": speaker,
                "speaker_id": speaker_id,
                "text": text,
                "is_final": is_final,
            })

        if is_bot_speech:
            return

        if self._responding:
            self._interrupted = True
            logger.info(
                f"[MeetingPipeline] Interrupted by {speaker}: '{text[:60]}'"
            )
            return

        wake_match = self.wake_detector.detect(
            transcript_text=text,
            speaker_id=speaker_id,
            is_final=is_final,
        )

        if wake_match:
            if self._pending_wake_task:
                self._pending_wake_task.cancel()
                self._pending_wake_task = None
            task = asyncio.create_task(
                self._respond_to_query(
                    wake_match.query_text, speaker, speaker_id
                )
            )
            self._active_response_tasks.add(task)
            task.add_done_callback(self._active_response_tasks.discard)
        elif self.wake_detector._pending_trigger and not self._pending_wake_task:
            pending = self.wake_detector._pending_trigger
            self._pending_wake_task = asyncio.create_task(
                self._auto_trigger_after_timeout(
                    pending["trigger"], speaker, pending.get("speaker_id", "")
                )
            )

    async def _auto_trigger_after_timeout(
        self, trigger: str, speaker: str, speaker_id: str
    ):
        """If no follow-up arrives within the wake word wait period,
        auto-trigger a response using the recent meeting context."""
        try:
            await asyncio.sleep(self.wake_detector.query_wait_seconds)
            if self.wake_detector._pending_trigger is None:
                return
            self.wake_detector._pending_trigger = None
            self.wake_detector._last_trigger_time = __import__("time").time()
            logger.info(
                f"[MeetingPipeline] Auto-triggering after bare wake word "
                f"'{trigger}' from {speaker} (no follow-up)"
            )
            recent = self.context_manager.get_recent_text(max_chars=200)
            query = recent if recent else f"I'm {self.agent_name}, how can I help?"
            task = asyncio.create_task(
                self._respond_to_query(query, speaker, speaker_id)
            )
            self._active_response_tasks.add(task)
            task.add_done_callback(self._active_response_tasks.discard)
        except asyncio.CancelledError:
            pass
        finally:
            self._pending_wake_task = None

    async def _respond_to_query(
        self, query: str, speaker: str, speaker_id: str = ""
    ):
        """Generate and deliver an LLM response for a triggered query.

        Uses streaming LLM so TTS + audio delivery starts as soon as the
        first sentence is complete, instead of waiting for the full response.
        """
        import time as _time

        if self._responding:
            logger.debug(
                f"[MeetingPipeline] Dropping overlapping query: '{query[:60]}'"
            )
            return

        self._responding = True
        slot_acquired = await acquire_response_slot()
        if not slot_acquired:
            self._responding = False
            logger.warning(
                f"[MeetingPipeline] All response slots busy, dropping query: '{query[:60]}'"
            )
            return

        t0 = _time.time()
        try:
            logger.info(f"[MeetingPipeline] Responding to query from {speaker}: '{query[:80]}'")

            context = self.context_manager.build_llm_context(query)

            is_simple = len(query.split()) <= 6
            kb_context = ""
            if self.organization_id and not is_simple:
                kb_context = await self._query_knowledge_base(query)

            messages = [
                {"role": "system", "content": self.system_prompt},
            ]

            if kb_context:
                messages.append({
                    "role": "system",
                    "content": f"Relevant knowledge base information:\n{kb_context}",
                })

            messages.append({
                "role": "user",
                "content": f"Meeting context:\n{context}\n\nRespond to the question concisely.",
            })

            self._interrupted = False
            response_text, delivered, total = await self._stream_and_speak(messages)

            if response_text:
                self.context_manager.add_utterance(
                    text=response_text,
                    speaker_id="agent",
                    speaker_name=self.agent_name,
                    is_agent=True,
                )

                if self._on_agent_response_callback:
                    await self._on_agent_response_callback({
                        "type": "agent_response",
                        "text": response_text,
                        "query": query,
                        "triggered_by": speaker,
                    })

            elapsed = _time.time() - t0
            logger.info(
                f"[MeetingPipeline] Response delivered in {elapsed:.1f}s "
                f"({delivered}/{total} chunks): "
                f"'{(response_text or '')[:80]}'"
            )

        except Exception as e:
            logger.error(f"[MeetingPipeline] Failed to respond: {e}", exc_info=True)
        finally:
            self._responding = False
            release_response_slot()

    async def _stream_and_speak(
        self, messages: list[dict]
    ) -> tuple[str, int, int]:
        """Stream LLM tokens and progressively deliver TTS audio.

        Instead of waiting for the full LLM response (~2-3s) before
        starting TTS, this streams tokens and fires off TTS + audio
        delivery as each sentence completes.  Time-to-first-audio drops
        from ~4s to ~1.5s.

        Falls back to the batch path if streaming fails.

        Returns:
            (full_response_text, sentences_delivered, total_sentences)
        """
        import json as _json
        import re as _re

        client = await pool_manager.openai()

        full_text = ""
        buffer = ""
        delivered = 0
        total = 0

        try:
            async with client.stream(
                "POST",
                "/v1/chat/completions",
                json={
                    "model": self.llm_model,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 150,
                    "stream": True,
                },
            ) as resp:
                resp.raise_for_status()

                async for raw_line in resp.aiter_lines():
                    if self._interrupted:
                        break

                    if not raw_line.startswith("data: "):
                        continue

                    payload = raw_line[6:].strip()
                    if payload == "[DONE]":
                        break

                    try:
                        chunk = _json.loads(payload)
                        token = (
                            chunk["choices"][0]
                            .get("delta", {})
                            .get("content", "")
                        )
                    except (ValueError, KeyError, IndexError):
                        continue

                    if not token:
                        continue

                    buffer += token
                    full_text += token

                    while _re.search(r"[.!?]\s", buffer):
                        match = _re.search(r"[.!?]\s", buffer)
                        sentence = buffer[: match.end()].strip()
                        buffer = buffer[match.end() :]

                        if sentence and self._bot_id and not self._interrupted:
                            total += 1
                            tts_audio = await self._generate_tts(sentence)
                            if tts_audio:
                                await self.recall_client.send_audio(
                                    self._bot_id, tts_audio
                                )
                                delivered += 1

        except Exception as e:
            logger.warning(
                f"[MeetingPipeline] Streaming LLM error, falling back to batch: {e}"
            )
            if not full_text:
                full_text = await self._call_llm(messages)
                if self._bot_id and not self._interrupted:
                    sentences = self._split_sentences(full_text)
                    total = len(sentences)
                    tts_results = await asyncio.gather(
                        *[self._generate_tts(s) for s in sentences]
                    )
                    for audio in tts_results:
                        if self._interrupted:
                            break
                        if audio:
                            await self.recall_client.send_audio(
                                self._bot_id, audio
                            )
                            delivered += 1
                return full_text, delivered, total

        remaining = buffer.strip()
        if remaining and self._bot_id and not self._interrupted:
            total += 1
            tts_audio = await self._generate_tts(remaining)
            if tts_audio:
                await self.recall_client.send_audio(self._bot_id, tts_audio)
                delivered += 1

        return full_text, delivered, total

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentence-level chunks for interruptible TTS."""
        import re as _re

        parts = _re.split(r'(?<=[.!?])\s+', text.strip())
        chunks: list[str] = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if chunks and len(chunks[-1]) + len(part) < 80:
                chunks[-1] = chunks[-1] + " " + part
            else:
                chunks.append(part)
        return chunks or [text]

    async def _call_llm(self, messages: list[dict]) -> str:
        """Call the LLM using the shared OpenAI connection pool."""
        client = await pool_manager.openai()
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": self.llm_model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 150,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def _generate_tts(self, text: str) -> Optional[bytes]:
        """Generate TTS audio using the shared Deepgram connection pool."""
        if not os.getenv("DEEPGRAM_API_KEY", ""):
            logger.warning("[MeetingPipeline] No DEEPGRAM_API_KEY set, skipping TTS")
            return None

        try:
            client = await pool_manager.deepgram()
            resp = await client.post(
                "/v1/speak",
                params={"model": "aura-asteria-en", "encoding": "mp3"},
                json={"text": text},
            )
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            logger.error(f"[MeetingPipeline] TTS generation failed: {e}")
            return None

    async def _query_knowledge_base(self, query: str) -> str:
        """Query the meeting agent knowledge base via Qdrant vector search.

        Embeds the query text, then searches the kb_chunks collection
        filtered by organization_id for the most relevant chunks.
        """
        if not self.organization_id:
            return ""
        try:
            from api.services.workflow.knowledge_base_retrieval import (
                retrieve_chunks_for_agent,
            )

            context = await retrieve_chunks_for_agent(
                organization_id=self.organization_id,
                user_query=query,
                top_k=5,
                max_context_tokens=4000,
            )
            return context
        except Exception as e:
            logger.warning(f"[MeetingPipeline] KB query failed: {e}")
        return ""

    async def _poll_bot_status(self):
        """Periodically check bot status using configurable interval."""
        last_status = ""
        while self._running:
            try:
                await asyncio.sleep(MEETING_BOT_POLL_INTERVAL_SECONDS)
                if not self._bot_id:
                    continue

                status = await self.recall_client.get_bot_status(self._bot_id)

                if status != last_status:
                    logger.info(f"[MeetingPipeline] Bot status: {last_status} → {status}")
                    last_status = status

                    if self._on_status_change_callback:
                        await self._on_status_change_callback({
                            "type": "status_change",
                            "status": status,
                            "bot_id": self._bot_id,
                        })

                    if status in ("call_ended", "fatal"):
                        logger.info(
                            f"[MeetingPipeline] Meeting ended (status={status})"
                        )
                        self._running = False
                        break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MeetingPipeline] Status poll error: {e}")

    async def _drain_transcript_queue(self):
        """Fast poll loop that drains transcripts queued by other workers via Redis."""
        from api.services.meeting.session_store import session_store

        logger.info(f"[MeetingPipeline] Drain loop started for bot {self._bot_id}")
        while self._running:
            try:
                await asyncio.sleep(0.5)
                if not self._bot_id:
                    continue
                items = await session_store.drain_transcript_queue(self._bot_id)
                if items:
                    logger.info(
                        f"[MeetingPipeline] Drained {len(items)} queued transcripts "
                        f"for bot {self._bot_id[:8]}"
                    )
                for payload in items:
                    try:
                        await self.handle_transcript_webhook(payload)
                    except Exception as exc:
                        logger.error(f"[MeetingPipeline] Error processing queued transcript: {exc}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MeetingPipeline] Transcript drain error: {e}")
                await asyncio.sleep(2)

    async def generate_post_meeting_summary(self) -> MeetingSummary:
        """Generate a post-meeting summary after the meeting ends."""
        transcript = self.context_manager.get_full_transcript()
        stats = self.context_manager.get_speaker_stats()
        duration = self.context_manager.duration_minutes

        return await self.post_processor.process(
            transcript=transcript,
            speaker_stats=stats,
            duration_minutes=duration,
        )
