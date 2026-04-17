# AppScan Custom Dashboard — Agent & Mode Guide

This project includes custom Copilot chat modes and autonomous agents tailored to the ASoC ASPM Dashboard codebase.

## File Structure

```
.github/
├── copilot-instructions.md              # Always-on project context (Layer 1)
├── copilot-chat-modes/                  # Chat mode personas — Ask / Edit mode (Layer 2)
│   ├── planner.chatmode.md              # Task breakdown and feature planning
│   ├── architect.chatmode.md            # API design and architecture decisions
│   ├── security-reviewer.chatmode.md    # Security audit and auth/authz review
│   ├── developer.chatmode.md            # Code implementation guidance
│   └── tester.chatmode.md              # Test writing and coverage review
├── agents/                              # Autonomous agents — Agent mode (Layer 3)
│   ├── planner.agent.md                 # Plans features, creates task lists
│   ├── architect.agent.md               # Designs APIs, evaluates architecture
│   ├── developer.agent.md               # Implements code, runs linters/tests
│   ├── security-reviewer.agent.md       # Audits code for vulnerabilities
│   └── tester.agent.md                  # Writes and runs tests
.vscode/
└── settings.json                        # Enables agents, points to instructions
```

## How to Use

### Chat Modes (Layer 2)
Select from the Copilot Chat dropdown (VS Code 1.96+). These are advisory — they guide responses but don't write files.

| Mode | When to Use |
|------|------------|
| **Planner** | Breaking down a feature into tasks |
| **Architect** | Designing an API or evaluating trade-offs |
| **Security Reviewer** | Reviewing code for auth gaps or OWASP risks |
| **Developer** | Getting implementation guidance |
| **Tester** | Writing test cases or reviewing coverage |

### Agents (Layer 3)
Invoke with `@name` in Agent mode (VS Code 1.99+). These are autonomous — they read files, write code, and run commands.

| Agent | Tools | Purpose |
|-------|-------|---------|
| **@planner** | read, search, web, todo | Plans tasks (read-only) |
| **@architect** | read, search, web, todo | Designs systems (read-only) |
| **@developer** | read, edit, search, execute, todo, agent | Implements code |
| **@security-reviewer** | read, search, todo | Audits security (read-only) |
| **@tester** | read, edit, search, execute, todo | Writes and runs tests |

### Recommended Workflow
1. **@planner** — Break down the feature request
2. **@architect** — Design the solution (if needed)
3. **@security-reviewer** — Review the design for security gaps
4. **@developer** — Implement the code
5. **@tester** — Write and run tests

## Project Guardrails (Enforced Across All Agents)
- **Read-only ASoC**: No DELETE/PATCH/PUT to ASoC endpoints
- **Auth required**: Every API endpoint needs `Depends(get_current_user)` + `assert_action_allowed()`
- **Asset-group scoping**: List endpoints must use `filter_by_asset_group()`
- **Async-first**: All I/O via async/await
- **Existing patterns**: Follow adjacent file conventions
