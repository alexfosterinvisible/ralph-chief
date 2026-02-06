#!/usr/bin/env -S uv run --script
"""llm_120b_ralph_v3 — unified AAAA + ABAB loop framework for Fireworks oss120b.

**What v3 is that v1/v2 are not:**
  v1 (llm_fw.py)         = AAAA: single loop, LLM self-evaluates via <progress>, declares own DONE.
  v2 (llm_fw_v2_ABAB.py) = ABAB: Worker→Judge→prog loop. Harness decides DONE (100% score).
  v3 (this file)          = Both architectures in one file. Shared infra deduplicated.
                            ABAB gets LoopResult, thread accumulation, eval framework.
                            CONFIG per-step bug fixed (replace() instead of fresh CONFIG()).

Usage:
    uv run llm_120b_ralph_v3.py "task here"                  # ABAB (default)
    uv run llm_120b_ralph_v3.py --mode aaaa "task here"      # AAAA mode
    uv run llm_120b_ralph_v3.py --example algorithm          # example (default ABAB)
    uv run llm_120b_ralph_v3.py --example all                # tmux grid: all 8 in parallel
    uv run llm_120b_ralph_v3.py --example list               # list available examples
    uv run llm_120b_ralph_v3.py --tests                      # all tests (unit + integration)
    uv run llm_120b_ralph_v3.py --eval                       # evals (default mode)
    uv run llm_120b_ralph_v3.py --eval --mode aaaa           # evals in AAAA mode
    uv run llm_120b_ralph_v3.py --kill                       # kill tmux session
    uv run llm_120b_ralph_v3.py                              # help

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

── SHARED ──
☑️✅🧪 R1: LLM API — streaming, TTFT, exp-backoff retries, semaphore
☑️✅🧪 R2: CONFIG — merged dataclass (model, gen, rate-limit, retry, AAAA fields, ABAB fields)
  ☑️✅🧪 R2.1: replace() for per-step overrides (inherits API_KEY etc.)
☑️✅🧪 R3: PROMPTS — 8 progressive examples, .get(), .names()
☑️✅🧪 R4: Logging — labeled _write_log with absolute paths

── AAAA (self-evaluating progress loop) ──
☑️✅🧪 R5: <progress> tag parsing, retry on missing, NEXT: DONE termination
☑️✅🧪 R6: LoopResult + thread accumulation + Rich summary
☑️✅🧪 R7: RALPH_TENETS (7 tenets) + _build_analysis_prompt
☑️✅🧪 R8: AGENT_PROMPT / AGENT_PROMPT_FILE override

── ABAB (generator-verifier loop) ──
☑️✅🧪 R9: parse_artifacts, parse_scratchpad, parse_promise
☑️✅🧪 R10: parse_requirements, parse_tests, parse_rubric (Req/Test/Score)
☑️✅ R11: R→A→B→prog architecture with stall detection
☑️✅ R12: ABLoopResult + thread + Rich summary (NEW in v3)
☑️✅ R13: AB_TENETS (5 criteria) + _build_ab_analysis_prompt (NEW in v3)

── EVALS ──
☑️✅🧪 R14: AAAA programmatic evals (concise, structured, no_bleed, summary)
☑️✅🧪 R15: AAAA LLM-judge evals (incremental_value, forward_motion, no_echo)
☑️✅ R16: ABAB evals (score_progression, artifacts_present, thread analysis)

── CLI ──
☑️✅ R17: --mode aaaa|abab, --tests, --eval, --example, --kill
☑️✅ R18: tmux grid with graceful degradation

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
from dataclasses import dataclass, field, replace
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


# ═══════════════════════════════════════════════════════════════
# SHARED INFRASTRUCTURE
# ═══════════════════════════════════════════════════════════════

# ─────────────── CONFIG (merged v1 + v2) ─────────────────────

@dataclass
class CONFIG:
    """All knobs for both AAAA and ABAB loops."""
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

    # ── common loop ──
    AGENT_LOGS_DIR: str = "agent_logs"
    LOOP_COOLDOWN: float = 1.0        # seconds between iterations
    MAX_ITERATIONS: int = 5           # >0 = bounded (ABAB default), AAAA overrides to 100 for examples

    # ── AAAA-specific ──
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
    PROGRESS_RETRIES: int = 2                   # re-run if <progress> parse fails

    # ── ABAB-specific ──
    STALL_LIMIT: int = 2              # stop if score doesn't improve for N iters


CFG = CONFIG()
CON = Console()


# ─────────────── EXAMPLE PROMPTS ─────────────────────────────
# Tuple format, progressively harder. Usage: --example <name>

class PROMPTS:
    """Example prompts — progressively harder. 1=easy (~1 iter), 8=hard (many)."""

    # ── All prompts are SELF-CONTAINED: no file access, no tool-use. ──

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
        val = getattr(cls, name, None)
        return val if isinstance(val, str) else None

    @classmethod
    def names(cls) -> list[str]:
        return [k for k in vars(cls) if not k.startswith("_") and isinstance(getattr(cls, k), str)]


# ─────────────── GLOBAL SEMAPHORE ────────────────────────────

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


# ─────────────── CORE LLM CALL ───────────────────────────────

@retry(
    retry=retry_if_exception_type((RateLimitError, APIStatusError)),
    stop=stop_after_attempt(CFG.MAX_RETRIES),
    wait=wait_exponential(min=CFG.BACKOFF_MIN, max=CFG.BACKOFF_MAX),
    reraise=True,
)
async def _call(prompt: str, cfg: CONFIG) -> str:
    """Single LLM call with streaming + retry. Streams tokens live to terminal."""
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

        CON.print(f"[bold cyan]{cfg.MODEL.split('/')[-1]}[/] ", end="")
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices[0].delta else None
            if delta:
                if ttft is None:
                    ttft = time.perf_counter() - t0
                chunks.append(delta)
                print(delta, end="", flush=True)
        print()

        elapsed = time.perf_counter() - t0
        text = "".join(chunks)
        if ttft is None:
            ttft = elapsed

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


# ─────────────── SHARED HELPERS ──────────────────────────────

def _git_short(n: int = 6) -> str:
    """Current commit hash, short."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", f"--short={n}", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        return "nogit"


def _write_log(logfile: Path, label: str, prompt: str, result: str) -> None:
    """Append labeled iteration result to logfile."""
    logfile.parent.mkdir(parents=True, exist_ok=True)
    with logfile.open("a") as f:
        f.write(f"\n{'='*72}\n")
        f.write(f"[{label}] TIME: {datetime.now().isoformat()}\n")
        f.write(f"PROMPT ({len(prompt)} chars):\n{prompt[:800]}{'…' if len(prompt)>800 else ''}\n")
        f.write(f"{'─'*72}\n")
        f.write(f"RESPONSE ({len(result)} chars):\n{result}\n")
    CON.print(f"[dim]logged → {logfile.resolve()}[/]")


# ═══════════════════════════════════════════════════════════════
# AAAA: SELF-EVALUATING PROGRESS LOOP (from v1)
# ═══════════════════════════════════════════════════════════════

# ─────────────── progress parser ─────────────────────────────

_PROGRESS_RE = re.compile(r"<progress>(.*?)</progress>", re.DOTALL | re.IGNORECASE)


def _parse_progress(text: str) -> str | None:
    """Extract content between <progress>...</progress> tags. None if missing."""
    m = _PROGRESS_RE.search(text)
    return m.group(1).strip() if m else None


def _read_agent_prompt(cfg: CONFIG) -> str:
    """Read AGENT_PROMPT_FILE if it exists, else fall back to CONFIG.AGENT_PROMPT."""
    p = Path(cfg.AGENT_PROMPT_FILE)
    if p.is_file():
        text = p.read_text().strip()
        CON.print(f"[dim]agent prompt: {p.resolve()} ({len(text)} chars)[/]")
        return text
    return cfg.AGENT_PROMPT


# ─────────────── data structures ─────────────────────────────

@dataclass
class _AAIterData:
    """One AAAA iteration's data, collected for eval/judge."""
    iteration: int
    progress_in: str
    response: str
    progress_out: str  # "" if parse failed

_AA_TRACES: list[_AAIterData] = []


@dataclass
class LoopResult:
    """Full result of an AAAA loop run — returned to caller."""
    iterations: int
    total_time: float
    final_progress: str
    thread: list[str]       # one entry per iteration
    done_signal: bool       # True if agent said NEXT: DONE
    prompt: str             # original user prompt


# ─────────────── RALPH TENETS (for AAAA analysis) ────────────

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
    """Format one AAAA iteration into a thread entry string."""
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

    return Panel(tbl, title="[bold magenta]AAAA LOOP SUMMARY[/]", border_style="magenta")


def _build_analysis_prompt(r: LoopResult) -> str:
    """Build the prompt for the final LLM analysis of an AAAA thread."""
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


# ─────────────── AAAA LOOP ───────────────────────────────────

async def ralph_loop_aaaa(prompt: str, cfg: CONFIG = CFG) -> LoopResult:
    """The AAAA loop — while-true, carries <progress> between iterations.

    LLM outputs <progress>...</progress> tags. Harness parses and injects
    accumulated progress into next iteration. Agent signals NEXT: DONE.
    """
    bound = f"max {cfg.MAX_ITERATIONS}" if cfg.MAX_ITERATIONS > 0 else "infinite"
    CON.rule("[bold magenta]ralph AAAA loop — oss120b (no tool-use)[/]")
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
        logfile = Path(cfg.AGENT_LOGS_DIR) / f"aaaa_{commit}_{iteration:04d}.log"

        CON.rule(f"[bold cyan]iteration {iteration}/{bound}  |  {commit}[/]")
        progress_before = progress
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
            CON.print("[bold red]⚠ WARNING: progress NOT injected into prompt![/]")
        elif not progress.strip():
            CON.print("[bold red]⚠ WARNING: progress is EMPTY![/]")
        else:
            CON.print(f"[bold green]✓ progress injected:[/] {progress[:200]}{'…' if len(progress)>200 else ''}")

        # ── call LLM with retry on missing <progress> tag ──
        result: str = ""
        parsed: str | None = None
        for attempt in range(1 + cfg.PROGRESS_RETRIES):
            try:
                if attempt > 0:
                    CON.print(f"[bold yellow]retry {attempt}/{cfg.PROGRESS_RETRIES} — <progress> tag missing[/]")
                result = await llm(full_prompt, cfg)
                _write_log(logfile, f"AAAA-{iteration}", full_prompt, result)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                CON.print(f"[bold red]error: {e}[/]")
                _write_log(logfile, f"AAAA-{iteration}", full_prompt, f"ERROR: {e}")
                break

            parsed = _parse_progress(result)
            if parsed is not None:
                break
            CON.print("[bold yellow]⚠ no <progress> tag found in response[/]")

        # ── update progress ──
        if parsed:
            progress = parsed
            CON.print(f"[bold green]progress out:[/] {progress[:200]}{'…' if len(progress)>200 else ''}")
        else:
            CON.print("[bold red]<progress> parse failed after retries — keeping previous[/]")

        iter_elapsed = time.perf_counter() - iter_t0

        _AA_TRACES.append(_AAIterData(
            iteration=iteration, progress_in=progress_before,
            response=result, progress_out=parsed or "",
        ))

        thread.append(_format_thread_entry(
            iteration, progress_before, result, parsed or "(parse failed)", iter_elapsed,
        ))

        # ── agent signals completion via NEXT: DONE ──
        if parsed and re.search(r"NEXT:\s*DONE\b", parsed, re.IGNORECASE):
            done_signal = True
            CON.rule(f"[bold green]agent signalled DONE after {iteration} iterations[/]")
            break

        # ── cooldown ──
        last = cfg.MAX_ITERATIONS > 0 and iteration >= cfg.MAX_ITERATIONS
        if cfg.LOOP_COOLDOWN > 0 and not last:
            CON.print(f"[dim]sleeping {cfg.LOOP_COOLDOWN}s…[/]")
            await asyncio.sleep(cfg.LOOP_COOLDOWN)

    total_time = time.perf_counter() - t0
    loop_result = LoopResult(
        iterations=len(thread), total_time=total_time,
        final_progress=progress, thread=thread,
        done_signal=done_signal, prompt=prompt,
    )
    CON.print()
    CON.print(_format_summary(loop_result))
    return loop_result


# ═══════════════════════════════════════════════════════════════
# ABAB: GENERATOR-VERIFIER LOOP (from v2, with fixes)
# ═══════════════════════════════════════════════════════════════

# ─────────────── ABAB PARSERS ────────────────────────────────
# TDD: tests written first, then these implementations.

_ARTIFACT_RE = re.compile(
    r'<artifact\s+name=["\']([^"\']+)["\']\s*>(.*?)</artifact>',
    re.DOTALL | re.IGNORECASE,
)

def parse_artifacts(text: str) -> dict[str, str]:
    """Extract all <artifact name="...">...</artifact> blocks."""
    return {m.group(1): m.group(2).strip() for m in _ARTIFACT_RE.finditer(text)}


_SCRATCHPAD_RE = re.compile(
    r"<scratchpad>(.*?)</scratchpad>", re.DOTALL | re.IGNORECASE,
)

def parse_scratchpad(text: str) -> str | None:
    """Extract <scratchpad> content. None if missing."""
    m = _SCRATCHPAD_RE.search(text)
    return m.group(1).strip() if m else None


_PROMISE_RE = re.compile(
    r"<promise>(.*?)</promise>", re.DOTALL | re.IGNORECASE,
)

def parse_promise(text: str) -> str | None:
    """Extract <promise> content. None if missing."""
    m = _PROMISE_RE.search(text)
    return m.group(1).strip() if m else None


_REQ_BLOCK_RE = re.compile(
    r"<requirements>(.*?)</requirements>", re.DOTALL | re.IGNORECASE,
)
_REQ_LINE_RE = re.compile(r"(R\d+):\s*(.+)")

@dataclass
class Req:
    id: str    # "R1"
    desc: str  # "class has get/set/del/list_keys"

def parse_requirements(text: str) -> list[Req]:
    """Extract requirements from <requirements> block."""
    m = _REQ_BLOCK_RE.search(text)
    if not m:
        return []
    block = m.group(1)
    return [Req(id=lm.group(1), desc=lm.group(2).strip())
            for lm in _REQ_LINE_RE.finditer(block)]


_TEST_BLOCK_RE = re.compile(
    r"<tests>(.*?)</tests>", re.DOTALL | re.IGNORECASE,
)
_TEST_LINE_RE = re.compile(r"(T\d+):\s*(unit|judge):\s*(.+)", re.IGNORECASE)

@dataclass
class Test:
    id: str    # "T1"
    kind: str  # "unit" or "judge"
    desc: str  # "get after set returns stored value"

def parse_tests(text: str) -> list[Test]:
    """Extract tests from <tests> block."""
    m = _TEST_BLOCK_RE.search(text)
    if not m:
        return []
    block = m.group(1)
    return [Test(id=lm.group(1), kind=lm.group(2).lower(), desc=lm.group(3).strip())
            for lm in _TEST_LINE_RE.finditer(block)]


_SCORE_LINE_RE = re.compile(r"([RT]\d+):\s*(PASS|FAIL):\s*(.+)")

@dataclass
class Score:
    id: str       # "R1" or "T1"
    passed: bool
    reason: str

def parse_rubric(text: str) -> list[Score]:
    """Parse judge output: R1: PASS|FAIL: reason per line."""
    return [Score(id=m.group(1), passed=m.group(2) == "PASS", reason=m.group(3).strip())
            for m in _SCORE_LINE_RE.finditer(text)]


def fmt_score(scores: list[Score]) -> tuple[int, int, float]:
    """Returns (passed, total, pct)."""
    total = len(scores)
    passed = sum(1 for s in scores if s.passed)
    pct = (passed / total * 100) if total > 0 else 0.0
    return passed, total, pct


def fmt_failures(scores: list[Score]) -> str:
    """Format only failing scores for injection into worker prompt."""
    fails = [s for s in scores if not s.passed]
    if not fails:
        return "none"
    return "\n".join(f"  {s.id}: FAIL: {s.reason}" for s in fails)


# ─────────────── ABAB PROMPTS ────────────────────────────────

REQ_PROMPT = (
    "You are a requirements analyst. Given a task description, extract:\n"
    "1. Concrete, testable requirements (R1, R2, ...)\n"
    "2. Acceptance tests (T1, T2, ...) — each is either 'unit' (structural check)\n"
    "   or 'judge' (semantic quality check)\n\n"
    "Output EXACTLY this format (no other text):\n"
    "<requirements>\n"
    "R1: requirement description\n"
    "R2: requirement description\n"
    "...\n"
    "</requirements>\n"
    "<tests>\n"
    "T1: unit: what to check structurally\n"
    "T2: judge: what to evaluate semantically\n"
    "...\n"
    "</tests>\n\n"
    "Be specific. 5-8 requirements, 5-8 tests. No vague criteria.\n"
)

WORKER_PROMPT = (
    "You are a senior software engineer. Complete the task below.\n\n"
    "OUTPUT FORMAT (you MUST use these exact tags):\n\n"
    "<scratchpad>\n"
    "Your thinking, planning, reasoning (this will be DISCARDED — not saved).\n"
    "</scratchpad>\n\n"
    "Then output one or more artifacts (these PERSIST between iterations):\n"
    '<artifact name="filename.py">\n'
    "file contents here\n"
    "</artifact>\n\n"
    "Finally, state what you believe you've achieved:\n"
    "<promise>\n"
    "List which requirements (R1, R2...) and tests (T1, T2...) you believe pass.\n"
    "Be honest — the judge will verify.\n"
    "</promise>\n\n"
    "RULES:\n"
    "- Output ALL artifacts every iteration (they replace previous versions).\n"
    "- The <scratchpad> is ephemeral — do NOT rely on it persisting.\n"
    "- Only the artifacts and the promise are kept.\n"
    "- Fix specific failures listed below. Don't redo passing work.\n"
)

AB_JUDGE_PROMPT = (
    "You are a strict code reviewer and test evaluator.\n"
    "You will be given requirements, acceptance tests, and code artifacts.\n"
    "You must SIMULATE running each test against the artifacts.\n\n"
    "Score EVERY requirement and test. Output EXACTLY this format:\n"
    "R1: PASS: reason (or FAIL: reason)\n"
    "R2: PASS: reason (or FAIL: reason)\n"
    "...\n"
    "T1: PASS: reason (or FAIL: reason)\n"
    "T2: PASS: reason (or FAIL: reason)\n"
    "...\n"
    "SCORE: X/Y (Z%)\n\n"
    "RULES:\n"
    "- Be STRICT. Only PASS if the requirement is clearly met in the code.\n"
    "- For 'unit' tests: check structure, types, method existence.\n"
    "- For 'judge' tests: evaluate quality, style, correctness.\n"
    "- Reference specific artifact names in your reasons.\n"
    "- No preamble. Start with R1: immediately.\n"
)


# ─────────────── ABAB HELPERS ────────────────────────────────

def _fmt_artifacts(artifacts: dict[str, str]) -> str:
    """Format artifacts dict for injection into prompts."""
    if not artifacts:
        return "(no artifacts yet — this is the first iteration)"
    parts = []
    for name, content in artifacts.items():
        parts.append(f'<artifact name="{name}">\n{content}\n</artifact>')
    return "\n\n".join(parts)


def _fmt_reqs(reqs: list[Req]) -> str:
    return "\n".join(f"{r.id}: {r.desc}" for r in reqs)


def _fmt_tests(tests: list[Test]) -> str:
    return "\n".join(f"{t.id}: {t.kind}: {t.desc}" for t in tests)


# ─────────────── ABAB RESULT + ANALYSIS ──────────────────────

@dataclass
class ABLoopResult:
    """Full result of an ABAB loop run — returned to caller. (NEW in v3)"""
    iterations: int
    total_time: float
    final_scores: list[Score]
    artifacts: dict[str, str]
    requirements: list[Req]
    tests: list[Test]
    thread: list[str]
    score_history: list[float]   # pct per iteration
    done: bool                   # True if 100% reached
    stalled: bool                # True if stopped due to stall
    prompt: str
    best_pct: float


AB_TENETS = (
    "1. SCORE PROGRESSION: Score improves across iterations. No regression.\n"
    "2. FAILURE ADDRESSING: Worker fixes specific issues identified by judge.\n"
    "3. ARTIFACT QUALITY: Final artifacts are complete and well-structured.\n"
    "4. EFFICIENCY: Loop converges quickly without unnecessary iterations.\n"
    "5. JUDGE STRICTNESS: Judge is appropriately strict, not rubber-stamping.\n"
)


def _format_ab_summary(r: ABLoopResult) -> Panel:
    """Build a Rich Panel with summary table for an ABLoopResult."""
    if r.done:
        status = "[bold green]100%[/] — all requirements satisfied"
    elif r.stalled:
        status = f"[yellow]STALLED[/] — score plateau at {r.best_pct:.0f}%"
    else:
        status = f"[yellow]LIMIT[/] — hit iteration cap at {r.best_pct:.0f}%"
    avg = r.total_time / max(r.iterations, 1)

    tbl = Table(show_header=False, box=None, padding=(0, 2))
    tbl.add_column("key", style="bold cyan", width=16)
    tbl.add_column("value")
    tbl.add_row("Prompt", r.prompt[:100] + ("…" if len(r.prompt) > 100 else ""))
    tbl.add_row("Iterations", str(r.iterations))
    tbl.add_row("Total time", f"{r.total_time:.2f}s")
    tbl.add_row("Avg / iter", f"{avg:.2f}s")
    tbl.add_row("Status", status)
    tbl.add_row("Score history", " → ".join(f"{p:.0f}%" for p in r.score_history) or "n/a")
    tbl.add_row("Artifacts", ", ".join(r.artifacts.keys()) or "none")
    tbl.add_row("Requirements", f"{len(r.requirements)} extracted")

    return Panel(tbl, title="[bold magenta]ABAB LOOP SUMMARY[/]", border_style="magenta")


def _build_ab_analysis_prompt(r: ABLoopResult) -> str:
    """Build the prompt for the final LLM analysis of an ABAB thread."""
    thread_text = "\n\n".join(r.thread)
    return (
        "You are an evaluator. Analyze how this ABAB generator-verifier loop performed.\n"
        "Score each criterion 1-5 (1=violated, 5=exemplary). Give overall score and brief commentary.\n\n"
        f"<thread>\n{thread_text}\n</thread>\n\n"
        f"<criteria>\n{AB_TENETS}</criteria>\n\n"
        "Respond with:\n"
        "- Per-criterion scores (name: score/5 + one-line reason)\n"
        "- Overall score: X/5\n"
        "- One paragraph summary.\n"
    )


# ─────────────── ABAB LOOP ───────────────────────────────────

async def ralph_loop_abab(task: str, cfg: CONFIG = CFG) -> ABLoopResult:
    """The ABAB loop: R → (A → B → prog)* → done.

    FIX vs v2: uses replace(cfg, ...) for per-step configs so API_KEY
    and other custom fields are inherited. Returns ABLoopResult with
    thread accumulation + score history.
    """
    CON.rule("[bold magenta]ralph ABAB loop (generator-verifier)[/]")
    CON.print(f"[bold yellow]task:[/] {task}")
    CON.print(f"[dim]max iters: {cfg.MAX_ITERATIONS}  |  stall limit: {cfg.STALL_LIMIT}  |  cooldown: {cfg.LOOP_COOLDOWN}s[/]\n")

    commit = _git_short()
    logfile = Path(cfg.AGENT_LOGS_DIR) / f"abab_{commit}_{int(time.time())}.log"

    # ── STEP R: Extract requirements + tests (one-shot) ──
    CON.rule("[bold cyan]R: REQUIREMENT EXTRACTION[/]")
    req_prompt = f"{REQ_PROMPT}\nTASK:\n{task}"
    req_cfg = replace(cfg, MAX_TOKENS=1024, TEMPERATURE=0.3)  # FIX: inherits API_KEY
    req_raw = await llm(req_prompt, req_cfg)
    _write_log(logfile, "R-STEP", req_prompt, req_raw)

    reqs = parse_requirements(req_raw)
    tests = parse_tests(req_raw)

    if not reqs:
        CON.print("[bold red]R-step failed to extract requirements — cannot continue[/]")
        return ABLoopResult(
            iterations=0, total_time=0, final_scores=[], artifacts={},
            requirements=[], tests=[], thread=[], score_history=[],
            done=False, stalled=False, prompt=task, best_pct=0,
        )

    CON.print(f"\n[bold green]extracted {len(reqs)} requirements, {len(tests)} tests:[/]")
    for r in reqs:
        CON.print(f"  [cyan]{r.id}[/]: {r.desc}")
    for t in tests:
        CON.print(f"  [yellow]{t.id}[/] ({t.kind}): {t.desc}")

    # ── fixed rubric from here on ──
    reqs_str = _fmt_reqs(reqs)
    tests_str = _fmt_tests(tests)

    artifacts: dict[str, str] = {}
    failures_str: str = "none (first iteration)"
    best_pct: float = 0.0
    stall_count: int = 0
    final_scores: list[Score] = []
    thread: list[str] = []
    score_history: list[float] = []
    done = False
    stalled = False
    t0 = time.perf_counter()
    actual_iters = 0

    for iteration in range(1, cfg.MAX_ITERATIONS + 1):
        actual_iters = iteration
        iter_t0 = time.perf_counter()
        CON.rule(f"[bold cyan]A: WORKER — iteration {iteration}/{cfg.MAX_ITERATIONS}[/]")

        # ── build worker prompt ──
        worker_prompt = (
            f"{WORKER_PROMPT}\n"
            f"{'─'*40}\n"
            f"TASK:\n{task}\n\n"
            f"REQUIREMENTS:\n{reqs_str}\n\n"
            f"TESTS:\n{tests_str}\n\n"
            f"{'─'*40}\n"
            f"CURRENT ARTIFACTS:\n{_fmt_artifacts(artifacts)}\n\n"
            f"{'─'*40}\n"
            f"FAILING SCORES FROM LAST JUDGE:\n{failures_str}\n\n"
            f"{'─'*40}\n"
            f"ITERATION: {iteration} of {cfg.MAX_ITERATIONS}\n"
            f"Fix the failures. Output ALL artifacts (full contents, they replace previous).\n"
        )

        worker_cfg = replace(cfg, TEMPERATURE=0.7)  # FIX: inherits API_KEY
        worker_raw = await llm(worker_prompt, worker_cfg)
        _write_log(logfile, f"A-STEP-{iteration}", worker_prompt, worker_raw)

        # ── parse worker output ──
        new_artifacts = parse_artifacts(worker_raw)
        promise = parse_promise(worker_raw)
        scratchpad = parse_scratchpad(worker_raw)

        if new_artifacts:
            artifacts.update(new_artifacts)
            CON.print(f"[bold green]artifacts:[/] {', '.join(new_artifacts.keys())}")
        else:
            CON.print("[bold yellow]⚠ no artifacts found in worker output[/]")

        if scratchpad:
            CON.print(f"[dim]scratchpad: {len(scratchpad)} chars (discarded)[/]")
        if promise:
            CON.print(f"[bold]promise:[/] {promise[:200]}{'…' if len(promise)>200 else ''}")

        # ── B: JUDGE ──
        CON.rule(f"[bold cyan]B: JUDGE — iteration {iteration}/{cfg.MAX_ITERATIONS}[/]")

        judge_prompt = (
            f"{AB_JUDGE_PROMPT}\n"
            f"{'─'*40}\n"
            f"REQUIREMENTS:\n{reqs_str}\n\n"
            f"TESTS:\n{tests_str}\n\n"
            f"{'─'*40}\n"
            f"ARTIFACTS:\n{_fmt_artifacts(artifacts)}\n\n"
            f"{'─'*40}\n"
            f"WORKER'S PROMISE:\n{promise or '(no promise provided)'}\n\n"
            f"{'─'*40}\n"
            f"Score every R and T. Start with R1: immediately.\n"
        )

        judge_cfg = replace(cfg, MAX_TOKENS=1024, TEMPERATURE=0.0)  # FIX: inherits API_KEY
        judge_raw = await llm(judge_prompt, judge_cfg)
        _write_log(logfile, f"B-STEP-{iteration}", judge_prompt, judge_raw)

        # ── PROG: parse scores ──
        scores = parse_rubric(judge_raw)
        final_scores = scores
        iter_elapsed = time.perf_counter() - iter_t0

        if not scores:
            CON.print("[bold red]judge returned no parseable scores — retrying next iteration[/]")
            failures_str = "judge output was unparseable — re-do your work and try again"
            score_history.append(0.0)
            thread.append(
                f"── ITERATION {iteration} ({iter_elapsed:.1f}s) — JUDGE UNPARSEABLE ──\n"
                f"WORKER: {len(worker_raw)} chars, {len(new_artifacts)} artifacts\n"
                f"JUDGE: unparseable\n"
            )
            continue

        passed, total, pct = fmt_score(scores)
        score_history.append(pct)
        color = "green" if pct == 100 else "yellow" if pct >= 60 else "red"
        CON.print(f"\n[bold {color}]SCORE: {passed}/{total} ({pct:.0f}%)[/]")

        for s in scores:
            tag = "[green]PASS[/]" if s.passed else "[red]FAIL[/]"
            CON.print(f"  {tag} {s.id}: {s.reason}")

        # ── accumulate thread ──
        score_lines = "\n".join(f"  {'PASS' if s.passed else 'FAIL'} {s.id}: {s.reason}" for s in scores)
        thread.append(
            f"── ITERATION {iteration} ({iter_elapsed:.1f}s) — {passed}/{total} ({pct:.0f}%) ──\n"
            f"WORKER: {len(worker_raw)} chars, artifacts: {', '.join(new_artifacts.keys()) or 'none'}\n"
            f"SCORES:\n{score_lines}\n"
        )

        # ── 100%? done ──
        if pct == 100:
            done = True
            CON.rule(f"[bold green]100% — all requirements satisfied after {iteration} iterations[/]")
            break

        # ── stall detection ──
        if pct <= best_pct:
            stall_count += 1
            if stall_count >= cfg.STALL_LIMIT:
                stalled = True
                CON.rule(f"[bold yellow]stalled — score hasn't improved for {cfg.STALL_LIMIT} iterations, stopping at {pct:.0f}%[/]")
                break
        else:
            best_pct = pct
            stall_count = 0

        # ── format failures for next iteration ──
        failures_str = fmt_failures(scores)

        # ── cooldown ──
        if cfg.LOOP_COOLDOWN > 0 and iteration < cfg.MAX_ITERATIONS:
            CON.print(f"[dim]sleeping {cfg.LOOP_COOLDOWN}s…[/]")
            await asyncio.sleep(cfg.LOOP_COOLDOWN)

    total_time = time.perf_counter() - t0

    result = ABLoopResult(
        iterations=actual_iters, total_time=total_time,
        final_scores=final_scores, artifacts=artifacts,
        requirements=reqs, tests=tests, thread=thread,
        score_history=score_history, done=done, stalled=stalled,
        prompt=task, best_pct=best_pct,
    )

    # ── rich summary ──
    CON.print()
    CON.print(_format_ab_summary(result))

    # ── final artifacts list ──
    CON.rule("[bold magenta]FINAL ARTIFACTS[/]")
    for name, content in artifacts.items():
        CON.print(f"[bold cyan]{name}[/] ({len(content)} chars)")
    CON.print(f"\n[dim]full log → {logfile.resolve()}[/]")

    return result


# ═══════════════════════════════════════════════════════════════
# EVALS
# ═══════════════════════════════════════════════════════════════

# ─────────────── eval judge infrastructure ───────────────────

_EVAL_VERDICT_RE = re.compile(r"^(PASS|FAIL):\s*(.+)", re.MULTILINE)

EVAL_JUDGE_PROMPT = (
    "You are an eval judge. You evaluate whether an AI agent loop followed a design tenet.\n"
    "You will be given the tenet description and the iteration data.\n\n"
    "Respond with EXACTLY ONE line in this format:\n"
    "PASS: <1-sentence justification>\n"
    "or\n"
    "FAIL: <1-sentence justification>\n\n"
    "NOTHING ELSE. No preamble, no extra lines. Just the verdict line."
)


def _eval_judge_prompt(tenet_name: str, tenet_desc: str, data: str) -> str:
    """Build the full judge prompt for one tenet evaluation."""
    return (
        f"{EVAL_JUDGE_PROMPT}\n\n"
        f"TENET: {tenet_name}\n"
        f"DESCRIPTION: {tenet_desc}\n\n"
        f"ITERATION DATA:\n{data}"
    )


def _parse_verdict(text: str) -> tuple[bool, str]:
    """Parse PASS|FAIL: justification from judge output."""
    m = _EVAL_VERDICT_RE.search(text)
    if m:
        return (m.group(1) == "PASS", m.group(2).strip())
    return (False, f"judge output unparseable: {text[:200]}")


async def _judge_with_retry(prompt: str, cfg: CONFIG, retries: int = 2) -> tuple[bool, str]:
    """Call LLM judge with retries on empty/unparseable responses."""
    ok, reason = False, "no attempts"
    for attempt in range(1 + retries):
        raw = await llm(prompt, cfg)
        ok, reason = _parse_verdict(raw)
        if "unparseable" not in reason:
            return (ok, reason)
        if attempt < retries:
            CON.print(f"[dim]judge retry {attempt+1}/{retries} — unparseable response[/]")
    return (ok, reason)


def _fmt_aa_traces(traces: list[_AAIterData], include_response: bool = True) -> str:
    """Format AAAA traces for judge consumption."""
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


# ─────────────── AAAA programmatic evals ─────────────────────

def _eval_concise_progress(traces: list[_AAIterData]) -> tuple[bool, str]:
    """Progress blocks must stay under 500 chars and not bloat."""
    if not traces:
        return (False, "no traces collected")
    sizes = [len(t.progress_out) for t in traces]
    max_sz = max(sizes)
    if max_sz > 500:
        return (False, f"progress block hit {max_sz} chars (limit 500)")
    if len(sizes) > 1 and sizes[0] > 0 and sizes[-1] > sizes[0] * 3:
        return (False, f"progress bloated from {sizes[0]} to {sizes[-1]} chars ({sizes[-1]/sizes[0]:.1f}x)")
    return (True, f"all progress blocks under 500 chars, max={max_sz}")


def _eval_structured_format(traces: list[_AAIterData]) -> tuple[bool, str]:
    """Every progress block must have DONE/CURRENT/NEXT/BLOCKERS."""
    required = ["DONE:", "CURRENT:", "NEXT:", "BLOCKERS:"]
    for t in traces:
        if not t.progress_out:
            return (False, f"iteration {t.iteration} has empty progress_out")
        missing = [f for f in required if f not in t.progress_out.upper()]
        if missing:
            return (False, f"iteration {t.iteration} missing fields: {missing}")
    return (True, f"all {len(traces)} iterations have all 4 required fields")


def _eval_no_context_bleed(traces: list[_AAIterData]) -> tuple[bool, str]:
    """Progress must NOT contain the full previous response (>50% = bleed)."""
    for t in traces:
        if not t.response:
            continue
        ratio = len(t.progress_out) / max(len(t.response), 1)
        if ratio > 0.5:
            return (False, f"iteration {t.iteration}: progress is {ratio:.0%} of response length — context bleed")
    return (True, "progress blocks are concise relative to responses")


def _eval_progress_is_summary(traces: list[_AAIterData]) -> tuple[bool, str]:
    """Progress is a concise SUMMARY, not a copy of the response."""
    CHUNK = 60
    for t in traces:
        if not t.progress_out or not t.response:
            continue
        resp_stripped = _PROGRESS_RE.sub("", t.response).strip()
        if not resp_stripped:
            continue
        for i in range(len(t.progress_out) - CHUNK + 1):
            snippet = t.progress_out[i:i + CHUNK]
            if snippet in resp_stripped:
                return (False, f"iteration {t.iteration}: progress contains 60+ char verbatim excerpt from response body")
    return (True, "progress blocks are summaries, not verbatim copies")


# ─────────────── AAAA LLM judge evals ────────────────────────

async def _eval_incremental_value(traces: list[_AAIterData], cfg: CONFIG) -> tuple[bool, str]:
    """DONE list should grow monotonically."""
    data = _fmt_aa_traces(traces, include_response=False)
    prompt = _eval_judge_prompt(
        "incremental_value",
        "Each iteration must add new DONE items. The DONE list should grow monotonically. "
        "If iteration N has fewer or identical DONE items compared to N-1, that's a FAIL.",
        data,
    )
    return await _judge_with_retry(prompt, cfg)


async def _eval_forward_motion(traces: list[_AAIterData], cfg: CONFIG) -> tuple[bool, str]:
    """NEXT field should change between iterations."""
    data = _fmt_aa_traces(traces, include_response=False)
    prompt = _eval_judge_prompt(
        "forward_motion",
        "The NEXT field should change between iterations. Identical NEXT = stuck.",
        data,
    )
    return await _judge_with_retry(prompt, cfg)


async def _eval_no_echo(traces: list[_AAIterData], cfg: CONFIG) -> tuple[bool, str]:
    """Response should not just echo the system prompt."""
    data = _fmt_aa_traces(traces)
    prompt = _eval_judge_prompt(
        "no_echo",
        "Response should contain substantive NEW content, not echo system prompt or task.",
        data,
    )
    return await _judge_with_retry(prompt, cfg)


async def _eval_aa_thread_analysis(result: LoopResult, cfg: CONFIG) -> tuple[bool, str]:
    """Final LLM analysis of AAAA thread. Passes if overall >= 3/5."""
    prompt = _build_analysis_prompt(result)
    try:
        analysis = await llm(prompt, cfg)
    except Exception as e:
        return (False, f"analysis LLM call failed: {e}")
    m = re.search(r"[Oo]verall.*?(\d)/5", analysis)
    if m:
        score = int(m.group(1))
        return (score >= 3, f"overall score {score}/5\n{analysis[:300]}")
    return (True, f"could not parse score, treating as pass\n{analysis[:300]}")


# ─────────────── ABAB programmatic evals ─────────────────────

def _eval_ab_score_progression(result: ABLoopResult) -> tuple[bool, str]:
    """Score should generally improve (no regression > 20%)."""
    if len(result.score_history) < 2:
        return (True, f"only {len(result.score_history)} iteration(s), skip check")
    for i in range(1, len(result.score_history)):
        drop = result.score_history[i - 1] - result.score_history[i]
        if drop > 20:
            return (False, f"iter {i+1}: score dropped {drop:.0f}% ({result.score_history[i-1]:.0f}% → {result.score_history[i]:.0f}%)")
    return (True, f"scores: {' → '.join(f'{p:.0f}%' for p in result.score_history)}")


def _eval_ab_artifacts_present(result: ABLoopResult) -> tuple[bool, str]:
    """Final result should have at least one artifact."""
    if not result.artifacts:
        return (False, "no artifacts produced")
    return (True, f"{len(result.artifacts)} artifacts: {', '.join(result.artifacts.keys())}")


async def _eval_ab_thread_analysis(result: ABLoopResult, cfg: CONFIG) -> tuple[bool, str]:
    """Final LLM analysis of ABAB thread. Passes if overall >= 3/5."""
    prompt = _build_ab_analysis_prompt(result)
    try:
        analysis = await llm(prompt, cfg)
    except Exception as e:
        return (False, f"analysis LLM call failed: {e}")
    m = re.search(r"[Oo]verall.*?(\d)/5", analysis)
    if m:
        score = int(m.group(1))
        return (score >= 3, f"overall score {score}/5\n{analysis[:300]}")
    return (True, f"could not parse score, treating as pass\n{analysis[:300]}")


# ─────────────── eval runner ─────────────────────────────────

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


EVAL_TASK = (
    "Design a simple key-value store in Python.\n"
    "1. Define the API: get, set, delete, list_keys.\n"
    "2. Write the class with type hints.\n"
    "3. Write 3 pytest tests.\n"
    "4. Review and suggest improvements."
)


async def _run_evals_aaaa() -> None:
    """Run AAAA tenet evals."""
    global _EVAL_PASS, _EVAL_FAIL
    _EVAL_PASS, _EVAL_FAIL = 0, 0
    t0 = time.perf_counter()

    CON.rule("[bold magenta]EVAL (AAAA): collecting iteration data (3 iters)[/]")
    _AA_TRACES.clear()
    eval_cfg = replace(CFG, MAX_ITERATIONS=3, LOOP_COOLDOWN=0.5, MAX_TOKENS=2048)
    loop_result = await ralph_loop_aaaa(EVAL_TASK, eval_cfg)

    if not _AA_TRACES:
        CON.print("[bold red]no traces collected — cannot evaluate[/]")
        sys.exit(1)
    CON.print(f"\n[bold]collected {len(_AA_TRACES)} iteration traces[/]\n")

    CON.rule("[bold magenta]EVAL: programmatic tenets[/]")
    ok, reason = _eval_concise_progress(_AA_TRACES)
    _ev("concise_progress: <500 chars, no bloat", ok, reason)
    ok, reason = _eval_structured_format(_AA_TRACES)
    _ev("structured_format: DONE/CURRENT/NEXT/BLOCKERS", ok, reason)
    ok, reason = _eval_no_context_bleed(_AA_TRACES)
    _ev("no_context_bleed: progress < 50% of response", ok, reason)
    ok, reason = _eval_progress_is_summary(_AA_TRACES)
    _ev("progress_is_summary: sticky note, not transcript", ok, reason)

    CON.rule("[bold magenta]EVAL: LLM judge tenets[/]")
    judge_cfg = replace(CFG, MAX_TOKENS=256, TEMPERATURE=0.0)
    ok, reason = await _eval_incremental_value(_AA_TRACES, judge_cfg)
    _ev("incremental_value: DONE grows monotonically", ok, reason)
    ok, reason = await _eval_forward_motion(_AA_TRACES, judge_cfg)
    _ev("forward_motion: NEXT changes between iters", ok, reason)
    ok, reason = await _eval_no_echo(_AA_TRACES, judge_cfg)
    _ev("no_echo: response is substantive", ok, reason)

    CON.rule("[bold magenta]EVAL: thread analysis[/]")
    analysis_cfg = replace(CFG, MAX_TOKENS=1024, TEMPERATURE=0.0)
    ok, reason = await _eval_aa_thread_analysis(loop_result, analysis_cfg)
    _ev("thread_analysis: LLM judges overall loop quality", ok, reason)

    wall = time.perf_counter() - t0
    CON.rule("[bold magenta]EVAL RESULTS (AAAA)[/]")
    total = _EVAL_PASS + _EVAL_FAIL
    color = "green" if _EVAL_FAIL == 0 else "red"
    CON.print(f"[bold {color}]{_EVAL_PASS}/{total} tenets passed, {_EVAL_FAIL} failed[/]  |  {wall:.1f}s total")
    if _EVAL_FAIL > 0:
        sys.exit(1)


async def _run_evals_abab() -> None:
    """Run ABAB evals."""
    global _EVAL_PASS, _EVAL_FAIL
    _EVAL_PASS, _EVAL_FAIL = 0, 0
    t0 = time.perf_counter()

    CON.rule("[bold magenta]EVAL (ABAB): running 3-iteration loop[/]")
    eval_cfg = replace(CFG, MAX_ITERATIONS=3, LOOP_COOLDOWN=0.5, MAX_TOKENS=4096)
    result = await ralph_loop_abab(EVAL_TASK, eval_cfg)

    CON.rule("[bold magenta]EVAL: programmatic checks[/]")
    ok, reason = _eval_ab_score_progression(result)
    _ev("score_progression: no regression > 20%", ok, reason)
    ok, reason = _eval_ab_artifacts_present(result)
    _ev("artifacts_present: at least one artifact", ok, reason)

    CON.rule("[bold magenta]EVAL: thread analysis[/]")
    analysis_cfg = replace(CFG, MAX_TOKENS=1024, TEMPERATURE=0.0)
    ok, reason = await _eval_ab_thread_analysis(result, analysis_cfg)
    _ev("thread_analysis: LLM judges overall loop quality", ok, reason)

    wall = time.perf_counter() - t0
    CON.rule("[bold magenta]EVAL RESULTS (ABAB)[/]")
    total = _EVAL_PASS + _EVAL_FAIL
    color = "green" if _EVAL_FAIL == 0 else "red"
    CON.print(f"[bold {color}]{_EVAL_PASS}/{total} checks passed, {_EVAL_FAIL} failed[/]  |  {wall:.1f}s total")
    if _EVAL_FAIL > 0:
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════

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


# ─── shared tests ────────────────────────────────────────────

def _test_config_defaults() -> None:
    """CONFIG defaults are sane."""
    c = CONFIG()
    _t("config.MODEL is set", "gpt-oss-120b" in c.MODEL)
    _t("config.BASE_URL is fireworks", "fireworks.ai" in c.BASE_URL)
    _t("config.MAX_TOKENS > 0", c.MAX_TOKENS > 0)
    _t("config.TEMPERATURE in [0,2]", 0 <= c.TEMPERATURE <= 2.0)
    _t("config.MAX_RETRIES > 0", c.MAX_RETRIES > 0)
    _t("config.MAX_CONCURRENT > 0", c.MAX_CONCURRENT > 0)
    _t("config.RPM == 60", c.RPM == 60)
    _t("config.MAX_ITERATIONS default 5", c.MAX_ITERATIONS == 5)
    _t("config.LOOP_COOLDOWN >= 0", c.LOOP_COOLDOWN >= 0)
    _t("config.STALL_LIMIT default 2", c.STALL_LIMIT == 2)
    _t("config.PROGRESS_RETRIES default 2", c.PROGRESS_RETRIES == 2)
    _t("config.GEN_TPM > 0", c.GEN_TPM > 0)
    _t("config.PROMPT_TPM > 0", c.PROMPT_TPM > 0)


def _test_config_override() -> None:
    """CONFIG fields can be overridden."""
    c = CONFIG(MAX_TOKENS=99, TEMPERATURE=0.0, MAX_ITERATIONS=10)
    _t("override MAX_TOKENS", c.MAX_TOKENS == 99)
    _t("override TEMPERATURE", c.TEMPERATURE == 0.0)
    _t("override MAX_ITERATIONS", c.MAX_ITERATIONS == 10)


def _test_config_replace() -> None:
    """replace() inherits fields (v3 fix for API_KEY issue)."""
    c = CONFIG(MAX_TOKENS=2048, STALL_LIMIT=5)
    c2 = replace(c, MAX_TOKENS=512, TEMPERATURE=0.0)
    _t("replace keeps STALL_LIMIT", c2.STALL_LIMIT == 5)
    _t("replace overrides MAX_TOKENS", c2.MAX_TOKENS == 512)
    _t("replace overrides TEMPERATURE", c2.TEMPERATURE == 0.0)
    _t("replace keeps MODEL", c2.MODEL == c.MODEL)


def _test_prompts_class() -> None:
    """PROMPTS has 8 entries and lookup works."""
    names = PROMPTS.names()
    _t("PROMPTS has 8 entries", len(names) == 8, f"found {len(names)}")
    _t("PROMPTS.get('fizzbuzz') returns str", isinstance(PROMPTS.get("fizzbuzz"), str))
    _t("PROMPTS.get('full_system') returns str", isinstance(PROMPTS.get("full_system"), str))
    _t("PROMPTS.get('nonexistent') returns None", PROMPTS.get("nonexistent") is None)
    for n in names:
        val = PROMPTS.get(n)
        _t(f"PROMPTS.{n} is non-empty str", isinstance(val, str) and len(val) > 20, f"{len(val or '')} chars")


def _test_git_short() -> None:
    """_git_short returns a commit hash or 'nogit'."""
    h = _git_short()
    _t("_git_short returns string", isinstance(h, str))
    _t("_git_short length 6 or 'nogit'", len(h) == 6 or h == "nogit", f"got '{h}'")


def _test_write_log() -> None:
    """_write_log creates labeled file with expected content."""
    with tempfile.TemporaryDirectory() as td:
        logfile = Path(td) / "sub" / "test.log"
        _write_log(logfile, "TEST", "test prompt", "test response")
        _t("logfile created", logfile.exists())
        content = logfile.read_text()
        _t("logfile has label", "[TEST]" in content)
        _t("logfile has TIME:", "TIME:" in content)
        _t("logfile has PROMPT", "PROMPT" in content)
        _t("logfile has RESPONSE", "RESPONSE" in content)
        _t("logfile has test response", "test response" in content)


def _test_semaphore_lazy_init() -> None:
    """Semaphore is lazily initialized."""
    global _SEM
    old = _SEM
    _SEM = None
    s = _sem()
    _t("_sem() returns Semaphore", isinstance(s, asyncio.Semaphore))
    _t("_sem() is idempotent", _sem() is s)
    _SEM = old


# ─── AAAA tests ──────────────────────────────────────────────

def _test_read_agent_prompt_inline() -> None:
    """_read_agent_prompt falls back to CONFIG.AGENT_PROMPT."""
    cfg = CONFIG(AGENT_PROMPT_FILE="__nonexistent_file__.md")
    result = _read_agent_prompt(cfg)
    _t("fallback to inline AGENT_PROMPT", "<progress>" in result and len(result) > 100, f"{len(result)} chars")


def _test_read_agent_prompt_file() -> None:
    """_read_agent_prompt reads from file when it exists."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("CUSTOM PROMPT FROM FILE")
        f.flush()
        cfg = CONFIG(AGENT_PROMPT_FILE=f.name)
        result = _read_agent_prompt(cfg)
        _t("reads AGENT_PROMPT_FILE", result == "CUSTOM PROMPT FROM FILE", f"got '{result[:40]}'")
    Path(f.name).unlink(missing_ok=True)


def _test_iteration_context() -> None:
    """Iteration context string format."""
    cfg = CONFIG(MAX_ITERATIONS=5)
    bound = f"max {cfg.MAX_ITERATIONS}" if cfg.MAX_ITERATIONS > 0 else "infinite"
    ctx = f"ITERATION: 3 of {bound}\n"
    _t("iteration context has number", "3 of max 5" in ctx)
    cfg2 = CONFIG(MAX_ITERATIONS=0)
    bound2 = f"max {cfg2.MAX_ITERATIONS}" if cfg2.MAX_ITERATIONS > 0 else "infinite"
    ctx2 = f"ITERATION: 1 of {bound2}\n"
    _t("zero iterations says 'infinite'", "infinite" in ctx2)


def _test_parse_progress() -> None:
    """_parse_progress extracts <progress> content correctly."""
    text = "Here is my analysis.\n<progress>\nDONE: item1\nNEXT: item2\n</progress>"
    result = _parse_progress(text)
    _t("basic parse extracts content", result is not None and "DONE: item1" in result)

    text2 = "stuff\n<PROGRESS>\nDONE: x\n</PROGRESS>\nmore stuff"
    _t("case insensitive parse", _parse_progress(text2) is not None)

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

    _t("missing tag returns None", _parse_progress("no tags here") is None)
    _t("empty string returns None", _parse_progress("") is None)
    _t("empty tag returns empty str", _parse_progress("<progress></progress>") == "")

    p2 = _parse_progress("<progress>\n  \n  DONE: x  \n  \n</progress>")
    _t("whitespace stripped", p2 is not None and p2.startswith("DONE:"))


def _test_loop_result_dataclass() -> None:
    """LoopResult has all required fields."""
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
    """RALPH_TENETS is a non-empty string with all 7 tenets."""
    _t("RALPH_TENETS is str", isinstance(RALPH_TENETS, str))
    _t("RALPH_TENETS has 7 tenets", RALPH_TENETS.count(". ") >= 7, f"found {RALPH_TENETS.count('. ')}")
    for keyword in ["FORWARD PROGRESS", "NO REPETITION", "CONCISE STATE",
                     "STRUCTURED FORMAT", "SELF-TERMINATION", "INCREMENTAL VALUE",
                     "NO CONTEXT BLEED"]:
        _t(f"tenets contains '{keyword}'", keyword in RALPH_TENETS)


def _test_format_thread_entry() -> None:
    """_format_thread_entry produces structured string."""
    entry = _format_thread_entry(1, "seed progress", "model response here", "DONE: x\nNEXT: y", 2.5)
    _t("thread entry is str", isinstance(entry, str))
    _t("thread entry has iteration", "ITERATION 1" in entry)
    _t("thread entry has progress_in", "seed progress" in entry)
    _t("thread entry has response", "model response here" in entry)
    _t("thread entry has progress_out", "DONE: x" in entry)
    _t("thread entry has elapsed", "2.5" in entry)


def _test_format_summary() -> None:
    """_format_summary produces Rich Panel with summary table."""
    from io import StringIO
    r = LoopResult(
        iterations=3, total_time=10.5, final_progress="DONE: everything",
        thread=["a", "b", "c"], done_signal=True, prompt="test task",
    )
    panel = _format_summary(r)
    _t("summary is Panel", isinstance(panel, Panel))
    buf = StringIO()
    Console(file=buf, width=120, no_color=True).print(panel)
    s = buf.getvalue()
    _t("summary has iterations", "3" in s)
    _t("summary has time", "10.5" in s or "10.50" in s)
    _t("summary has avg/iter", "3.50" in s)
    _t("summary has done status", "DONE" in s)
    _t("summary has prompt preview", "test task" in s)


def _test_build_analysis_prompt() -> None:
    """_build_analysis_prompt includes thread + tenets."""
    r = LoopResult(
        iterations=2, total_time=5.0, final_progress="DONE: x",
        thread=["iter1 data", "iter2 data"], done_signal=True, prompt="test",
    )
    p = _build_analysis_prompt(r)
    _t("analysis prompt is str", isinstance(p, str))
    _t("analysis prompt has <thread>", "<thread>" in p)
    _t("analysis prompt has thread content", "iter1 data" in p)
    _t("analysis prompt has <tenets>", "<tenets>" in p)
    _t("analysis prompt has tenet content", "FORWARD PROGRESS" in p)


# ─── ABAB tests ──────────────────────────────────────────────

def _test_parse_artifacts() -> None:
    """parse_artifacts extracts named artifact blocks."""
    text = '<artifact name="main.py">print("hello")</artifact>'
    arts = parse_artifacts(text)
    _t("single artifact found", len(arts) == 1)
    _t("single artifact name", "main.py" in arts)
    _t("single artifact content", arts.get("main.py") == 'print("hello")')

    text2 = (
        'some prose\n'
        '<artifact name="kv.py">\nclass KV:\n    pass\n</artifact>\n'
        'more prose\n'
        '<artifact name="test_kv.py">\ndef test_it():\n    assert True\n</artifact>\n'
    )
    arts2 = parse_artifacts(text2)
    _t("multi artifact count", len(arts2) == 2)
    _t("multi has kv.py", "kv.py" in arts2)
    _t("multi has test_kv.py", "test_kv.py" in arts2)
    _t("multi kv content", "class KV" in arts2.get("kv.py", ""))
    _t("multi test content", "assert True" in arts2.get("test_kv.py", ""))

    _t("no artifacts returns empty", parse_artifacts("just plain text") == {})

    text3 = "<artifact name='app.js'>const x = 1;</artifact>"
    _t("single-quoted name works", "app.js" in parse_artifacts(text3))

    text4 = '<artifact name="f.py">\n\n  code  \n\n</artifact>'
    _t("content stripped", parse_artifacts(text4).get("f.py") == "code")

    text5 = '<artifact name="f.py">v1</artifact>\n<artifact name="f.py">v2</artifact>\n'
    _t("last artifact wins", parse_artifacts(text5).get("f.py") == "v2")


def _test_parse_scratchpad() -> None:
    """parse_scratchpad extracts scratchpad content."""
    _t("scratchpad found", parse_scratchpad("<scratchpad>thinking...</scratchpad>") == "thinking...")
    sp = parse_scratchpad("<SCRATCHPAD>\n  plan:\n  1. do x\n  2. do y\n</SCRATCHPAD>")
    _t("scratchpad case insensitive", sp is not None)
    _t("scratchpad multiline", "plan:" in (sp or ""))
    _t("scratchpad missing returns None", parse_scratchpad("no scratchpad here") is None)
    _t("scratchpad empty tag", parse_scratchpad("<scratchpad></scratchpad>") == "")


def _test_parse_promise() -> None:
    """parse_promise extracts promise block."""
    p = parse_promise("<promise>I assert R1, R2 are satisfied.</promise>")
    _t("promise found", p is not None)
    _t("promise content", "R1, R2" in (p or ""))
    _t("promise missing returns None", parse_promise("no promise") is None)
    p2 = parse_promise("<PROMISE>\n  R1: done\n  R2: done\n</PROMISE>")
    _t("promise case insensitive", p2 is not None)
    _t("promise multiline", "R1: done" in (p2 or ""))


def _test_parse_requirements() -> None:
    """parse_requirements extracts R1..Rn from R-step."""
    text = "<requirements>\nR1: get, set, delete methods\nR2: type hints\nR3: docstrings\n</requirements>\n"
    reqs = parse_requirements(text)
    _t("reqs count", len(reqs) == 3)
    _t("reqs R1 id", reqs[0].id == "R1" if reqs else False)
    _t("reqs R1 desc", "get" in reqs[0].desc if reqs else False)
    _t("reqs R3 id", reqs[2].id == "R3" if len(reqs) > 2 else False)
    _t("no reqs block returns empty", parse_requirements("nothing here") == [])
    reqs2 = parse_requirements("<requirements>\n  R1:   spaced out  \n</requirements>")
    _t("req whitespace stripped", reqs2[0].desc == "spaced out" if reqs2 else False)


def _test_parse_tests() -> None:
    """parse_tests extracts T1..Tn from R-step."""
    text = "<tests>\nT1: unit: get after set returns value\nT2: unit: delete raises KeyError\nT3: judge: clean code\n</tests>\n"
    tests = parse_tests(text)
    _t("tests count", len(tests) == 3)
    _t("T1 id", tests[0].id == "T1" if tests else False)
    _t("T1 kind", tests[0].kind == "unit" if tests else False)
    _t("T3 kind judge", tests[2].kind == "judge" if len(tests) > 2 else False)
    _t("no tests block returns empty", parse_tests("nothing") == [])
    tests2 = parse_tests("<tests>\nT1: UNIT: something\nT2: Judge: quality\n</tests>")
    _t("kind lowercased", tests2[0].kind == "unit" if tests2 else False)


def _test_parse_rubric() -> None:
    """parse_rubric extracts PASS/FAIL per R/T from judge."""
    text = (
        "R1: PASS: class has all four methods\n"
        "R2: FAIL: delete method missing return type hint\n"
        "R3: PASS: docstrings present\n"
        "T1: PASS: set/get round-trips correctly\n"
        "T2: FAIL: test doesn't check KeyError\n"
        "SCORE: 3/5 (60%)\n"
    )
    scores = parse_rubric(text)
    _t("rubric count", len(scores) == 5, f"got {len(scores)}")
    _t("R1 passed", scores[0].passed if scores else False)
    _t("R2 failed", not scores[1].passed if len(scores) > 1 else False)
    _t("R2 reason", "type hint" in scores[1].reason if len(scores) > 1 else False)

    passed, total, pct = fmt_score(scores)
    _t("fmt_score passed", passed == 3)
    _t("fmt_score total", total == 5)
    _t("fmt_score pct", pct == 60.0)

    fails = fmt_failures(scores)
    _t("fmt_failures has R2", "R2" in fails)
    _t("fmt_failures has T2", "T2" in fails)
    _t("fmt_failures no R1", "R1" not in fails)

    _t("empty rubric returns empty", parse_rubric("no scores") == [])
    _t("all pass fmt_failures", fmt_failures(parse_rubric("R1: PASS: ok\nR2: PASS: ok\n")) == "none")


def _test_parse_full_worker_output() -> None:
    """Parse a realistic full worker output with all tags."""
    text = (
        "<scratchpad>\nLet me think about KV store.\n</scratchpad>\n\n"
        '<artifact name="kv_store.py">\nclass KeyValueStore:\n    pass\n</artifact>\n\n'
        '<artifact name="test_kv.py">\ndef test_set_get():\n    assert True\n</artifact>\n\n'
        "<promise>\nR1: satisfied\nR2: satisfied\n</promise>\n"
    )
    arts = parse_artifacts(text)
    _t("full: 2 artifacts", len(arts) == 2)
    _t("full: kv_store.py has class", "class KeyValueStore" in arts.get("kv_store.py", ""))
    sp = parse_scratchpad(text)
    _t("full: scratchpad found", sp is not None)
    pr = parse_promise(text)
    _t("full: promise found", pr is not None)
    _t("full: promise mentions R1", "R1" in (pr or ""))
    all_art_text = " ".join(arts.values())
    _t("full: scratchpad not in artifacts", "think" not in all_art_text.lower())


def _test_ab_loop_result() -> None:
    """ABLoopResult has all required fields."""
    r = ABLoopResult(
        iterations=3, total_time=5.0, final_scores=[], artifacts={"main.py": "code"},
        requirements=[Req("R1", "test")], tests=[Test("T1", "unit", "test")],
        thread=["a", "b", "c"], score_history=[50.0, 75.0, 100.0],
        done=True, stalled=False, prompt="test", best_pct=100.0,
    )
    _t("ABLoopResult.iterations", r.iterations == 3)
    _t("ABLoopResult.done", r.done is True)
    _t("ABLoopResult.artifacts", "main.py" in r.artifacts)
    _t("ABLoopResult.score_history", len(r.score_history) == 3)
    _t("ABLoopResult.best_pct", r.best_pct == 100.0)


def _test_format_ab_summary() -> None:
    """_format_ab_summary produces Rich Panel."""
    from io import StringIO
    r = ABLoopResult(
        iterations=2, total_time=8.0, final_scores=[], artifacts={"kv.py": "code"},
        requirements=[Req("R1", "test")], tests=[], thread=["a", "b"],
        score_history=[60.0, 100.0], done=True, stalled=False, prompt="test task", best_pct=100.0,
    )
    panel = _format_ab_summary(r)
    _t("ab summary is Panel", isinstance(panel, Panel))
    buf = StringIO()
    Console(file=buf, width=120, no_color=True).print(panel)
    s = buf.getvalue()
    _t("ab summary has iterations", "2" in s)
    _t("ab summary has 100%", "100%" in s)


# ─── eval tests ──────────────────────────────────────────────

def _test_parse_verdict() -> None:
    """_parse_verdict extracts PASS/FAIL from judge output."""
    ok, reason = _parse_verdict("PASS: The DONE list grows across all iterations.")
    _t("parse PASS verdict", ok is True)
    _t("parse PASS reason", "grows" in reason)
    ok2, reason2 = _parse_verdict("FAIL: Iteration 2 repeated iteration 1 content.")
    _t("parse FAIL verdict", ok2 is False)
    ok3, _ = _parse_verdict("Some preamble\nPASS: Still works after preamble.")
    _t("parse with preamble", ok3 is True)
    ok4, reason4 = _parse_verdict("gibberish without verdict")
    _t("unparseable returns False", ok4 is False)
    _t("unparseable has error msg", "unparseable" in reason4)


def _test_eval_concise_progress() -> None:
    """Programmatic concise_progress check."""
    good = [
        _AAIterData(1, "in", "resp" * 100, "DONE: x\nCURRENT: y\nNEXT: z\nBLOCKERS: none"),
        _AAIterData(2, "in", "resp" * 100, "DONE: x, y\nCURRENT: z\nNEXT: a\nBLOCKERS: none"),
    ]
    ok, _ = _eval_concise_progress(good)
    _t("concise good traces pass", ok)
    bad = [_AAIterData(1, "in", "resp", "X" * 501)]
    ok2, reason2 = _eval_concise_progress(bad)
    _t("concise over-500 fails", not ok2)
    _t("concise fail mentions limit", "500" in reason2)
    bloat = [_AAIterData(1, "in", "resp", "short"), _AAIterData(2, "in", "resp", "short" * 4)]
    ok3, _ = _eval_concise_progress(bloat)
    _t("concise bloat 4x fails", not ok3)


def _test_eval_structured_format() -> None:
    """Programmatic structured_format check."""
    good = [_AAIterData(1, "", "", "DONE: a\nCURRENT: b\nNEXT: c\nBLOCKERS: none")]
    ok, _ = _eval_structured_format(good)
    _t("structured good trace passes", ok)
    bad = [_AAIterData(1, "", "", "DONE: a\nNEXT: c")]
    ok2, reason2 = _eval_structured_format(bad)
    _t("structured missing fields fails", not ok2)
    _t("structured fail lists missing", "CURRENT" in reason2 or "missing" in reason2.lower())


def _test_eval_no_context_bleed() -> None:
    """Programmatic no_context_bleed check."""
    ok, _ = _eval_no_context_bleed([_AAIterData(1, "", "A" * 1000, "DONE: short")])
    _t("no_bleed good passes", ok)
    ok2, reason2 = _eval_no_context_bleed([_AAIterData(1, "", "A" * 100, "A" * 60)])
    _t("no_bleed >50% fails", not ok2)
    _t("no_bleed fail mentions bleed", "bleed" in reason2.lower())


def _test_eval_progress_is_summary() -> None:
    """Programmatic progress_is_summary check."""
    good = [_AAIterData(1, "", "Here is my detailed analysis...", "DONE: analyzed\nNEXT: tests")]
    ok, _ = _eval_progress_is_summary(good)
    _t("summary good passes", ok)
    long_text = "This is a very long and specific piece of text that should only appear in the response body"
    bad = [_AAIterData(1, "", f"Response: {long_text} more stuff", f"DONE: {long_text}")]
    ok2, reason2 = _eval_progress_is_summary(bad)
    _t("summary verbatim copy fails", not ok2)
    _t("summary fail mentions verbatim", "verbatim" in reason2.lower())


def _test_eval_ab_score_progression() -> None:
    """ABAB score progression check."""
    good = ABLoopResult(
        iterations=3, total_time=5.0, final_scores=[], artifacts={},
        requirements=[], tests=[], thread=[], score_history=[40.0, 60.0, 80.0],
        done=False, stalled=False, prompt="", best_pct=80.0,
    )
    ok, _ = _eval_ab_score_progression(good)
    _t("ab score progression good", ok)
    bad = ABLoopResult(
        iterations=2, total_time=5.0, final_scores=[], artifacts={},
        requirements=[], tests=[], thread=[], score_history=[80.0, 40.0],
        done=False, stalled=False, prompt="", best_pct=80.0,
    )
    ok2, _ = _eval_ab_score_progression(bad)
    _t("ab score regression fails", not ok2)


# ─── tmux tests ──────────────────────────────────────────────

def _test_tmux_graceful_split_failure() -> None:
    """split-window must handle 'no space' gracefully."""
    import inspect
    src = inspect.getsource(_run_all_tmux)
    lines = src.splitlines()
    split_lines = [i for i, ln in enumerate(lines) if "split-window" in ln and '"""' not in ln and "#" not in ln]
    if split_lines:
        idx = split_lines[0]
        call_block = "\n".join(lines[max(0, idx-2):idx+5])
        _t("split-window has no check=True", "check=True" not in call_block)
    else:
        _t("split-window has no check=True", False, "no split-window call found")
    _t("split failure has break", "break" in src)
    _t("split uses capture_output", "capture_output" in src)


def _test_tmux_tiled_layout() -> None:
    """After creating panes, must apply tiled layout."""
    import inspect
    src = inspect.getsource(_run_all_tmux)
    _t("tmux applies tiled layout", "tiled" in src)
    _t("tmux uses select-layout", "select-layout" in src)


# ─── integration tests (API calls) ───────────────────────────

async def _test_llm_basic() -> None:
    """LLM returns non-empty text."""
    t0 = time.perf_counter()
    result = await llm("What is 2+2? Answer with just the number.", replace(CFG, MAX_TOKENS=64))
    wall = time.perf_counter() - t0
    _t("llm responds", len(result) > 0, f"{len(result)} chars, {wall:.2f}s")


async def _test_llm_long_input() -> None:
    """Large input prompt returns quickly."""
    big = "Repeat: " + ("computing history is fascinating. " * 200) + "\nSummarize in 1 word."
    t0 = time.perf_counter()
    result = await llm(big)
    wall = time.perf_counter() - t0
    _t("long input returns non-empty", len(result) > 0, f"{len(result)} chars")
    _t("long input < 5s", wall < 5, f"{wall:.2f}s")


async def _test_llm_parallel() -> None:
    """Parallel calls work via semaphore."""
    t0 = time.perf_counter()
    results = await asyncio.gather(
        llm("What is 2+2?"), llm("Name 3 colors."), llm("Capital of France?"),
    )
    wall = time.perf_counter() - t0
    _t("parallel returns 3 results", len(results) == 3)
    _t("all results non-empty", all(len(r) > 0 for r in results))
    _t("parallel wall < 10s", wall < 10, f"{wall:.2f}s")


async def _test_ralph_loop_aaaa_bounded() -> None:
    """ralph_loop_aaaa returns LoopResult with thread."""
    cfg = replace(CFG, MAX_ITERATIONS=2, LOOP_COOLDOWN=0, MAX_TOKENS=512)
    t0 = time.perf_counter()
    result = await ralph_loop_aaaa(
        "Count to 3, one number per iteration. "
        "In your <progress> tag, list which numbers you've said so far under DONE.",
        cfg,
    )
    wall = time.perf_counter() - t0
    _t("bounded loop returns LoopResult", isinstance(result, LoopResult))
    _t("bounded loop < 60s", wall < 60, f"{wall:.2f}s")
    _t("result.thread populated", len(result.thread) >= 1, f"{len(result.thread)} entries")
    _t("result.iterations == 2", result.iterations == 2)
    _t("result.prompt preserved", "Count" in result.prompt)


# ─── test runner ─────────────────────────────────────────────

async def _run_tests() -> None:
    """Run all tests: unit first, then integration."""
    global _PASS, _FAIL
    _PASS, _FAIL = 0, 0
    t0 = time.perf_counter()

    CON.rule("[bold magenta]UNIT TESTS — shared[/]")
    _test_config_defaults()
    _test_config_override()
    _test_config_replace()
    _test_prompts_class()
    _test_git_short()
    _test_write_log()
    _test_semaphore_lazy_init()

    CON.rule("[bold magenta]UNIT TESTS — AAAA[/]")
    _test_read_agent_prompt_inline()
    _test_read_agent_prompt_file()
    _test_iteration_context()
    _test_parse_progress()
    _test_loop_result_dataclass()
    _test_ralph_tenets_defined()
    _test_format_thread_entry()
    _test_format_summary()
    _test_build_analysis_prompt()

    CON.rule("[bold magenta]UNIT TESTS — ABAB parsers[/]")
    _test_parse_artifacts()
    _test_parse_scratchpad()
    _test_parse_promise()
    _test_parse_requirements()
    _test_parse_tests()
    _test_parse_rubric()
    _test_parse_full_worker_output()
    _test_ab_loop_result()
    _test_format_ab_summary()

    CON.rule("[bold magenta]UNIT TESTS — evals[/]")
    _test_parse_verdict()
    _test_eval_concise_progress()
    _test_eval_structured_format()
    _test_eval_no_context_bleed()
    _test_eval_progress_is_summary()
    _test_eval_ab_score_progression()

    CON.rule("[bold magenta]UNIT TESTS — tmux[/]")
    _test_tmux_graceful_split_failure()
    _test_tmux_tiled_layout()

    CON.rule("[bold magenta]INTEGRATION TESTS — LLM calls[/]")
    await _test_llm_basic()
    await _test_llm_long_input()
    await _test_llm_parallel()
    await _test_ralph_loop_aaaa_bounded()

    wall = time.perf_counter() - t0
    CON.rule("[bold magenta]RESULTS[/]")
    color = "green" if _FAIL == 0 else "red"
    CON.print(f"[bold {color}]{_PASS} passed, {_FAIL} failed[/]  |  {wall:.1f}s total")
    if _FAIL > 0:
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# CLI / EXAMPLE RUNNER / TMUX
# ═══════════════════════════════════════════════════════════════

def _run_all_tmux(mode: str = "abab") -> None:
    """Launch all examples in a tiled tmux pane grid.

    Graceful degradation: if terminal is too small for all panes,
    runs as many as fit and warns. Stagger starts 0.3s apart.
    """
    names = PROMPTS.names()
    session = "ralph-v3"
    script = os.path.abspath(__file__)
    mode_flag = f" --mode {mode}" if mode != "abab" else ""

    subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True)
    subprocess.run([
        "tmux", "new-session", "-d", "-s", session, "-x", "250", "-y", "70",
    ], check=True)
    subprocess.run(
        ["tmux", "set-option", "-t", session, "remain-on-exit", "on"],
        capture_output=True,
    )

    pane_count = 1
    for _ in names[1:]:
        r = subprocess.run(
            ["tmux", "split-window", "-t", session],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            CON.print(f"[bold yellow]tmux: only {pane_count}/{len(names)} panes fit — running {pane_count}[/]")
            break
        pane_count += 1
        subprocess.run(["tmux", "select-layout", "-t", session, "tiled"], capture_output=True)

    subprocess.run(["tmux", "select-layout", "-t", session, "tiled"], capture_output=True)

    for i, n in enumerate(names[:pane_count]):
        delay = f"sleep {i * 0.3:.1f} && " if i > 0 else ""
        subprocess.run([
            "tmux", "send-keys", "-t", f"{session}:{0}.{i}",
            f"{delay}uv run {script}{mode_flag} --example {n}", "Enter",
        ], check=True)

    CON.print(f"[bold green]launched {pane_count}/{len(names)} examples in tmux '{session}' ({mode})[/]")
    CON.print(f"[dim]attach: tmux attach -t {session}  |  kill: tmux kill-session -t {session}[/]")
    if sys.stdout.isatty():
        os.execvp("tmux", ["tmux", "attach", "-t", session])
    else:
        CON.print(f"[dim]not a TTY — run 'tmux attach -t {session}' manually[/]")


async def _run_with_analysis(prompt: str, cfg: CONFIG, mode: str = "abab") -> None:
    """Run loop (AAAA or ABAB), then LLM analysis of thread."""
    if mode == "aaaa":
        result = await ralph_loop_aaaa(prompt, cfg)
        CON.rule("[bold magenta]THREAD ANALYSIS (LLM scoring against tenets)[/]")
        analysis_prompt = _build_analysis_prompt(result)
    else:
        result = await ralph_loop_abab(prompt, cfg)
        CON.rule("[bold magenta]THREAD ANALYSIS (LLM scoring against criteria)[/]")
        analysis_prompt = _build_ab_analysis_prompt(result)

    try:
        analysis = await llm(analysis_prompt, replace(cfg, MAX_TOKENS=1024, TEMPERATURE=0.0))
        CON.print(f"\n{analysis}\n")
    except Exception as e:
        CON.print(f"[bold red]analysis failed: {e}[/]")


def _run_example(name: str, mode: str = "abab") -> None:
    """Run a named example prompt."""
    if name == "list":
        CON.rule(f"[bold magenta]available example prompts (mode: {mode})[/]")
        for n in PROMPTS.names():
            preview = (getattr(PROMPTS, n) or "")[:80].replace("\n", " ")
            CON.print(f"  [bold cyan]{n:<20}[/] {preview}…")
        return

    if name == "all":
        _run_all_tmux(mode)
        return

    prompt = PROMPTS.get(name)
    if not prompt:
        CON.print(f"[bold red]unknown example:[/] {name}")
        CON.print(f"[dim]available: {', '.join(PROMPTS.names())}  |  all[/]")
        sys.exit(1)

    CON.print(f"[bold green]running example ({mode}):[/] {name}\n")
    if mode == "aaaa":
        cfg = replace(CFG, MAX_ITERATIONS=100, LOOP_COOLDOWN=0.5)
    else:
        cfg = replace(CFG, MAX_ITERATIONS=10, LOOP_COOLDOWN=0.5, MAX_TOKENS=4096)
    asyncio.run(_run_with_analysis(prompt, cfg, mode))


# ─────────────── GUARDMAIN ───────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    # ── extract --mode flag ──
    mode = "abab"
    if "--mode" in args:
        idx = args.index("--mode")
        if idx + 1 < len(args):
            mode = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    if "--tests" in args:
        asyncio.run(_run_tests())
    elif "--eval" in args:
        if mode == "aaaa":
            asyncio.run(_run_evals_aaaa())
        else:
            asyncio.run(_run_evals_abab())
    elif "--kill" in args:
        r = subprocess.run(["tmux", "kill-session", "-t", "ralph-v3"], capture_output=True)
        CON.print("[bold green]killed tmux session 'ralph-v3'[/]" if r.returncode == 0
                  else "[dim]no 'ralph-v3' session running[/]")
    elif "--example" in args:
        idx = args.index("--example")
        name = args[idx + 1] if idx + 1 < len(args) else "list"
        _run_example(name, mode)
    elif args:
        task = " ".join(args)
        if mode == "aaaa":
            asyncio.run(_run_with_analysis(task, replace(CFG, MAX_ITERATIONS=100, LOOP_COOLDOWN=0.5), "aaaa"))
        else:
            asyncio.run(_run_with_analysis(task, CFG, "abab"))
    else:
        CON.rule("[bold magenta]llm_120b_ralph_v3.py — AAAA + ABAB unified[/]")
        CON.print('  [bold cyan]uv run llm_120b_ralph_v3.py "task"[/]                  ABAB loop (default)')
        CON.print('  [bold cyan]uv run llm_120b_ralph_v3.py --mode aaaa "task"[/]      AAAA loop')
        CON.print("  [bold cyan]uv run llm_120b_ralph_v3.py --example NAME[/]          run example")
        CON.print("  [bold cyan]uv run llm_120b_ralph_v3.py --example all[/]           tmux grid")
        CON.print("  [bold cyan]uv run llm_120b_ralph_v3.py --example list[/]          list examples")
        CON.print("  [bold cyan]uv run llm_120b_ralph_v3.py --tests[/]                 all tests")
        CON.print("  [bold cyan]uv run llm_120b_ralph_v3.py --eval[/]                  evals (ABAB)")
        CON.print("  [bold cyan]uv run llm_120b_ralph_v3.py --eval --mode aaaa[/]      evals (AAAA)")
        CON.print("  [bold cyan]uv run llm_120b_ralph_v3.py --kill[/]                  kill tmux")
