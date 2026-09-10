# Workflow Orchestration

## Example Execution

### Step 1
Retrieve the target issue.

### Step 2
Analyze the issue text and identify technical search terms.

### Step 3
Search the repository for relevant symbols/files.

### Step 4
Inspect the most relevant files.

### Step 5
Search related issues and PRs if historical context is useful.

### Step 6
Cross-check evidence and identify likely root cause.

### Step 7
Generate resolution and test plans.

### Step 8
Validate the final structured output.

### Step 9
Persist the analysis and execution summary.

## Dynamic Behavior
The sequence must not be a rigid hard-coded chain. The LLM should be able to decide whether a tool is needed next, within safety limits.

## Context Management
Keep:
- User task
- Repository/issue identity
- Tool results
- Important evidence
- Previous actions
- Current objective

Avoid:
- Duplicate tool results
- Unbounded file contents
- Sensitive values
- Irrelevant context

## Failure Strategy
A failed non-critical search should be recorded and the agent may continue. A missing issue or authentication failure should terminate the run with a clear error.
