# Database Design

## Database
SQLite for the MVP.

## Tables

### analyses
- id
- repository
- issue_number
- status
- created_at
- completed_at
- error_message

### execution_events
- id
- analysis_id
- sequence
- event_type
- tool_name
- status
- summary
- created_at

### resolution_reports
- id
- analysis_id
- issue_summary
- category
- priority
- root_cause
- confidence
- resolution_plan_json
- affected_files_json
- test_plan_json
- warnings_json
- created_at

### approvals
- id
- analysis_id
- action_type
- action_payload_json
- status
- created_at
- resolved_at

## Rules
- Keep raw GitHub responses out of the database unless specifically required.
- Store bounded summaries/results.
- Use foreign keys between analysis-related records.
- Add indexes only where justified.
