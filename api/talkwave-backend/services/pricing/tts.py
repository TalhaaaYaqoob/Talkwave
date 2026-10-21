"""
TTS (Text-to-Speech) pricing models for different providers.

Prices are per character for TTS services.

Pricing references (May 2026, verified per provider pricing pages):
    - OpenAI gpt-4o-mini-tts: $0.60 per 1M characters → $6e-7/char
    - Deepgram Aura-2:        $0.030 per 1k characters → $3e-5/char
    - Deepgram Aura-1:        $0.015 per 1k characters → $1.5e-5/char
    - Cartesia Sonic-3.5:     ~$0.030 per 1k characters at Scale tier
                              (1 credit/char, ~$3.33/100k credits)
                              See https://cartesia.ai/pricing
    - ElevenLabs Flash v2.5 (Scale tier):  ~$0.083 per 1k characters
                              (16.5k credits/$22 cost basis at Scale).
                              Drops to ~$0.06/1k at Business and below at Enterprise.
                              See https://elevenlabs.io/pricing

These rates feed `cost_calculator.calculate_tts_cost(...)` so we can attribute
margin per workflow run. Update them when you renegotiate provider contracts.
"""

from decimal import Decimal
from typing import Dict

from api.services.configuration.registry import ServiceProviders

from .models import CharacterPricingModel

# TTS pricing registry
TTS_PRICING: Dict[str, Dict[str, CharacterPricingModel]] = {
    ServiceProviders.OPENAI: {
        "gpt-4o-mini-tts": CharacterPricingModel(Decimal("0.6") / 1_000_000),
        "default": CharacterPricingModel(Decimal("0.6") / 1_000_000),
    },
    ServiceProviders.DEEPGRAM: {
        "aura-2": CharacterPricingModel(Decimal("0.030") / 1_000),
        "aura-1": CharacterPricingModel(Decimal("0.015") / 1_000),
        "default": CharacterPricingModel(Decimal("0.030") / 1_000),
    },
    ServiceProviders.CARTESIA: {
        # Sonic-3.5 — 1 credit per character at Scale tier ≈ $0.030/1k chars.
        "sonic-3.5": CharacterPricingModel(Decimal("0.030") / 1_000),
        "sonic-3": CharacterPricingModel(Decimal("0.030") / 1_000),
        "default": CharacterPricingModel(Decimal("0.030") / 1_000),
    },
    ServiceProviders.ELEVENLABS: {
        # Flash v2.5 ≈ $0.083 per 1k characters at the Scale tier ($330/4M chars).
        # Drop to ~$0.06/1k at Business and ~$0.025/1k under an Enterprise contract.
        "eleven_flash_v2_5": CharacterPricingModel(Decimal("0.083") / 1_000),
        "eleven_turbo_v2_5": CharacterPricingModel(Decimal("0.099") / 1_000),
        "default": CharacterPricingModel(Decimal("0.083") / 1_000),
    },
    "default": {"default": CharacterPricingModel(Decimal("0.030") / 1_000)},
}
