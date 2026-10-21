"""
Load test for voice agents — simulates 100+ concurrent Twilio-style calls.

Exercises the full pipeline: DB → WebSocket → Pipecat engine → STT/LLM/TTS,
without real Twilio accounts or phone numbers.

Each simulated call:
  1. Creates a WorkflowRun with gathered_context={provider: "twilio"} via direct DB
  2. Opens a WebSocket mimicking Twilio's media-stream protocol
  3. Sends silence (μ-law encoded) for a configurable duration
  4. Listens for TTS audio coming back from the agent
  5. Gracefully disconnects

Prerequisites:
  pip install websockets aiohttp

Usage (run from the repo root):

  # 100 concurrent calls, 15s each, against a local backend
  python -m api.tests.load_test_voice_agents \\
      --base-url http://localhost:8000 \\
      --workflow-id 42 \\
      --user-id 1 \\
      --concurrency 100 \\
      --call-duration 15

  # Quick 10-call smoke test
  python -m api.tests.load_test_voice_agents \\
      --base-url http://localhost:8000 \\
      --workflow-id 42 \\
      --user-id 1 \\
      --concurrency 10 \\
      --call-duration 5

Environment variables (loaded from .env automatically):
  DATABASE_URL   — required (async postgres connection string)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import random
import string
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Load .env from the api/ directory so DATABASE_URL is available
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


# ─── Result tracking ─────────────────────────────────────────────────────────

@dataclass
class CallResult:
    call_index: int
    workflow_run_id: Optional[int] = None
    ws_connected: bool = False
    pipeline_started: bool = False
    first_audio_received: bool = False
    agent_spoke: bool = False
    error: Optional[str] = None
    duration_s: float = 0.0
    time_to_ws_connect_ms: float = 0.0
    time_to_first_audio_ms: float = 0.0
    messages_sent: int = 0
    messages_received: int = 0


@dataclass
class LoadTestReport:
    total_calls: int = 0
    successful: int = 0
    failed: int = 0
    ws_connect_failures: int = 0
    pipeline_start_failures: int = 0
    no_audio_received: int = 0
    avg_ws_connect_ms: float = 0.0
    avg_first_audio_ms: float = 0.0
    avg_duration_s: float = 0.0
    p50_ws_connect_ms: float = 0.0
    p95_ws_connect_ms: float = 0.0
    p99_ws_connect_ms: float = 0.0
    p50_first_audio_ms: float = 0.0
    p95_first_audio_ms: float = 0.0
    p99_first_audio_ms: float = 0.0
    errors: list = field(default_factory=list)
    results: list = field(default_factory=list)


# ─── Twilio protocol simulation helpers ──────────────────────────────────────

def _rand_id(prefix: str, length: int = 32) -> str:
    return prefix + "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def make_silence_payload(duration_ms: int = 20) -> str:
    """Base64-encoded μ-law silence (0xFF). 8 kHz mono → 160 bytes per 20 ms."""
    n = int(8000 * duration_ms / 1000)
    return base64.b64encode(b"\xff" * n).decode()


SILENCE_20MS = make_silence_payload(20)


# ─── Database helpers (direct async SQLAlchemy) ──────────────────────────────

_engine = None
_Session = None


async def _init_db():
    """Lazy-init a lightweight async engine + session factory."""
    global _engine, _Session

    if _engine is not None:
        return

    import ssl
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL not set. Copy api/.env or export it in your shell."
        )

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    _engine = create_async_engine(
        db_url,
        pool_size=20,
        max_overflow=30,
        connect_args={"ssl": ssl_ctx, "prepared_statement_cache_size": 0},
    )
    _Session = async_sessionmaker(_engine, expire_on_commit=False)


async def create_run_in_db(workflow_id: int, user_id: int, call_index: int) -> int:
    """Insert a WorkflowRun row with gathered_context already set for Twilio."""
    await _init_db()

    from sqlalchemy import text

    name = f"LOAD-TEST-{call_index:04d}-{random.randint(1000, 9999)}"
    gathered = json.dumps({
        "provider": "twilio",
        "call_direction": "outbound",
        "greeting_played_by_provider": False,
    })

    async with _Session() as session:
        # Look up the current definition for this workflow
        def_row = await session.execute(text(
            "SELECT id FROM workflow_definitions "
            "WHERE workflow_id = :wid AND is_current = true LIMIT 1"
        ), {"wid": workflow_id})
        def_id = def_row.scalar()

        # Look up template_context_variables for initial_context
        wf_row = await session.execute(text(
            "SELECT template_context_variables FROM workflows WHERE id = :wid AND user_id = :uid"
        ), {"wid": workflow_id, "uid": user_id})
        row = wf_row.fetchone()
        if row is None:
            raise RuntimeError(
                f"Workflow {workflow_id} not found for user {user_id}. "
                f"Double-check --workflow-id and --user-id."
            )
        initial_ctx = row[0] or "{}"
        if isinstance(initial_ctx, dict):
            initial_ctx = json.dumps(initial_ctx)

        result = await session.execute(text("""
            INSERT INTO workflow_runs
                (name, workflow_id, mode, definition_id, initial_context,
                 gathered_context, state, is_completed, logs, storage_backend,
                 created_at, updated_at)
            VALUES
                (:name, :wid, 'twilio', :def_id, :initial_ctx::jsonb,
                 :gathered::jsonb, 'initialized', false, '{}'::jsonb, 'supabase',
                 NOW(), NOW())
            RETURNING id
        """), {
            "name": name,
            "wid": workflow_id,
            "def_id": def_id,
            "initial_ctx": initial_ctx,
            "gathered": gathered,
        })
        run_id = result.scalar()
        await session.commit()
        return run_id


async def cleanup_runs(run_ids: list[int]):
    """Delete load-test workflow runs to keep the DB clean."""
    if not run_ids:
        return
    await _init_db()
    from sqlalchemy import text

    async with _Session() as session:
        await session.execute(
            text("DELETE FROM workflow_runs WHERE id = ANY(:ids)"),
            {"ids": run_ids},
        )
        await session.commit()


# ─── Single call simulation ─────────────────────────────────────────────────

async def simulate_call(
    ws_base_url: str,
    workflow_id: int,
    user_id: int,
    call_index: int,
    call_duration_s: float,
    ramp_delay: float,
) -> CallResult:
    import websockets
    import websockets.exceptions

    result = CallResult(call_index=call_index)
    t0 = time.perf_counter()

    if ramp_delay > 0:
        await asyncio.sleep(ramp_delay)

    try:
        # 1. Create the workflow run directly in the DB
        run_id = await create_run_in_db(workflow_id, user_id, call_index)
        result.workflow_run_id = run_id

        # 2. Connect WebSocket
        ws_url = f"{ws_base_url}/api/v1/telephony/ws/{workflow_id}/{user_id}/{run_id}"
        stream_sid = _rand_id("MZ")
        call_sid = _rand_id("CA")

        t_ws = time.perf_counter()
        async with websockets.connect(
            ws_url,
            max_size=2**20,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            result.ws_connected = True
            result.time_to_ws_connect_ms = (time.perf_counter() - t_ws) * 1000

            # 3. Twilio "connected" event
            await ws.send(json.dumps({
                "event": "connected",
                "protocol": "Call",
                "version": "1.0.0",
            }))

            # 4. Twilio "start" event
            await ws.send(json.dumps({
                "event": "start",
                "sequenceNumber": "1",
                "start": {
                    "streamSid": stream_sid,
                    "accountSid": "ACloadtest000000000000000000000000",
                    "callSid": call_sid,
                    "tracks": ["inbound"],
                    "mediaFormat": {
                        "encoding": "audio/x-mulaw",
                        "sampleRate": 8000,
                        "channels": 1,
                    },
                },
                "streamSid": stream_sid,
            }))
            result.pipeline_started = True

            # 5. Stream silence & receive in parallel
            t_first_audio = None
            stop = asyncio.Event()

            async def _sender():
                seq = 2
                end_at = time.perf_counter() + call_duration_s
                while time.perf_counter() < end_at and not stop.is_set():
                    try:
                        await ws.send(json.dumps({
                            "event": "media",
                            "sequenceNumber": str(seq),
                            "media": {
                                "track": "inbound",
                                "chunk": str(seq),
                                "timestamp": str((seq - 2) * 20),
                                "payload": SILENCE_20MS,
                            },
                            "streamSid": stream_sid,
                        }))
                    except websockets.exceptions.ConnectionClosed:
                        break
                    result.messages_sent += 1
                    seq += 1
                    await asyncio.sleep(0.02)

                try:
                    await ws.send(json.dumps({"event": "stop", "streamSid": stream_sid}))
                except websockets.exceptions.ConnectionClosed:
                    pass
                stop.set()

            async def _receiver():
                nonlocal t_first_audio
                try:
                    async for raw in ws:
                        result.messages_received += 1
                        try:
                            msg = json.loads(raw)
                            if msg.get("event") == "media" and t_first_audio is None:
                                t_first_audio = time.perf_counter()
                                result.first_audio_received = True
                                result.agent_spoke = True
                                result.time_to_first_audio_ms = (t_first_audio - t_ws) * 1000
                        except (json.JSONDecodeError, TypeError):
                            pass

                        if stop.is_set():
                            await asyncio.sleep(0.5)
                            break
                except websockets.exceptions.ConnectionClosed:
                    pass

            await asyncio.gather(_sender(), _receiver())

    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"

    result.duration_s = time.perf_counter() - t0
    return result


# ─── Orchestrator ────────────────────────────────────────────────────────────

def _pct(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    return s[min(int(len(s) * p / 100), len(s) - 1)]


async def run_load_test(
    base_url: str,
    workflow_id: int,
    user_id: int,
    concurrency: int,
    call_duration_s: float,
    ramp_up_s: float,
    cleanup: bool,
) -> LoadTestReport:
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")

    print(f"\n{'='*70}")
    print(f"  VOICE AGENT LOAD TEST")
    print(f"{'='*70}")
    print(f"  Target:          {base_url}")
    print(f"  WebSocket:       {ws_url}")
    print(f"  Workflow ID:     {workflow_id}")
    print(f"  User ID:         {user_id}")
    print(f"  Concurrency:     {concurrency} simultaneous calls")
    print(f"  Call duration:   {call_duration_s}s per call")
    print(f"  Ramp-up:         {ramp_up_s}s")
    print(f"  Cleanup DB:      {cleanup}")
    print(f"{'='*70}\n")

    # Validate DB connection early
    await _init_db()
    print("  [OK] Database connection established")

    delay_per = ramp_up_s / max(concurrency, 1)

    tasks = [
        simulate_call(
            ws_base_url=ws_url,
            workflow_id=workflow_id,
            user_id=user_id,
            call_index=i,
            call_duration_s=call_duration_s,
            ramp_delay=i * delay_per,
        )
        for i in range(concurrency)
    ]

    print(f"  Launching {concurrency} calls...\n")
    t_start = time.perf_counter()

    # Print progress every 5 seconds
    async def _progress():
        while True:
            await asyncio.sleep(5)
            done = sum(1 for t in tasks_set if t.done())
            elapsed = time.perf_counter() - t_start
            print(f"  [{elapsed:.0f}s] {done}/{concurrency} calls completed")

    tasks_set = [asyncio.ensure_future(t) for t in tasks]
    progress_task = asyncio.create_task(_progress())

    results: list[CallResult] = await asyncio.gather(*tasks_set)
    progress_task.cancel()
    total_time = time.perf_counter() - t_start

    # Cleanup test runs
    if cleanup:
        run_ids = [r.workflow_run_id for r in results if r.workflow_run_id]
        if run_ids:
            print(f"\n  Cleaning up {len(run_ids)} test workflow runs...")
            try:
                await cleanup_runs(run_ids)
                print("  [OK] Cleanup done")
            except Exception as e:
                print(f"  [WARN] Cleanup failed: {e}")

    # Close DB engine
    if _engine:
        await _engine.dispose()

    # ── Compile report ───────────────────────────────────────────────────
    report = LoadTestReport(total_calls=concurrency, results=results)

    ws_times: list[float] = []
    audio_times: list[float] = []
    durations: list[float] = []

    for r in results:
        if r.error:
            report.failed += 1
            report.errors.append(f"Call #{r.call_index} (run={r.workflow_run_id}): {r.error}")
        else:
            report.successful += 1

        if not r.ws_connected:
            report.ws_connect_failures += 1
        else:
            ws_times.append(r.time_to_ws_connect_ms)

        if r.ws_connected and not r.pipeline_started:
            report.pipeline_start_failures += 1

        if r.pipeline_started and not r.first_audio_received:
            report.no_audio_received += 1

        if r.first_audio_received:
            audio_times.append(r.time_to_first_audio_ms)

        durations.append(r.duration_s)

    report.avg_ws_connect_ms = sum(ws_times) / max(len(ws_times), 1)
    report.p50_ws_connect_ms = _pct(ws_times, 50)
    report.p95_ws_connect_ms = _pct(ws_times, 95)
    report.p99_ws_connect_ms = _pct(ws_times, 99)

    report.avg_first_audio_ms = sum(audio_times) / max(len(audio_times), 1)
    report.p50_first_audio_ms = _pct(audio_times, 50)
    report.p95_first_audio_ms = _pct(audio_times, 95)
    report.p99_first_audio_ms = _pct(audio_times, 99)

    report.avg_duration_s = sum(durations) / max(len(durations), 1)

    # ── Print report ─────────────────────────────────────────────────────
    sr = report.successful / max(report.total_calls, 1) * 100

    print(f"\n{'='*70}")
    print(f"  LOAD TEST RESULTS")
    print(f"{'='*70}")
    print(f"  Wall time:               {total_time:.1f}s")
    print(f"  Total calls:             {report.total_calls}")
    print(f"  Successful:              {report.successful}  ({sr:.1f}%)")
    print(f"  Failed:                  {report.failed}")
    print(f"{'─'*70}")
    print(f"  WS connect failures:     {report.ws_connect_failures}")
    print(f"  Pipeline start failures: {report.pipeline_start_failures}")
    print(f"  No audio received:       {report.no_audio_received}")
    print(f"{'─'*70}")
    print(f"  WS connect  p50/p95/p99: {report.p50_ws_connect_ms:.0f} / {report.p95_ws_connect_ms:.0f} / {report.p99_ws_connect_ms:.0f} ms")
    print(f"  First audio p50/p95/p99: {report.p50_first_audio_ms:.0f} / {report.p95_first_audio_ms:.0f} / {report.p99_first_audio_ms:.0f} ms")
    print(f"  Avg call duration:       {report.avg_duration_s:.1f}s")
    print(f"{'='*70}")

    if report.errors:
        print(f"\n  ERRORS ({len(report.errors)}):")
        for e in report.errors[:25]:
            print(f"    - {e}")
        if len(report.errors) > 25:
            print(f"    ... and {len(report.errors) - 25} more")

    if sr >= 95:
        print(f"\n  PASS  ({sr:.1f}% success rate)")
    else:
        print(f"\n  FAIL  ({sr:.1f}% success rate — below 95% threshold)")

    return report


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Load test voice agents with simulated Twilio calls",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 100 concurrent calls
  python -m api.tests.load_test_voice_agents \\
      --base-url http://localhost:8000 \\
      --workflow-id 42 --user-id 1 \\
      --concurrency 100

  # Quick 10-call smoke test
  python -m api.tests.load_test_voice_agents \\
      --base-url http://localhost:8000 \\
      --workflow-id 42 --user-id 1 \\
      --concurrency 10 --call-duration 5

  # Against production (be careful!)
  python -m api.tests.load_test_voice_agents \\
      --base-url https://api.yoursite.com \\
      --workflow-id 42 --user-id 1 \\
      --concurrency 50 --call-duration 10 --ramp-up 30
        """,
    )
    parser.add_argument("--base-url", default="http://localhost:8000",
                        help="Backend URL (default: http://localhost:8000)")
    parser.add_argument("--workflow-id", type=int, required=True,
                        help="Workflow ID to test against")
    parser.add_argument("--user-id", type=int, required=True,
                        help="User ID that owns the workflow")
    parser.add_argument("--concurrency", type=int, default=100,
                        help="Number of simultaneous calls (default: 100)")
    parser.add_argument("--call-duration", type=float, default=15,
                        help="Seconds each call lasts (default: 15)")
    parser.add_argument("--ramp-up", type=float, default=10,
                        help="Seconds to stagger call starts (default: 10)")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Keep test workflow runs in the DB (default: clean up)")
    args = parser.parse_args()

    report = asyncio.run(
        run_load_test(
            base_url=args.base_url.rstrip("/"),
            workflow_id=args.workflow_id,
            user_id=args.user_id,
            concurrency=args.concurrency,
            call_duration_s=args.call_duration,
            ramp_up_s=args.ramp_up,
            cleanup=not args.no_cleanup,
        )
    )

    sr = report.successful / max(report.total_calls, 1) * 100
    sys.exit(0 if sr >= 95 else 1)


if __name__ == "__main__":
    main()
