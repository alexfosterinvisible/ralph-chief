#!/usr/bin/env bash
set -euo pipefail
# Tests for lib/utils/event-emitter.sh

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIGGUM_HOME="$(dirname "$TESTS_DIR")"
export WIGGUM_HOME

source "$TESTS_DIR/test-framework.sh"
export LOG_FILE="/dev/null"
source "$WIGGUM_HOME/lib/core/logger.sh"
source "$WIGGUM_HOME/lib/core/file-lock.sh"

TEST_DIR=""
setup() {
    TEST_DIR=$(mktemp -d)
    export PROJECT_DIR="$TEST_DIR"
    export EVENTS_LOG=""
    source "$WIGGUM_HOME/lib/utils/event-emitter.sh"
}

teardown() {
    rm -rf "$TEST_DIR"
}

# =============================================================================
# events_init() Tests
# =============================================================================

test_events_init_creates_file() {
    events_init "$TEST_DIR"

    local expected_file="$TEST_DIR/.ralph/logs/events.jsonl"
    assert_file_exists "$expected_file" "events.jsonl should be created"
    assert_equals "$expected_file" "$EVENTS_LOG" "EVENTS_LOG should be set to correct path"
}

# =============================================================================
# emit_event() Tests
# =============================================================================

test_emit_event_writes_valid_json() {
    events_init "$TEST_DIR"

    emit_event "test.event" '"key":"value"'

    local events_file="$TEST_DIR/.ralph/logs/events.jsonl"
    assert_file_contains "$events_file" '"event_type":"test.event"' "Should contain event_type"
    assert_file_contains "$events_file" '"timestamp"' "Should contain timestamp"
    assert_file_contains "$events_file" '"key":"value"' "Should contain data fields"

    # Validate JSON with jq
    jq -c '.' "$events_file" > /dev/null 2>&1
    assert_equals "0" "$?" "Output should be valid JSON"
}

test_emit_event_without_data_creates_minimal_event() {
    events_init "$TEST_DIR"

    emit_event "minimal.event"

    local events_file="$TEST_DIR/.ralph/logs/events.jsonl"
    assert_file_contains "$events_file" '"event_type":"minimal.event"' "Should contain event_type"
    assert_file_contains "$events_file" '"timestamp"' "Should contain timestamp"

    # Should still be valid JSON
    local line
    line=$(cat "$events_file")
    local keys
    keys=$(echo "$line" | jq 'keys | length' 2>/dev/null)
    assert_equals "2" "$keys" "Minimal event should have exactly 2 keys (timestamp, event_type)"
}

# =============================================================================
# emit_task_started() Tests
# =============================================================================

test_emit_task_started_correct_event() {
    events_init "$TEST_DIR"

    emit_task_started "TASK-100" "worker-TASK-100-111"

    local events_file="$TEST_DIR/.ralph/logs/events.jsonl"
    assert_file_contains "$events_file" '"event_type":"task.started"' "Should have task.started event type"
    assert_file_contains "$events_file" '"task_id":"TASK-100"' "Should include task_id"
    assert_file_contains "$events_file" '"worker_id":"worker-TASK-100-111"' "Should include worker_id"
}

# =============================================================================
# emit_task_completed() Tests
# =============================================================================

test_emit_task_completed_includes_result() {
    events_init "$TEST_DIR"

    emit_task_completed "TASK-200" "worker-TASK-200-222" "PASS"

    local events_file="$TEST_DIR/.ralph/logs/events.jsonl"
    assert_file_contains "$events_file" '"event_type":"task.completed"' "Should have task.completed event type"
    assert_file_contains "$events_file" '"result":"PASS"' "Should include result field"
    assert_file_contains "$events_file" '"task_id":"TASK-200"' "Should include task_id"
    assert_file_contains "$events_file" '"worker_id":"worker-TASK-200-222"' "Should include worker_id"
}

# =============================================================================
# emit_task_failed() Tests
# =============================================================================

test_emit_task_failed_includes_reason() {
    events_init "$TEST_DIR"

    emit_task_failed "TASK-300" "worker-TASK-300-333" "timeout_exceeded"

    local events_file="$TEST_DIR/.ralph/logs/events.jsonl"
    assert_file_contains "$events_file" '"event_type":"task.failed"' "Should have task.failed event type"
    assert_file_contains "$events_file" '"reason":"timeout_exceeded"' "Should include reason field"
    assert_file_contains "$events_file" '"task_id":"TASK-300"' "Should include task_id"
}

# =============================================================================
# emit_iteration_started() Tests
# =============================================================================

test_emit_iteration_started_includes_iteration_number() {
    events_init "$TEST_DIR"

    emit_iteration_started "worker-TASK-400-444" 3 "session-abc123"

    local events_file="$TEST_DIR/.ralph/logs/events.jsonl"
    assert_file_contains "$events_file" '"event_type":"iteration.started"' "Should have iteration.started event type"
    assert_file_contains "$events_file" '"iteration":3' "Should include iteration number as integer"
    assert_file_contains "$events_file" '"worker_id":"worker-TASK-400-444"' "Should include worker_id"
    assert_file_contains "$events_file" '"session_id":"session-abc123"' "Should include session_id"
}

# =============================================================================
# emit_error() Tests
# =============================================================================

test_emit_error_escapes_quotes_in_message() {
    events_init "$TEST_DIR"

    emit_error "worker-ERR-500" "validation" 'File "main.py" has errors'

    local events_file="$TEST_DIR/.ralph/logs/events.jsonl"
    assert_file_contains "$events_file" '"event_type":"error"' "Should have error event type"
    assert_file_contains "$events_file" '"error_type":"validation"' "Should include error_type"
    assert_file_contains "$events_file" '"worker_id":"worker-ERR-500"' "Should include worker_id"

    # Verify the line is still valid JSON despite quotes in message
    jq -c '.' "$events_file" > /dev/null 2>&1
    local exit_code=$?
    assert_equals "0" "$exit_code" "Should produce valid JSON even with quotes in message"
}

# =============================================================================
# emit_agent_started() Tests
# =============================================================================

test_emit_agent_started_with_optional_task_id() {
    events_init "$TEST_DIR"

    # With task_id
    emit_agent_started "coder" "worker-AGT-600" "TASK-600"

    local events_file="$TEST_DIR/.ralph/logs/events.jsonl"
    assert_file_contains "$events_file" '"agent_type":"coder"' "Should include agent_type"
    assert_file_contains "$events_file" '"task_id":"TASK-600"' "Should include optional task_id when provided"

    # Without task_id
    rm -f "$events_file"
    touch "$events_file"
    emit_agent_started "reviewer" "worker-AGT-601"

    assert_file_contains "$events_file" '"agent_type":"reviewer"' "Should include agent_type without task_id"
    assert_file_not_contains "$events_file" '"task_id"' "Should not include task_id when not provided"
}

# =============================================================================
# emit_pr_created() Tests
# =============================================================================

test_emit_pr_created_includes_fields() {
    events_init "$TEST_DIR"

    emit_pr_created "TASK-700" "https://github.com/org/repo/pull/42" "feature/task-700"

    local events_file="$TEST_DIR/.ralph/logs/events.jsonl"
    assert_file_contains "$events_file" '"event_type":"pr.created"' "Should have pr.created event type"
    assert_file_contains "$events_file" '"pr_url":"https://github.com/org/repo/pull/42"' "Should include pr_url"
    assert_file_contains "$events_file" '"branch":"feature/task-700"' "Should include branch"
    assert_file_contains "$events_file" '"task_id":"TASK-700"' "Should include task_id"
}

# =============================================================================
# emit_violation() Tests
# =============================================================================

test_emit_violation_escapes_quotes_in_details() {
    events_init "$TEST_DIR"

    emit_violation "worker-VIO-800" "file_access" 'Accessed "/etc/passwd" outside sandbox'

    local events_file="$TEST_DIR/.ralph/logs/events.jsonl"
    assert_file_contains "$events_file" '"event_type":"violation"' "Should have violation event type"
    assert_file_contains "$events_file" '"violation_type":"file_access"' "Should include violation_type"
    assert_file_contains "$events_file" '"worker_id":"worker-VIO-800"' "Should include worker_id"

    # Verify valid JSON despite quotes in details
    jq -c '.' "$events_file" > /dev/null 2>&1
    local exit_code=$?
    assert_equals "0" "$exit_code" "Should produce valid JSON even with quotes in details"
}

# =============================================================================
# events_query_by_type() Tests
# =============================================================================

test_events_query_by_type_filters_correctly() {
    events_init "$TEST_DIR"

    emit_task_started "TASK-A" "worker-A"
    emit_task_completed "TASK-B" "worker-B" "PASS"
    emit_task_started "TASK-C" "worker-C"
    emit_task_failed "TASK-D" "worker-D" "error"

    local result
    result=$(events_query_by_type "task.started" "$TEST_DIR")
    local count
    count=$(echo "$result" | wc -l | tr -d '[:space:]')

    assert_equals "2" "$count" "Should return exactly 2 task.started events"
    assert_output_contains "$result" "TASK-A" "Should contain first started task"
    assert_output_contains "$result" "TASK-C" "Should contain second started task"
}

# =============================================================================
# events_query_by_task() Tests
# =============================================================================

test_events_query_by_task_filters_correctly() {
    events_init "$TEST_DIR"

    emit_task_started "TASK-ALPHA" "worker-1"
    emit_task_started "TASK-BETA" "worker-2"
    emit_task_completed "TASK-ALPHA" "worker-1" "PASS"
    emit_task_failed "TASK-BETA" "worker-2" "error"

    local result
    result=$(events_query_by_task "TASK-ALPHA" "$TEST_DIR")
    local count
    count=$(echo "$result" | wc -l | tr -d '[:space:]')

    assert_equals "2" "$count" "Should return exactly 2 events for TASK-ALPHA"
    assert_output_contains "$result" "task.started" "Should contain started event"
    assert_output_contains "$result" "task.completed" "Should contain completed event"
}

# =============================================================================
# events_query_by_worker() Tests
# =============================================================================

test_events_query_by_worker_filters_correctly() {
    events_init "$TEST_DIR"

    emit_task_started "TASK-X" "worker-FIRST"
    emit_task_started "TASK-Y" "worker-SECOND"
    emit_task_completed "TASK-X" "worker-FIRST" "PASS"

    local result
    result=$(events_query_by_worker "worker-FIRST" "$TEST_DIR")
    local count
    count=$(echo "$result" | wc -l | tr -d '[:space:]')

    assert_equals "2" "$count" "Should return exactly 2 events for worker-FIRST"
    assert_output_contains "$result" "TASK-X" "Should contain events for worker-FIRST"
}

# =============================================================================
# events_count() Tests
# =============================================================================

test_events_count_returns_correct_count() {
    events_init "$TEST_DIR"

    emit_task_started "TASK-1" "worker-1"
    emit_task_started "TASK-2" "worker-2"
    emit_task_completed "TASK-3" "worker-3" "PASS"
    emit_task_failed "TASK-4" "worker-4" "err"
    emit_error "worker-5" "timeout" "timed out"

    local count
    count=$(events_count "" "$TEST_DIR")
    assert_equals "5" "$count" "Should count all 5 events"
}

test_events_count_with_type_filter() {
    events_init "$TEST_DIR"

    emit_task_started "TASK-1" "worker-1"
    emit_task_started "TASK-2" "worker-2"
    emit_task_completed "TASK-3" "worker-3" "PASS"
    emit_task_failed "TASK-4" "worker-4" "err"

    local count
    count=$(events_count "task.started" "$TEST_DIR")
    assert_equals "2" "$count" "Should count only task.started events"

    count=$(events_count "task.completed" "$TEST_DIR")
    assert_equals "1" "$count" "Should count only task.completed events"
}

test_events_count_returns_0_for_nonexistent_file() {
    local count
    count=$(events_count "" "/nonexistent/path/nowhere")
    assert_equals "0" "$count" "Should return 0 for non-existent events file"
}

# =============================================================================
# Run All Tests
# =============================================================================

# events_init tests
run_test test_events_init_creates_file

# emit_event tests
run_test test_emit_event_writes_valid_json
run_test test_emit_event_without_data_creates_minimal_event

# emit_task_started tests
run_test test_emit_task_started_correct_event

# emit_task_completed tests
run_test test_emit_task_completed_includes_result

# emit_task_failed tests
run_test test_emit_task_failed_includes_reason

# emit_iteration_started tests
run_test test_emit_iteration_started_includes_iteration_number

# emit_error tests
run_test test_emit_error_escapes_quotes_in_message

# emit_agent_started tests
run_test test_emit_agent_started_with_optional_task_id

# emit_pr_created tests
run_test test_emit_pr_created_includes_fields

# emit_violation tests
run_test test_emit_violation_escapes_quotes_in_details

# events_query_by_type tests
run_test test_events_query_by_type_filters_correctly

# events_query_by_task tests
run_test test_events_query_by_task_filters_correctly

# events_query_by_worker tests
run_test test_events_query_by_worker_filters_correctly

# events_count tests
run_test test_events_count_returns_correct_count
run_test test_events_count_with_type_filter
run_test test_events_count_returns_0_for_nonexistent_file

print_test_summary
exit_with_test_result
