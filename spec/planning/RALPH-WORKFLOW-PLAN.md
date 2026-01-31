# Ralph Workflow Plan (Claude)

A disciplined workflow for autonomous agent development using ralph-orchestrator, with intentional friction to prevent premature patching.

---

## Overview: The Five Phases

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   1. INTEL        →    2. SPEC        →    3. KANBAN      →    4. RUN      │
│   (Gather)             (Design)            (Decompose)          (Observe)   │
│                                                                             │
│                                     ↓                                       │
│                              5. RETROSPECT                                  │
│                              (Learn & Decide)                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: INTEL (Gather Context)

**Goal**: Understand the problem space before writing any spec.

### Actions
```bash
# Research patterns, prior art, edge cases
# Use episodic memory to check past attempts
mcp__plugin_episodic-memory_episodic-memory__search "similar problem"

# Explore codebase for relevant code
ralph init --preset research
ralph run -p "Understand how [X] currently works"

# Gather external references
# - API docs
# - Library documentation
# - Similar implementations
```

### Outputs
- `specs/intel/<feature>-context.md` - raw notes, links, findings
- Clear understanding of constraints and dependencies

### Checkpoint
- [ ] Do I understand the happy path?
- [ ] Do I know the edge cases?
- [ ] Do I know what NOT to do?

---

## Phase 2: SPEC (Design PRD + Gates + Promise)

**Goal**: Write a tight specification with explicit quality gates.

### 2.1 PRD Structure

```markdown
# Feature: [Name]

## Problem Statement
What problem does this solve? Why now?

## Success Criteria (Completion Promise)
- [ ] Criterion 1 (testable)
- [ ] Criterion 2 (testable)
- [ ] Criterion 3 (testable)

## Non-Goals (Explicit Scope Boundaries)
- NOT doing X
- NOT changing Y
- NOT supporting Z

## Technical Approach
High-level design, key decisions made.

## Quality Gates
| Gate | Command | Required |
|------|---------|----------|
| Unit tests | `uv run pytest tests/unit` | Yes |
| Lint | `ruff check .` | Yes |
| Type check | `mypy src/` | No |
| Build | `npm run build` | Yes |

## Risks & Mitigations
- Risk 1 → Mitigation
- Risk 2 → Mitigation
```

### 2.2 Completion Promise

The completion promise is **sacred**. Write it as a testable statement:

```yaml
# In ralph.yml
core:
  completion_promise: |
    All success criteria pass:
    - Unit tests pass (pytest)
    - Integration tests pass
    - Lint clean (ruff)
    - No type errors (mypy)
    - Feature works as specified in PRD
```

### 2.3 Quality Gates Design

Gates provide **backpressure** - if they fail, the iteration is rejected.

**Principle**: If it matters, gate it. If it doesn't, don't.

```yaml
gates:
  # REQUIRED gates block until passing
  - name: core-tests
    command: "uv run pytest tests/ -x"
    required: true

  - name: lint
    command: "ruff check . --fix && ruff format ."
    required: true

  # ADVISORY gates inform but don't block
  - name: type-check
    command: "mypy src/ --ignore-missing-imports"
    required: false

  - name: coverage
    command: "uv run pytest --cov=src --cov-fail-under=80"
    required: false
```

### Outputs
- `specs/prd/<feature>.md` - the PRD
- `ralph.yml` configured with gates and promise
- `.taskmaster/docs/prd.md` updated (for TaskMaster)

---

## Phase 3: KANBAN (Decompose into Tasks)

**Goal**: Break the PRD into a dependency-aware task list.

### Using TaskMaster

```bash
# Parse PRD into tasks
task-master parse-prd --input specs/prd/<feature>.md

# View task board
task-master list

# Expand complex tasks
task-master expand --id <task-id>
```

### Task Decomposition Principles

**For ralph-orchestrator, prefer SMALLER tasks:**

| PRD Size | Decomposition | Rationale |
|----------|---------------|-----------|
| Small (1-3 files) | 1 ralph run | Single coherent change |
| Medium (4-10 files) | 2-4 tasks | Logical groupings |
| Large (10+ files) | 5-8 tasks | Risk isolation |

**Rule of thumb**: Each task should be completable in 10-25 iterations with clear gates.

### Creating Ralph Tasks from TaskMaster

```bash
# Generate ralph task files from TaskMaster
ralph code-task --from-taskmaster

# Or manually create
ralph task add "Implement user model with validation"
ralph task add "Add authentication endpoints"
ralph task add "Write integration tests"
```

### Task Dependencies (Promise DAG)

Ralph tasks can form a DAG via dependencies:

```yaml
# In task file or via CLI
tasks:
  - id: user-model
    description: "Implement User model"

  - id: auth-endpoints
    description: "Add auth endpoints"
    depends_on: [user-model]

  - id: integration-tests
    description: "Write integration tests"
    depends_on: [auth-endpoints]
```

### Outputs
- `.taskmaster/tasks/tasks.json` - task board
- `.ralph/agent/tasks.jsonl` - ralph task queue
- Clear dependency graph

---

## Phase 4: RUN (Execute & Observe)

**Goal**: Run ralph while capturing learnings in real-time.

### Start the Run

```bash
# Single task execution
ralph run -P specs/prd/<feature>.md --max-iterations 25

# Or from task queue
ralph run  # Picks from tasks.jsonl

# With web dashboard for observation
ralph web &
ralph run -P specs/prd/<feature>.md
```

### Real-Time Observation

**During the run, DO NOT INTERVENE. Instead, OBSERVE and NOTE.**

Create a learnings file:
```bash
touch .af/learnings/$(date +%Y-%m-%d)-<feature>-observations.md
```

### Learnings Template

```markdown
# Learnings: <Feature> - <Date>

## Spec Issues Noticed
- [ ] PRD didn't specify X (iteration 5 struggled)
- [ ] Gate command was wrong (needed --fix flag)
- [ ] Missing dependency on Y

## Agent Behavior Patterns
- [ ] Kept trying to refactor unrelated code
- [ ] Didn't read the existing tests first
- [ ] Good: Found edge case I missed

## Quality Gate Feedback
- [ ] Lint gate caught real issues
- [ ] Type check too noisy (make advisory?)

## Questions for Next Run
- Should we add a gate for X?
- Is the completion promise too vague?
```

### Hands-Tied Protocol

**CRITICAL**: During execution, your hands are tied. You may only:

1. **OBSERVE** - Watch the dashboard, read logs
2. **NOTE** - Write to `.af/learnings/`
3. **STOP** - `ralph loops stop <id>` if completely broken

You may **NOT**:
- Edit code
- Change the spec
- Add "quick fixes"
- Intervene "just this once"

**Why**: Patching teaches the agent nothing. A re-run with better spec teaches it everything.

---

## Phase 5: RETROSPECT (Learn & Decide)

**Goal**: Process learnings and decide: re-run or ship.

### Retrospect Process

```bash
# After run completes (or fails)
cd .af/learnings/

# Review observations
cat $(date +%Y-%m-%d)-<feature>-observations.md

# Aggregate into index
echo "## <Feature> - <Date>" >> af-learnings-index.md
cat $(date +%Y-%m-%d)-<feature>-observations.md >> af-learnings-index.md
```

### Decision Framework

```
┌─────────────────────────────────────────────────────────┐
│                   RUN COMPLETED                         │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  All gates passing?   │
              └───────────────────────┘
                    │           │
                   Yes          No
                    │           │
                    ▼           ▼
         ┌──────────────┐  ┌──────────────┐
         │ Manual QA    │  │ Review logs  │
         │ passed?      │  │ & learnings  │
         └──────────────┘  └──────────────┘
              │    │            │
             Yes   No           │
              │    │            │
              ▼    └────────────┘
         ┌────────┐      │
         │  SHIP  │      ▼
         └────────┘  ┌───────────────────┐
                     │ Update spec with  │
                     │ learnings         │
                     └───────────────────┘
                              │
                              ▼
                     ┌───────────────────┐
                     │    FULL RE-RUN    │
                     │  (clean slate)    │
                     └───────────────────┘
```

### Default to RE-RUN

**The default answer is always RE-RUN with improved spec.**

Only skip re-run if ALL of these are true:
- [ ] Gates all passing
- [ ] Manual QA passed
- [ ] No learnings that would change the spec
- [ ] Confident the agent understood the task

**Patching is allowed ONLY for**:
- Typos
- Import ordering
- Trivial formatting
- Never for logic, tests, or structure

### Updating Spec for Re-Run

```bash
# Edit the PRD with learnings
vim specs/prd/<feature>.md

# Update gates if needed
vim ralph.yml

# Clean previous state
ralph clean

# Re-run from scratch
ralph run -P specs/prd/<feature>.md
```

---

## PRD Decomposition Guide

### When to Decompose

| Signal | Action |
|--------|--------|
| PRD > 500 lines | Split into phases |
| > 10 files touched | Split by layer/module |
| > 3 independent concerns | Split by concern |
| Cross-cutting changes | DO NOT split (risky) |

### How to Decompose

**By Phase (Sequential)**
```
Phase 1: Data model + migrations
Phase 2: Business logic + unit tests
Phase 3: API endpoints + integration tests
Phase 4: UI components + e2e tests
```

**By Layer (Parallel-safe)**
```
Layer 1: Database/models (no deps)
Layer 2: Services (depends on 1)
Layer 3: API (depends on 2)
Layer 4: Tests (depends on 3)
```

**Anti-pattern: Over-decomposition**
- Don't split below 1-file granularity
- Don't create artificial boundaries
- Don't split just because it's "big"

### Let Ralph Handle It

For medium PRDs (5-10 files), consider letting ralph decompose itself:

```yaml
# ralph.yml
hats:
  planner:
    system_prompt: |
      You are a technical planner. Break this PRD into
      discrete, testable tasks. Each task should be
      completable in one focused session.
    delegates_to: [implementer]
```

---

## File Structure Summary

```
.af/
└── learnings/
    ├── af-learnings-index.md          # Aggregated learnings
    └── 2026-01-29-auth-observations.md # Per-run notes

specs/
├── intel/
│   └── auth-context.md                # Research notes
├── prd/
│   └── auth.md                        # PRD specification
└── RALPH-WORKFLOW-PLAN.md             # This document

.ralph/
├── agent/
│   ├── memories.md                    # Agent learnings
│   └── tasks.jsonl                    # Task queue
└── ralph.yml                          # Configuration

.taskmaster/
├── tasks/
│   └── tasks.json                     # Kanban board
└── docs/
    └── prd.md                         # TaskMaster PRD
```

---

## Quick Reference

```bash
# Phase 1: Intel
ralph init --preset research
ralph run -p "Understand X"

# Phase 2: Spec
vim specs/prd/<feature>.md
vim ralph.yml

# Phase 3: Kanban
task-master parse-prd --input specs/prd/<feature>.md
task-master list

# Phase 4: Run
ralph web &
ralph run -P specs/prd/<feature>.md
# HANDS OFF - write to .af/learnings/ only

# Phase 5: Retrospect
cat .af/learnings/*.md
# Decision: RE-RUN (default) or SHIP (if all criteria met)
ralph clean && ralph run -P specs/prd/<feature>.md  # re-run
# OR
git add . && git commit -m "feat: <feature>"         # ship
```

---

## The Psychological Trick

You mentioned wanting to tie your hands to prevent patching. Here's the protocol:

1. **Before running**: Close your editor. `vim` is not allowed during runs.
2. **During running**: Only terminal for `ralph web` and `.af/learnings/` notes.
3. **After running**: Read learnings FIRST. If any learnings exist, re-run is mandatory.

The mantra: **"If I learned something, the agent should learn it too."**

---

*Last updated: 2026-01-29*
