#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Cerebras LLM service implementation using OpenAI-compatible interface."""

import asyncio
from typing import List

import httpx
from loguru import logger
from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from pipecat.adapters.services.open_ai_adapter import OpenAILLMInvocationParams
from pipecat.services.openai.llm import OpenAILLMService


class CerebrasLLMService(OpenAILLMService):
    """A service for interacting with Cerebras's API using the OpenAI-compatible interface.

    This service extends OpenAILLMService to connect to Cerebras's API endpoint while
    maintaining full compatibility with OpenAI's interface and functionality.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.cerebras.ai/v1",
        model: str = "gpt-oss-120b",
        **kwargs,
    ):
        super().__init__(api_key=api_key, base_url=base_url, model=model, **kwargs)

    def create_client(self, api_key=None, base_url=None, **kwargs):
        """Create AsyncOpenAI client with aggressive retry for Cerebras 429s."""
        logger.debug(f"Creating Cerebras client with api {base_url}")
        kwargs.pop("organization", None)
        kwargs.pop("project", None)
        kwargs.pop("default_headers", None)
        return AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=5,
            timeout=httpx.Timeout(10.0, connect=5.0),
            http_client=DefaultAsyncHttpxClient(
                limits=httpx.Limits(
                    max_keepalive_connections=100,
                    max_connections=1000,
                    keepalive_expiry=None,
                )
            ),
        )

    async def get_chat_completions(self, params_from_context):
        """Override to add application-level retry with backoff for Cerebras 429s.

        The SDK's built-in max_retries handles transport-level retries, but
        Cerebras can return 429 bursts that exhaust those quickly.  This adds
        a second retry layer with longer back-off so the call isn't silently
        dropped during a brief rate-limit spike.
        """
        from openai import RateLimitError

        max_app_retries = 3
        for attempt in range(max_app_retries + 1):
            try:
                return await super().get_chat_completions(params_from_context)
            except RateLimitError as e:
                if attempt == max_app_retries:
                    raise
                wait = 0.5 * (2 ** attempt)  # 0.5s, 1s, 2s
                logger.warning(
                    f"Cerebras 429 (attempt {attempt + 1}/{max_app_retries + 1}), "
                    f"retrying in {wait:.1f}s: {e}"
                )
                await asyncio.sleep(wait)

    def build_chat_completion_params(self, params_from_context: OpenAILLMInvocationParams) -> dict:
        """Build parameters for Cerebras chat completion request.

        Cerebras supports a subset of OpenAI parameters, focusing on core
        completion settings without advanced features like frequency/presence penalties.

        Args:
            params_from_context: Parameters, derived from the LLM context, to
                use for the chat completion. Contains messages, tools, and tool
                choice.

        Returns:
            Dictionary of parameters for the chat completion request.
        """
        params = {
            "model": self.model_name,
            "stream": True,
            "seed": self._settings["seed"],
            "temperature": self._settings["temperature"],
            "top_p": self._settings["top_p"],
            "max_completion_tokens": self._settings["max_completion_tokens"],
        }

        # Messages, tools, tool_choice
        params.update(params_from_context)

        params.update(self._settings["extra"])
        return params
