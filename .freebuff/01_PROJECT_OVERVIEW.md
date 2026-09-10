# GitPilot — Project Overview

## Project
GitPilot is an AI-powered GitHub Issue Resolution & Triage Agent.

## Goal
Given a GitHub repository and issue number, the system gathers relevant issue, repository, and related-issue context through tools, reasons over that context, and produces a structured resolution report.

## Core Outcome
The agent should provide:
- Issue summary
- Priority and category
- Likely root cause
- Relevant files
- Recommended resolution steps
- Test strategy
- Confidence
- Agent execution timeline

## Week 3 Alignment
The system demonstrates prompt engineering, tool/function calling, multi-step workflows, context management, structured outputs, error handling, and logging.

## Scope
The initial implementation is read-heavy and safe. GitHub write actions such as adding labels or comments require explicit user approval.

## Non-Goals
- Autonomous merging of pull requests
- Autonomous production deployment
- Fully autonomous code commits
- Multi-agent swarm architecture
- Fine-tuning an LLM
