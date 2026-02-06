#!/usr/bin/env -S uv run --script
"""Fireworks oss120b — v2 ABAB architecture (generator-verifier loop).

**What v2 is that v1 is not:**
  v1 = single loop, LLM self-evaluates via <progress>, declares own DONE.
  v2 = A→B→prog→A loop. Worker (A) produces artifacts. Judge (B) scores
       against a fixed rubric. Harness decides DONE (100% score), not LLM.
       Artifacts persist, scratchpad is ephemeral, context stays bounded.

Usage:
    uv run llm_fw_v2_ABAB.py "your task here"    # run ABAB loop
    uv run llm_fw_v2_ABAB.py --example algorithm # run one example
    uv run llm_fw_v2_ABAB.py --example all       # tmux grid: all 8 in parallel
    uv run llm_fw_v2_ABAB.py --example list      # list available examples
    uv run llm_fw_v2_ABAB.py --tests             # unit + integration tests
    uv run llm_fw_v2_ABAB.py --eval              # full eval run
    uv run llm_fw_v2_ABAB.py --kill              # kill tmux session
    uv run llm_fw_v2_ABAB.py                     # help

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

☑️✅🧪 R1: parse_artifacts — extract named <artifact> blocks from LLM output
  ☑️✅🧪 R1.1: single artifact extraction (name + content)
  ☑️✅🧪 R1.2: multiple artifacts in one response
  ☑️✅🧪 R1.3: empty dict when no artifacts present
  ☑️✅🧪 R1.4: single-quoted and double-quoted name attrs
  ☑️✅🧪 R1.5: content whitespace stripping
  ☑️✅🧪 R1.6: duplicate names → last wins (overwrite)
☑️✅🧪 R2: parse_scratchpad — extract <scratchpad> (ephemeral, discarded)
  ☑️✅🧪 R2.1: basic extraction
  ☑️✅🧪 R2.2: case-insensitive tags
  ☑️✅🧪 R2.3: multiline content
  ☑️✅🧪 R2.4: None for missing, "" for empty tag
☑️✅🧪 R3: parse_promise — extract <promise> block
  ☑️✅🧪 R3.1: basic extraction
  ☑️✅🧪 R3.2: case-insensitive tags
  ☑️✅🧪 R3.3: multiline content
  ☑️✅🧪 R3.4: None for missing
☑️✅🧪 R4: parse_requirements — extract R1..Rn from R-step output
  ☑️✅🧪 R4.1: extracts from <requirements> block
  ☑️✅🧪 R4.2: parses R{n}: desc format per line → Req dataclass
  ☑️✅🧪 R4.3: empty list when no block
  ☑️✅🧪 R4.4: whitespace stripping on desc
☑️✅🧪 R5: parse_tests — extract T1..Tn (unit/judge) from R-step output
  ☑️✅🧪 R5.1: extracts from <tests> block
  ☑️✅🧪 R5.2: parses T{n}: unit|judge: desc format → Test dataclass
  ☑️✅🧪 R5.3: lowercases kind field
  ☑️✅🧪 R5.4: empty list when no block
☑️✅🧪 R6: parse_rubric — extract PASS|FAIL per R/T from judge output
  ☑️✅🧪 R6.1: parses R{n}/T{n}: PASS|FAIL: reason → Score dataclass
  ☑️✅🧪 R6.2: fmt_score computes (passed, total, pct)
  ☑️✅🧪 R6.3: fmt_failures formats only failing scores for injection
  ☑️✅🧪 R6.4: empty list when no scores parseable
☑️✅ R7: ralph_loop_v2 — R→A→B→prog→A architecture
  ☑️✅ R7.1: R-step: one-shot requirement+test extraction via REQ_PROMPT
  ☑️✅ R7.2: A-step: worker produces artifacts + scratchpad + promise
  ☑️✅ R7.3: B-step: judge scores all R/T as PASS|FAIL with reasons
  ☑️✅ R7.4: prog: parse rubric, check 100%, format failures for next A
  ☑️✅ R7.5: failure injection: only failing scores fed back to worker
  ☑️✅ R7.6: graceful handling when judge returns empty/unparseable
☑️✅ R8: Prompt engineering — three distinct role prompts
  ☑️✅ R8.1: REQ_PROMPT instructs structured requirement+test extraction
  ☑️✅ R8.2: WORKER_PROMPT instructs artifact+scratchpad+promise output
  ☑️✅ R8.3: JUDGE_PROMPT instructs per-item PASS|FAIL rubric scoring
☑️✅ R9: Harness-controlled termination (not LLM DONE)
  ☑️✅ R9.1: 100% rubric score → done
  ☑️✅ R9.2: stall detection (score plateau for STALL_LIMIT iters → stop)
  ☑️✅ R9.3: MAX_ITERATIONS hard cap
☑️✅ R10: Context bounding — artifacts persist, scratchpad discarded
  ☑️✅ R10.1: artifacts dict persists across iterations (update/overwrite)
  ☑️✅ R10.2: scratchpad parsed but NOT injected into next iteration
  ☑️✅ R10.3: only artifacts + failures injected (bounded context growth)
☑️✅ R11: CONFIG dataclass — all tunable params in one place
  ☑️✅ R11.1: model/API fields (MODEL, BASE_URL, API_KEY from env)
  ☑️✅ R11.2: generation fields (MAX_TOKENS, TEMPERATURE, STREAM)
  ☑️✅ R11.3: ABAB loop fields (MAX_ITERATIONS, STALL_LIMIT, LOOP_COOLDOWN)
☑️✅ R12: LLM infrastructure (inherited from v1)
  ☑️✅ R12.1: streaming with TTFT measurement
  ☑️✅ R12.2: tenacity exp-backoff retries on rate limit
  ☑️✅ R12.3: asyncio.Semaphore for concurrency control
  ☑️✅ R12.4: Rich console output with color
☑️✅ R13: Per-step logging with absolute paths
  ☑️✅ R13.1: R/A/B step labels + timestamps in logfile
  ☑️✅ R13.2: absolute log path printed to console
☑️✅ R14: CLI interface
  ☑️✅ R14.1: --tests runs unit + integration tests
  ☑️✅ R14.2: --eval runs full ABAB eval (kv-store task)
  ☑️✅ R14.3: positional arg runs ABAB loop with task
  ☑️✅ R14.4: no args shows help
☑️✅🧪 R15: Structured dataclasses for parsed data
  ☑️✅🧪 R15.1: Req(id, desc) for requirements
  ☑️✅🧪 R15.2: Test(id, kind, desc) for acceptance tests
  ☑️✅🧪 R15.3: Score(id, passed, reason) for rubric results
☑️✅ R16: PROMPTS class — 8 progressive examples (tuple format)
  ☑️✅ R16.1: fizzbuzz (trivial), algorithm (easy), bug_hunt (easy-med)
  ☑️✅ R16.2: feature_design (medium), refactor (medium)
  ☑️✅ R16.3: architecture (hard), interpreter (hard)
  ☑️✅ R16.4: full_system (very hard — MANY iters)
  ☑️✅ R16.5: .get(name), .names() classmethods
☑️✅ R17: Example runner + tmux grid
  ☑️✅ R17.1: --example NAME runs single example via ABAB loop
  ☑️✅ R17.2: --example list shows all examples with previews
  ☑️✅ R17.3: --example all launches tmux grid (all 8 in parallel)
  ☑️✅ R17.4: --kill terminates tmux session
  ☑️✅ R17.5: tmux optimized — single layout pass, staggered starts, remain-on-exit
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
    """All knobs for the ABAB loop."""
    # ── model ──
    MODEL: str = "accounts/fireworks/models/gpt-oss-120b"
    BASE_URL: str = "https://api.fireworks.ai/inference/v1"
    API_KEY: str = field(default_factory=lambda: os.environ.get("FIREWORKS_API_KEY", ""))

    # ── generation ──
    MAX_TOKENS: int = 4096
    TEMPERATURE: float = 0.7
    STREAM: bool = True

    # ── rate-limit / concurrency ──
    MAX_CONCURRENT: int = 10
    RPM: int = 60

    # ── retry ──
    MAX_RETRIES: int = 3
    BACKOFF_MIN: float = 1.0
    BACKOFF_MAX: float = 8.0

    # ── ABAB loop ──
    MAX_ITERATIONS: int = 5           # max A→B cycles
    LOOP_COOLDOWN: float = 1.0        # seconds between iterations
    STALL_LIMIT: int = 2              # stop if score doesn't improve for N iters
    AGENT_LOGS_DIR: str = "agent_logs"


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


# ─────────────── GLOBAL SEMAPHORE ─────────────────────────────

_SEM: asyncio.Semaphore | None = None

def _sem() -> asyncio.Semaphore:
    global _SEM
    if _SEM is None:
        _SEM = asyncio.Semaphore(CFG.MAX_CONCURRENT)
    return _SEM

# ─────────────── CLIENT ──────────────────────────────────────

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
    CON.print(f"[bold yellow]→ prompt:[/] {prompt[:120]}{'…' if len(prompt)>120 else ''}")
    return await _call(prompt, cfg)


# ─────────────── PARSERS ─────────────────────────────────────
# TDD: tests written first (see _test_parse_* functions below),
# then these implementations to make them pass.

# ── artifact parser ──────────────────────────────────────────

_ARTIFACT_RE = re.compile(
    r'<artifact\s+name=["\']([^"\']+)["\']\s*>(.*?)</artifact>',
    re.DOTALL | re.IGNORECASE,
)


def parse_artifacts(text: str) -> dict[str, str]:
    """Extract all <artifact name="...">...</artifact> blocks.

    Returns dict mapping artifact name → content (stripped).
    """
    return {m.group(1): m.group(2).strip() for m in _ARTIFACT_RE.finditer(text)}


# ── scratchpad parser ────────────────────────────────────────

_SCRATCHPAD_RE = re.compile(
    r"<scratchpad>(.*?)</scratchpad>", re.DOTALL | re.IGNORECASE,
)


def parse_scratchpad(text: str) -> str | None:
    """Extract <scratchpad> content. None if missing."""
    m = _SCRATCHPAD_RE.search(text)
    return m.group(1).strip() if m else None


# ── promise parser ───────────────────────────────────────────

_PROMISE_RE = re.compile(
    r"<promise>(.*?)</promise>", re.DOTALL | re.IGNORECASE,
)


def parse_promise(text: str) -> str | None:
    """Extract <promise> content. None if missing."""
    m = _PROMISE_RE.search(text)
    return m.group(1).strip() if m else None


# ── requirements parser (from R-step output) ─────────────────

_REQ_BLOCK_RE = re.compile(
    r"<requirements>(.*?)</requirements>", re.DOTALL | re.IGNORECASE,
)
_REQ_LINE_RE = re.compile(r"(R\d+):\s*(.+)")


@dataclass
class Req:
    id: str    # "R1"
    desc: str  # "class has get/set/del/list_keys"


def parse_requirements(text: str) -> list[Req]:
    """Extract requirements from <requirements> block.

    Each line: R1: description
    """
    m = _REQ_BLOCK_RE.search(text)
    if not m:
        return []
    block = m.group(1)
    return [Req(id=lm.group(1), desc=lm.group(2).strip())
            for lm in _REQ_LINE_RE.finditer(block)]


# ── tests parser (from R-step output) ────────────────────────

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
    """Extract tests from <tests> block.

    Each line: T1: unit: description
    """
    m = _TEST_BLOCK_RE.search(text)
    if not m:
        return []
    block = m.group(1)
    return [Test(id=lm.group(1), kind=lm.group(2).lower(), desc=lm.group(3).strip())
            for lm in _TEST_LINE_RE.finditer(block)]


# ── rubric / score parser (from judge output) ────────────────

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


# ─────────────── PROMPTS ─────────────────────────────────────

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

JUDGE_PROMPT = (
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


# ─────────────── HELPERS ─────────────────────────────────────

def _git_short(n: int = 6) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", f"--short={n}", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        return "nogit"


def _write_log(logfile: Path, label: str, prompt: str, result: str) -> None:
    logfile.parent.mkdir(parents=True, exist_ok=True)
    with logfile.open("a") as f:
        f.write(f"\n{'='*72}\n")
        f.write(f"[{label}] TIME: {datetime.now().isoformat()}\n")
        f.write(f"PROMPT ({len(prompt)} chars):\n{prompt[:800]}{'…' if len(prompt)>800 else ''}\n")
        f.write(f"{'─'*72}\n")
        f.write(f"RESPONSE ({len(result)} chars):\n{result}\n")
    CON.print(f"[dim]logged → {logfile.resolve()}[/]")


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


# ─────────────── ABAB LOOP ───────────────────────────────────

async def ralph_loop_v2(task: str, cfg: CONFIG = CFG) -> tuple[list[Score], dict[str, str]]:
    """The ABAB loop: R → (A → B → prog)* → done.

    Returns (final_scores, final_artifacts).
    """
    CON.rule("[bold magenta]ralph v2 — ABAB loop (generator-verifier)[/]")
    CON.print(f"[bold yellow]task:[/] {task}")
    CON.print(f"[dim]max iters: {cfg.MAX_ITERATIONS}  |  stall limit: {cfg.STALL_LIMIT}  |  cooldown: {cfg.LOOP_COOLDOWN}s[/]\n")

    commit = _git_short()
    logfile = Path(cfg.AGENT_LOGS_DIR) / f"abab_{commit}_{int(time.time())}.log"

    # ── STEP R: Extract requirements + tests (one-shot) ──
    CON.rule("[bold cyan]R: REQUIREMENT EXTRACTION[/]")
    req_prompt = f"{REQ_PROMPT}\nTASK:\n{task}"
    req_cfg = CONFIG(MAX_TOKENS=1024, TEMPERATURE=0.3)
    req_raw = await llm(req_prompt, req_cfg)
    _write_log(logfile, "R-STEP", req_prompt, req_raw)

    reqs = parse_requirements(req_raw)
    tests = parse_tests(req_raw)

    if not reqs:
        CON.print("[bold red]R-step failed to extract requirements — cannot continue[/]")
        return ([], {})

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

    for iteration in range(1, cfg.MAX_ITERATIONS + 1):
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

        worker_cfg = CONFIG(MAX_TOKENS=cfg.MAX_TOKENS, TEMPERATURE=0.7)
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
            f"{JUDGE_PROMPT}\n"
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

        judge_cfg = CONFIG(MAX_TOKENS=1024, TEMPERATURE=0.0)
        judge_raw = await llm(judge_prompt, judge_cfg)
        _write_log(logfile, f"B-STEP-{iteration}", judge_prompt, judge_raw)

        # ── PROG: parse scores ──
        scores = parse_rubric(judge_raw)
        final_scores = scores

        if not scores:
            CON.print("[bold red]judge returned no parseable scores — retrying next iteration[/]")
            failures_str = "judge output was unparseable — re-do your work and try again"
            continue

        passed, total, pct = fmt_score(scores)
        color = "green" if pct == 100 else "yellow" if pct >= 60 else "red"
        CON.print(f"\n[bold {color}]SCORE: {passed}/{total} ({pct:.0f}%)[/]")

        for s in scores:
            tag = "[green]PASS[/]" if s.passed else "[red]FAIL[/]"
            CON.print(f"  {tag} {s.id}: {s.reason}")

        # ── 100%? done ──
        if pct == 100:
            CON.rule(f"[bold green]100% — all requirements satisfied after {iteration} iterations[/]")
            break

        # ── stall detection ──
        if pct <= best_pct:
            stall_count += 1
            if stall_count >= cfg.STALL_LIMIT:
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

    # ── final summary ──
    CON.rule("[bold magenta]FINAL ARTIFACTS[/]")
    for name, content in artifacts.items():
        CON.print(f"[bold cyan]{name}[/] ({len(content)} chars)")

    CON.print(f"\n[dim]full log → {logfile.resolve()}[/]")
    return (final_scores, artifacts)


# ─────────────── TESTS ───────────────────────────────────────
# TDD: these were written BEFORE the parsers.

_PASS = 0
_FAIL = 0


def _t(name: str, ok: bool, detail: str = "") -> bool:
    global _PASS, _FAIL
    tag = "[bold green]PASS[/]" if ok else "[bold red]FAIL[/]"
    suffix = f"  [dim]{detail}[/]" if detail else ""
    CON.print(f"  {tag}  {name}{suffix}")
    if ok:
        _PASS += 1
    else:
        _FAIL += 1
    return ok


# ─── R1: parse_artifacts ─────────────────────────────────────

def _test_parse_artifacts() -> None:
    """R1: parse_artifacts extracts named artifact blocks."""
    # ── single artifact ──
    text = '<artifact name="main.py">print("hello")</artifact>'
    arts = parse_artifacts(text)
    _t("single artifact found", len(arts) == 1)
    _t("single artifact name", "main.py" in arts)
    _t("single artifact content", arts.get("main.py") == 'print("hello")')

    # ── multiple artifacts ──
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

    # ── no artifacts ──
    _t("no artifacts returns empty", parse_artifacts("just plain text") == {})

    # ── single-quoted name ──
    text3 = "<artifact name='app.js'>const x = 1;</artifact>"
    arts3 = parse_artifacts(text3)
    _t("single-quoted name works", "app.js" in arts3)

    # ── content stripping ──
    text4 = '<artifact name="f.py">\n\n  code  \n\n</artifact>'
    _t("content stripped", parse_artifacts(text4).get("f.py") == "code")

    # ── overwrites: last wins ──
    text5 = (
        '<artifact name="f.py">v1</artifact>\n'
        '<artifact name="f.py">v2</artifact>\n'
    )
    _t("last artifact wins", parse_artifacts(text5).get("f.py") == "v2")


# ─── R2: parse_scratchpad ────────────────────────────────────

def _test_parse_scratchpad() -> None:
    """R2: parse_scratchpad extracts scratchpad content."""
    text = "<scratchpad>thinking about the problem...</scratchpad>"
    _t("scratchpad found", parse_scratchpad(text) == "thinking about the problem...")

    text2 = "<SCRATCHPAD>\n  plan:\n  1. do x\n  2. do y\n</SCRATCHPAD>"
    sp = parse_scratchpad(text2)
    _t("scratchpad case insensitive", sp is not None)
    _t("scratchpad multiline", "plan:" in (sp or ""))

    _t("scratchpad missing returns None", parse_scratchpad("no scratchpad here") is None)
    _t("scratchpad empty tag", parse_scratchpad("<scratchpad></scratchpad>") == "")


# ─── R3: parse_promise ───────────────────────────────────────

def _test_parse_promise() -> None:
    """R3: parse_promise extracts promise block."""
    text = "<promise>I assert R1, R2 are satisfied. T1, T2 should pass.</promise>"
    p = parse_promise(text)
    _t("promise found", p is not None)
    _t("promise content", "R1, R2" in (p or ""))

    _t("promise missing returns None", parse_promise("no promise") is None)

    text2 = "<PROMISE>\n  R1: done\n  R2: done\n  T1: passes\n</PROMISE>"
    p2 = parse_promise(text2)
    _t("promise case insensitive", p2 is not None)
    _t("promise multiline", "R1: done" in (p2 or ""))


# ─── R4: parse_requirements ──────────────────────────────────

def _test_parse_requirements() -> None:
    """R4: parse_requirements extracts R1..Rn from R-step."""
    text = (
        "<requirements>\n"
        "R1: class has get, set, delete, list_keys methods\n"
        "R2: all methods have type hints\n"
        "R3: docstrings on all public methods\n"
        "</requirements>\n"
    )
    reqs = parse_requirements(text)
    _t("reqs count", len(reqs) == 3)
    _t("reqs R1 id", reqs[0].id == "R1" if reqs else False)
    _t("reqs R1 desc", "get" in reqs[0].desc if reqs else False)
    _t("reqs R3 id", reqs[2].id == "R3" if len(reqs) > 2 else False)

    # ── no block ──
    _t("no reqs block returns empty", parse_requirements("nothing here") == [])

    # ── extra whitespace ──
    text2 = "<requirements>\n  R1:   spaced out  \n</requirements>"
    reqs2 = parse_requirements(text2)
    _t("req whitespace stripped", reqs2[0].desc == "spaced out" if reqs2 else False)


# ─── R5: parse_tests ─────────────────────────────────────────

def _test_parse_tests() -> None:
    """R5: parse_tests extracts T1..Tn from R-step."""
    text = (
        "<tests>\n"
        "T1: unit: get after set returns stored value\n"
        "T2: unit: delete raises KeyError for missing key\n"
        "T3: judge: code is clean and idiomatic Python\n"
        "</tests>\n"
    )
    tests = parse_tests(text)
    _t("tests count", len(tests) == 3)
    _t("T1 id", tests[0].id == "T1" if tests else False)
    _t("T1 kind", tests[0].kind == "unit" if tests else False)
    _t("T1 desc", "set returns" in tests[0].desc if tests else False)
    _t("T3 kind judge", tests[2].kind == "judge" if len(tests) > 2 else False)

    _t("no tests block returns empty", parse_tests("nothing") == [])

    # ── case insensitive kind ──
    text2 = "<tests>\nT1: UNIT: something\nT2: Judge: quality\n</tests>"
    tests2 = parse_tests(text2)
    _t("kind lowercased", tests2[0].kind == "unit" if tests2 else False)
    _t("judge lowercased", tests2[1].kind == "judge" if len(tests2) > 1 else False)


# ─── R6: parse_rubric ────────────────────────────────────────

def _test_parse_rubric() -> None:
    """R6: parse_rubric extracts PASS/FAIL per R/T from judge."""
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
    _t("T2 failed", not scores[4].passed if len(scores) > 4 else False)

    # ── fmt_score ──
    passed, total, pct = fmt_score(scores)
    _t("fmt_score passed", passed == 3)
    _t("fmt_score total", total == 5)
    _t("fmt_score pct", pct == 60.0)

    # ── fmt_failures ──
    fails = fmt_failures(scores)
    _t("fmt_failures has R2", "R2" in fails)
    _t("fmt_failures has T2", "T2" in fails)
    _t("fmt_failures no R1", "R1" not in fails)

    # ── empty ──
    _t("empty rubric returns empty", parse_rubric("no scores") == [])

    # ── all pass ──
    all_pass = parse_rubric("R1: PASS: ok\nR2: PASS: ok\n")
    _t("all pass fmt_failures", fmt_failures(all_pass) == "none")


# ─── extra: combined parse test ──────────────────────────────

def _test_parse_full_worker_output() -> None:
    """Parse a realistic full worker output with all tags."""
    text = (
        "<scratchpad>\n"
        "Let me think about the KV store design.\n"
        "I need get, set, delete, list_keys.\n"
        "</scratchpad>\n\n"
        '<artifact name="kv_store.py">\n'
        "from typing import Any\n\n"
        "class KeyValueStore:\n"
        "    def __init__(self) -> None:\n"
        "        self._store: dict[str, Any] = {}\n\n"
        "    def get(self, key: str) -> Any:\n"
        "        return self._store[key]\n\n"
        "    def set(self, key: str, value: Any) -> None:\n"
        "        self._store[key] = value\n\n"
        "    def delete(self, key: str) -> None:\n"
        "        del self._store[key]\n\n"
        "    def list_keys(self) -> list[str]:\n"
        "        return list(self._store.keys())\n"
        "</artifact>\n\n"
        '<artifact name="test_kv.py">\n'
        "def test_set_get():\n"
        "    s = KeyValueStore()\n"
        "    s.set('a', 1)\n"
        "    assert s.get('a') == 1\n"
        "</artifact>\n\n"
        "<promise>\n"
        "R1: satisfied — class has all 4 methods\n"
        "R2: satisfied — type hints present\n"
        "T1: should pass\n"
        "</promise>\n"
    )

    arts = parse_artifacts(text)
    _t("full: 2 artifacts", len(arts) == 2)
    _t("full: kv_store.py has class", "class KeyValueStore" in arts.get("kv_store.py", ""))
    _t("full: test_kv.py has test", "def test_set_get" in arts.get("test_kv.py", ""))

    sp = parse_scratchpad(text)
    _t("full: scratchpad found", sp is not None)
    _t("full: scratchpad has thinking", "think" in (sp or "").lower())

    pr = parse_promise(text)
    _t("full: promise found", pr is not None)
    _t("full: promise mentions R1", "R1" in (pr or ""))

    # ── verify scratchpad is NOT in artifacts ──
    all_art_text = " ".join(arts.values())
    _t("full: scratchpad not in artifacts", "think about" not in all_art_text)


# ─── config tests ────────────────────────────────────────────

def _test_config_v2() -> None:
    """CONFIG v2 fields."""
    c = CONFIG()
    _t("STALL_LIMIT default 2", c.STALL_LIMIT == 2)
    _t("MAX_ITERATIONS default 5", c.MAX_ITERATIONS == 5)
    c2 = CONFIG(STALL_LIMIT=3, MAX_ITERATIONS=10)
    _t("STALL_LIMIT override", c2.STALL_LIMIT == 3)
    _t("MAX_ITERATIONS override", c2.MAX_ITERATIONS == 10)


def _test_prompts_v2() -> None:
    """R16: PROMPTS class has 8 entries and lookup works."""
    names = PROMPTS.names()
    _t("PROMPTS has 8 entries", len(names) == 8, f"found {len(names)}")
    _t("PROMPTS.get('fizzbuzz') returns str", isinstance(PROMPTS.get("fizzbuzz"), str))
    _t("PROMPTS.get('full_system') returns str", isinstance(PROMPTS.get("full_system"), str))
    _t("PROMPTS.get('nonexistent') returns None", PROMPTS.get("nonexistent") is None)
    for n in names:
        val = PROMPTS.get(n)
        _t(f"PROMPTS.{n} is non-empty str", isinstance(val, str) and len(val) > 20, f"{len(val or '')} chars")


# ─── test runner ──────────────────────────────────────────────

async def _run_tests() -> None:
    global _PASS, _FAIL
    _PASS, _FAIL = 0, 0
    t0 = time.perf_counter()

    CON.rule("[bold magenta]UNIT TESTS — v2 ABAB parsers[/]")
    _test_parse_artifacts()
    _test_parse_scratchpad()
    _test_parse_promise()
    _test_parse_requirements()
    _test_parse_tests()
    _test_parse_rubric()
    _test_parse_full_worker_output()
    _test_config_v2()
    _test_prompts_v2()

    CON.rule("[bold magenta]INTEGRATION TESTS — LLM calls[/]")
    # quick smoke test: LLM responds
    t1 = time.perf_counter()
    result = await llm("What is 2+2? Answer with just the number.", CONFIG(MAX_TOKENS=64))
    wall = time.perf_counter() - t1
    _t("llm responds", len(result) > 0, f"{len(result)} chars, {wall:.2f}s")

    wall = time.perf_counter() - t0
    CON.rule("[bold magenta]RESULTS[/]")
    color = "green" if _FAIL == 0 else "red"
    CON.print(f"[bold {color}]{_PASS} passed, {_FAIL} failed[/]  |  {wall:.1f}s total")
    if _FAIL > 0:
        sys.exit(1)


# ─────────────── EXAMPLE RUNNER / TMUX ────────────────────────

def _run_all_tmux() -> None:
    """Launch all examples in separate tmux windows (one per example).

    Uses windows (tabs) instead of panes to avoid 'no space for new pane'
    when terminal is too small for 8 splits. Each example gets a full-size
    terminal. Navigate: Ctrl-b n (next) / Ctrl-b p (prev).
    Stagger starts 0.3s apart to avoid rate-limit burst.
    """
    names = PROMPTS.names()
    session = "ralph-v2-all"
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
        CON.print(f"[dim]not a TTY — run 'tmux attach -t {session}' manually[/]")


def _run_example(name: str) -> None:
    """Run a named example through the ABAB loop."""
    if name == "list":
        CON.rule("[bold magenta]available example prompts (v2 ABAB)[/]")
        for n in PROMPTS.names():
            preview = (getattr(PROMPTS, n) or "")[:80].replace("\n", " ")
            CON.print(f"  [bold cyan]{n:<20}[/] {preview}…")
        return

    if name == "all":
        _run_all_tmux()
        return

    prompt = PROMPTS.get(name)
    if not prompt:
        CON.print(f"[bold red]unknown example:[/] {name}")
        CON.print(f"[dim]available: {', '.join(PROMPTS.names())}  |  all[/]")
        sys.exit(1)

    CON.print(f"[bold green]running example (v2 ABAB):[/] {name}\n")
    cfg = CONFIG(MAX_ITERATIONS=10, LOOP_COOLDOWN=0.5, MAX_TOKENS=4096)
    asyncio.run(ralph_loop_v2(prompt, cfg))


# ─────────────── GUARDMAIN ───────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--tests":
        asyncio.run(_run_tests())
    elif len(sys.argv) > 1 and sys.argv[1] == "--eval":
        async def _eval():
            cfg = CONFIG(MAX_ITERATIONS=3, LOOP_COOLDOWN=0.5, MAX_TOKENS=4096)
            scores, arts = await ralph_loop_v2(
                "Design a simple key-value store in Python.\n"
                "1. Define the API: get, set, delete, list_keys.\n"
                "2. Write the class with type hints.\n"
                "3. Write 3 pytest tests.\n"
                "4. Review and suggest improvements.",
                cfg,
            )
            if scores:
                p, t, pct = fmt_score(scores)
                CON.print(f"\n[bold]EVAL RESULT: {p}/{t} ({pct:.0f}%)[/]")
        asyncio.run(_eval())
    elif len(sys.argv) > 1 and sys.argv[1] == "--kill":
        r = subprocess.run(["tmux", "kill-session", "-t", "ralph-v2-all"], capture_output=True)
        CON.print("[bold green]killed tmux session 'ralph-v2-all'[/]" if r.returncode == 0
                  else "[dim]no 'ralph-v2-all' session running[/]")
    elif len(sys.argv) > 1 and sys.argv[1] == "--example":
        name = sys.argv[2] if len(sys.argv) > 2 else "list"
        _run_example(name)
    elif len(sys.argv) > 1:
        asyncio.run(ralph_loop_v2(" ".join(sys.argv[1:])))
    else:
        CON.rule("[bold magenta]llm_fw_v2_ABAB.py — Fireworks oss120b (ABAB loop)[/]")
        CON.print('  [bold cyan]uv run llm_fw_v2_ABAB.py "task"[/]          ABAB loop')
        CON.print("  [bold cyan]uv run llm_fw_v2_ABAB.py --example NAME[/]  run example")
        CON.print("  [bold cyan]uv run llm_fw_v2_ABAB.py --example all[/]   tmux grid: all 8 in parallel")
        CON.print("  [bold cyan]uv run llm_fw_v2_ABAB.py --example list[/]  list examples")
        CON.print("  [bold cyan]uv run llm_fw_v2_ABAB.py --tests[/]         run all tests")
        CON.print("  [bold cyan]uv run llm_fw_v2_ABAB.py --eval[/]          eval run (kv-store task)")
        CON.print("  [bold cyan]uv run llm_fw_v2_ABAB.py --kill[/]          kill tmux session")
