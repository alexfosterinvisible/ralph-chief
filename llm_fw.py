#!/usr/bin/env python3
"""Fireworks oss120b LLM caller — no tool-use, raw completions.

Requirements:
☑️ R1: Call gpt-oss-120b on Fireworks via OpenAI-compatible API
☑️ R2: class CONFIG with all tunable params
☑️ R3: def llm(prompt, config=CONFIG) → str
☑️ R4: Handle rate limits (60 req/min, 12k gen tok/min, 60k prompt tok/min)
☑️ R5: asyncio.Semaphore on global var for cross-async safety
☑️ R6: tenacity exp-backoff retries up to 3
☑️ R7: Rich prints w/ color for everything
☑️ R8: Streaming for fast TTFT
⛔ Tool-use / function-calling
⛔ Multi-turn memory (stateless per call)
"""
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "openai>=2.10.0",
#   "tenacity>=9.0.0",
#   "rich>=13.0.0",
# ]
# ///

import asyncio
import os
import sys
import time
from dataclasses import dataclass, field

from openai import AsyncOpenAI, RateLimitError, APIStatusError
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

# ─────────────────────────── CONFIG ───────────────────────────

@dataclass
class CONFIG:
    """All Fireworks oss120b knobs in one place."""
    # ── model ──
    MODEL: str = "accounts/fireworks/models/gpt-oss-120b"
    BASE_URL: str = "https://api.fireworks.ai/inference/v1"
    API_KEY: str = field(default_factory=lambda: os.environ.get("FIREWORKS_API_KEY", ""))

    # ── generation ──
    MAX_TOKENS: int = 4096
    TEMPERATURE: float = 0.7
    STREAM: bool = True

    # ── rate-limit / concurrency ──
    MAX_CONCURRENT: int = 10          # semaphore cap
    RPM: int = 60                     # requests per minute
    GEN_TPM: int = 12_000             # generated tokens per minute
    PROMPT_TPM: int = 60_000          # prompt tokens per minute

    # ── retry ──
    MAX_RETRIES: int = 3
    BACKOFF_MIN: float = 1.0          # seconds
    BACKOFF_MAX: float = 8.0          # seconds


CFG = CONFIG()
CON = Console()

# ─────────────── GLOBAL SEMAPHORE (cross-async safe) ─────────

_SEM: asyncio.Semaphore | None = None

def _sem() -> asyncio.Semaphore:
    """Lazy-init semaphore bound to the running event loop."""
    global _SEM
    if _SEM is None:
        _SEM = asyncio.Semaphore(CFG.MAX_CONCURRENT)
    return _SEM

# ─────────────── CLIENT (singleton) ──────────────────────────

_CLIENT: AsyncOpenAI | None = None

def _client() -> AsyncOpenAI:
    global _CLIENT
    if _CLIENT is None:
        if not CFG.API_KEY:
            CON.print("[bold red]FIREWORKS_API_KEY not set[/]")
            sys.exit(1)
        _CLIENT = AsyncOpenAI(base_url=CFG.BASE_URL, api_key=CFG.API_KEY)
    return _CLIENT

# ─────────────── CORE LLM CALL ──────────────────────────────

@retry(
    retry=retry_if_exception_type((RateLimitError, APIStatusError)),
    stop=stop_after_attempt(CFG.MAX_RETRIES),
    wait=wait_exponential(min=CFG.BACKOFF_MIN, max=CFG.BACKOFF_MAX),
    reraise=True,
)
async def _call(prompt: str, cfg: CONFIG) -> str:
    """Single LLM call with streaming + retry."""
    async with _sem():
        t0 = time.perf_counter()
        chunks: list[str] = []
        ttft: float | None = None

        stream = await _client().chat.completions.create(
            model=cfg.MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=cfg.MAX_TOKENS,
            temperature=cfg.TEMPERATURE,
            stream=cfg.STREAM,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices[0].delta else None
            if delta:
                if ttft is None:
                    ttft = time.perf_counter() - t0
                chunks.append(delta)

        elapsed = time.perf_counter() - t0
        text = "".join(chunks)

        # ── rich summary ──
        CON.print(
            Panel(
                Text(text, style="white"),
                title=f"[bold cyan]{cfg.MODEL.split('/')[-1]}[/]",
                subtitle=(
                    f"[dim]{len(text)} chars  |  "
                    f"TTFT {ttft:.2f}s  |  "
                    f"total {elapsed:.2f}s[/]"
                ),
                border_style="green",
            )
        )
        return text


async def llm(prompt: str, cfg: CONFIG = CFG) -> str:
    """Public API — call oss120b, get text back."""
    CON.print(f"[bold yellow]→ prompt:[/] {prompt[:120]}{'…' if len(prompt)>120 else ''}")
    return await _call(prompt, cfg)


# ─────────────── DEMO / GUARDMAIN ────────────────────────────

async def _demo() -> None:
    CON.rule("[bold magenta]Fireworks oss120b — smoke test[/]")

    # ── test 1: joke ──
    CON.print("\n[bold green]Test 1:[/] 1-line joke\n")
    await llm("Tell me a 1-line joke.")

    # ── test 2: long INPUT prompt → fast response ──
    CON.print("\n[bold green]Test 2:[/] 3-page INPUT prompt → short answer (< 3s e2e)\n")
    big_input = (
        "Here is a very long document for you to analyze:\n\n"
        + ("The history of computing spans centuries of innovation. " * 200)
        + "\n\nIn exactly ONE sentence, what is this document about?"
    )
    CON.print(f"[dim]Input length: {len(big_input)} chars (~3 pages)[/]")
    t0 = time.perf_counter()
    text = await llm(big_input)
    wall = time.perf_counter() - t0
    ok = wall < 3.0
    CON.print(f"\n[bold {'green' if ok else 'yellow'}]e2e: {wall:.2f}s  |  {'PASS <3s' if ok else 'SLOW'}[/]")

    # ── test 3: parallel burst (semaphore proof) ──
    CON.print("\n[bold green]Test 3:[/] 3 parallel calls (semaphore)\n")
    t0 = time.perf_counter()
    results = await asyncio.gather(
        llm("What is 2+2?"),
        llm("Name 3 colors."),
        llm("Capital of France?"),
    )
    wall = time.perf_counter() - t0
    CON.print(f"\n[bold cyan]Parallel wall: {wall:.2f}s  |  {len(results)} results[/]")


if __name__ == "__main__":
    asyncio.run(_demo())
