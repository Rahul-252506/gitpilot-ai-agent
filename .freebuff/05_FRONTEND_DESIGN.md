# Frontend Design

## Main Screen

### Header
- GitPilot title
- Short description
- Connection/configuration status without exposing secrets

### Input Section
Fields:
- Repository: `owner/repository`
- Issue number
- Analyze button

Validation:
- Repository format
- Positive integer issue number
- Prevent duplicate submissions while running

## Agent Timeline
Display chronological events:
- Tool started
- Tool completed
- Tool failed
- Reasoning/status summary that is safe to expose
- Current step number

Do not expose hidden chain-of-thought. Show concise execution events and tool results summaries instead.

## Result Sections
1. Issue Summary
2. Classification
3. Root Cause
4. Affected Files
5. Resolution Plan
6. Test Plan
7. Confidence
8. Warnings/Limitations

## Approval UI
If the agent proposes a GitHub write action:
- Show the proposed action
- Show its target
- Require explicit Approve/Reject
- Never perform writes merely because analysis completed

## States
- Idle
- Validating
- Running
- Completed
- Failed
- Waiting for approval

## UX
Keep the interface clean and developer-oriented. Prioritize readable execution status over decorative elements.
