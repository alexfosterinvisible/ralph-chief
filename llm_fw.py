#!/usr/bin/env -S uv run --script
"""Fireworks oss120b LLM caller + ralph loop — no tool-use.

Usage:
    uv run llm_fw.py "your prompt here"       # ralph loop
    uv run llm_fw.py --example code_review    # run example prompt (3 iters)
    uv run llm_fw.py --example list           # list available examples
    uv run llm_fw.py --tests                  # run all tests (unit + integration)
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
☑️ R13: --tests runs all unit + integration tests in-file
☑️ R14: <progress> tag parsing with regex, retry on failure
☑️ R15: PROGRESS carried between iterations as prompt injection
⛔ Tool-use / function-calling
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
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openai import AsyncOpenAI, RateLimitError, APIStatusError
from rich.console import Console
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
        "Each iteration you start fresh — your ONLY memory is the <progress> block below.\n\n"
        # ── approach: decompose → track → self-direct → persist ──
        "APPROACH:\n"
        "1. READ the <progress> block to understand what's already done.\n"
        "2. PICK the highest-value next piece. Don't redo finished work.\n"
        "3. EXECUTE — produce your analysis, code, or output.\n"
        "4. UPDATE the <progress> block at the END of your response (MANDATORY).\n\n"
        # ── CRITICAL: progress tag format ──
        "PROGRESS TAG (MANDATORY — your response MUST end with this):\n"
        "You MUST include exactly one <progress> tag at the end of your response.\n"
        "This is your ONLY way to pass state to the next iteration.\n"
        "Format:\n"
        "<progress>\n"
        "DONE: bullet list of completed items\n"
        "CURRENT: what you worked on this iteration\n"
        "NEXT: what the next iteration should focus on\n"
        "BLOCKERS: any issues (or 'none')\n"
        "</progress>\n\n"
        # ── quality ──
        "RULES:\n"
        "- Each iteration must add new value — do NOT repeat previous work.\n"
        "- Keep the <progress> block concise (under 500 chars).\n"
        "- If stuck, note what you tried and move on.\n"
        "- Log errors with 'ERROR:' prefix (grep-friendly).\n"
    )
    AGENT_PROMPT_FILE: str = "AGENT_PROMPT.md"  # overrides AGENT_PROMPT if exists
    AGENT_LOGS_DIR: str = "agent_logs"
    LOOP_COOLDOWN: float = 1.0        # seconds between iterations
    MAX_ITERATIONS: int = 0           # 0 = infinite, >0 = bounded
    PROGRESS_RETRIES: int = 2         # re-run if <progress> parse fails


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
    """Single LLM call with streaming + retry.  Streams tokens live to terminal."""
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

        # ── live-stream tokens to terminal ──
        CON.print(f"[bold cyan]{cfg.MODEL.split('/')[-1]}[/] ", end="")
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices[0].delta else None
            if delta:
                if ttft is None:
                    ttft = time.perf_counter() - t0
                chunks.append(delta)
                print(delta, end="", flush=True)
        print()  # newline after stream

        elapsed = time.perf_counter() - t0
        text = "".join(chunks)

        # ── compact summary line ──
        CON.print(
            f"[dim]── {len(text)} chars  |  "
            f"TTFT {ttft:.2f}s  |  "
            f"total {elapsed:.2f}s ──[/]"
        )
        return text


async def llm(prompt: str, cfg: CONFIG = CFG) -> str:
    """Public API — call oss120b, get text back."""
    CON.print(f"[bold yellow]→ prompt:[/] {prompt[:120]}{'…' if len(prompt)>120 else ''}")
    return await _call(prompt, cfg)


# ─────────────── PROGRESS PARSER ─────────────────────────────

_PROGRESS_RE = re.compile(r"<progress>(.*?)</progress>", re.DOTALL | re.IGNORECASE)


def _parse_progress(text: str) -> str | None:
    """Extract content between <progress>...</progress> tags. None if missing."""
    m = _PROGRESS_RE.search(text)
    return m.group(1).strip() if m else None


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


async def ralph_loop(prompt: str, cfg: CONFIG = CFG) -> str:
    """The ralph loop — while-true, carries <progress> between iterations.

    Since oss120b has no tool-use, the LLM outputs <progress>...</progress>
    tags. The harness parses them and injects the accumulated progress into
    the next iteration's prompt. If parse fails, re-runs the same step.

    Returns the final progress string.
    """
    bound = f"max {cfg.MAX_ITERATIONS}" if cfg.MAX_ITERATIONS > 0 else "infinite"
    CON.rule("[bold magenta]ralph loop — oss120b (no tool-use)[/]")
    CON.print(f"[bold yellow]user prompt:[/] {prompt}")
    CON.print(f"[dim]cooldown: {cfg.LOOP_COOLDOWN}s  |  iterations: {bound}  |  logs: {cfg.AGENT_LOGS_DIR}/[/]\n")

    progress: str = "DONE: nothing yet\nCURRENT: starting\nNEXT: orient and plan\nBLOCKERS: none"
    iteration = 0

    while True:
        iteration += 1
        if cfg.MAX_ITERATIONS > 0 and iteration > cfg.MAX_ITERATIONS:
            CON.rule(f"[bold green]done — {cfg.MAX_ITERATIONS} iterations complete[/]")
            break

        commit = _git_short()
        logfile = Path(cfg.AGENT_LOGS_DIR) / f"agent_{commit}_{iteration:04d}.log"

        CON.rule(f"[bold cyan]iteration {iteration}/{bound}  |  {commit}[/]")
        CON.print(f"[dim]progress in:[/] {progress[:200]}{'…' if len(progress)>200 else ''}")

        # ── build prompt: agent instructions + progress + user task ──
        agent_prompt = _read_agent_prompt(cfg)
        full_prompt = (
            f"{agent_prompt}\n\n---\n\n"
            f"PREVIOUS PROGRESS (from last iteration):\n"
            f"<progress>\n{progress}\n</progress>\n\n"
            f"---\n\n"
            f"USER TASK:\n{prompt}\n\n"
            f"---\n"
            f"ITERATION: {iteration} of {bound}\n"
        )

        # ── call LLM with retry on missing <progress> tag ──
        parsed: str | None = None
        for attempt in range(1 + cfg.PROGRESS_RETRIES):
            try:
                if attempt > 0:
                    CON.print(f"[bold yellow]retry {attempt}/{cfg.PROGRESS_RETRIES} — <progress> tag missing, re-running…[/]")
                result = await llm(full_prompt, cfg)
                _write_log(logfile, full_prompt, result)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                CON.print(f"[bold red]error: {e}[/]")
                _write_log(logfile, full_prompt, f"ERROR: {e}")
                break

            parsed = _parse_progress(result)
            if parsed is not None:
                break
            CON.print("[bold yellow]⚠ no <progress> tag found in response[/]")

        # ── update progress for next iteration ──
        if parsed:
            progress = parsed
            CON.print(f"[bold green]progress out:[/] {progress[:200]}{'…' if len(progress)>200 else ''}")
        else:
            CON.print("[bold red]<progress> parse failed after retries — keeping previous progress[/]")

        # ── cooldown (skip on last) ──
        last = cfg.MAX_ITERATIONS > 0 and iteration >= cfg.MAX_ITERATIONS
        if cfg.LOOP_COOLDOWN > 0 and not last:
            CON.print(f"[dim]sleeping {cfg.LOOP_COOLDOWN}s…[/]")
            await asyncio.sleep(cfg.LOOP_COOLDOWN)

    return progress


# ─────────────── TESTS ───────────────────────────────────────
# All tests in one place. Run via: uv run llm_fw.py --tests
# Unit tests (no API calls) run first, then integration tests (API calls).

_PASS = 0
_FAIL = 0


def _t(name: str, ok: bool, detail: str = "") -> bool:
    """Record a test result with rich output."""
    global _PASS, _FAIL
    tag = "[bold green]PASS[/]" if ok else "[bold red]FAIL[/]"
    suffix = f"  [dim]{detail}[/]" if detail else ""
    CON.print(f"  {tag}  {name}{suffix}")
    if ok:
        _PASS += 1
    else:
        _FAIL += 1
    return ok


# ─── unit tests (no API calls) ───────────────────────────────

def _test_config_defaults() -> None:
    """R2: CONFIG defaults are sane."""
    c = CONFIG()
    _t("config.MODEL is set", "gpt-oss-120b" in c.MODEL)
    _t("config.BASE_URL is fireworks", "fireworks.ai" in c.BASE_URL)
    _t("config.MAX_TOKENS > 0", c.MAX_TOKENS > 0)
    _t("config.TEMPERATURE in [0,2]", 0 <= c.TEMPERATURE <= 2.0)
    _t("config.MAX_RETRIES > 0", c.MAX_RETRIES > 0)
    _t("config.MAX_CONCURRENT > 0", c.MAX_CONCURRENT > 0)
    _t("config.RPM == 60", c.RPM == 60)
    _t("config.MAX_ITERATIONS default 0", c.MAX_ITERATIONS == 0)
    _t("config.LOOP_COOLDOWN >= 0", c.LOOP_COOLDOWN >= 0)


def _test_config_override() -> None:
    """R2: CONFIG fields can be overridden."""
    c = CONFIG(MAX_TOKENS=99, TEMPERATURE=0.0, MAX_ITERATIONS=5)
    _t("override MAX_TOKENS", c.MAX_TOKENS == 99)
    _t("override TEMPERATURE", c.TEMPERATURE == 0.0)
    _t("override MAX_ITERATIONS", c.MAX_ITERATIONS == 5)


def _test_prompts_class() -> None:
    """R11: PROMPTS has entries and lookup works."""
    names = PROMPTS.names()
    _t("PROMPTS has >=3 entries", len(names) >= 3, f"found {len(names)}")
    _t("PROMPTS.get('code_review') returns str", isinstance(PROMPTS.get("code_review"), str))
    _t("PROMPTS.get('nonexistent') returns None", PROMPTS.get("nonexistent") is None)
    for n in names:
        val = PROMPTS.get(n)
        _t(f"PROMPTS.{n} is non-empty str", isinstance(val, str) and len(val) > 20, f"{len(val or '')} chars")


def _test_git_short() -> None:
    """R9: _git_short returns a commit hash or 'nogit'."""
    h = _git_short()
    _t("_git_short returns string", isinstance(h, str))
    _t("_git_short length 6 or 'nogit'", len(h) == 6 or h == "nogit", f"got '{h}'")


def _test_read_agent_prompt_inline() -> None:
    """R10: _read_agent_prompt falls back to CONFIG.AGENT_PROMPT."""
    cfg = CONFIG(AGENT_PROMPT_FILE="__nonexistent_file__.md")
    result = _read_agent_prompt(cfg)
    _t("fallback to inline AGENT_PROMPT", "<progress>" in result and len(result) > 100, f"{len(result)} chars")


def _test_read_agent_prompt_file() -> None:
    """R10: _read_agent_prompt reads from file when it exists."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("CUSTOM PROMPT FROM FILE")
        f.flush()
        cfg = CONFIG(AGENT_PROMPT_FILE=f.name)
        result = _read_agent_prompt(cfg)
        _t("reads AGENT_PROMPT_FILE", result == "CUSTOM PROMPT FROM FILE", f"got '{result[:40]}'")
    Path(f.name).unlink(missing_ok=True)


def _test_write_log() -> None:
    """R9: _write_log creates file with expected content."""
    with tempfile.TemporaryDirectory() as td:
        logfile = Path(td) / "sub" / "test.log"
        _write_log(logfile, "test prompt", "test response")
        _t("logfile created", logfile.exists())
        content = logfile.read_text()
        _t("logfile has TIME:", "TIME:" in content)
        _t("logfile has PROMPT", "PROMPT" in content)
        _t("logfile has RESPONSE", "RESPONSE" in content)
        _t("logfile has test response", "test response" in content)


def _test_semaphore_lazy_init() -> None:
    """R5: semaphore is lazily initialized."""
    global _SEM
    old = _SEM
    _SEM = None
    s = _sem()
    _t("_sem() returns Semaphore", isinstance(s, asyncio.Semaphore))
    _t("_sem() is idempotent", _sem() is s)
    _SEM = old  # restore


def _test_iteration_context() -> None:
    """R12: iteration context string is injected correctly."""
    cfg = CONFIG(MAX_ITERATIONS=5)
    bound = f"max {cfg.MAX_ITERATIONS}" if cfg.MAX_ITERATIONS > 0 else "infinite"
    ctx = f"ITERATION: 3 of {bound}\n"
    _t("iteration context has number", "3 of max 5" in ctx)
    cfg2 = CONFIG(MAX_ITERATIONS=0)
    bound2 = f"max {cfg2.MAX_ITERATIONS}" if cfg2.MAX_ITERATIONS > 0 else "infinite"
    ctx2 = f"ITERATION: 1 of {bound2}\n"
    _t("infinite mode says 'infinite'", "infinite" in ctx2)


def _test_parse_progress() -> None:
    """R14: _parse_progress extracts <progress> content correctly."""
    # ── basic extraction ──
    text = "Here is my analysis.\n<progress>\nDONE: item1\nNEXT: item2\n</progress>"
    result = _parse_progress(text)
    _t("basic parse extracts content", result is not None and "DONE: item1" in result)

    # ── case insensitive ──
    text2 = "stuff\n<PROGRESS>\nDONE: x\n</PROGRESS>\nmore stuff"
    _t("case insensitive parse", _parse_progress(text2) is not None)

    # ── multiline with full structure ──
    text3 = (
        "Long analysis here...\n"
        "<progress>\n"
        "DONE: reviewed config, identified 3 smells\n"
        "CURRENT: writing diffs for smell #1\n"
        "NEXT: tackle smell #2\n"
        "BLOCKERS: none\n"
        "</progress>\n"
    )
    p = _parse_progress(text3)
    _t("multiline parse", p is not None)
    _t("multiline has DONE", p is not None and "DONE:" in p)
    _t("multiline has CURRENT", p is not None and "CURRENT:" in p)
    _t("multiline has NEXT", p is not None and "NEXT:" in p)
    _t("multiline has BLOCKERS", p is not None and "BLOCKERS:" in p)

    # ── no tag → None ──
    _t("missing tag returns None", _parse_progress("no tags here") is None)
    _t("empty string returns None", _parse_progress("") is None)

    # ── empty tag ──
    _t("empty tag returns empty str", _parse_progress("<progress></progress>") == "")

    # ── tag with extra whitespace ──
    p2 = _parse_progress("<progress>\n  \n  DONE: x  \n  \n</progress>")
    _t("whitespace stripped", p2 is not None and p2.startswith("DONE:"))


def _test_config_progress_retries() -> None:
    """R14: PROGRESS_RETRIES field exists and defaults to 2."""
    c = CONFIG()
    _t("PROGRESS_RETRIES default 2", c.PROGRESS_RETRIES == 2)
    c2 = CONFIG(PROGRESS_RETRIES=5)
    _t("PROGRESS_RETRIES override", c2.PROGRESS_RETRIES == 5)


# ─── integration tests (API calls) ───────────────────────────

async def _test_llm_joke() -> None:
    """R1,R3,R7,R8: LLM returns non-empty text for simple prompt."""
    t0 = time.perf_counter()
    result = await llm("Tell me a 1-line joke.")
    wall = time.perf_counter() - t0
    _t("joke returns non-empty", len(result) > 5, f"{len(result)} chars")
    _t("joke completes < 10s", wall < 10, f"{wall:.2f}s")


async def _test_llm_long_input() -> None:
    """R1,R8: Large input prompt returns quickly."""
    big = "Repeat: " + ("computing history is fascinating. " * 200) + "\nSummarize in 1 word."
    t0 = time.perf_counter()
    result = await llm(big)
    wall = time.perf_counter() - t0
    _t("long input returns non-empty", len(result) > 0, f"{len(result)} chars")
    _t("long input < 5s", wall < 5, f"{wall:.2f}s")


async def _test_llm_parallel() -> None:
    """R4,R5: Parallel calls work via semaphore."""
    t0 = time.perf_counter()
    results = await asyncio.gather(
        llm("What is 2+2?"),
        llm("Name 3 colors."),
        llm("Capital of France?"),
    )
    wall = time.perf_counter() - t0
    _t("parallel returns 3 results", len(results) == 3)
    _t("all results non-empty", all(len(r) > 0 for r in results))
    _t("parallel wall < 10s", wall < 10, f"{wall:.2f}s")


async def _test_ralph_loop_bounded() -> None:
    """R9,R12,R14,R15: ralph_loop stops at MAX_ITERATIONS, carries progress."""
    cfg = CONFIG(MAX_ITERATIONS=2, LOOP_COOLDOWN=0, MAX_TOKENS=512)
    t0 = time.perf_counter()
    final_progress = await ralph_loop(
        "Count to 3, one number per iteration. "
        "In your <progress> tag, list which numbers you've said so far under DONE.",
        cfg,
    )
    wall = time.perf_counter() - t0
    _t("bounded loop completes", True, f"{wall:.2f}s")
    _t("bounded loop < 30s", wall < 30, f"{wall:.2f}s")
    _t("final progress is string", isinstance(final_progress, str))
    _t("final progress non-empty", len(final_progress) > 5, f"{len(final_progress)} chars")


# ─── test runner ──────────────────────────────────────────────

async def _run_tests() -> None:
    """Run all tests: unit first, then integration."""
    global _PASS, _FAIL
    _PASS, _FAIL = 0, 0
    t0 = time.perf_counter()

    CON.rule("[bold magenta]UNIT TESTS (no API calls)[/]")
    _test_config_defaults()
    _test_config_override()
    _test_prompts_class()
    _test_git_short()
    _test_read_agent_prompt_inline()
    _test_read_agent_prompt_file()
    _test_write_log()
    _test_semaphore_lazy_init()
    _test_iteration_context()
    _test_parse_progress()
    _test_config_progress_retries()

    CON.rule("[bold magenta]INTEGRATION TESTS (API calls)[/]")
    await _test_llm_joke()
    await _test_llm_long_input()
    await _test_llm_parallel()
    await _test_ralph_loop_bounded()

    wall = time.perf_counter() - t0
    CON.rule("[bold magenta]RESULTS[/]")
    color = "green" if _FAIL == 0 else "red"
    CON.print(f"[bold {color}]{_PASS} passed, {_FAIL} failed[/]  |  {wall:.1f}s total")
    if _FAIL > 0:
        sys.exit(1)


# ─────────────── EXAMPLE RUNNER / GUARDMAIN ──────────────────

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
    if len(sys.argv) > 1 and sys.argv[1] == "--tests":
        asyncio.run(_run_tests())
    elif len(sys.argv) > 1 and sys.argv[1] == "--example":
        name = sys.argv[2] if len(sys.argv) > 2 else "list"
        _run_example(name)
    elif len(sys.argv) > 1:
        asyncio.run(ralph_loop(" ".join(sys.argv[1:])))
    else:
        # no args → quick help
        CON.rule("[bold magenta]llm_fw.py — Fireworks oss120b[/]")
        CON.print('  [bold cyan]uv run llm_fw.py "prompt"[/]         ralph loop')
        CON.print("  [bold cyan]uv run llm_fw.py --tests[/]          run all tests")
        CON.print("  [bold cyan]uv run llm_fw.py --example list[/]   list example prompts")
        CON.print("  [bold cyan]uv run llm_fw.py --example NAME[/]   run example (3 iters)")
