# Chief Wiggum (Ralph) - Project Brief

> An agentic task runner that autonomously executes software engineering tasks using Claude Code.

## Overview

Chief Wiggum is a CLI tool that spawns isolated workers to implement features, run tests, and create pull requests—all driven by a Kanban-style task board.

**Repository**: [0kenx/chief-wiggum](https://github.com/0kenx/chief-wiggum)  
**License**: MIT  
**Languages**: Shell (87.3%), Python (12.7%)

---

## Core Concept

1. Define tasks in `.ralph/kanban.md`
2. Chief Wiggum spawns isolated git worktrees per task
3. A pipeline of agents executes: **execution → audit → test → docs → validation**
4. Pull Requests are automatically created

---

## Prerequisites

| Dependency | Requirement |
|------------|-------------|
| OS | Linux / macOS |
| Bash | 4.0+ |
| Git | 2.20+ |
| Claude Code | `claude` CLI installed & authenticated |
| GitHub CLI | `gh` installed & authenticated |
| jq | JSON processor |
| setsid | Worker process isolation (`brew install util-linux` on macOS) |

---

## Installation

### Option 1: Global Install
```bash
./install.sh
export PATH="$HOME/.claude/chief-wiggum/bin:$PATH"
```

### Option 2: Run from Source
```bash
export WIGGUM_HOME=$(pwd)
export PATH="$WIGGUM_HOME/bin:$PATH"
```

---

## Quick Start

```bash
# 1. Initialize project
cd /path/to/your/project
wiggum init

# 2. Edit .ralph/kanban.md with tasks
# 3. Run workers
wiggum run --max-workers 8

# 4. Monitor progress
wiggum status
wiggum monitor split

# 5. Review & merge PRs
wiggum review list
wiggum review merge-all
```

---

## Kanban Task Format

```markdown
## TASKS

- [ ] **[TASK-001]** Add user authentication
  - Description: Implement JWT-based auth with login/logout endpoints
  - Priority: HIGH
```

### Task Markers

| Marker | Status |
|--------|--------|
| `[ ]` | Pending |
| `[=]` | In Progress |
| `[x]` | Complete |
| `[*]` | Failed |

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `wiggum init` | Initialize project with `.ralph/` directory |
| `wiggum run` | Start workers for pending tasks |
| `wiggum status` | Show worker status overview |
| `wiggum monitor` | Live log viewer |
| `wiggum monitor split` | Split pane per worker |
| `wiggum review` | PR management |
| `wiggum review list` | List open PRs |
| `wiggum review pr <id> view` | View specific PR |
| `wiggum review merge-all` | Merge all worker PRs |
| `wiggum validate` | Validate kanban format |
| `wiggum clean` | Remove worker worktrees |
| `wiggum inspect` | Debug workers, pipelines, agents |

---

## Configuration

### Pipeline Configuration
Customize agent pipeline in `config/pipeline.json`. Reference: `docs/PIPELINE-SCHEMA.md`

### Project Settings
Override defaults in `.ralph/config.json`:

```json
{
  "max_workers": 4,
  "max_iterations": 20,
  "max_turns": 50
}
```

---

## Repository Structure

```
chief-wiggum/
├── .github/workflows/   # CI/CD
├── bin/                 # CLI entry points
├── config/              # Pipeline & default configs
├── docs/                # Documentation
│   ├── PIPELINE-SCHEMA.md
│   └── Architecture docs
├── hooks/               # Git hooks
├── lib/                 # Core library code
├── skills/              # Prompt engineering / agent skills
├── tests/               # Test suite
├── tui/                 # Terminal UI components
├── CLAUDE.md            # Claude Code instructions
├── KanbanSpecification.md
├── install.sh
└── install-symlink.sh
```

---

## Architecture Highlights

- **Isolated Worktrees**: Each task runs in its own git worktree for conflict-free parallel execution
- **Agent Pipeline**: Configurable sequence of agents (execution → audit → test → docs → validation)
- **PRD Generation**: Automatically generates Product Requirements Documents from task specs
- **GitHub Integration**: Native PR creation and management via `gh` CLI

---

## Documentation References

- **Pipeline Schema**: `docs/PIPELINE-SCHEMA.md`
- **Architecture Guide**: `docs/` (Developer guide and internals)
- **Agent Development**: Writing custom agents

---

## Stats

- ⭐ 27 stars
- 🍴 3 forks
- Latest Release: v0.6.1
