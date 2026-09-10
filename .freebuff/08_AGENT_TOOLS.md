# Agent Tools

## Read Tools

### get_issue
Input:
- owner
- repo
- issue_number

Returns:
- title
- body
- labels
- state
- author
- comments summary
- timestamps

### search_repository
Input:
- owner
- repo
- query

Returns bounded matching file paths and snippets.

### get_file
Input:
- owner
- repo
- path
- optional ref

Returns bounded file content.

### search_issues
Input:
- owner
- repo
- query

Returns related issues.

### search_pull_requests
Input:
- owner
- repo
- query

Returns related PRs.

## Optional Write Tools

### add_issue_label
Requires explicit user approval.

### add_issue_comment
Requires explicit user approval.

## Tool Rules
- Validate all arguments.
- Use timeouts.
- Return structured errors.
- Truncate large outputs.
- Never return access tokens.
- Never allow arbitrary API URLs from the model.
- Use the authenticated GitHub service internally.

## Tool Registry
The orchestrator should register tools centrally so the agent can discover the available capabilities.
