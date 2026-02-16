# AF Learnings Index

This file indexes all verified learnings extracted from project transcripts.

========================================
CODE PROJECT (swebench-harness)
========================================

# DOCKER

---

## L006: Docker Platform Flag Required on Apple Silicon

**Problem:** Docker build failed with platform mismatch on M1/M2/M3 Macs
**Cause:** Base images built for amd64 don't run on arm64 without explicit emulation
**Verified cause:** Build command failed immediately with architecture mismatch error on M2 MacBook Pro
**Fix:** Add `--platform linux/amd64` to docker build and docker run commands
**Verified fix:** All 5 multi-language images built successfully with --platform flag
**Detail:** [L006-docker-platform-flag-apple-silicon.md](./L006-docker-platform-flag-apple-silicon.md)

---

## L013: Docker Setup Scripts Can Be Inlined, Eval Scripts Cannot

**Problem:** Unclear which scripts could be embedded in Dockerfile vs kept as separate files
**Cause:** Confusion between BUILD time (docker build) and RUN time (docker run)
**Verified cause:** User requested inlining, analysis showed setup is BUILD, eval is RUN
**Fix:** Inline setup_repo.sh as RUN commands, keep eval.sh separate for runtime execution
**Verified fix:** Reduced from 3 files to 2 per task, all builds succeeded
**Detail:** [L013-docker-build-vs-run-time-scripts.md](./L013-docker-build-vs-run-time-scripts.md)

# RUST BUILDS

---

## L014: Rust Debug Builds May Be Faster for Single-Run Tests

**Problem:** Nushell builds took 30min with --release for single-run test evaluation
**Cause:** Release optimizations increase compile time but reduce runtime, tests only run once
**Verified cause:** Analysis showed --release = 30min compile, debug = 10min compile
**Fix:** For single-run tests, use debug builds (10-15min total vs 30min release)
**Verified fix:** Extends L004 with debug vs release tradeoff analysis
**Detail:** [L014-rust-debug-vs-release-tradeoff.md](./L014-rust-debug-vs-release-tradeoff.md)

---

## L004: GCP Spot Instance Build Optimization for Rust

**Problem:** Large Rust projects (Nushell) taking ~30 minutes to build locally
**Cause:** Limited local CPU cores (4-16) and slow traditional linkers bottleneck compilation
**Verified cause:** Industry research confirmed pattern; GCP n2-standard-32 (32 cores) + mold linker tested; measured 5m 30s vs expected 30min local
**Fix:** Use GCP n2-standard-32 spot instances ($0.47/hr) with mold linker; created `gcp_create_builder.sh` with self-destruct timer
**Verified fix:** Nushell Docker build completed in 5m 30s (exit code 0); cost $0.04 per build; 5.5x speedup measured
**Detail:** [L004-gcp-spot-rust-builds.md](./L004-gcp-spot-rust-builds.md)

# MULTI-LANGUAGE PARSING

---

## L008: Multi-Language Test File Detection Patterns

**Problem:** Single regex can't identify test files across Go, Rust, Java, Ruby, TypeScript
**Cause:** Languages use different conventions (\_test.go vs \_spec.rb vs Test.java vs tests/ directory)
**Verified cause:** Naive "test" pattern missed Ruby \_spec.rb and incorrectly flagged non-test files
**Fix:** Language-specific detector checking both file patterns AND directory conventions
**Verified fix:** Parser extracted test files from all 5 languages with no false positives
**Detail:** [L008-multi-language-test-file-detection.md](./L008-multi-language-test-file-detection.md)

---

## L009: Git Diff Header Parsing for File Paths

**Problem:** Test file paths needed extraction from git diff, +++/--- lines unreliable
**Cause:** +++ shows /dev/null for new files, --- shows old path for renames
**Verified cause:** Parser using +++ failed for new test files and returned wrong paths for renames
**Fix:** Parse `diff --git a/... b/...` headers and extract b/ path (destination)
**Verified fix:** Extraction worked across all 5 languages including new files and subdirectories
**Detail:** [L009-git-diff-path-extraction.md](./L009-git-diff-path-extraction.md)

---

## L010: Centralize ALL Language-Specific Knowledge

**Problem:** Language config scattered across multiple files, changes required editing 3+ locations
**Cause:** Incremental development added language logic wherever needed, no consolidation
**Verified cause:** Adding Ruby required modifying 3 functions, forgot one, tests failed
**Fix:** Extend LANGUAGE_CONFIG dict to include ALL language knowledge (commands, patterns, flags)
**Verified fix:** Added TypeScript by updating only LANGUAGE_CONFIG, no code changes elsewhere
**Detail:** [L010-centralized-language-config.md](./L010-centralized-language-config.md)

# BASH / EVAL SCRIPTS

---

## L007: Bash Special Character Escaping in Generated Scripts

**Problem:** Test names with backticks caused command substitution errors in generated bash scripts
**Cause:** F-string interpolation doesn't escape shell metacharacters (backticks, $, quotes)
**Verified cause:** Test "rescue" failed with "rescue: command not found" due to backtick execution
**Fix:** Create `sanitize_for_bash()` to escape `, $, " before interpolation
**Verified fix:** All Ruby tests with backticks executed successfully (exit code 0)
**Detail:** [L007-bash-escaping-generated-scripts.md](./L007-bash-escaping-generated-scripts.md)

========================================
GCP / GCLOUD
========================================

---

## L019: GCP Instances Require google_compute_engine SSH Key

**Problem:** SSH to GCP instance failing despite trying multiple standard SSH keys
**Cause:** GCP uses specific key created by gcloud CLI, standard keys don't work
**Verified cause:** Multiple SSH attempts with different keys failed, only google_compute_engine worked
**Fix:** Use `ssh -i ~/.ssh/google_compute_engine` to specify GCP key explicitly
**Verified fix:** SSH connection and file transfers succeeded with google_compute_engine key
**Detail:** [L019-gcp-ssh-google-compute-engine-key.md](./L019-gcp-ssh-google-compute-engine-key.md)

========================================
IDE / TOOLING (personal)
========================================

# VSCODE / CURSOR

---

## L005: VSCode Terminal Keybindings Need Both Focus Contexts

**Problem:** Terminal keybindings work in content but not when clicking tab name
**Cause:** `when` clause has `terminalFocus` but missing `terminalTabsFocus`
**Verified cause:** User clicked terminal tab → keybinding didn't trigger, closed editor instead
**Fix:** Use `when: "terminalFocus || terminalTabsFocus"` for complete coverage
**Verified fix:** User tested both contexts (content + tab name) and confirmed "perfect"
**Detail:** [L005-vscode-terminal-keybindings-both-focus-contexts.md](L005-vscode-terminal-keybindings-both-focus-contexts.md)

---

## L011: VSCode Markdown Folding Requires Auto Strategy

**Problem:** Markdown header folding controls appeared but clicking had no effect
**Cause:** `editor.foldingStrategy: "indentation"` ignores markdown structure, only folds by whitespace
**Verified cause:** Web search confirmed indentation mode bypasses language-specific folding
**Fix:** Set `editor.foldingStrategy: "auto"` in VSCode/Cursor settings
**Verified fix:** User confirmed headers fold correctly, all keyboard shortcuts work
**Detail:** [L011-vscode-markdown-folding-strategy.md](./L011-vscode-markdown-folding-strategy.md)

---

## L012: Cursor Secondary Sidebar Uses toggleAuxiliaryBar Command

**Problem:** User wanted keybinding for Cursor agent panel but didn't know command name
**Cause:** Agent panel is "auxiliary bar" not "secondary sidebar" in VSCode terminology
**Verified cause:** User tried `toggleSecondarySideBar` but command doesn't exist
**Fix:** Use `workbench.action.toggleAuxiliaryBar` command in keybindings.json
**Verified fix:** User confirmed "Works immediately, no restart required"
**Detail:** [L012-cursor-secondary-sidebar-toggle.md](./L012-cursor-secondary-sidebar-toggle.md)

# SHELL / CLI

---

## L015: Learnings Directory Template Initialization Pattern

**Problem:** Each project required manual .learnings/ setup with no standardized bootstrap
**Cause:** No global template for learnings directory structure and example files
**Verified cause:** User requested reusable template for initializing learnings across projects
**Fix:** Create ~/.claude/af-templates/.learnings/ with claude.md, example, and index
**Verified fix:** Added to global CLAUDE.md, successfully bootstrapped swebench-harness learnings
**Detail:** [L015-learnings-directory-template-pattern.md](./L015-learnings-directory-template-pattern.md)

---

## L016: cp Requires -r Flag for Directory Contents

**Problem:** `cp ~/.templates/dir/ ./dest/` failed without -r flag and proper glob
**Cause:** cp without -r only copies files, directory path without /_ or /. is ambiguous
**Verified cause:** User identified issue in CLAUDE.md command, requested correction
**Fix:** Use `cp -r source/_ dest/`for contents or`cp -r source/. dest/` for all files
**Verified fix:** Updated CLAUDE.md, successfully copied learnings template
**Detail:** [L016-cp-recursive-flag-requirement.md](./L016-cp-recursive-flag-requirement.md)

========================================
RALPH
========================================

---

## L002: Ralph Multiple Installation Conflicts

**Problem:** `ralph --version` shows outdated 2.3.1 despite Homebrew reporting 2.4.3 installed
**Cause:** Three competing installations: standalone binary in ~/.local/bin (shadowing), npm symlink in Homebrew bin (blocking), and unlinked Homebrew Cellar install
**Verified cause:** `which ralph` showed ~/.local/bin taking precedence; `ls -la /opt/homebrew/bin/ralph` confirmed npm symlink blocking Homebrew
**Fix:** Remove ~/.local/bin/ralph, remove npm symlink, run `brew link ralph-orchestrator`
**Verified fix:** `ralph --version` returned 2.4.3 after cleanup; `ralph bot status` confirmed working
**Detail:** [L002-ralph-multiple-installation-conflicts.md](./L002-ralph-multiple-installation-conflicts.md)

---

## L017: Ralph Preset Files Must Exist as Separate Files

**Problem:** `ralph run --config presets/spec-driven.yml` failed despite preset documented in comments
**Cause:** Ralph looks for actual .yml files, documentation in comments doesn't work
**Verified cause:** presets/ directory didn't exist, spec-driven only in ralph.yml comments
**Fix:** Create presets/ directory and fetch/create actual preset .yml files
**Verified fix:** After creating preset file, ralph run succeeded
**Detail:** [L017-ralph-preset-files-must-exist.md](./L017-ralph-preset-files-must-exist.md)

---

## L018: Ralph Expects PROMPT.md in Workspace Root

**Problem:** Ralph failed with "PROMPT.md not found" when prompt was in specs/ subdirectory
**Cause:** Ralph default behavior looks in workspace root, not spec-driven subdirectories
**Verified cause:** File existed at specs/learnings-extraction/PROMPT.md but not at root
**Fix:** Symlink from spec directory to root: `ln -sf specs/feature/PROMPT.md PROMPT.md`
**Verified fix:** Symlinked to root, ralph run succeeded
**Detail:** [L018-ralph-prompt-path-expectation.md](./L018-ralph-prompt-path-expectation.md)
