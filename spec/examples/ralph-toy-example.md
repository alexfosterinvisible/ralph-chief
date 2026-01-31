# Ralph Toy Example: URL Shortener API

This walkthrough shows exactly what happens during a Ralph session.

---

## Setup

```bash
mkdir url-shortener && cd url-shortener
git init
npm i -g @iannuttall/ralph
ralph install && ralph install --skills

# Configure for Claude Code
cat >> .agents/ralph/config.sh << 'EOF'
AGENT_CMD="claude -p --dangerously-skip-permissions \"\$(cat {prompt})\""
MAX_ITERATIONS=10
EOF
```

## Step 1: Generate PRD

```bash
ralph prd "A URL shortener API with Hono on Cloudflare Workers.
Store mappings in KV.
Endpoints: POST /shorten (returns short code), GET /:code (redirects)"
```

### Generated: `.agents/tasks/prd-url-shortener.json`

```json
{
  "version": 1,
  "project": "url-shortener",
  "description": "URL shortener API on Cloudflare Workers with KV storage",
  "qualityGates": [
    "npm run build must pass",
    "npm run test must pass",
    "wrangler types must pass"
  ],
  "stories": [
    {
      "id": "S001",
      "title": "Project scaffolding",
      "description": "Initialize Hono project with Cloudflare Workers template",
      "status": "open",
      "dependsOn": [],
      "acceptanceCriteria": [
        "npm create hono with cloudflare-workers template",
        "wrangler.toml configured with KV namespace",
        "npm run dev starts local server"
      ]
    },
    {
      "id": "S002",
      "title": "POST /shorten endpoint",
      "description": "Accept URL in body, generate short code, store in KV, return code",
      "status": "open",
      "dependsOn": ["S001"],
      "acceptanceCriteria": [
        "POST /shorten with {url: 'https://...'} returns {code: 'abc123'}",
        "Code is 6 alphanumeric characters",
        "Mapping stored in KV as code -> url",
        "Returns 400 if url missing or invalid"
      ]
    },
    {
      "id": "S003",
      "title": "GET /:code redirect",
      "description": "Look up code in KV, redirect to original URL",
      "status": "open",
      "dependsOn": ["S001"],
      "acceptanceCriteria": [
        "GET /abc123 redirects (302) to stored URL",
        "Returns 404 if code not found",
        "Redirect uses Location header"
      ]
    },
    {
      "id": "S004",
      "title": "Rate limiting",
      "description": "Limit POST /shorten to 10 requests per minute per IP",
      "status": "open",
      "dependsOn": ["S002"],
      "acceptanceCriteria": [
        "Track request count per IP in KV with 60s TTL",
        "Return 429 if limit exceeded",
        "Include Retry-After header"
      ]
    }
  ]
}
```

---

## Step 2: Run Iteration 1

```bash
ralph build 1
```

### What Happens Internally

```
1. loop.sh reads PRD, finds S001 (no deps, status=open)
2. Sets S001.status = "in_progress", S001.startedAt = now
3. Renders PROMPT_build.md with S001 context
4. Invokes: claude -p --dangerously-skip-permissions "$(cat rendered-prompt.md)"
```

### Agent Session (Iteration 1)

```
═══════════════════════════════════════════════════════
  Ralph Iteration 1 of 10
═══════════════════════════════════════════════════════

[Agent reads guardrails.md - sees core signs]
[Agent reads errors.log - empty]
[Agent reads PRD for context]

Working on: S001 - Project scaffolding

> Creating Hono project with Cloudflare Workers...

$ npm create hono@latest . -- --template cloudflare-workers
$ npm install

> Configuring wrangler.toml with KV...

[Creates wrangler.toml with kv_namespaces]

> Testing local dev server...

$ npm run dev
[Server starts on localhost:8787]
[Ctrl+C to stop]

> Running quality gates...

$ npm run build
✓ Build successful

$ wrangler types
✓ Types generated

> Committing via $commit skill...

$ git add -A
$ git commit -m "feat: scaffold Hono project with Cloudflare Workers (S001)"
[main abc1234] feat: scaffold Hono project with Cloudflare Workers (S001)

> Appending to progress.md...

<promise>COMPLETE</promise>
```

### After Iteration 1

**PRD Updated:**
```json
{
  "id": "S001",
  "status": "done",
  "startedAt": "2026-01-29T10:00:00Z",
  "completedAt": "2026-01-29T10:05:23Z"
}
```

**progress.md:**
```markdown
## [2026-01-29 10:05:23] - S001: Project scaffolding
Run: 20260129-100000-12345 (iteration 1)
- Commit: abc1234 feat: scaffold Hono project with Cloudflare Workers (S001)
- Verification:
  - npm run build -> PASS
  - wrangler types -> PASS
  - npm run dev -> PASS (manual check)
- Files changed:
  - package.json
  - wrangler.toml
  - src/index.ts
  - tsconfig.json
```

---

## Step 3: Run Iteration 2

```bash
ralph build 1  # Run another single iteration
```

### Agent Session (Iteration 2)

```
═══════════════════════════════════════════════════════
  Ralph Iteration 2 of 10
═══════════════════════════════════════════════════════

[Agent reads guardrails.md]
[Agent reads progress.md - sees S001 completed]

Working on: S002 - POST /shorten endpoint
(S001 is done, deps met)

> Reading existing code to understand structure...

[Reads src/index.ts]

> Implementing shorten endpoint...

[Creates src/shorten.ts with generateCode() and POST handler]
[Updates src/index.ts to import route]

> Adding validation...

[Adds URL validation with try/catch for invalid URLs]

> Writing tests...

[Creates test/shorten.test.ts]

> Running quality gates...

$ npm run build -> PASS
$ npm test -> PASS
$ wrangler types -> PASS

> Testing manually...

$ npm run dev &
$ curl -X POST http://localhost:8787/shorten -d '{"url":"https://example.com"}'
{"code":"x7k2m9"}

> Committing...

$ git commit -m "feat: add POST /shorten endpoint with KV storage (S002)"

<promise>COMPLETE</promise>
```

---

## Step 4: Parallel Stories (S003)

Note: S003 also depends only on S001, so if we ran multiple agents, both S002 and S003 could run in parallel. With single-agent Ralph, they run sequentially.

```bash
ralph build 1
```

### Agent Session (Iteration 3)

```
═══════════════════════════════════════════════════════
  Ralph Iteration 3 of 10
═══════════════════════════════════════════════════════

Working on: S003 - GET /:code redirect
(S001 done, S002 done but not a dep)

> Implementing redirect handler...

[Creates src/redirect.ts]
[Adds GET /:code route]

> Testing...

$ npm test -> PASS

> Manual verification...

# First create a short URL
$ curl -X POST localhost:8787/shorten -d '{"url":"https://google.com"}'
{"code":"abc123"}

# Then test redirect
$ curl -I localhost:8787/abc123
HTTP/1.1 302 Found
Location: https://google.com

<promise>COMPLETE</promise>
```

---

## Step 5: Failure and Recovery (S004)

```bash
ralph build 1
```

### Agent Session (Iteration 4) - FAILURE

```
═══════════════════════════════════════════════════════
  Ralph Iteration 4 of 10
═══════════════════════════════════════════════════════

Working on: S004 - Rate limiting
(S002 done, dep met)

> Implementing rate limiter with KV...

[Creates src/ratelimit.ts]
[Updates POST /shorten to check rate limit]

> Running tests...

$ npm test
FAIL test/ratelimit.test.ts
  ✕ should return 429 after 10 requests

  Expected: 429
  Received: 200

  KV mock not properly tracking state across requests

[NO COMPLETION SIGNAL - tests failed]
```

### After Failed Iteration

**PRD Updated:**
```json
{
  "id": "S004",
  "status": "open"  // Reset for retry
}
```

**errors.log Updated:**
```
[2026-01-29 10:25:47] S004 failed - KV mock not tracking state in tests
```

---

### Agent Session (Iteration 5) - RETRY SUCCESS

```
═══════════════════════════════════════════════════════
  Ralph Iteration 5 of 10
═══════════════════════════════════════════════════════

[Agent reads errors.log - sees KV mock issue]

Working on: S004 - Rate limiting (retry)

> Reading previous attempt...
> Fixing KV mock to use shared state...

[Updates test setup to use persistent mock Map]

$ npm test -> PASS

> Adding guardrail for future...

[Appends to guardrails.md:]

### Sign: KV Mocks Need Shared State
- **Trigger**: Writing tests that use KV across multiple requests
- **Instruction**: Use a shared Map instance, not fresh mocks per test
- **Added after**: S004 rate limit tests failed due to isolated mocks

<promise>COMPLETE</promise>
```

---

## Final State

### Git Log

```
$ git log --oneline
e5f6789 feat: add rate limiting to POST /shorten (S004)
d4e5678 feat: add GET /:code redirect endpoint (S003)
c3d4567 feat: add POST /shorten endpoint with KV storage (S002)
abc1234 feat: scaffold Hono project with Cloudflare Workers (S001)
```

### PRD Final State

```json
{
  "stories": [
    {"id": "S001", "status": "done", "completedAt": "2026-01-29T10:05:23Z"},
    {"id": "S002", "status": "done", "completedAt": "2026-01-29T10:15:47Z"},
    {"id": "S003", "status": "done", "completedAt": "2026-01-29T10:25:12Z"},
    {"id": "S004", "status": "done", "completedAt": "2026-01-29T10:35:89Z"}
  ]
}
```

### progress.md Summary

```markdown
# Progress Log
Started: 2026-01-29 10:00:00

## Codebase Patterns
- Hono app with Cloudflare Workers
- KV for persistent storage
- Tests use vitest with KV mocks

---

## [2026-01-29 10:05:23] - S001: Project scaffolding
Commit: abc1234
Files: package.json, wrangler.toml, src/index.ts

## [2026-01-29 10:15:47] - S002: POST /shorten endpoint
Commit: c3d4567
Files: src/shorten.ts, src/index.ts, test/shorten.test.ts

## [2026-01-29 10:25:12] - S003: GET /:code redirect
Commit: d4e5678
Files: src/redirect.ts, test/redirect.test.ts

## [2026-01-29 10:35:89] - S004: Rate limiting
Commit: e5f6789 (after retry)
Files: src/ratelimit.ts, test/ratelimit.test.ts
**Learnings:** KV mocks need shared state across requests
```

### guardrails.md Accumulated

```markdown
# Guardrails (Signs)

## Core Signs
### Sign: Read Before Writing
### Sign: Test Before Commit

## Learned Signs
### Sign: KV Mocks Need Shared State
- **Trigger**: Writing tests that use KV across multiple requests
- **Instruction**: Use a shared Map instance, not fresh mocks per test
- **Added after**: S004 rate limit tests failed due to isolated mocks
```

---

## Key Observations

1. **5 iterations for 4 stories** - One retry due to test failure
2. **Each commit is atomic** - One story = one commit
3. **Learnings accumulate** - guardrails.md grows with project
4. **Fresh context each time** - Agent doesn't remember previous iterations, but files do
5. **Quality gates enforced** - No completion without passing tests
6. **Progress is auditable** - Full history in progress.md and git log

---

## Running Autonomously

```bash
# Let it run until done or max iterations
ralph build 25

# Output:
═══════════════════════════════════════════════════════
  Ralph Iteration 1 of 25
═══════════════════════════════════════════════════════
...
Completion signal received; story marked done.
Remaining stories: 3

═══════════════════════════════════════════════════════
  Ralph Iteration 2 of 25
═══════════════════════════════════════════════════════
...
Remaining stories: 2

...

═══════════════════════════════════════════════════════
  Ralph Iteration 5 of 25
═══════════════════════════════════════════════════════
...
Remaining stories: 0
No remaining stories.
```
