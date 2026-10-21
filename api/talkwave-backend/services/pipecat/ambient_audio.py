"""Ambient-audio asset provisioning.

The voice transports support mixing a low-volume background loop into the
agent's outgoing audio so the call sounds like it's coming from a real
office rather than a soundproofed booth. The original implementation
referenced ``api/assets/office-ambience-<sample_rate>-mono.wav`` — but
those files were never committed to the repository, so toggling the
"ambient noise" setting was a silent no-op (``SoundfileMixer`` just
logged ``Unable to open file ...`` and the mixer produced silence).

This module fixes that by providing the asset on demand: if the static
file exists we use it, otherwise we synthesize a soft brown-noise loop
at the requested sample rate and cache it under a temp dir keyed by
sample rate. The synthesized loop is tame enough to sit underneath
speech without intruding (low-pass filtered noise around -28 dBFS).
"""

from __future__ import annotations

import math
import os
import random
import struct
import tempfile
import wave
from pathlib import Path
from threading import Lock

from loguru import logger

from api.constants import APP_ROOT_DIR


_STATIC_ASSETS_DIR = APP_ROOT_DIR / "assets"

# 8 seconds is long enough to mask the loop point and short enough to
# keep the on-disk size and generation time small.
_LOOP_SECONDS = 8

# Brown noise produces a warmer, less hissy ambience than pure white
# noise. We then run a one-pole low-pass over it to roll off the very
# top end further. The final amplitude target is around -28 dBFS (i.e.
# roughly 4% of int16 full-scale) so that the user-facing "volume"
# slider on the workflow setting can fade it in/out comfortably.
_TARGET_PEAK_FRACTION = 0.04

_generation_lock = Lock()


def _cache_dir() -> Path:
    base = Path(tempfile.gettempdir()) / "dograh-ambient-cache"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _synthesize_brown_noise_wav(path: Path, sample_rate: int) -> None:
    """Render ~8 seconds of soft brown-noise to ``path`` as mono int16."""
    rng = random.Random(0xC0FFEE)  # deterministic for cache reuse
    n_samples = sample_rate * _LOOP_SECONDS

    # Brown noise = integrated white noise. Track a running accumulator
    # with a leak factor so it can't drift to int16 saturation.
    leak = 0.997
    walk = 0.0
    raw = [0.0] * n_samples
    for i in range(n_samples):
        walk = leak * walk + rng.gauss(0.0, 1.0)
        raw[i] = walk

    # One-pole low-pass to suppress remaining sibilant content.
    cutoff_hz = 1800.0
    rc = 1.0 / (2.0 * math.pi * cutoff_hz)
    dt = 1.0 / sample_rate
    alpha = dt / (rc + dt)
    prev = 0.0
    for i in range(n_samples):
        prev = prev + alpha * (raw[i] - prev)
        raw[i] = prev

    # Normalize to target peak amplitude.
    peak = max((abs(v) for v in raw), default=1.0) or 1.0
    target = _TARGET_PEAK_FRACTION * 32767.0
    scale = target / peak

    # Apply a short raised-cosine fade to the loop join so it doesn't
    # click. We crossfade the first/last `fade_n` samples.
    fade_n = min(int(0.05 * sample_rate), n_samples // 8)
    pcm = bytearray(n_samples * 2)
    for i in range(n_samples):
        sample = raw[i] * scale
        if i < fade_n:
            mix = 0.5 - 0.5 * math.cos(math.pi * (i / fade_n))
            tail = raw[n_samples - fade_n + i] * scale
            sample = sample * mix + tail * (1.0 - mix)
        clipped = max(-32768, min(32767, int(sample)))
        struct.pack_into("<h", pcm, i * 2, clipped)

    tmp_path = path.with_suffix(".wav.tmp")
    with wave.open(str(tmp_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(pcm))
    os.replace(tmp_path, path)


def get_office_ambience_path(sample_rate: int) -> Path:
    """Return a path to an office-ambience WAV at the requested rate.

    Resolution order:
      1. ``api/assets/office-ambience-<sample_rate>-mono.wav`` — the
         original location, if a real asset has been committed.
      2. A cached synthesized loop in the OS temp dir. Synthesized once
         per process lifetime (and per sample rate) under a lock so
         concurrent calls don't race.
    """
    static_path = (
        _STATIC_ASSETS_DIR / f"office-ambience-{sample_rate}-mono.wav"
    )
    if static_path.exists():
        return static_path

    cached = _cache_dir() / f"office-ambience-{sample_rate}-mono.wav"
    if cached.exists():
        return cached

    with _generation_lock:
        # Re-check after acquiring the lock to avoid double generation.
        if cached.exists():
            return cached
        logger.info(
            f"[AmbientAudio] No static asset at {static_path}; "
            f"synthesizing soft office ambience at {sample_rate} Hz "
            f"(cached at {cached})"
        )
        _synthesize_brown_noise_wav(cached, sample_rate)
    return cached
