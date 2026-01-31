# RALPH'S 5 COMMANDMENTS

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         RALPH'S 5 COMMANDMENTS                              │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. ONE STORY PER CONTEXT WINDOW                                           │
│     • Complete it or reset it                                              │
│     • Never "partial" - binary done/not-done                               │
│     • Fresh context prevents drift                                          │
│                                                                             │
│  2. FILES ARE MEMORY                                                       │
│     • progress.md = what happened                                          │
│     • guardrails.md = what we learned                                      │
│     • errors.log = what failed                                             │
│     • prd.json = what's left                                               │
│     • git = permanent record                                               │
│                                                                             │
│  3. QUALITY GATES BEFORE COMPLETION                                        │
│     • All gates must pass                                                  │
│     • No completion signal without verification                            │
│     • Build → Test → Lint → Type-check                                     │
│                                                                             │
│  4. READ BEFORE ACTING                                                     │
│     • Read guardrails first (learned signs)                                │
│     • Read errors log (past failures)                                      │
│     • Read code before modifying                                           │
│                                                                             │
│  5. COMPLETION SIGNAL IS SACRED                                            │
│     • Output <promise>COMPLETE</promise> ONLY when truly done              │
│     • The loop trusts this signal                                          │
│     • Lying breaks the system                                              │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## The Memory Layer

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  FILE                   │  PURPOSE                    │  BEHAVIOR           │
├─────────────────────────┼─────────────────────────────┼─────────────────────┤
│  progress.md            │  What happened each run     │  Append-only        │
│  guardrails.md          │  Lessons learned (Signs)    │  Grows over time    │
│  errors.log             │  Repeated failures          │  For pattern detect │
│  activity.log           │  Timing + events            │  Audit trail        │
│  prd.json               │  Story definitions + status │  Source of truth    │
│  git commits            │  Code changes               │  Permanent          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## The Agent Execution Box

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         AGENT EXECUTION                                  │
│                                                                          │
│  1. Read guardrails.md (learned signs)                                  │
│  2. Read errors.log (past failures)                                     │
│  3. Read progress.md (what's been done)                                 │
│  4. Implement ONLY this story                                           │
│  5. Run quality gates (build, test, lint)                               │
│  6. Commit via $commit skill                                            │
│  7. Append to progress.md                                               │
│  8. Output <promise>COMPLETE</promise> if all passed                    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Signs Pattern (Guardrails)

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

---

## Quality Gates

```
┌──────────────────────────────────────────────────────────────────┐
│  GLOBAL GATES (from PRD qualityGates[]):                        │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ 1. Build passes    │  npm run build / cargo build          │ │
│  │ 2. Tests pass      │  npm test / cargo test                │ │
│  │ 3. Lint clean      │  eslint / clippy                      │ │
│  │ 4. Type check      │  tsc --noEmit                         │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  STORY GATES (from story.acceptanceCriteria[]):                 │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ • Specific verification steps                              │ │
│  │ • Browser testing for UI changes                           │ │
│  │ • API endpoint tests                                       │ │
│  │ • Manual verification commands                             │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ALL MUST PASS before <promise>COMPLETE</promise>               │
└──────────────────────────────────────────────────────────────────┘
```

---

## The Loop State Machine

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                               │
│                              ┌─────────────────┐                             │
│                              │   ralph build   │                             │
│                              └────────┬────────┘                             │
│                                       │                                       │
│                                       ▼                                       │
│                         ┌─────────────────────────┐                          │
│                         │     select_story()      │                          │
│                         │   status=open           │                          │
│                         │   deps all done         │                          │
│                         └───────────┬─────────────┘                          │
│                                     │                                         │
│               ┌─────────────────────┼─────────────────────┐                  │
│               │                     │                     │                  │
│               ▼                     ▼                     ▼                  │
│    ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐         │
│    │ No stories       │  │ All blocked      │  │ Story found      │         │
│    │ remaining        │  │ (deps not met)   │  │                  │         │
│    │                  │  │                  │  │ Lock it:         │         │
│    │ EXIT: DONE       │  │ EXIT: BLOCKED    │  │ status=in_prog   │         │
│    └──────────────────┘  └──────────────────┘  └────────┬─────────┘         │
│                                                          │                   │
│                                                          ▼                   │
│                                               ┌──────────────────┐           │
│                                               │ Invoke Agent     │           │
│                                               │ (fresh context)  │           │
│                                               └────────┬─────────┘           │
│                                                        │                     │
│                                          ┌─────────────┴─────────────┐       │
│                                          │                           │       │
│                                          ▼                           ▼       │
│                               ┌──────────────────┐       ┌──────────────────┐│
│                               │ COMPLETE signal  │       │ No signal        ││
│                               │                  │       │                  ││
│                               │ status = done    │       │ status = open    ││
│                               │ completedAt=now  │       │ (retry next run) ││
│                               └────────┬─────────┘       └────────┬─────────┘│
│                                        │                          │          │
│                                        └───────────┬──────────────┘          │
│                                                    │                         │
│                                                    ▼                         │
│                                          ┌──────────────────┐                │
│                                          │ i < MAX_ITER ?   │                │
│                                          └────────┬─────────┘                │
│                                                   │                          │
│                                      ┌────────────┴────────────┐             │
│                                      │                         │             │
│                                      ▼                         ▼             │
│                           ┌──────────────────┐      ┌──────────────────┐     │
│                           │ YES              │      │ NO               │     │
│                           │ Loop to top      │      │ EXIT: MAX        │     │
│                           └──────────────────┘      └──────────────────┘     │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Anti-Patterns (What NOT To Do)

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              ANTI-PATTERNS                                  │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ✗ Working on multiple stories in one context                              │
│    → Context contamination, harder to rollback                             │
│                                                                             │
│  ✗ Outputting COMPLETE when tests fail                                     │
│    → Loop marks story done, but it's broken                                │
│                                                                             │
│  ✗ Skipping guardrails.md read                                             │
│    → Repeat same mistakes from past runs                                   │
│                                                                             │
│  ✗ Editing PRD status manually                                             │
│    → Loop manages status; agent manages code                               │
│                                                                             │
│  ✗ Leaving uncommitted changes                                             │
│    → Next iteration starts dirty, confuses diffs                           │
│                                                                             │
│  ✗ Partial implementations with TODOs                                      │
│    → Either complete or don't signal completion                            │
│                                                                             │
│  ✗ Not appending to progress.md                                            │
│    → Next iteration has no context of what happened                        │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Quick Reference

```
┌────────────────────────────────────────────────────────────────────────────┐
│                           QUICK REFERENCE                                   │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  INSTALL:     npm i -g @iannuttall/ralph                                   │
│  INIT:        ralph install && ralph install --skills                      │
│  GENERATE:    ralph prd "your project description"                         │
│  RUN ONE:     ralph build 1                                                │
│  RUN MANY:    ralph build 10                                               │
│  DRY RUN:     ralph build 1 --no-commit                                    │
│                                                                             │
│  CLAUDE CONFIG (.agents/ralph/config.sh):                                  │
│  AGENT_CMD="claude -p --dangerously-skip-permissions \"\$(cat {prompt})\"" │
│                                                                             │
│  COMPLETION SIGNAL:                                                        │
│  <promise>COMPLETE</promise>                                               │
│                                                                             │
│  STATE FILES:                                                              │
│  .ralph/progress.md      - append your run summary                         │
│  .ralph/guardrails.md    - add Signs when you learn something              │
│  .ralph/errors.log       - log repeated failures                           │
│  .agents/tasks/prd.json  - DO NOT EDIT status (loop manages it)            │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```
