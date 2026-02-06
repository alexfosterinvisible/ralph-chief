#!/usr/bin/env -S uv run --script
"""Fireworks oss120b LLM caller + ralph loop — no tool-use.

Usage:
    uv run llm_fw.py "your prompt here"       # ralph loop
    uv run llm_fw.py --example code_review    # run example prompt (3 iters)
    uv run llm_fw.py --example list           # list available examples
    uv run llm_fw.py                          # smoke-test demo

Requirements:
☑️ R1: Call gpt-oss-120b on Fireworks via OpenAI-compatible API
☑️ R2: class CONFIG with all tunable params
☑️ R3: def llm(prompt, config=CONFIG) → str
☑️ R4: Handle rate limits (60 req/min, 12k gen tok/min, 60k prompt tok/min)
☑️ R5: asyncio.Semaphore on global var for cross-async safety
☑️ R6: tenacity exp-backoff retries up to 3
☑️ R7: Rich prints w/ color for everything
☑️ R8: Streaming for fast TTFT
☑️ R9: ralph_loop(prompt) — while-true loop, logs per-commit
☑️ R10: AGENT_PROMPT in CONFIG, read fresh each iteration
☑️ R11: PROMPTS class w/ example prompts (tuple format)
☑️ R12: MAX_ITERATIONS for bounded loop runs (0 = infinite)
⛔ Tool-use / function-calling
⛔ Multi-turn memory (stateless per call)
"""
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "openai>=2.10.0",
#   "tenacity>=9.0.0",
#   "rich>=13.0.0",
# ]
# ///

import asyncio
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openai import AsyncOpenAI, RateLimitError, APIStatusError
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
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

    # ── ralph loop ──
    # Full agent prompt — pattern from anthropic.com/engineering/building-c-compiler
    # The AGENT_PROMPT_FILE overrides this if it exists on disk.
    AGENT_PROMPT: str = (
        # ── role & mindset ──
        "You are a senior software engineer working autonomously in a loop.\n"
        "Each iteration you start fresh — no memory of previous runs.\n"
        "Your only context is this prompt, the codebase, and any files you read.\n\n"
        # ── approach: decompose → track → self-direct → persist ──
        "APPROACH:\n"
        "1. ORIENT — Read progress files, READMEs, and recent git log to understand current state.\n"
        "2. DECOMPOSE — Break the task into small, independently-completable pieces.\n"
        "3. PICK ONE — Choose the highest-value next piece. Don't redo finished work.\n"
        "4. EXECUTE — Implement it. Write code, tests, or analysis as needed.\n"
        "5. RECORD — Update progress files so the NEXT iteration knows what you did.\n"
        "6. NEVER STOP EARLY — Keep going until the piece is complete and verified.\n\n"
        # ── state management (you start fresh each loop) ──
        "STATE MANAGEMENT:\n"
        "- Maintain a PROGRESS.md with: what's done, what's in-progress, what's next.\n"
        "- Log errors with 'ERROR:' prefix on the same line (grep-friendly).\n"
        "- Pre-compute summary stats instead of dumping raw output.\n"
        "- Keep context concise — don't emit thousands of lines of noise.\n\n"
        # ── quality ──
        "QUALITY:\n"
        "- Each change should be small, correct, and tested before moving on.\n"
        "- Don't break existing functionality — verify before and after.\n"
        "- If stuck, document what you tried and why it failed, then move on.\n"
    )
    AGENT_PROMPT_FILE: str = "AGENT_PROMPT.md"  # overrides AGENT_PROMPT if exists
    AGENT_LOGS_DIR: str = "agent_logs"
    LOOP_COOLDOWN: float = 1.0        # seconds between iterations
    MAX_ITERATIONS: int = 0           # 0 = infinite, >0 = bounded


CFG = CONFIG()


# ─────────────── EXAMPLE PROMPTS ─────────────────────────────
# Tuple format: multi-line strings, comments between lines.
# Usage: uv run llm_fw.py --example <name>

class PROMPTS:
    """Example prompts that exercise the ralph loop sensibly."""

    # ── code review: analyze a real file in the repo ──
    code_review = (
        "Review the file llm_fw.py in this repository.\n"
        "1. List every function and its purpose (1-line each).\n"
        "2. Identify the top 3 code smells or improvements.\n"
        "3. For each improvement, show the exact diff you'd apply.\n"
        "4. Rate overall code quality 1-10 with justification.\n"
        # agent should produce structured, actionable output
        "5. STATUS: summarize findings, suggest next iteration focus."
    )

    # ── feature design: plan a new capability ──
    feature_design = (
        "Design a retry-with-circuit-breaker for the LLM caller.\n"
        "1. Define the state machine: CLOSED → OPEN → HALF-OPEN.\n"
        "2. Specify thresholds: failure count, timeout, half-open probe.\n"
        "3. Write the Python dataclass for CircuitBreaker state.\n"
        "4. Write the async wrapper function with full type hints.\n"
        "5. Write 3 unit tests (pytest style) covering each transition.\n"
        # each iteration should produce deeper / more refined output
        "6. STATUS: what's designed, what needs refinement, what's next."
    )

    # ── bug hunt: find and fix a hypothetical issue ──
    bug_hunt = (
        "The streaming response sometimes returns empty text.\n"
        "1. Trace the data flow: API call → stream chunks → join → return.\n"
        "2. List every place where empty/None could leak through.\n"
        "3. For each, propose a defensive check with exact code.\n"
        "4. Write a test that reproduces empty-response edge case.\n"
        "5. STATUS: root causes found, fixes proposed, confidence level."
    )

    # ── refactor: simplify existing code ──
    refactor = (
        "Refactor the CONFIG dataclass in llm_fw.py.\n"
        "1. Group related fields into nested dataclasses (ModelCfg, RetryCfg, etc).\n"
        "2. Add validation in __post_init__ (e.g. MAX_TOKENS > 0).\n"
        "3. Add a .from_env() classmethod that loads from env vars.\n"
        "4. Show the complete refactored code.\n"
        "5. STATUS: what changed, what's cleaner, backwards-compat notes."
    )

    # ── architecture: design a multi-agent system ──
    architecture = (
        "Design a parallel agent system (like anthropic.com/engineering/building-c-compiler).\n"
        "1. Define the coordination protocol: task locks, git sync, conflict resolution.\n"
        "2. Sketch the Docker container setup for N parallel agents.\n"
        "3. Define the AGENT_PROMPT.md that each agent reads.\n"
        "4. Show the bash harness (while-true loop + git push/pull).\n"
        "5. STATUS: architecture complete? gaps? next steps?"
    )

    @classmethod
    def get(cls, name: str) -> str | None:
        """Lookup prompt by name, return None if not found."""
        val = getattr(cls, name, None)
        return val if isinstance(val, str) else None

    @classmethod
    def names(cls) -> list[str]:
        """All available prompt names."""
        return [k for k in vars(cls) if not k.startswith("_") and isinstance(getattr(cls, k), str)]
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


# ─────────────── RALPH LOOP ──────────────────────────────────

def _git_short(n: int = 6) -> str:
    """Current commit hash, short."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", f"--short={n}", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        return "nogit"


def _read_agent_prompt(cfg: CONFIG) -> str:
    """Read AGENT_PROMPT_FILE if it exists, else fall back to CONFIG.AGENT_PROMPT."""
    p = Path(cfg.AGENT_PROMPT_FILE)
    if p.is_file():
        text = p.read_text().strip()
        CON.print(f"[dim]agent prompt: {p.resolve()} ({len(text)} chars)[/]")
        return text
    return cfg.AGENT_PROMPT


def _write_log(logfile: Path, prompt: str, result: str) -> None:
    """Append iteration result to logfile."""
    logfile.parent.mkdir(parents=True, exist_ok=True)
    with logfile.open("a") as f:
        f.write(f"\n{'='*72}\n")
        f.write(f"TIME: {datetime.now().isoformat()}\n")
        f.write(f"PROMPT ({len(prompt)} chars):\n{prompt[:500]}{'…' if len(prompt)>500 else ''}\n")
        f.write(f"{'─'*72}\n")
        f.write(f"RESPONSE ({len(result)} chars):\n{result}\n")
    CON.print(f"[dim]logged → {logfile.resolve()}[/]")


async def ralph_loop(prompt: str, cfg: CONFIG = CFG) -> None:
    """The ralph loop — while-true, fresh context each iteration.

    Pattern from anthropic.com/engineering/building-c-compiler:
    each iteration reads agent prompt fresh, gets git commit,
    calls LLM, logs output, repeats.
    """
    bound = f"max {cfg.MAX_ITERATIONS}" if cfg.MAX_ITERATIONS > 0 else "infinite"
    CON.rule("[bold magenta]ralph loop — oss120b (no tool-use)[/]")
    CON.print(f"[bold yellow]user prompt:[/] {prompt}")
    CON.print(f"[dim]cooldown: {cfg.LOOP_COOLDOWN}s  |  iterations: {bound}  |  logs: {cfg.AGENT_LOGS_DIR}/[/]\n")

    iteration = 0
    while True:
        iteration += 1
        if cfg.MAX_ITERATIONS > 0 and iteration > cfg.MAX_ITERATIONS:
            CON.rule(f"[bold green]done — {cfg.MAX_ITERATIONS} iterations complete[/]")
            break

        commit = _git_short()
        logfile = Path(cfg.AGENT_LOGS_DIR) / f"agent_{commit}_{iteration:04d}.log"

        CON.rule(f"[bold cyan]iteration {iteration}/{bound}  |  {commit}[/]")

        # ── build full prompt: agent instructions + user prompt + iteration ctx ──
        agent_prompt = _read_agent_prompt(cfg)
        full_prompt = (
            f"{agent_prompt}\n\n---\n\n"
            f"USER TASK:\n{prompt}\n\n"
            f"---\n"
            f"ITERATION: {iteration} of {bound}\n"
            f"INSTRUCTION: On iteration 1, orient and plan. On subsequent iterations,\n"
            f"build on your previous analysis — go deeper, refine, or tackle the next piece.\n"
            f"Do NOT repeat yourself. Each iteration must add new value.\n"
        )

        try:
            result = await llm(full_prompt, cfg)
            _write_log(logfile, full_prompt, result)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            CON.print(f"[bold red]error: {e}[/]")
            _write_log(logfile, full_prompt, f"ERROR: {e}")

        # ── cooldown before next iteration (skip on last) ──
        last = cfg.MAX_ITERATIONS > 0 and iteration >= cfg.MAX_ITERATIONS
        if cfg.LOOP_COOLDOWN > 0 and not last:
            CON.print(f"[dim]sleeping {cfg.LOOP_COOLDOWN}s…[/]")
            await asyncio.sleep(cfg.LOOP_COOLDOWN)


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
    await llm(big_input)
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


def _run_example(name: str) -> None:
    """Run a named example prompt through the ralph loop (3 iterations)."""
    if name == "list":
        CON.rule("[bold magenta]available example prompts[/]")
        for n in PROMPTS.names():
            preview = (getattr(PROMPTS, n) or "")[:80].replace("\n", " ")
            CON.print(f"  [bold cyan]{n:<20}[/] {preview}…")
        return

    prompt = PROMPTS.get(name)
    if not prompt:
        CON.print(f"[bold red]unknown example:[/] {name}")
        CON.print(f"[dim]available: {', '.join(PROMPTS.names())}[/]")
        sys.exit(1)

    CON.print(f"[bold green]running example:[/] {name} (3 iterations)\n")
    cfg = CONFIG(MAX_ITERATIONS=3, LOOP_COOLDOWN=0.5)
    asyncio.run(ralph_loop(prompt, cfg))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--example":
        # --example <name> → bounded ralph loop with example prompt
        name = sys.argv[2] if len(sys.argv) > 2 else "list"
        _run_example(name)
    elif len(sys.argv) > 1:
        # CLI arg = prompt → ralph loop (infinite unless MAX_ITERATIONS set)
        asyncio.run(ralph_loop(" ".join(sys.argv[1:])))
    else:
        # no args → smoke test
        asyncio.run(_demo())
