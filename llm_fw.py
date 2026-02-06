#!/usr/bin/env -S uv run --script
"""Fireworks oss120b LLM caller + ralph loop — no tool-use.

Usage:
    uv run llm_fw.py "your prompt here"       # ralph loop + thread analysis
    uv run llm_fw.py --example algorithm      # run one example (agent decides when done)
    uv run llm_fw.py --example all            # tmux grid: all 8 examples in parallel
    uv run llm_fw.py --example list           # list available examples
    uv run llm_fw.py --kill                   # kill tmux 'ralph-all' session
    uv run llm_fw.py --tests                  # run all tests (unit + integration)
    uv run llm_fw.py --eval                   # LLM-judge tenet evaluations
    uv run llm_fw.py                          # quick help

Examples (progressive difficulty):
    1. fizzbuzz       — trivial one-shot (~1 iter)
    2. algorithm      — binary heap priority queue (~1-2 iters)
    3. bug_hunt       — trace empty-response bug (~2 iters)
    4. feature_design — circuit breaker design (~2-3 iters)
    5. refactor       — CONFIG dataclass redesign (~3 iters)
    6. architecture   — parallel agent system (~4-5 iters)
    7. interpreter    — calculator language w/ lexer/parser/eval (~5-7 iters)
    8. full_system    — distributed task queue system (MANY iters)

Requirements:

<R1> LLM API layer
  ☑️✅🧪 <R1.1> Call gpt-oss-120b on Fireworks via OpenAI-compatible API
  ☑️✅🧪 <R1.2> Streaming for fast TTFT — tokens printed live to terminal
  ☑️✅🧪 <R1.3> Compact summary line after stream (chars, TTFT, total time)

<R2> Configuration
  ☑️✅🧪 <R2.1> @dataclass CONFIG with all tunable params (model, generation, rate-limit, retry, loop)
  ☑️✅🧪 <R2.2> CONFIG overridable per-call (e.g. CONFIG(MAX_TOKENS=512))
  ☑️✅    <R2.3> AGENT_PROMPT in CONFIG — no-tool-use prompt w/ progress tag instructions
  ☑️✅    <R2.4> AGENT_PROMPT_FILE overrides CONFIG.AGENT_PROMPT if file exists on disk

<R3> Public API
  ☑️✅🧪 <R3.1> async def llm(prompt, config=CONFIG) → str
  ☑️✅🧪 <R3.2> asyncio.Semaphore on lazy global for cross-async safety
  ☑️✅🧪 <R3.3> tenacity exp-backoff retries up to MAX_RETRIES

<R4> Rate limits
  ☑️✅    <R4.1> Respect 60 req/min, 12k gen tok/min, 60k prompt tok/min
  ☑️✅🧪 <R4.2> MAX_CONCURRENT semaphore cap (default 10)

<R5> Ralph loop (core)
  ☑️✅🧪 <R5.1> ralph_loop(prompt) — while-true loop, logs per-commit
  ☑️✅🧪 <R5.2> MAX_ITERATIONS for bounded loops (0 = infinite)
  ☑️✅🧪 <R5.3> <progress> tag parsing with regex (_PROGRESS_RE)
  ☑️✅🧪 <R5.4> Retry on missing <progress> tag (PROGRESS_RETRIES)
  ☑️✅🧪 <R5.5> Progress injected into next iteration's prompt
  ☑️✅    <R5.6> Red warning if progress injection fails or is empty
  ☑️✅🧪 <R5.7> Agent self-termination via NEXT: DONE
  ☑️✅    <R5.8> Per-iteration logfile written to AGENT_LOGS_DIR

<R6> LoopResult + thread
  ☑️✅🧪 <R6.1> LoopResult dataclass (iterations, total_time, final_progress, thread[], done_signal, prompt)
  ☑️✅🧪 <R6.2> THREAD[] accumulates _format_thread_entry per iteration
  ☑️✅🧪 <R6.3> Rich summary printed at end of every loop (_format_summary)

<R7> Thread analysis
  ☑️✅🧪 <R7.1> RALPH_TENETS — 7 tenets as reusable string
  ☑️✅🧪 <R7.2> _build_analysis_prompt — wraps <thread> + <tenets>, asks LLM to score 1-5
  ☑️✅    <R7.3> Analysis runs automatically after examples and free-form prompts

<R8> Examples
  ☑️✅    <R8.1> PROMPTS singleton class w/ 5 self-contained examples (tuple format)
  ☑️✅    <R8.2> --example NAME runs single example (max 100 iters, agent decides when done)
  ☑️✅    <R8.3> --example list shows available examples
  ☑️✅    <R8.4> --example all — tmux pane grid, all examples in parallel
  ☑️✅    <R8.5> --kill — kill tmux ralph-all session

<R9> Testing
  ☑️✅🧪 <R9.1> --tests runs unit + integration tests in-file (116 tests)
  ☑️✅🧪 <R9.2> Unit tests: CONFIG, PROMPTS, git, agent prompt, logfile, semaphore, progress parse
  ☑️✅🧪 <R9.3> Unit tests: eval functions (concise, structured, no_bleed, summary)
  ☑️✅🧪 <R9.4> Unit tests: LoopResult, RALPH_TENETS, thread entry, summary, analysis prompt
  ☑️✅🧪 <R9.5> Integration tests: llm call, long input, parallel, ralph_loop bounded

<R10> Evals
  ☑️✅🧪 <R10.1> --eval runs programmatic + LLM-judge tenet evals
  ☑️✅🧪 <R10.2> Programmatic: concise_progress, structured_format, no_context_bleed, progress_is_summary
  ☑️✅🧪 <R10.3> LLM judge: incremental_value, forward_motion, no_echo
  ☑️✅🧪 <R10.4> Thread analysis eval: overall X/5 score, per-tenet breakdown

<R11> Display
  ☑️✅    <R11.1> Rich prints w/ color for all output
  ☑️✅    <R11.2> --help (no args) shows all CLI commands

⛔ Tool-use / function-calling (model has none, prompts are self-contained)
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
from rich.panel import Panel
from rich.table import Table
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
        # ── role & constraints ──
        "You are a senior software engineer working autonomously in a loop.\n"
        "You have NO tool-use — you cannot read files, run commands, or access the internet.\n"
        "Everything you need is provided IN THIS PROMPT. Do NOT ask for more information.\n"
        "Each iteration you start fresh — your ONLY memory is the <progress> block below.\n\n"
        # ── approach ──
        "APPROACH:\n"
        "1. READ the <progress> block to understand what's already done.\n"
        "2. PICK the highest-value next piece. Don't redo finished work.\n"
        "3. EXECUTE — produce your analysis, code, or output using ONLY the context given.\n"
        "4. UPDATE the <progress> block at the END of your response (MANDATORY).\n\n"
        # ── CRITICAL: progress tag format ──
        "PROGRESS TAG (MANDATORY — your response MUST end with this):\n"
        "You MUST include exactly one <progress> tag at the end of your response.\n"
        "This is your ONLY way to pass state to the next iteration.\n"
        "Format:\n"
        "<progress>\n"
        "DONE: bullet list of completed items\n"
        "CURRENT: what you worked on this iteration\n"
        "NEXT: what the next iteration should focus on (or 'DONE' if task is complete)\n"
        "BLOCKERS: any issues (or 'none')\n"
        "</progress>\n\n"
        # ── termination ──
        "TERMINATION:\n"
        "- When the task is FULLY COMPLETE, set NEXT: DONE in your <progress> tag.\n"
        "- The loop will stop automatically when it sees NEXT: DONE.\n"
        "- Do NOT stop early — only signal DONE when all sub-tasks are finished.\n\n"
        # ── quality ──
        "RULES:\n"
        "- You have NO file access. Work only with what's in this prompt.\n"
        "- Each iteration must add new value — do NOT repeat previous work.\n"
        "- Keep the <progress> block concise (under 500 chars).\n"
        "- If stuck, note what you tried and move on.\n"
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
    """Example prompts — progressively harder. 1=easy (~1 iter), 8=hard (many)."""

    # ── All prompts are SELF-CONTAINED: no file access, no tool-use. ──
    # ── The model must complete the task using ONLY this text. ──
    # ── Ordered by expected difficulty / iteration count. ──

    # ── 1. trivial: one-shot answer (~1 iter) ──
    fizzbuzz = (
        "Write FizzBuzz in Python for 1 to 100.\n"
        "1. Print 'Fizz' for multiples of 3, 'Buzz' for 5, 'FizzBuzz' for both.\n"
        "2. Write 3 pytest tests covering the key cases.\n"
        "3. STATUS: done or not."
    )

    # ── 2. easy: small algorithm (~1-2 iters) ──
    algorithm = (
        "Implement a priority queue backed by a binary heap in Python.\n"
        "1. Write the class with push, pop, peek, and __len__.\n"
        "2. Use a list as the backing store, no heapq import.\n"
        "3. Support (priority, item) tuples, lower priority = higher urgency.\n"
        "4. Write 5 pytest tests covering: empty pop, ordering, duplicates, peek, len.\n"
        "5. Analyze time complexity for each operation.\n"
        "6. STATUS: implementation complete? tests pass? edge cases covered?"
    )

    # ── 3. easy-medium: trace a bug (~2 iters) ──
    bug_hunt = (
        "A streaming LLM API sometimes returns empty text. The code does:\n"
        "  chunks = []\n"
        "  async for chunk in stream:\n"
        "    delta = chunk.choices[0].delta.content\n"
        "    if delta: chunks.append(delta)\n"
        "  return ''.join(chunks)\n\n"
        "1. Trace the data flow and list every place empty/None could leak.\n"
        "2. For each, propose a defensive check with exact code.\n"
        "3. Write a pytest that reproduces the empty-response edge case.\n"
        "4. STATUS: root causes found, fixes proposed, confidence level."
    )

    # ── 4. medium: design a component (~2-3 iters) ──
    feature_design = (
        "Design a retry-with-circuit-breaker for an async Python LLM caller.\n"
        "1. Define the state machine: CLOSED → OPEN → HALF-OPEN.\n"
        "2. Specify thresholds: failure count, timeout, half-open probe.\n"
        "3. Write the Python dataclass for CircuitBreaker state.\n"
        "4. Write the async wrapper function with full type hints.\n"
        "5. Write 3 unit tests (pytest style) covering each transition.\n"
        "6. STATUS: what's designed, what needs refinement, what's next."
    )

    # ── 5. medium: refactor existing code (~3 iters) ──
    refactor = (
        "Refactor this CONFIG dataclass:\n\n"
        "  @dataclass\n"
        "  class CONFIG:\n"
        "    MODEL: str = 'gpt-oss-120b'\n"
        "    BASE_URL: str = 'https://api.fireworks.ai/inference/v1'\n"
        "    API_KEY: str = ''  # from env\n"
        "    MAX_TOKENS: int = 4096\n"
        "    TEMPERATURE: float = 0.7\n"
        "    MAX_CONCURRENT: int = 10\n"
        "    MAX_RETRIES: int = 3\n"
        "    BACKOFF_MIN: float = 1.0\n"
        "    BACKOFF_MAX: float = 8.0\n"
        "    LOOP_COOLDOWN: float = 1.0\n"
        "    MAX_ITERATIONS: int = 0\n\n"
        "1. Group related fields into nested dataclasses (ModelCfg, RetryCfg, etc).\n"
        "2. Add validation in __post_init__ (e.g. MAX_TOKENS > 0).\n"
        "3. Add a .from_env() classmethod that loads from env vars.\n"
        "4. Show the complete refactored code.\n"
        "5. STATUS: what changed, what's cleaner, backwards-compat notes."
    )

    # ── 6. hard: system architecture (~4-5 iters) ──
    architecture = (
        "Design a parallel agent system for autonomous coding (no tool-use required).\n"
        "1. Define the coordination protocol: task locks, git sync, conflict resolution.\n"
        "2. Sketch the Docker container setup for N parallel agents.\n"
        "3. Write the AGENT_PROMPT.md content that each agent reads.\n"
        "4. Write the bash harness (while-true loop + git push/pull).\n"
        "5. Design the failure recovery: agent crash, merge conflict, deadlock.\n"
        "6. Write a monitoring dashboard design (what metrics, how displayed).\n"
        "7. STATUS: architecture complete? gaps? next steps?"
    )

    # ── 7. hard: build an interpreter (~5-7 iters) ──
    interpreter = (
        "Build a calculator language interpreter in Python.\n"
        "The language supports: integers, floats, +, -, *, /, parentheses,\n"
        "variable assignment (let x = 5), and if/else expressions.\n\n"
        "1. Write a Lexer class that tokenizes input strings.\n"
        "2. Write a Parser class that builds an AST from tokens.\n"
        "3. Write an Evaluator class that walks the AST and computes results.\n"
        "4. Support these expressions:\n"
        "   - '2 + 3 * 4' → 14\n"
        "   - 'let x = 10; x * 2' → 20\n"
        "   - 'if 1 > 0 then 42 else 0' → 42\n"
        "5. Write 8 pytest tests covering: arithmetic, precedence, variables,\n"
        "   if/else, nested parens, division by zero, syntax errors.\n"
        "6. Add error messages with line/column info.\n"
        "7. STATUS: what works, what's missing, what edge cases remain."
    )

    # ── 8. very hard: full system design (MANY iters) ──
    full_system = (
        "Design and implement a complete distributed task queue system in Python.\n\n"
        "COMPONENTS (all must be fully coded, not just sketched):\n"
        "1. TaskQueue class: submit(task), get_next(), complete(task_id), fail(task_id, reason).\n"
        "2. Worker class: polls queue, executes tasks, reports results.\n"
        "3. Scheduler: priority-based, with retry logic (3 attempts, exp backoff).\n"
        "4. Dead-letter queue: tasks that fail 3x are moved here.\n"
        "5. Concurrency: support N workers processing in parallel (asyncio).\n"
        "6. Persistence: tasks survive restart (use sqlite3, no external deps).\n"
        "7. Monitoring: track task counts by state (pending/running/done/failed/dead).\n"
        "8. CLI: submit, status, drain, purge-dead commands.\n\n"
        "ACCEPTANCE CRITERIA:\n"
        "- All classes fully implemented with type hints and docstrings.\n"
        "- 10+ pytest tests covering: submit/get, priority ordering, retry logic,\n"
        "  dead-letter, concurrent workers, persistence across restart, monitoring.\n"
        "- Error handling: worker crash, db corruption, duplicate task IDs.\n"
        "- The design must be explained: why each decision, tradeoffs considered.\n\n"
        "STATUS: what's built, what's tested, what needs work."
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
        if ttft is None:
            ttft = elapsed  # no chunks received

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


# ─────────────── ITERATION TRACE (for evals) ─────────────────

@dataclass
class _IterData:
    """One iteration's data, collected for eval/judge."""
    iteration: int
    progress_in: str
    response: str
    progress_out: str  # "" if parse failed

_TRACES: list[_IterData] = []


@dataclass
class LoopResult:
    """Full result of a ralph loop run — returned to caller."""
    iterations: int
    total_time: float
    final_progress: str
    thread: list[str]       # stdout-like log, one entry per iteration
    done_signal: bool       # True if agent said NEXT: DONE
    prompt: str             # original user prompt


# ─────────────── RALPH TENETS (for final analysis) ────────────

RALPH_TENETS = (
    "1. FORWARD PROGRESS: Each iteration must advance the task. DONE list grows monotonically.\n"
    "2. NO REPETITION: Never redo finished work. Read progress, pick what's NEW.\n"
    "3. CONCISE STATE: <progress> is a sticky note (<500 chars), not a transcript.\n"
    "4. STRUCTURED FORMAT: Every <progress> has DONE/CURRENT/NEXT/BLOCKERS.\n"
    "5. SELF-TERMINATION: Agent sets NEXT: DONE when task is complete. Not too early, not too late.\n"
    "6. INCREMENTAL VALUE: Each response contains substantive new content.\n"
    "7. NO CONTEXT BLEED: Progress is a summary, not a copy of the response.\n"
)


def _format_thread_entry(iteration: int, progress_in: str, response: str,
                          progress_out: str, elapsed: float) -> str:
    """Format one iteration into a thread entry string."""
    return (
        f"── ITERATION {iteration} ({elapsed:.1f}s) ──\n"
        f"PROGRESS IN:\n{progress_in}\n\n"
        f"RESPONSE:\n{response}\n\n"
        f"PROGRESS OUT:\n{progress_out}\n"
    )


def _format_summary(r: LoopResult) -> Panel:
    """Build a Rich Panel with summary table for a LoopResult."""
    status = "[bold green]DONE[/] — agent signalled completion" if r.done_signal \
        else "[yellow]LIMIT[/] — hit iteration cap"
    avg = r.total_time / max(r.iterations, 1)

    tbl = Table(show_header=False, box=None, padding=(0, 2))
    tbl.add_column("key", style="bold cyan", width=16)
    tbl.add_column("value")
    tbl.add_row("Prompt", r.prompt[:100] + ("…" if len(r.prompt) > 100 else ""))
    tbl.add_row("Iterations", str(r.iterations))
    tbl.add_row("Total time", f"{r.total_time:.2f}s")
    tbl.add_row("Avg / iter", f"{avg:.2f}s")
    tbl.add_row("Status", status)
    tbl.add_row("Thread size", f"{len(r.thread)} entries")
    tbl.add_row("Final progress", r.final_progress)

    return Panel(tbl, title="[bold magenta]RALPH LOOP SUMMARY[/]", border_style="magenta")


def _build_analysis_prompt(r: LoopResult) -> str:
    """Build the prompt for the final LLM analysis of the thread."""
    thread_text = "\n\n".join(r.thread)
    return (
        "You are an evaluator. Analyze how this autonomous agent loop performed.\n"
        "Score each tenet 1-5 (1=violated, 5=exemplary). Give overall score and brief commentary.\n\n"
        f"<thread>\n{thread_text}\n</thread>\n\n"
        f"<tenets>\n{RALPH_TENETS}</tenets>\n\n"
        "Respond with:\n"
        "- Per-tenet scores (tenet name: score/5 + one-line reason)\n"
        "- Overall score: X/5\n"
        "- One paragraph summary of how the loop went.\n"
    )


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


async def ralph_loop(prompt: str, cfg: CONFIG = CFG) -> LoopResult:
    """The ralph loop — while-true, carries <progress> between iterations.

    Since oss120b has no tool-use, the LLM outputs <progress>...</progress>
    tags. The harness parses them and injects the accumulated progress into
    the next iteration's prompt. If parse fails, re-runs the same step.

    Returns LoopResult with thread[], summary, and final progress.
    """
    bound = f"max {cfg.MAX_ITERATIONS}" if cfg.MAX_ITERATIONS > 0 else "infinite"
    CON.rule("[bold magenta]ralph loop — oss120b (no tool-use)[/]")
    CON.print(f"[bold yellow]user prompt:[/] {prompt}")
    CON.print(f"[dim]cooldown: {cfg.LOOP_COOLDOWN}s  |  iterations: {bound}  |  logs: {cfg.AGENT_LOGS_DIR}/[/]\n")

    progress: str = "DONE: nothing yet\nCURRENT: starting\nNEXT: orient and plan\nBLOCKERS: none"
    thread: list[str] = []
    iteration = 0
    done_signal = False
    t0 = time.perf_counter()

    while True:
        iteration += 1
        if cfg.MAX_ITERATIONS > 0 and iteration > cfg.MAX_ITERATIONS:
            CON.rule(f"[bold green]done — {cfg.MAX_ITERATIONS} iterations complete[/]")
            break

        commit = _git_short()
        logfile = Path(cfg.AGENT_LOGS_DIR) / f"agent_{commit}_{iteration:04d}.log"

        CON.rule(f"[bold cyan]iteration {iteration}/{bound}  |  {commit}[/]")
        progress_before = progress  # snapshot for trace
        iter_t0 = time.perf_counter()

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

        # ── validate progress injection ──
        progress_tag = f"<progress>\n{progress}\n</progress>"
        if progress_tag not in full_prompt:
            CON.print("[bold red]⚠ WARNING: progress NOT injected into prompt! Injection FAILED.[/]")
        elif not progress.strip():
            CON.print("[bold red]⚠ WARNING: progress is EMPTY! Injection FAILED.[/]")
        else:
            CON.print(f"[bold green]✓ progress injected:[/] {progress[:200]}{'…' if len(progress)>200 else ''}")

        # ── call LLM with retry on missing <progress> tag ──
        result: str = ""
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

        # ── update progress for next iteration + record trace ──
        if parsed:
            progress = parsed
            CON.print(f"[bold green]progress out:[/] {progress[:200]}{'…' if len(progress)>200 else ''}")
        else:
            CON.print("[bold red]<progress> parse failed after retries — keeping previous progress[/]")

        iter_elapsed = time.perf_counter() - iter_t0

        _TRACES.append(_IterData(
            iteration=iteration,
            progress_in=progress_before,
            response=result,
            progress_out=parsed or "",
        ))

        # ── accumulate thread ──
        thread.append(_format_thread_entry(
            iteration, progress_before, result, parsed or "(parse failed)", iter_elapsed,
        ))

        # ── agent signals completion via NEXT: DONE ──
        if parsed and re.search(r"NEXT:\s*DONE\b", parsed, re.IGNORECASE):
            done_signal = True
            CON.rule(f"[bold green]agent signalled DONE after {iteration} iterations[/]")
            break

        # ── cooldown (skip on last) ──
        last = cfg.MAX_ITERATIONS > 0 and iteration >= cfg.MAX_ITERATIONS
        if cfg.LOOP_COOLDOWN > 0 and not last:
            CON.print(f"[dim]sleeping {cfg.LOOP_COOLDOWN}s…[/]")
            await asyncio.sleep(cfg.LOOP_COOLDOWN)

    total_time = time.perf_counter() - t0
    # iteration was already incremented past max when we broke, so use len(thread)
    loop_result = LoopResult(
        iterations=len(thread),
        total_time=total_time,
        final_progress=progress,
        thread=thread,
        done_signal=done_signal,
        prompt=prompt,
    )

    # ── rich summary ──
    CON.print()
    CON.print(_format_summary(loop_result))

    return loop_result


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
    _t("PROMPTS has 8 entries", len(names) == 8, f"found {len(names)}")
    _t("PROMPTS.get('feature_design') returns str", isinstance(PROMPTS.get("feature_design"), str))
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


def _test_parse_verdict() -> None:
    """R16: _parse_verdict extracts PASS/FAIL from judge output."""
    ok, reason = _parse_verdict("PASS: The DONE list grows across all iterations.")
    _t("parse PASS verdict", ok is True)
    _t("parse PASS reason", "grows" in reason)

    ok2, reason2 = _parse_verdict("FAIL: Iteration 2 repeated iteration 1 content.")
    _t("parse FAIL verdict", ok2 is False)
    _t("parse FAIL reason", "repeated" in reason2)

    ok3, reason3 = _parse_verdict("Some preamble\nPASS: Still works after preamble.")
    _t("parse with preamble", ok3 is True)

    ok4, reason4 = _parse_verdict("gibberish without verdict")
    _t("unparseable returns False", ok4 is False)
    _t("unparseable has error msg", "unparseable" in reason4)


def _test_eval_concise_progress() -> None:
    """R16: programmatic concise_progress check."""
    # ── all under 500 → pass ──
    good = [
        _IterData(1, "in", "resp" * 100, "DONE: x\nCURRENT: y\nNEXT: z\nBLOCKERS: none"),
        _IterData(2, "in", "resp" * 100, "DONE: x, y\nCURRENT: z\nNEXT: a\nBLOCKERS: none"),
    ]
    ok, _ = _eval_concise_progress(good)
    _t("concise good traces pass", ok)

    # ── over 500 → fail ──
    bad = [_IterData(1, "in", "resp", "X" * 501)]
    ok2, reason2 = _eval_concise_progress(bad)
    _t("concise over-500 fails", not ok2)
    _t("concise fail mentions limit", "500" in reason2)

    # ── bloat 4x → fail ──
    bloat = [
        _IterData(1, "in", "resp", "short"),
        _IterData(2, "in", "resp", "short" * 4),
    ]
    ok3, _ = _eval_concise_progress(bloat)
    _t("concise bloat 4x fails", not ok3)


def _test_eval_structured_format() -> None:
    """R16: programmatic structured_format check."""
    good = [_IterData(1, "", "", "DONE: a\nCURRENT: b\nNEXT: c\nBLOCKERS: none")]
    ok, _ = _eval_structured_format(good)
    _t("structured good trace passes", ok)

    bad = [_IterData(1, "", "", "DONE: a\nNEXT: c")]
    ok2, reason2 = _eval_structured_format(bad)
    _t("structured missing fields fails", not ok2)
    _t("structured fail lists missing", "CURRENT" in reason2 or "missing" in reason2.lower())


def _test_eval_no_context_bleed() -> None:
    """R16: programmatic no_context_bleed check."""
    good = [_IterData(1, "", "A" * 1000, "DONE: short summary")]
    ok, _ = _eval_no_context_bleed(good)
    _t("no_bleed good passes", ok)

    bad = [_IterData(1, "", "A" * 100, "A" * 60)]  # 60% ratio
    ok2, reason2 = _eval_no_context_bleed(bad)
    _t("no_bleed >50% fails", not ok2)
    _t("no_bleed fail mentions bleed", "bleed" in reason2.lower())


def _test_eval_progress_is_summary() -> None:
    """R16: programmatic progress_is_summary check."""
    # ── good: progress is a short summary, not in response ──
    good = [_IterData(1, "", "Here is my detailed analysis of the code...", "DONE: analyzed code\nNEXT: write tests")]
    ok, _ = _eval_progress_is_summary(good)
    _t("summary good passes", ok)

    # ── bad: progress contains 60+ char verbatim copy from response ──
    long_text = "This is a very long and specific piece of text that should only appear in the response body"
    bad = [_IterData(1, "", f"Response: {long_text} more stuff", f"DONE: {long_text}")]
    ok2, reason2 = _eval_progress_is_summary(bad)
    _t("summary verbatim copy fails", not ok2)
    _t("summary fail mentions verbatim", "verbatim" in reason2.lower())


# ─── unit tests: LoopResult + thread (R17, R18) ─────────────

def _test_loop_result_dataclass() -> None:
    """R17: LoopResult has all required fields."""
    r = LoopResult(
        iterations=3, total_time=5.0, final_progress="DONE: x",
        thread=["iter1", "iter2", "iter3"], done_signal=True, prompt="test",
    )
    _t("LoopResult.iterations", r.iterations == 3)
    _t("LoopResult.total_time", r.total_time == 5.0)
    _t("LoopResult.final_progress", r.final_progress == "DONE: x")
    _t("LoopResult.thread has 3 entries", len(r.thread) == 3)
    _t("LoopResult.done_signal", r.done_signal is True)
    _t("LoopResult.prompt", r.prompt == "test")


def _test_ralph_tenets_defined() -> None:
    """R18: RALPH_TENETS is a non-empty string with all 7 tenets."""
    _t("RALPH_TENETS is str", isinstance(RALPH_TENETS, str))
    _t("RALPH_TENETS has 7 tenets", RALPH_TENETS.count(". ") >= 7, f"found {RALPH_TENETS.count('. ')}")
    for keyword in ["FORWARD PROGRESS", "NO REPETITION", "CONCISE STATE",
                     "STRUCTURED FORMAT", "SELF-TERMINATION", "INCREMENTAL VALUE",
                     "NO CONTEXT BLEED"]:
        _t(f"tenets contains '{keyword}'", keyword in RALPH_TENETS)


def _test_format_thread_entry() -> None:
    """R17: _format_thread_entry produces structured string."""
    entry = _format_thread_entry(1, "seed progress", "model response here", "DONE: x\nNEXT: y", 2.5)
    _t("thread entry is str", isinstance(entry, str))
    _t("thread entry has iteration", "ITERATION 1" in entry)
    _t("thread entry has progress_in", "seed progress" in entry)
    _t("thread entry has response", "model response here" in entry)
    _t("thread entry has progress_out", "DONE: x" in entry)
    _t("thread entry has elapsed", "2.5" in entry)


def _test_format_summary() -> None:
    """R17: _format_summary produces Rich Panel with summary table."""
    from io import StringIO
    r = LoopResult(
        iterations=3, total_time=10.5, final_progress="DONE: everything",
        thread=["a", "b", "c"], done_signal=True, prompt="test task",
    )
    panel = _format_summary(r)
    _t("summary is Panel", isinstance(panel, Panel))
    # render to plain text for content checks
    buf = StringIO()
    Console(file=buf, width=120, no_color=True).print(panel)
    s = buf.getvalue()
    _t("summary has iterations", "3" in s)
    _t("summary has time", "10.5" in s or "10.50" in s)
    _t("summary has avg/iter", "3.50" in s)
    _t("summary has done status", "DONE" in s)
    _t("summary has prompt preview", "test task" in s)


def _test_build_analysis_prompt() -> None:
    """R18: _build_analysis_prompt includes thread + tenets."""
    r = LoopResult(
        iterations=2, total_time=5.0, final_progress="DONE: x",
        thread=["iter1 data", "iter2 data"], done_signal=True, prompt="test",
    )
    p = _build_analysis_prompt(r)
    _t("analysis prompt is str", isinstance(p, str))
    _t("analysis prompt has <thread>", "<thread>" in p)
    _t("analysis prompt has </thread>", "</thread>" in p)
    _t("analysis prompt has thread content", "iter1 data" in p)
    _t("analysis prompt has <tenets>", "<tenets>" in p)
    _t("analysis prompt has </tenets>", "</tenets>" in p)
    _t("analysis prompt has tenet content", "FORWARD PROGRESS" in p)
    _t("analysis prompt asks for score", "score" in p.lower() or "rate" in p.lower())


def _test_tmux_windows_approach() -> None:
    """R8.4: _run_all_tmux uses windows (not panes) to avoid 'no space' error."""
    import inspect
    src = inspect.getsource(_run_all_tmux)
    _t("tmux uses new-window", "new-window" in src)
    _t("tmux no split-window", "split-window" not in src, "windows avoid 'no space for new pane'")
    _t("tmux uses remain-on-exit", "remain-on-exit" in src)
    _t("tmux names windows", '"-n"' in src or "'-n'" in src)


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
    """R9,R12,R14,R15,R17: ralph_loop returns LoopResult with thread."""
    cfg = CONFIG(MAX_ITERATIONS=2, LOOP_COOLDOWN=0, MAX_TOKENS=512)
    t0 = time.perf_counter()
    result = await ralph_loop(
        "Count to 3, one number per iteration. "
        "In your <progress> tag, list which numbers you've said so far under DONE.",
        cfg,
    )
    wall = time.perf_counter() - t0
    _t("bounded loop returns LoopResult", isinstance(result, LoopResult))
    _t("bounded loop completes", True, f"{wall:.2f}s")
    _t("bounded loop < 60s", wall < 60, f"{wall:.2f}s")
    _t("result.final_progress is string", isinstance(result.final_progress, str))
    _t("result.final_progress non-empty", len(result.final_progress) > 5, f"{len(result.final_progress)} chars")
    _t("result.thread populated", len(result.thread) >= 1, f"{len(result.thread)} entries")
    _t("result.iterations == 2", result.iterations == 2)
    _t("result.total_time > 0", result.total_time > 0, f"{result.total_time:.2f}s")
    _t("result.prompt preserved", "Count" in result.prompt)


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
    _test_parse_verdict()
    _test_eval_concise_progress()
    _test_eval_structured_format()
    _test_eval_no_context_bleed()
    _test_eval_progress_is_summary()
    _test_loop_result_dataclass()
    _test_ralph_tenets_defined()
    _test_format_thread_entry()
    _test_format_summary()
    _test_build_analysis_prompt()
    _test_tmux_windows_approach()

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


# ─────────────── EVALS: LLM JUDGE TENETS ─────────────────────
# Run via: uv run llm_fw.py --eval
# Runs a 3-iteration ralph loop, then evaluates each tenet
# with a mix of programmatic checks + LLM-as-judge calls.
# Output: structured PASS|FAIL + justification per tenet.

_JUDGE_RE = re.compile(r"^(PASS|FAIL):\s*(.+)", re.MULTILINE)

JUDGE_PROMPT = (
    "You are an eval judge. You evaluate whether an AI agent loop followed a design tenet.\n"
    "You will be given the tenet description and the iteration data.\n\n"
    "Respond with EXACTLY ONE line in this format:\n"
    "PASS: <1-sentence justification>\n"
    "or\n"
    "FAIL: <1-sentence justification>\n\n"
    "NOTHING ELSE. No preamble, no extra lines. Just the verdict line."
)


def _judge_prompt(tenet_name: str, tenet_desc: str, data: str) -> str:
    """Build the full judge prompt for one tenet evaluation."""
    return (
        f"{JUDGE_PROMPT}\n\n"
        f"TENET: {tenet_name}\n"
        f"DESCRIPTION: {tenet_desc}\n\n"
        f"ITERATION DATA:\n{data}"
    )


def _parse_verdict(text: str) -> tuple[bool, str]:
    """Parse PASS|FAIL: justification from judge output. Returns (passed, reason)."""
    m = _JUDGE_RE.search(text)
    if m:
        return (m.group(1) == "PASS", m.group(2).strip())
    return (False, f"judge output unparseable: {text[:200]}")


async def _judge_with_retry(prompt: str, cfg: CONFIG, retries: int = 2) -> tuple[bool, str]:
    """Call LLM judge with retries on empty/unparseable responses."""
    for attempt in range(1 + retries):
        raw = await llm(prompt, cfg)
        ok, reason = _parse_verdict(raw)
        if "unparseable" not in reason:
            return (ok, reason)
        if attempt < retries:
            CON.print(f"[dim]judge retry {attempt+1}/{retries} — empty/unparseable response[/]")
    return (ok, reason)


def _fmt_traces(traces: list[_IterData], include_response: bool = True) -> str:
    """Format traces for judge consumption — concise, numbered.

    Set include_response=False for judges that only need progress blocks.
    """
    parts: list[str] = []
    for t in traces:
        block = (
            f"--- iteration {t.iteration} ---\n"
            f"PROGRESS_IN:\n{t.progress_in}\n\n"
        )
        if include_response:
            resp_trunc = t.response[:800] + ("…" if len(t.response) > 800 else "")
            block += f"RESPONSE ({len(t.response)} chars, first 800):\n{resp_trunc}\n\n"
        block += f"PROGRESS_OUT:\n{t.progress_out}\n"
        parts.append(block)
    return "\n".join(parts)


# ─── programmatic tenet checks ───────────────────────────────

def _eval_concise_progress(traces: list[_IterData]) -> tuple[bool, str]:
    """TENET: Progress blocks must stay under 500 chars and not bloat."""
    if not traces:
        return (False, "no traces collected")
    sizes = [len(t.progress_out) for t in traces]
    max_sz = max(sizes)
    # check absolute limit
    if max_sz > 500:
        return (False, f"progress block hit {max_sz} chars (limit 500)")
    # check for bloat: last shouldn't be >3x first (if >1 iteration)
    if len(sizes) > 1 and sizes[0] > 0 and sizes[-1] > sizes[0] * 3:
        return (False, f"progress bloated from {sizes[0]} to {sizes[-1]} chars ({sizes[-1]/sizes[0]:.1f}x)")
    return (True, f"all progress blocks under 500 chars, max={max_sz}")


def _eval_structured_format(traces: list[_IterData]) -> tuple[bool, str]:
    """TENET: Every progress block must have DONE/CURRENT/NEXT/BLOCKERS."""
    required = ["DONE:", "CURRENT:", "NEXT:", "BLOCKERS:"]
    for t in traces:
        if not t.progress_out:
            return (False, f"iteration {t.iteration} has empty progress_out")
        missing = [f for f in required if f not in t.progress_out.upper()]
        if missing:
            return (False, f"iteration {t.iteration} missing fields: {missing}")
    return (True, f"all {len(traces)} iterations have all 4 required fields")


def _eval_no_context_bleed(traces: list[_IterData]) -> tuple[bool, str]:
    """TENET: Progress must NOT contain the full previous response.

    Heuristic: progress_out should be <30% of response length.
    If progress is >50% of response, the model is stuffing context.
    """
    for t in traces:
        if not t.response:
            continue
        ratio = len(t.progress_out) / max(len(t.response), 1)
        if ratio > 0.5:
            return (False, f"iteration {t.iteration}: progress is {ratio:.0%} of response length — context bleed")
    return (True, "progress blocks are concise relative to responses")


# ─── LLM judge tenet checks ──────────────────────────────────

async def _eval_incremental_value(traces: list[_IterData], cfg: CONFIG) -> tuple[bool, str]:
    """TENET: Each iteration must add new DONE items — DONE list grows monotonically."""
    data = _fmt_traces(traces, include_response=False)
    prompt = _judge_prompt(
        "incremental_value",
        (
            "Each iteration must add new DONE items. The DONE list should grow monotonically. "
            "If iteration N has fewer or identical DONE items compared to iteration N-1, that's a FAIL. "
            "The agent should NOT repeat work — each iteration adds new value."
        ),
        data,
    )
    return await _judge_with_retry(prompt, cfg)


async def _eval_forward_motion(traces: list[_IterData], cfg: CONFIG) -> tuple[bool, str]:
    """TENET: NEXT field should change between iterations (not stuck in a loop)."""
    data = _fmt_traces(traces, include_response=False)
    prompt = _judge_prompt(
        "forward_motion",
        (
            "The NEXT field in the progress block should change between iterations. "
            "If iteration N and N+1 have identical NEXT fields, the agent is stuck. "
            "Minor wording changes are OK, but the intent/focus should shift as work completes."
        ),
        data,
    )
    return await _judge_with_retry(prompt, cfg)


async def _eval_no_echo(traces: list[_IterData], cfg: CONFIG) -> tuple[bool, str]:
    """TENET: Response should not just echo back the system prompt or user task."""
    data = _fmt_traces(traces)
    prompt = _judge_prompt(
        "no_echo",
        (
            "The agent's response should contain substantive NEW content — analysis, code, plans, etc. "
            "It should NOT be mostly a copy/echo of the system prompt, user task, or previous progress. "
            "The bulk of the response should be original work, not repetition."
        ),
        data,
    )
    return await _judge_with_retry(prompt, cfg)


def _eval_progress_is_summary(traces: list[_IterData]) -> tuple[bool, str]:
    """TENET: Progress is a concise SUMMARY, not a copy of the response.

    Programmatic check: no contiguous 60+ char substring from progress_out
    should appear verbatim in the response body (excluding the <progress>
    tag itself, since the response naturally contains it).
    """
    CHUNK = 60  # min verbatim overlap to flag
    for t in traces:
        if not t.progress_out or not t.response:
            continue
        # strip the <progress>...</progress> block from the response before checking
        resp_stripped = _PROGRESS_RE.sub("", t.response).strip()
        if not resp_stripped:
            continue
        # slide a window of CHUNK chars across progress_out, check if in response body
        for i in range(len(t.progress_out) - CHUNK + 1):
            snippet = t.progress_out[i:i + CHUNK]
            if snippet in resp_stripped:
                return (False, f"iteration {t.iteration}: progress contains 60+ char verbatim excerpt from response body")
    return (True, "progress blocks are summaries, not verbatim copies")


# ─── thread analysis eval ─────────────────────────────────────

async def _eval_thread_analysis(result: LoopResult, cfg: CONFIG) -> tuple[bool, str]:
    """TENET: Final LLM analysis of the full thread against RALPH_TENETS.

    Passes if the LLM scores overall >= 3/5.
    """
    prompt = _build_analysis_prompt(result)
    try:
        analysis = await llm(prompt, cfg)
    except Exception as e:
        return (False, f"analysis LLM call failed: {e}")

    # look for "Overall score: X/5" or "overall: X/5"
    m = re.search(r"[Oo]verall.*?(\d)/5", analysis)
    if m:
        score = int(m.group(1))
        passed = score >= 3
        return (passed, f"overall score {score}/5 — {'passed' if passed else 'below threshold (3/5)'}\n{analysis[:300]}")
    return (True, f"could not parse score, treating as pass\n{analysis[:300]}")


# ─── eval runner ──────────────────────────────────────────────

_EVAL_PASS = 0
_EVAL_FAIL = 0


def _ev(name: str, passed: bool, reason: str) -> None:
    """Record an eval result with rich output."""
    global _EVAL_PASS, _EVAL_FAIL
    tag = "[bold green]PASS[/]" if passed else "[bold red]FAIL[/]"
    CON.print(f"  {tag}  {name}")
    CON.print(f"        [dim]{reason}[/]")
    if passed:
        _EVAL_PASS += 1
    else:
        _EVAL_FAIL += 1


async def _run_evals() -> None:
    """Run all tenet evals: collect traces via ralph loop, then judge."""
    global _EVAL_PASS, _EVAL_FAIL, _TRACES
    _EVAL_PASS, _EVAL_FAIL = 0, 0
    t0 = time.perf_counter()

    # ── step 1: run a 3-iteration ralph loop to collect data ──
    CON.rule("[bold magenta]EVAL: collecting iteration data (3 iters)[/]")
    _TRACES.clear()
    eval_cfg = CONFIG(MAX_ITERATIONS=3, LOOP_COOLDOWN=0.5, MAX_TOKENS=2048)
    eval_prompt = (
        "Design a simple key-value store in Python.\n"
        "1. Define the API: get, set, delete, list_keys.\n"
        "2. Write the class with type hints.\n"
        "3. Write 3 pytest tests.\n"
        "4. Review and suggest improvements."
    )
    loop_result = await ralph_loop(eval_prompt, eval_cfg)

    if not _TRACES:
        CON.print("[bold red]no traces collected — cannot evaluate[/]")
        sys.exit(1)

    CON.print(f"\n[bold]collected {len(_TRACES)} iteration traces[/]\n")

    # ── step 2: programmatic tenets ──
    CON.rule("[bold magenta]EVAL: programmatic tenets[/]")

    ok, reason = _eval_concise_progress(_TRACES)
    _ev("concise_progress: <500 chars, no bloat", ok, reason)

    ok, reason = _eval_structured_format(_TRACES)
    _ev("structured_format: DONE/CURRENT/NEXT/BLOCKERS", ok, reason)

    ok, reason = _eval_no_context_bleed(_TRACES)
    _ev("no_context_bleed: progress < 50% of response", ok, reason)

    ok, reason = _eval_progress_is_summary(_TRACES)
    _ev("progress_is_summary: sticky note, not transcript", ok, reason)

    # ── step 3: LLM judge tenets ──
    CON.rule("[bold magenta]EVAL: LLM judge tenets[/]")
    judge_cfg = CONFIG(MAX_TOKENS=256, TEMPERATURE=0.0)

    ok, reason = await _eval_incremental_value(_TRACES, judge_cfg)
    _ev("incremental_value: DONE grows monotonically", ok, reason)

    ok, reason = await _eval_forward_motion(_TRACES, judge_cfg)
    _ev("forward_motion: NEXT changes between iters", ok, reason)

    ok, reason = await _eval_no_echo(_TRACES, judge_cfg)
    _ev("no_echo: response is substantive, not parroting", ok, reason)

    # ── step 4: thread analysis eval (R18) ──
    CON.rule("[bold magenta]EVAL: thread analysis (LLM scores against tenets)[/]")
    analysis_cfg = CONFIG(MAX_TOKENS=1024, TEMPERATURE=0.0)
    ok, reason = await _eval_thread_analysis(loop_result, analysis_cfg)
    _ev("thread_analysis: LLM judges overall loop quality", ok, reason)

    # ── results ──
    wall = time.perf_counter() - t0
    CON.rule("[bold magenta]EVAL RESULTS[/]")
    total = _EVAL_PASS + _EVAL_FAIL
    color = "green" if _EVAL_FAIL == 0 else "red"
    CON.print(f"[bold {color}]{_EVAL_PASS}/{total} tenets passed, {_EVAL_FAIL} failed[/]  |  {wall:.1f}s total")
    if _EVAL_FAIL > 0:
        sys.exit(1)


# ─────────────── EXAMPLE RUNNER / GUARDMAIN ──────────────────

def _run_all_tmux() -> None:
    """Launch all examples in separate tmux windows (one per example).

    Uses windows (tabs) instead of panes to avoid 'no space for new pane'
    when terminal is too small for 8 splits. Each example gets a full-size
    terminal. Navigate: Ctrl-b n (next) / Ctrl-b p (prev).
    Stagger starts 0.3s apart to avoid rate-limit burst.
    """
    names = PROMPTS.names()
    session = "ralph-all"
    script = os.path.abspath(__file__)

    subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True)

    # create session — first window named after first example
    subprocess.run([
        "tmux", "new-session", "-d", "-s", session, "-n", names[0],
    ], check=True)
    subprocess.run(
        ["tmux", "set-option", "-t", session, "remain-on-exit", "on"],
        capture_output=True,
    )

    # create a new window for each remaining example
    for n in names[1:]:
        subprocess.run([
            "tmux", "new-window", "-t", session, "-n", n,
        ], check=True)

    # send staggered commands to each window
    for i, n in enumerate(names):
        delay = f"sleep {i * 0.3:.1f} && " if i > 0 else ""
        subprocess.run([
            "tmux", "send-keys", "-t", f"{session}:{n}",
            f"{delay}uv run {script} --example {n}", "Enter",
        ], check=True)

    # select first window
    subprocess.run(["tmux", "select-window", "-t", f"{session}:{names[0]}"], capture_output=True)

    CON.print(f"[bold green]launched {len(names)} examples in tmux session '{session}'[/]")
    CON.print(f"[dim]attach: tmux attach -t {session}  |  Ctrl-b n/p to switch  |  kill: tmux kill-session -t {session}[/]")
    if sys.stdout.isatty():
        os.execvp("tmux", ["tmux", "attach", "-t", session])
    else:
        CON.print("[dim]not a TTY — run 'tmux attach -t ralph-all' manually[/]")


async def _run_example_with_analysis(prompt: str, cfg: CONFIG) -> None:
    """Run ralph loop, then call LLM to analyze the thread against tenets."""
    result = await ralph_loop(prompt, cfg)

    # ── final LLM analysis ──
    CON.rule("[bold magenta]THREAD ANALYSIS (LLM scoring against tenets)[/]")
    analysis_prompt = _build_analysis_prompt(result)
    try:
        analysis = await llm(analysis_prompt, CONFIG(MAX_TOKENS=1024, TEMPERATURE=0.0))
        CON.print(f"\n{analysis}\n")
    except Exception as e:
        CON.print(f"[bold red]analysis failed: {e}[/]")


def _run_example(name: str) -> None:
    """Run a named example prompt through the ralph loop (max 100 iterations)."""
    if name == "list":
        CON.rule("[bold magenta]available example prompts[/]")
        for n in PROMPTS.names():
            preview = (getattr(PROMPTS, n) or "")[:80].replace("\n", " ")
            CON.print(f"  [bold cyan]{n:<20}[/] {preview}…")
        return

    if name == "all":
        _run_all_tmux()
        return  # unreachable — execvp replaces process

    prompt = PROMPTS.get(name)
    if not prompt:
        CON.print(f"[bold red]unknown example:[/] {name}")
        CON.print(f"[dim]available: {', '.join(PROMPTS.names())}  |  all[/]")
        sys.exit(1)

    CON.print(f"[bold green]running example:[/] {name} (max 100 iterations — agent decides when done)\n")
    cfg = CONFIG(MAX_ITERATIONS=100, LOOP_COOLDOWN=0.5)
    asyncio.run(_run_example_with_analysis(prompt, cfg))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--tests":
        asyncio.run(_run_tests())
    elif len(sys.argv) > 1 and sys.argv[1] == "--eval":
        asyncio.run(_run_evals())
    elif len(sys.argv) > 1 and sys.argv[1] == "--kill":
        r = subprocess.run(["tmux", "kill-session", "-t", "ralph-all"], capture_output=True)
        CON.print("[bold green]killed tmux session 'ralph-all'[/]" if r.returncode == 0
                  else "[dim]no 'ralph-all' session running[/]")
    elif len(sys.argv) > 1 and sys.argv[1] == "--example":
        name = sys.argv[2] if len(sys.argv) > 2 else "list"
        _run_example(name)
    elif len(sys.argv) > 1:
        asyncio.run(_run_example_with_analysis(" ".join(sys.argv[1:]), CFG))
    else:
        # no args → quick help
        CON.rule("[bold magenta]llm_fw.py — Fireworks oss120b[/]")
        CON.print('  [bold cyan]uv run llm_fw.py "prompt"[/]         ralph loop')
        CON.print("  [bold cyan]uv run llm_fw.py --tests[/]          run all tests")
        CON.print("  [bold cyan]uv run llm_fw.py --eval[/]           LLM-judge tenet evals")
        CON.print("  [bold cyan]uv run llm_fw.py --example list[/]   list example prompts")
        CON.print("  [bold cyan]uv run llm_fw.py --example NAME[/]   run example")
        CON.print("  [bold cyan]uv run llm_fw.py --example all[/]    tmux grid: all in parallel")
        CON.print("  [bold cyan]uv run llm_fw.py --kill[/]            kill tmux 'ralph-all' session")
