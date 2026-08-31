# Code Harness

[简体中文](README.zh-CN.md) | English

A lightweight coding agent harness for autonomous software engineering tasks.

## Features

- OpenAI-compatible model client
- Agent loop with file, search, edit, and command tools
- Workspace isolation and safe file editing
- Multi-turn conversations with saved sessions
- Manual and automatic context compaction
- Project memory and `@file` references
- Read-only Plan Mode with review before execution
- Reusable Skills with explicit activation
- Compact CLI output with status and diff views

## Setup

Code Harness requires Python 3.10 or later.

```bash
python -m pip install -e .
```

Copy `.env.example` to `.env`, then add your API configuration:

```dotenv
OPENAI_API_KEY=
OPENAI_BASE_URL=
MODEL_NAME=
```

`OPENAI_BASE_URL` is optional when the provider uses the SDK default.

## Usage

Start the interactive CLI:

```bash
code-harness
```

Run one task directly:

```bash
code-harness "Create a hello world script"
```

Use another workspace:

```bash
code-harness --workspace path/to/project
```

Inside the CLI, type `/` to view and complete commands:

| Command | Purpose |
| --- | --- |
| `/open <path>` | Switch to an existing workspace |
| `/workspace` | Show the current workspace |
| `/resume` | Resume a saved session |
| `/plan <task>` | Explore with read-only tools and create a plan |
| `/act` | Execute the latest reviewed plan |
| `/cancel` | Discard the current plan |
| `/compact` | Compact the current conversation context |
| `/remember <note>` | Save a project note |
| `/memory` | Show project memory |
| `/skills` | List available Skills |
| `/skill <name\|off>` | Activate a Skill or disable the current one |
| `/status` | Show files changed by the latest task |
| `/diff` | Show text changes from the latest task |
| `/verbose` | Toggle full tool output |
| `/help` | Show available commands |
| `/exit` | Save the session and exit |

Reference a workspace file by adding it to a task:

```text
Task> Review @src/main.py and improve its error handling
```

Plan Mode accepts feedback before execution:

```text
Task> /plan add input validation
Plan> Do not add new dependencies
Plan> /act
```

## Skills

A Skill is a `SKILL.md` file containing reusable instructions for a specific type of task. Bundled Skills live in `skills/`. Local Skills that should not be committed can be placed in `.agent/skills/`:

```text
skills/
└── python-testing/
    └── SKILL.md
```

Each `SKILL.md` starts with a small metadata block. Its `name` must match the directory name:

```markdown
---
name: python-testing
description: Diagnose and fix Python test failures with focused verification.
---

# Python Testing

- Run the smallest relevant test before changing code.
```

List and activate Skills from the CLI:

```text
Task> /skills
Task> /skill python-testing
Task> Diagnose the failing Python tests
Task> /skill off
```

Only the selected Skill is added to the agent instructions. The selection lasts for the current CLI process and does not bypass workspace or tool safety checks.

## Tests

Run the test suite without creating bytecode cache files:

```bash
python -B -m unittest discover -s tests
```

The live API test is disabled by default. Enable it only when `.env` contains a working API configuration:

```powershell
$env:RUN_LIVE_TESTS = "1"
python -B -m unittest tests.test_live_agent -v
```

## Status

Under active development.
