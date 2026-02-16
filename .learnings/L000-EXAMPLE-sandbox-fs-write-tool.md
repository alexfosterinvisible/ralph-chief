# L001: SandboxLocalFileSystem Missing Write Tool

## Summary

ARE's `SandboxLocalFileSystem` exposes file reading tools but NOT file writing tools to agents, making file-editing scenarios impossible without custom tooling.

## Discovery

When running `af_are/code_bugfix-v0` scenario:

- Agent correctly read file with `cat`
- Agent identified the bug
- Agent had NO WAY to write the fix back
- Agent repeatedly called `open(path, mode='w')` which truncates file but returns `None`
- File got corrupted, scenario failed

## Root Cause

### fsspec (underlying library) provides both:

```python
def cat(self, path):
    """Read file contents"""

def pipe(self, path, value):
    """Put value into path (counterpart to cat)"""
```

### ARE only exposes `cat`, not `pipe`:

| Tool   | @app_tool? | Agent Can Use?  |
| ------ | ---------- | --------------- |
| `cat`  | ✅ Yes     | ✅ Read files   |
| `pipe` | ❌ No      | ❌ Can't write  |
| `open` | ✅ Yes     | ⚠️ Returns None |

## Solution

Created `WritableFileSystem` subclass in `src/af_are/scenarios/code_bugfix.py`:

```python
class WritableFileSystem(SandboxLocalFileSystem):
    """Sandbox filesystem with write_text exposed as agent tool."""

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def write_text(self, path: str, content: str) -> bool:
        """Write text content to a file."""
        real_path = self._validate_path(path)
        self.local_fs.pipe_file(real_path, content.encode("utf-8"))
        return True
```

## Result

- Before: 18+ iterations, hit max, **FAIL**
- After: 3 iterations, **SUCCESS** (100%)

## Verification (Cause)

**Method:** Grep'd installed ARE source for `@app_tool` decorators

**Command:**

```bash
grep -n "@app_tool" .venv/lib/python3.11/site-packages/are/simulation/apps/sandbox_file_system.py
```

**Result:** Found 12 `@app_tool` decorators on methods:

- `open`, `cat`, `mkdir`, `makedirs`, `mv`, `ls`, `rm`, `exists`, `display`, `info`, `tree`, `read_document`

**Confirmed:** No `@app_tool` on `pipe`, `pipe_file`, or any write method.

**Also verified:** fsspec docs explicitly state `pipe` is "counterpart to `cat`" for writing.

## Verification (Fix)

**Method:** Ran scenario before and after fix

**Before fix:**

```bash
uv run are-run -s af_are/code_bugfix-v0 -a default --provider openai --model gpt-4o
# Result: 18+ iterations, hit max, FAIL
# Validation: "File missing or corrupted: divide function not found"
```

**After fix:**

```bash
uv run are-run -s af_are/code_bugfix-v0 -a default --provider openai --model gpt-4o
# Result: 3 iterations, SUCCESS
# Agent used WritableFileSystem__write_text to save fix
# Validation: ScenarioValidationResult(success=True)
```

**Also ran:** `uv run pytest tests/ -v` — all 16 tests pass.

## Files Changed

- `src/af_are/scenarios/code_bugfix.py`

## Implications

Any ARE scenario requiring file writing needs this pattern. Could be:

1. Contributed upstream to ARE
2. Made into a reusable base class in `af_are`
3. Documented as known limitation
