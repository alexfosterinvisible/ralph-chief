# Wiggum Playground
# Usage: just <recipe> [args]

# Bash 4+ required (macOS ships with 3.2), util-linux for flock
export PATH := "/opt/homebrew/opt/util-linux/bin:/opt/homebrew/bin:" + env_var("PATH")

wiggum_home := justfile_directory() / "bin/chief-wiggum"
projects_dir := justfile_directory() / "projects"

# List projects
list:
    @ls -1 {{projects_dir}} 2>/dev/null || echo "(none)"

# Initialize new project
init name:
    mkdir -p {{projects_dir}}/{{name}}
    cd {{projects_dir}}/{{name}} && git init && WIGGUM_HOME={{wiggum_home}} {{wiggum_home}}/bin/wiggum init
    @echo "Created: {{projects_dir}}/{{name}}"

# Wiggum commands
run project *args:
    cd {{projects_dir}}/{{project}} && WIGGUM_HOME={{wiggum_home}} {{wiggum_home}}/bin/wiggum run {{args}}

status project:
    cd {{projects_dir}}/{{project}} && WIGGUM_HOME={{wiggum_home}} {{wiggum_home}}/bin/wiggum status

validate project:
    cd {{projects_dir}}/{{project}} && WIGGUM_HOME={{wiggum_home}} {{wiggum_home}}/bin/wiggum validate

monitor project *args:
    cd {{projects_dir}}/{{project}} && WIGGUM_HOME={{wiggum_home}} {{wiggum_home}}/bin/wiggum monitor {{args}}

inspect project *args:
    cd {{projects_dir}}/{{project}} && WIGGUM_HOME={{wiggum_home}} {{wiggum_home}}/bin/wiggum inspect {{args}}

clean project:
    cd {{projects_dir}}/{{project}} && WIGGUM_HOME={{wiggum_home}} {{wiggum_home}}/bin/wiggum clean

wiggum project *args:
    cd {{projects_dir}}/{{project}} && WIGGUM_HOME={{wiggum_home}} {{wiggum_home}}/bin/wiggum {{args}}

# Update lib
update:
    cd {{wiggum_home}} && git pull origin main

# TUI monitor
tui project:
    cd {{projects_dir}}/{{project}} && uv run --project {{wiggum_home}}/tui wiggum-tui

# Auto-merge all pending PRs
merge project:
    cd {{projects_dir}}/{{project}} && WIGGUM_HOME={{wiggum_home}} {{wiggum_home}}/bin/wiggum pr merge-all --auto-merge --squash

# Sync PR status (marks merged PRs as [x])
pr-sync project:
    cd {{projects_dir}}/{{project}} && WIGGUM_HOME={{wiggum_home}} {{wiggum_home}}/bin/wiggum pr sync

# Help
help:
    WIGGUM_HOME={{wiggum_home}} {{wiggum_home}}/bin/wiggum --help
