# Ralph Orchestrator Cheatsheet (Claude)

**Version**: 2.3.1
**Source**: [mikeyobrien/ralph-orchestrator](https://github.com/mikeyobrien/ralph-orchestrator)
**Install**: `~/.local/bin/ralph`, `ralph-bench`, `ralph-e2e`

---

## Core Philosophy

Ralph implements the **Ralph Commandments** correctly:

| Commandment | Implementation |
|-------------|----------------|
| One story per context | Fresh PTY-spawned process each iteration |
| Files are memory | `.ralph/agent/memories.md`, `tasks.jsonl` |
| Quality gates | Backpressure via test/lint/build gates |
| Read before acting | Signs pattern in guardrails |
| Completion signal is sacred | `LOOP_COMPLETE` termination signal |

---

## Quick Start

```bash
# Initialize config from preset
ralph init --preset feature

# Run with inline prompt
ralph run -p "Implement user authentication"

# Run with prompt file
ralph run -P ./specs/feature.md

# Run in autonomous mode (headless)
ralph run -a -p "Fix the login bug"

# Continue interrupted run
ralph run --continue

# Dry run (show what would execute)
ralph run --dry-run -p "Add caching layer"
```

---

## Binaries

| Binary | Purpose |
|--------|---------|
| `ralph` | Main orchestration CLI |
| `ralph-bench` | Benchmark harness for measuring agent performance |
| `ralph-e2e` | End-to-end testing framework |

---

## Commands Reference

### Core Commands

```bash
ralph run [OPTIONS]         # Run orchestration loop
ralph plan [IDEA]           # Start PDD planning session
ralph init --preset <NAME>  # Initialize config from preset
ralph clean                 # Remove .agent/ directory
ralph web                   # Launch web dashboard (port 5173)
```

### Loop Management

```bash
ralph loops list            # List all parallel loops
ralph loops logs <ID>       # View loop output
ralph loops history <ID>    # Show event history
ralph loops attach <ID>     # Open shell in worktree
ralph loops diff <ID>       # Show changes from merge-base
ralph loops merge <ID>      # Merge completed loop
ralph loops stop <ID>       # Stop running loop
ralph loops discard <ID>    # Abandon and cleanup
ralph loops prune           # Clean stale loops
```

### Hat Management

```bash
ralph hats list             # List configured hats
ralph hats show <NAME>      # Show hat details
ralph hats validate         # Validate topology
ralph hats graph            # Display topology graph
```

### Agent-Facing Tools

```bash
ralph tools memory add "learning"    # Add persistent memory
ralph tools memory list              # List memories
ralph tools task add "task desc"     # Add work item
ralph tools task list                # List tasks
```

---

## Presets (25 Built-in)

```bash
ralph init --list-presets  # See all
```

### Development
| Preset | Purpose |
|--------|---------|
| `feature` | Feature dev with code review |
| `feature-minimal` | Minimal feature, auto-derived instructions |
| `tdd-red-green` | Test-driven red-green-refactor |
| `refactor` | Code refactoring workflow |
| `debug` | Bug investigation |
| `deploy` | Deployment and release |

### Documentation & Planning
| Preset | Purpose |
|--------|---------|
| `documentation-first` | Docs-driven development |
| `docs` | Documentation generation |
| `spec-driven` | Specification-driven development |
| `gap-analysis` | Gap analysis and planning |
| `research` | Deep exploration tasks |

### Review & Security
| Preset | Purpose |
|--------|---------|
| `review` | Code review workflow |
| `pr-review` | Multi-perspective PR review |
| `adversarial-review` | Red/Blue team security review |
| `incident-response` | Production incident handling |

### Specialized
| Preset | Purpose |
|--------|---------|
| `api-design` | API-first design |
| `code-archaeology` | Legacy code modernization |
| `migration-safety` | Safe DB/API migrations |
| `performance-optimization` | Performance tuning |
| `scientific-method` | Hypothesis-driven experimentation |
| `socratic-learning` | Learning via questioning |
| `mob-programming` | Mob programming with roles |
| `confession-loop` | Confidence-aware completion |
| `merge-loop` | Merge worktree to main |
| `hatless-baseline` | Baseline for comparison |

---

## Configuration (ralph.yml)

```yaml
core:
  backend: claude              # claude, kiro, gemini, codex, amp, custom
  max_iterations: 25
  completion_promise: "All tests pass"
  default_mode: autonomous     # autonomous | interactive

gates:
  - name: tests
    command: "uv run pytest"
    required: true
  - name: lint
    command: "ruff check ."
    required: false

hats:
  architect:
    system_prompt: "You are a senior architect..."
    delegates_to: [implementer, reviewer]
  implementer:
    system_prompt: "You write production code..."
  reviewer:
    system_prompt: "You review for correctness..."
```

---

## Run Options

| Flag | Purpose |
|------|---------|
| `-p, --prompt <TEXT>` | Inline prompt |
| `-P, --prompt-file <FILE>` | Prompt from file |
| `-b, --backend <NAME>` | Override backend |
| `-a, --autonomous` | Force headless mode |
| `--max-iterations <N>` | Override iteration limit |
| `--continue` | Resume interrupted run |
| `--dry-run` | Show without executing |
| `--no-tui` | Disable TUI mode |
| `--chaos` | Post-completion exploration |
| `--exclusive` | Single loop only |
| `-v, --verbose` | Show tool results |
| `-q, --quiet` | Suppress streaming |

---

## File Structure

```
.ralph/
├── agent/
│   ├── memories.md       # Persistent learnings
│   ├── tasks.jsonl       # Work item queue
│   └── scratchpad/       # Current iteration state
└── loops/
    └── <loop-id>/        # Parallel loop worktrees
```

---

## Backends (7 Supported)

| Backend | Provider |
|---------|----------|
| `claude` | Anthropic Claude Code |
| `kiro` | Amazon Kiro |
| `gemini` | Google Gemini |
| `codex` | OpenAI Codex |
| `amp` | Sourcegraph Amp |
| `custom` | Custom command |
| (auto) | Auto-detect from environment |

---

## Quality Gates Pattern

Gates provide **backpressure** - bad iterations get rejected:

```yaml
gates:
  - name: unit-tests
    command: "uv run pytest tests/unit"
    required: true      # Blocks until passing

  - name: lint
    command: "ruff check ."
    required: false     # Advisory only

  - name: build
    command: "npm run build"
    required: true
```

---

## Web Dashboard

```bash
ralph web                           # Open dashboard
ralph web --no-open                 # Start without browser
ralph web --backend-port 3001       # Custom ports
ralph web --workspace /path/to/repo # Different workspace
```

Dashboard shows:
- Active loops and their status
- Event history timeline
- Memory/task state
- Merge queue

---

## Useful Patterns

### Parallel Development
```bash
# Main feature in primary loop
ralph run -p "Implement auth system"

# Bug fix in parallel (spawns worktree)
ralph run -p "Fix login redirect bug"

# Check parallel loops
ralph loops list

# Merge when ready
ralph loops merge <loop-id>
```

### Resume After Failure
```bash
# Run gets interrupted
ralph run -p "Large refactor"
# ... Ctrl+C or crash

# Resume from where it stopped
ralph run --continue
```

### Configuration Overrides
```bash
# Use preset but override backend
ralph run -c builtin:feature -c core.backend=kiro -p "Add feature"

# Stack multiple overrides
ralph run -c ralph.yml -c core.max_iterations=50 -p "Big task"
```

---

## vs. taskmaster loop

| Aspect | ralph-orchestrator | taskmaster loop |
|--------|-------------------|-----------------|
| Fresh context | Per iteration (PTY spawn) | Per iteration |
| Memory | `.ralph/agent/memories.md` | In-memory |
| Quality gates | Configurable YAML | Fixed presets |
| Hats/roles | Full delegation system | None |
| Parallel loops | Git worktree isolation | None |
| Web dashboard | Built-in (port 5173) | None |
| Backends | 7 providers | Claude only |

---

## Troubleshooting

```bash
# Verbose output for debugging
ralph run -v -p "Debug this"

# View events for a run
ralph events

# Clean slate
ralph clean

# Validate hat topology
ralph hats validate
```

---

*Last updated: 2026-01-29*
