# Ralph System Design for Long-Running Agents (Claude)

## Overview

Ralph is a **file-based agent loop** that treats git + files as memory instead of model context. Each iteration starts fresh, reads the same on-disk state, and commits work for exactly one story at a time.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           RALPH LOOP ARCHITECTURE                            │
└──────────────────────────────────────────────────────────────────────────────┘

                              ┌─────────────────┐
                              │   ralph CLI     │
                              │  (orchestrator) │
                              └────────┬────────┘
                                       │
                                       ▼
                         ┌─────────────────────────┐
                         │     Agent Runner        │
                         │ codex | claude | droid  │
                         └─────────────┬───────────┘
                                       │
               ┌───────────────────────┼───────────────────────┐
               │                       │                       │
               ▼                       ▼                       ▼
    ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
    │ .agents/ralph/   │    │ .agents/tasks/   │    │    .ralph/       │
    │ (templates)      │    │ (PRD JSON)       │    │    (state)       │
    │                  │    │                  │    │                  │
    │ • loop.sh        │    │ • prd-*.json     │    │ • progress.md    │
    │ • PROMPT_build   │    │   - stories[]    │    │ • guardrails.md  │
    │ • config.sh      │    │   - qualityGates │    │ • errors.log     │
    │ • references/    │    │   - status       │    │ • activity.log   │
    └──────────────────┘    └──────────────────┘    │ • runs/          │
                                                    └──────────────────┘
```

---

## The Core Loop

```
                           ┌──────────────────┐
                           │  ralph build N   │
                           └────────┬─────────┘
                                    │
                          /─────────┴─────────\
                         <     PRD exists?     >
                          \─────────┬─────────/
                                    │
                       no ──────────┴────────── yes
           ┌──────────────────────┐        ┌──────────────────────┐
           │ ralph prd 'desc'     │        │  Start Iteration i   │
           └──────────┬───────────┘        └──────────┬───────────┘
                      │                               │
                      └───────────────┬───────────────┘
                                      │
                                      ▼
                      ┌───────────────────────────────┐
                      │        select_story           │
                      │   (status=open, deps met)     │
                      └───────────────┬───────────────┘
                                      │
                            /─────────┴─────────\
                           <    Story found?     >
                            \─────────┬─────────/
                                      │
               no (blocked) ──────────┼────────── yes
           ┌─────────────────────┐    │    ┌─────────────────────┐
           │   EXIT: Blocked     │    │    │ Set status=in_prog  │
           └─────────────────────┘    │    │ startedAt=now       │
                                      │    └──────────┬──────────┘
                no (all done) ────────┘               │
           ┌─────────────────────┐         ┌──────────▼──────────┐
           │ EXIT: All complete  │         │ Render PROMPT_build │
           └─────────────────────┘         └──────────┬──────────┘
                                                      │
                                           ┌──────────▼──────────┐
                                           │  Invoke agent CLI   │
                                           │  (claude -p ...)    │
                                           └──────────┬──────────┘
                                                      │
                                           ┌──────────▼──────────┐
                                           │   Agent executes:   │
                                           │   1. Guardrails     │
                                           │   2. Errors log     │
                                           │   3. Implement      │
                                           │   4. Quality gates  │
                                           │   5. Commit         │
                                           │   6. Progress.md    │
                                           └──────────┬──────────┘
                                                      │
                                            /─────────┴─────────\
                                           <  COMPLETE signal?   >
                                            \─────────┬─────────/
                                                      │
                                         no ──────────┴────────── yes
                               ┌─────────────────────┐    ┌─────────────────────┐
                               │   Set status=open   │    │   Set status=done   │
                               └──────────┬──────────┘    └──────────┬──────────┘
                                          │                          │
                                          └───────────┬──────────────┘
                                                      │
                                            /─────────┴─────────\
                                           < Stories remaining?  >
                                            \─────────┬─────────/
                                                      │
                      no ──────────── i < N ──────────┼──────────── i >= N
           ┌───────────────────┐    ┌─────────────────▼─┐    ┌───────────────────┐
           │ EXIT: All complete│    │ Start Iteration i │    │ EXIT: Max reached │
           └───────────────────┘    └───────────────────┘    └───────────────────┘
```

---

## The Rules (Non-Negotiable)

### 1. ONE Story Per Context Window

```
┌──────────────────────────────────────────────────────────────────┐
│  RULE: Never work on multiple stories in a single invocation    │
│                                                                  │
│  WHY:                                                            │
│  • Fresh context = fresh perspective = fewer errors              │
│  • One commit per story = easy rollback                          │
│  • Verifiable progress: done or not done, no "partial"           │
│  • Reduced cognitive drift over long sessions                    │
└──────────────────────────────────────────────────────────────────┘
```

### 2. Files Are Memory

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  MEMORY LAYER           │  PURPOSE                    │  PERSISTENCE        │
├─────────────────────────┼─────────────────────────────┼─────────────────────┤
│  progress.md            │  What happened each run     │  Append-only        │
│  guardrails.md          │  Lessons learned (Signs)    │  Grows over time    │
│  errors.log             │  Repeated failures          │  For pattern detect │
│  activity.log           │  Timing + events            │  Audit trail        │
│  prd.json               │  Story definitions + status │  Source of truth    │
│  git commits            │  Code changes               │  Permanent          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3. Quality Gates Before Commit

```
┌──────────────────────────────────────────────────────────────────┐
│  GLOBAL GATES (from PRD qualityGates[]):                        │
│  • Build passes: npm run build / cargo build                    │
│  • Tests pass: npm test / cargo test                            │
│  • Lint clean: eslint / clippy                                  │
│  • Type check: tsc --noEmit                                     │
│                                                                  │
│  STORY GATES (from story.acceptanceCriteria[]):                 │
│  • Specific verification steps                                  │
│  • Browser testing for UI changes                               │
│  • API endpoint tests                                           │
│                                                                  │
│  ALL MUST PASS before <promise>COMPLETE</promise>               │
└──────────────────────────────────────────────────────────────────┘
```

### 4. Guardrails (Signs) Pattern

```
┌──────────────────────────────────────────────────────────────────┐
│  SIGN FORMAT (in guardrails.md):                                │
│                                                                  │
│  ### Sign: [Name]                                               │
│  - **Trigger**: When this situation occurs                      │
│  - **Instruction**: What to do instead                          │
│  - **Added after**: [Failure that caused this]                  │
│                                                                  │
│  EXAMPLE:                                                        │
│  ### Sign: Read Before Writing                                  │
│  - **Trigger**: Before modifying any file                       │
│  - **Instruction**: Read the file first to understand context   │
│  - **Added after**: Blind edits broke existing functionality    │
└──────────────────────────────────────────────────────────────────┘
```

### 5. Completion Signal

```
┌──────────────────────────────────────────────────────────────────┐
│  OUTPUT EXACTLY THIS when story is fully complete:              │
│                                                                  │
│  <promise>COMPLETE</promise>                                    │
│                                                                  │
│  DO NOT OUTPUT if:                                              │
│  • Quality gates failed                                         │
│  • Acceptance criteria not met                                  │
│  • Uncommitted changes remain                                   │
│  • Any verification step failed                                 │
│                                                                  │
│  The loop uses grep to detect this signal.                      │
└──────────────────────────────────────────────────────────────────┘
```

---

## Using Ralph with Claude Code

### Installation

```bash
# Install Ralph globally
npm i -g @iannuttall/ralph

# In your project, initialize
ralph install              # Creates .agents/ralph/
ralph install --skills     # Installs commit, prd, dev-browser skills

# Select Claude as runner
# Edit .agents/ralph/config.sh:
AGENT_CMD="claude -p --dangerously-skip-permissions \"\$(cat {prompt})\""
```

### Claude Code Specific Config

```bash
# .agents/ralph/config.sh

# Use Claude Code as the agent runner
AGENT_CMD="claude -p --dangerously-skip-permissions \"\$(cat {prompt})\""

# For PRD generation (can use different model)
PRD_AGENT_CMD="claude -p --dangerously-skip-permissions \"\$(cat {prompt})\""

# Quality gates
MAX_ITERATIONS=25
STALE_SECONDS=3600  # Reset stuck stories after 1 hour

# No auto-push (safety)
NO_COMMIT=false  # Commits locally, doesn't push
```

### Running

```bash
# Generate PRD from description
ralph prd "A CLI tool that converts markdown to PDF with syntax highlighting"

# Run one iteration (human-in-the-loop)
ralph build 1

# Run N iterations (semi-autonomous)
ralph build 10

# Dry run (no commits)
ralph build 1 --no-commit
```

---

## PRD JSON Format

```json
{
  "version": 1,
  "project": "md2pdf",
  "description": "CLI tool to convert markdown to PDF",
  "qualityGates": [
    "npm run build must pass",
    "npm test must pass",
    "npm run lint must pass"
  ],
  "stories": [
    {
      "id": "S001",
      "title": "Parse markdown input",
      "description": "Accept markdown file path or stdin, parse to AST",
      "status": "open",
      "dependsOn": [],
      "acceptanceCriteria": [
        "Reads .md file from path argument",
        "Reads from stdin if no path given",
        "Outputs parsed AST to stdout with --debug flag"
      ]
    },
    {
      "id": "S002",
      "title": "Render to PDF",
      "description": "Convert parsed AST to PDF using puppeteer",
      "status": "open",
      "dependsOn": ["S001"],
      "acceptanceCriteria": [
        "Generates valid PDF file",
        "Respects --output flag for destination",
        "Default output is input-name.pdf"
      ]
    },
    {
      "id": "S003",
      "title": "Syntax highlighting",
      "description": "Add code block highlighting with highlight.js",
      "status": "open",
      "dependsOn": ["S002"],
      "acceptanceCriteria": [
        "Code blocks render with syntax colors",
        "Supports --theme flag (github, monokai, etc)",
        "Default theme is github"
      ]
    }
  ]
}
```

---

## Example: Toy Repo Progression

### Iteration 1: S001 (Parse markdown)

```
═══════════════════════════════════════════════════════
  Ralph Iteration 1 of 10
═══════════════════════════════════════════════════════

Selected story: S001 - Parse markdown input

Agent actions:
1. Read guardrails.md (core signs)
2. Read errors.log (empty)
3. npm init -y
4. npm install unified remark-parse
5. Create src/parser.ts
6. Create src/cli.ts
7. npm run build -> PASS
8. npm test -> PASS (created test)
9. git add -A && git commit "feat: add markdown parser (S001)"
10. Append to progress.md

Output: <promise>COMPLETE</promise>

PRD updated: S001.status = "done"
```

### Iteration 2: S002 (Render to PDF)

```
═══════════════════════════════════════════════════════
  Ralph Iteration 2 of 10
═══════════════════════════════════════════════════════

Selected story: S002 - Render to PDF
(S001 is done, so deps are met)

Agent actions:
1. Read guardrails.md
2. Read errors.log
3. Read progress.md (learns parser structure)
4. npm install puppeteer
5. Create src/renderer.ts
6. Update src/cli.ts with --output flag
7. npm run build -> PASS
8. npm test -> PASS
9. Manual test: echo "# Test" | node dist/cli.js -> PDF created
10. git commit "feat: add PDF rendering (S002)"
11. Append to progress.md

Output: <promise>COMPLETE</promise>

PRD updated: S002.status = "done"
```

### Iteration 3: S003 (Syntax highlighting) - FAILURE

```
═══════════════════════════════════════════════════════
  Ralph Iteration 3 of 10
═══════════════════════════════════════════════════════

Selected story: S003 - Syntax highlighting

Agent actions:
1. Read guardrails.md
2. npm install highlight.js
3. Update renderer to inject highlight.js
4. npm run build -> FAIL (type error)
5. Fix types
6. npm run build -> PASS
7. npm test -> FAIL (snapshot mismatch)

NO COMPLETION SIGNAL (tests failed)

PRD updated: S003.status = "open" (reset for retry)
Errors logged: "S003 failed - snapshot mismatch on code block colors"
```

### Iteration 4: S003 (Retry with learning)

```
═══════════════════════════════════════════════════════
  Ralph Iteration 4 of 10
═══════════════════════════════════════════════════════

Selected story: S003 - Syntax highlighting (retry)

Agent actions:
1. Read guardrails.md
2. Read errors.log -> sees snapshot issue
3. Read progress.md -> understands prior attempt
4. Update snapshots after verifying output correct
5. npm test -> PASS
6. Add guardrail: "Sign: Update Snapshots After Visual Changes"
7. git commit "feat: add syntax highlighting (S003)"

Output: <promise>COMPLETE</promise>

Stories remaining: 0
EXIT: All stories complete
```

---

## State File Examples

### progress.md (append-only)

```markdown
# Progress Log
Started: 2026-01-29 10:00:00

## Codebase Patterns
- Uses TypeScript with strict mode
- Tests use vitest
- Entry point is src/cli.ts

---

## [2026-01-29 10:05:23] - S001: Parse markdown input
Run: 20260129-100500-12345 (iteration 1)
- Guardrails reviewed: yes
- Commit: a1b2c3d feat: add markdown parser (S001)
- Post-commit status: clean
- Verification:
  - Command: npm run build -> PASS
  - Command: npm test -> PASS
- Files changed:
  - src/parser.ts
  - src/cli.ts
  - package.json
- **Learnings:**
  - unified/remark-parse is the standard markdown parser
  - AST can be logged with --debug flag
---

## [2026-01-29 10:15:47] - S002: Render to PDF
Run: 20260129-101000-12346 (iteration 2)
...
```

### guardrails.md (Signs)

```markdown
# Guardrails (Signs)

> Lessons learned from failures. Read before acting.

## Core Signs

### Sign: Read Before Writing
- **Trigger**: Before modifying any file
- **Instruction**: Read the file first
- **Added after**: Core principle

### Sign: Test Before Commit
- **Trigger**: Before committing changes
- **Instruction**: Run required tests and verify outputs
- **Added after**: Core principle

---

## Learned Signs

### Sign: Update Snapshots After Visual Changes
- **Trigger**: When changing visual output (CSS, templates)
- **Instruction**: Run `npm test -- -u` to update snapshots after verifying correctness
- **Added after**: S003 failed due to stale snapshots
```

---

## Directory Structure

```
my-project/
├── .agents/
│   ├── ralph/                    # Loop templates (optional overrides)
│   │   ├── PROMPT_build.md       # Main agent prompt
│   │   ├── loop.sh               # Orchestrator script
│   │   ├── config.sh             # Configuration
│   │   ├── log-activity.sh       # Activity logger
│   │   └── references/           # Reference docs
│   │       ├── GUARDRAILS.md     # Sign template
│   │       └── CONTEXT_ENGINEERING.md
│   └── tasks/
│       └── prd-myproject.json    # Story definitions
├── .ralph/                       # State (gitignored usually)
│   ├── progress.md               # Append-only progress log
│   ├── guardrails.md             # Learned signs
│   ├── errors.log                # Failure patterns
│   ├── activity.log              # Event timeline
│   ├── .tmp/                     # Rendered prompts
│   └── runs/                     # Per-run logs and summaries
├── AGENTS.md                     # Project-specific build/test instructions
├── src/
└── package.json
```

---

## Comparison: Ralph vs Manual Agent Sessions

```
┌────────────────────┬──────────────────────────┬──────────────────────────┐
│ ASPECT             │ MANUAL CLAUDE CODE       │ RALPH LOOP               │
├────────────────────┼──────────────────────────┼──────────────────────────┤
│ Context            │ Accumulates, can drift   │ Fresh each iteration     │
│ Memory             │ Model context only       │ Files + git              │
│ Task selection     │ Human decides            │ PRD JSON with deps       │
│ Quality gates      │ Ad-hoc                   │ Enforced per-story       │
│ Progress tracking  │ Chat history             │ progress.md              │
│ Failure recovery   │ Start over               │ Retry same story         │
│ Learnings          │ Lost between sessions    │ guardrails.md persists   │
│ Commit discipline  │ Variable                 │ One per story            │
└────────────────────┴──────────────────────────┴──────────────────────────┘
```

---

## When to Use Ralph

**Good fit:**
- Multi-story projects with clear acceptance criteria
- Need auditability (progress log, run summaries)
- Want automatic retry on failure
- Building incrementally over days/weeks
- Need fresh context per task

**Not ideal:**
- Quick one-off tasks
- Exploratory coding without clear goals
- Tasks requiring heavy human guidance
- Projects without clear story decomposition

---

## Quick Start Recipe

```bash
# 1. Install
npm i -g @iannuttall/ralph

# 2. Initialize project
cd my-project
ralph install
ralph install --skills

# 3. Configure for Claude
echo 'AGENT_CMD="claude -p --dangerously-skip-permissions \"\$(cat {prompt})\""' >> .agents/ralph/config.sh

# 4. Generate PRD
ralph prd "A REST API for todo items with SQLite storage"

# 5. Review generated PRD
cat .agents/tasks/prd-*.json

# 6. Run first iteration
ralph build 1

# 7. Check progress
cat .ralph/progress.md

# 8. Continue building
ralph build 10
```

---

## References

- [Ralph GitHub](https://github.com/iannuttall/ralph)
- [HiWave Browser](https://github.com/hiwavebrowser/hiwave-macos) - Production example
- [Cursor Agent Best Practices](https://cursor.com/blog/agent-best-practices)
- [Cursor Scaling Agents](https://cursor.com/blog/scaling-agents)
