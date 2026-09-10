# Agent Architecture

## Agent Role
The agent is a GitHub issue investigation and resolution-planning specialist.

## Agent Inputs
- Repository
- Issue number
- Issue data
- Available tool definitions

## Agent Loop

```text
Task
  |
  v
Observe current context
  |
  v
Decide whether more information is needed
  |
  +--> Call tool --> Observe result --+
  |                                   |
  +-----------------------------------+
  |
  v
Produce structured resolution
```

## Required Agent Behaviors
1. Start with issue context.
2. Identify important technical terms.
3. Search relevant repository areas.
4. Inspect only relevant files.
5. Look for related issues/PRs when useful.
6. Avoid unnecessary tool calls.
7. Distinguish evidence from inference.
8. State uncertainty.
9. Produce the final schema only when enough evidence exists.

## Termination
The agent must terminate when:
- It has enough evidence for a useful report, or
- It reaches a configured step/time limit, or
- A fatal dependency failure prevents further progress.

## Important
Do not implement hidden chain-of-thought display. Store and show only concise action/status information.
