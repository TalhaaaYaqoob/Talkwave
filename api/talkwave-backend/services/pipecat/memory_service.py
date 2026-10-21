"""Persistent, cross-call memory for the live voice pipeline.

Pipecat pipelines are stateless between calls: every conversation starts from
scratch. This module adds long-term memory to the *standard* voice pipeline
using the Mem0 memory engine (self-hosted / "local" config — the vector store
is your own Qdrant and the embedder/LLM are your own OpenAI key, so no
conversation data leaves your infrastructure).

The memory processor sits between the user context aggregator and the LLM
service, exactly like the reference Mem0 integration:

    transport.input()
      -> STT
      -> user_context_aggregator
      -> WorkflowMemoryService   <-- recall (before LLM) + retain (after turn)
      -> llm
      -> ...

Why a subclass instead of the vendored ``Mem0MemoryService`` directly?
The vendored service calls Mem0's ``search()`` / ``add()`` **synchronously**
inside ``process_frame``. Those calls hit the network (OpenAI embeddings, LLM
fact-extraction) and can take hundreds of milliseconds to seconds — which would
stall the entire real-time audio loop. ``WorkflowMemoryService`` overrides the
frame handling so that:

  * Recall runs in a worker thread and is awaited with a hard timeout, so the
    event loop stays responsive and a slow/broken memory backend can never hang
    a call (it just skips recall for that turn).
  * Retain runs as a fire-and-forget background task after each turn, so storing
    memories never blocks the response.

Scoping: memory banks are keyed per ``(organization, caller phone number)`` so a
returning caller gets their own history and there is no cross-tenant leakage.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

from loguru import logger

from api.services.compliance.phone_utils import normalize_e164

try:
    from pipecat.frames.frames import Frame, LLMContextFrame, LLMMessagesFrame
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContextFrame
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
    from pipecat.services.mem0.memory import Mem0MemoryService

    _MEM0_IMPORT_ERROR: Optional[Exception] = None
except Exception as _e:  # pragma: no cover - depends on optional mem0ai install
    Mem0MemoryService = object  # type: ignore
    FrameProcessor = object  # type: ignore
    _MEM0_IMPORT_ERROR = _e


# Default embedding dimensions for OpenAI text-embedding-3-small.
_DEFAULT_EMBEDDING_DIMS = 1536
# Hard cap on how long a recall may take before we give up for this turn.
_DEFAULT_RECALL_TIMEOUT_S = 1.5


def build_memory_scope_id(
    organization_id: Optional[int],
    phone_number: Optional[str],
) -> Optional[str]:
    """Build the Mem0 ``user_id`` (memory bank id) for a call.

    Scoped per ``(organization, caller phone)``. Returns ``None`` when we don't
    have enough information to identify a stable caller, in which case memory is
    skipped for the call (we never want an "anonymous" shared bank).
    """
    if not phone_number:
        return None
    normalized = normalize_e164(phone_number) or "".join(
        c for c in str(phone_number) if c.isdigit()
    )
    if not normalized:
        return None
    org_part = f"org{organization_id}" if organization_id is not None else "orgunknown"
    return f"{org_part}:{normalized}"


def build_local_mem0_config() -> Optional[Dict[str, Any]]:
    """Assemble a Mem0 ``local_config`` from environment / platform config.

    Vector store  -> your Qdrant (``QDRANT_URL`` / ``QDRANT_API_KEY``)
    Embedder      -> OpenAI ``text-embedding-3-small``
    Extraction LLM-> OpenAI (``MEMORY_LLM_MODEL``, default ``gpt-4o-mini``)

    Returns ``None`` if the required credentials aren't present, so the caller
    can gracefully disable memory instead of crashing a call.
    """
    from api.constants import QDRANT_API_KEY, QDRANT_URL

    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        logger.warning(
            "[Memory] OPENAI_API_KEY not set — persistent memory disabled "
            "(embedder + extraction LLM require it)."
        )
        return None

    if not QDRANT_URL:
        logger.warning(
            "[Memory] QDRANT_URL not set — persistent memory disabled "
            "(self-hosted Mem0 needs a vector store)."
        )
        return None

    embed_model = os.getenv("MEMORY_EMBED_MODEL", "text-embedding-3-small")
    embed_dims = int(os.getenv("MEMORY_EMBED_DIMS", str(_DEFAULT_EMBEDDING_DIMS)))
    llm_model = os.getenv("MEMORY_LLM_MODEL", "gpt-4o-mini")
    collection = os.getenv("MEMORY_QDRANT_COLLECTION", "voice_agent_memory")

    qdrant_config: Dict[str, Any] = {
        "collection_name": collection,
        "url": QDRANT_URL,
        "embedding_model_dims": embed_dims,
    }
    if QDRANT_API_KEY:
        qdrant_config["api_key"] = QDRANT_API_KEY

    return {
        "vector_store": {
            "provider": "qdrant",
            "config": qdrant_config,
        },
        "embedder": {
            "provider": "openai",
            "config": {"model": embed_model, "api_key": openai_key},
        },
        "llm": {
            "provider": "openai",
            "config": {"model": llm_model, "api_key": openai_key},
        },
    }


if _MEM0_IMPORT_ERROR is None:

    class WorkflowMemoryService(Mem0MemoryService):
        """Non-blocking persistent-memory processor for the voice pipeline."""

        def __init__(
            self,
            *args,
            recall_timeout: float = _DEFAULT_RECALL_TIMEOUT_S,
            enable_recall: bool = True,
            enable_retain: bool = True,
            **kwargs,
        ):
            super().__init__(*args, **kwargs)
            self._recall_timeout = recall_timeout
            self._enable_recall = enable_recall
            self._enable_retain = enable_retain
            self._retain_tasks: "set[asyncio.Task]" = set()
            # Reference to the memory message we last injected, so we can replace
            # it each turn rather than appending a new one (avoids unbounded
            # context growth over a long call).
            self._injected_message: Optional[Dict[str, Any]] = None

        async def process_frame(self, frame: Frame, direction: FrameDirection):
            # Intentionally call the *base* FrameProcessor bookkeeping and skip
            # Mem0MemoryService.process_frame, whose blocking search()/add()
            # calls would stall the real-time pipeline.
            await FrameProcessor.process_frame(self, frame, direction)

            context = None
            messages = None
            if isinstance(frame, (LLMContextFrame, OpenAILLMContextFrame)):
                context = frame.context
            elif isinstance(frame, LLMMessagesFrame):
                messages = frame.messages
                context = LLMContext(messages)

            if context is None:
                await self.push_frame(frame, direction)
                return

            try:
                context_messages = context.get_messages()
                latest_user_message = None
                for message in reversed(context_messages):
                    if message.get("role") == "user" and isinstance(
                        message.get("content"), str
                    ):
                        latest_user_message = message.get("content")
                        break

                if latest_user_message:
                    if self._enable_recall:
                        await self._recall(context, latest_user_message)
                    if self._enable_retain:
                        # Only persist genuine conversation turns; never feed our
                        # own injected memory block or other system prompts back
                        # into memory (avoids a recall→retain feedback loop).
                        retainable = [
                            m
                            for m in context.get_messages()
                            if m.get("role") in ("user", "assistant")
                            and m is not self._injected_message
                        ]
                        if retainable:
                            self._retain(retainable)

                if messages is not None:
                    await self.push_frame(LLMMessagesFrame(context.get_messages()))
                else:
                    await self.push_frame(frame)
            except Exception as e:
                logger.error(f"[Memory] process_frame error (non-fatal): {e}")
                await self.push_frame(frame)

        async def _recall(self, context, query: str) -> None:
            """Search memory off the event loop and inject results as a system
            message before the LLM. Bounded by ``recall_timeout``."""
            if self.last_query == query:
                return
            self.last_query = query

            try:
                memories = await asyncio.wait_for(
                    asyncio.to_thread(self._retrieve_memories, query),
                    timeout=self._recall_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"[Memory] recall exceeded {self._recall_timeout}s — "
                    f"skipping recall for this turn"
                )
                return
            except Exception as e:
                logger.error(f"[Memory] recall failed (non-fatal): {e}")
                return

            results = self._extract_results(memories)
            if not results:
                return

            memory_text = self.system_prompt
            for i, memory in enumerate(results, 1):
                memory_text += f"{i}. {memory.get('memory', '')}\n\n"

            # Drop the memory message we injected on the previous turn so the
            # context carries at most one memory block at a time.
            self._remove_injected_message(context)

            role = "system" if self.add_as_system_message else "user"
            message = {"role": role, "content": memory_text}
            context.add_message(message)
            self._injected_message = message
            logger.info(f"[Memory] recalled {len(results)} memory item(s)")

        def _remove_injected_message(self, context) -> None:
            prev = self._injected_message
            if prev is None:
                return
            self._injected_message = None
            try:
                messages = getattr(context, "_messages", None)
                if isinstance(messages, list):
                    messages[:] = [m for m in messages if m is not prev]
            except Exception as e:
                logger.debug(f"[Memory] could not prune prior memory message: {e}")

        def _retain(self, messages: List[Dict[str, Any]]) -> None:
            """Persist the current exchange as a fire-and-forget background task."""
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            task = loop.create_task(self._retain_async(list(messages)))
            self._retain_tasks.add(task)
            task.add_done_callback(self._retain_tasks.discard)

        async def _retain_async(self, messages: List[Dict[str, Any]]) -> None:
            try:
                await asyncio.to_thread(self._store_messages, messages)
            except Exception as e:
                logger.error(f"[Memory] retain failed (non-fatal): {e}")

        @staticmethod
        def _extract_results(memories: Any) -> List[Dict[str, Any]]:
            """Normalize Mem0 search output across client/version shapes."""
            if not memories:
                return []
            if isinstance(memories, dict):
                return memories.get("results", []) or []
            if isinstance(memories, list):
                return memories
            return []

else:  # pragma: no cover - mem0ai not installed

    class WorkflowMemoryService:  # type: ignore
        """Placeholder used only when ``mem0ai`` isn't installed."""

        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                f"mem0ai is not available: {_MEM0_IMPORT_ERROR}. "
                f"Install it with `pip install mem0ai` to enable persistent memory."
            )


def create_workflow_memory_service(
    *,
    organization_id: Optional[int],
    phone_number: Optional[str],
    recall_timeout: float = _DEFAULT_RECALL_TIMEOUT_S,
    enable_recall: bool = True,
    enable_retain: bool = True,
    search_limit: int = 6,
    search_threshold: float = 0.3,
) -> Optional["WorkflowMemoryService"]:
    """Build a ready-to-use memory processor, or ``None`` if unavailable.

    Never raises: any misconfiguration (missing deps / credentials / caller id)
    results in ``None`` so the call proceeds without memory instead of failing.
    """
    if _MEM0_IMPORT_ERROR is not None:
        logger.warning(
            f"[Memory] mem0ai not installed ({_MEM0_IMPORT_ERROR}) — "
            f"persistent memory disabled."
        )
        return None

    scope_id = build_memory_scope_id(organization_id, phone_number)
    if not scope_id:
        logger.info(
            "[Memory] No stable caller id (missing phone number) — "
            "persistent memory disabled for this call."
        )
        return None

    local_config = build_local_mem0_config()
    if not local_config:
        return None

    try:
        params = Mem0MemoryService.InputParams(
            search_limit=search_limit,
            search_threshold=search_threshold,
            system_prompt=(
                "Relevant memories from past conversations with this caller:\n\n"
            ),
            add_as_system_message=True,
        )
        service = WorkflowMemoryService(
            local_config=local_config,
            user_id=scope_id,
            params=params,
            recall_timeout=recall_timeout,
            enable_recall=enable_recall,
            enable_retain=enable_retain,
        )
        logger.info(
            f"[Memory] Persistent memory enabled | bank={scope_id} | "
            f"recall={enable_recall} retain={enable_retain} "
            f"limit={search_limit} threshold={search_threshold}"
        )
        return service
    except Exception as e:
        logger.error(f"[Memory] Failed to initialize memory service (non-fatal): {e}")
        return None
