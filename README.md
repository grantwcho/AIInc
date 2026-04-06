# AI CEO

`ai-ceo` is a Python scaffold for a persistent AI-native company operating system.

It now supports the architecture needed for a very large agent population:

- an immutable top-level objective,
- long-term memory for decisions and durable notes,
- a persistent registry of agents created by the CEO, other agents, or humans,
- queue-driven work execution so the runtime only touches runnable agents,
- agent-to-agent and human-to-agent messaging, and
- creator lineage so every agent keeps track of who made it.

## What This Architecture Supports

This repo is no longer limited to a small CEO-and-a-few-workers pattern.

The system is designed so you can have potentially thousands of agents because:

- agents are persisted in SQLite instead of being treated as ephemeral prompt fragments,
- only agents with queued work or queued messages are processed,
- humans and agents both use the same persistent creation model,
- work and messaging are stored as queue primitives, and
- the CEO sees summaries and queue pressure instead of the full roster every cycle.

This is the right base architecture for a large swarm, even though the current runtime is still a single-process scaffold rather than a distributed production system.

## Core Components

- `MemoryStore`: SQLite-backed persistence for objective state, agent registry, work queue, message queue, decisions, cycles, and memory.
- `CEOEngine`: CEO planning loop plus queue processing for runnable agents.
- `OpenAIBrain`: OpenAI-backed reasoning through the Responses API.
- `HeuristicBrain`: deterministic fallback for local testing without an API key.

## Current Runtime Model

The runtime is queue-driven:

1. The CEO runs a planning cycle.
2. The CEO may create/update/terminate agents.
3. The CEO may queue work items or messages.
4. The runtime processes only agents that currently have queued work or queued messages.
5. Agents may in turn create other agents, queue follow-up work, or send messages to other agents.

That means human-created agents and CEO-created agents are both first-class citizens in the same graph.

## Quick Start

1. Create a virtual environment and install the package:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

2. Initialize the company:

```bash
ai-ceo init \
  --company "AI Inc" \
  --objective "Build the most successful company in the world by creating compounding AI products, teams, and market advantages."
```

3. Create a human-owned agent:

```bash
ai-ceo create-agent \
  --agent-id founder_ops \
  --name "Founder Ops" \
  --role "Operator" \
  --mandate "Turn strategic intent into coordinated execution." \
  --system-prompt "Operate like an elite operator and coordinate execution across the company." \
  --creator-id grant
```

4. Queue work or send messages:

```bash
ai-ceo queue-work \
  --to founder_ops \
  --title "Build the first execution map" \
  --description "Define the first bottlenecks, owners, and success metrics." \
  --from-id grant

ai-ceo message-agent \
  --to founder_ops \
  --subject "Priority shift" \
  --body "Bias toward the narrowest painful wedge with obvious willingness to pay." \
  --from-id grant
```

5. Run the CEO cycle or just process queued agents:

```bash
ai-ceo cycle --input "Find our strongest initial wedge and staff the right specialist agents."
ai-ceo process-queue --max-agents 50
```

6. Open the live dashboard:

```bash
ai-ceo-dashboard --db state/ai_ceo.sqlite3 --open
```

7. Inspect the system from the terminal too:

```bash
ai-ceo status
ai-ceo agents --limit 20
ai-ceo messages --agent founder_ops
ai-ceo decisions
ai-ceo memory --query "wedge"
```

## Using a Real Model

If `OPENAI_API_KEY` is set and the `openai` package is installed, `ai-ceo cycle` and `ai-ceo process-queue` can use the OpenAI-backed brain.

Example:

```bash
export OPENAI_API_KEY="your-key"
export AI_CEO_MODEL="gpt-4.1-mini"
ai-ceo cycle --brain openai --input "Design the next 90 days of company expansion."
```

If `ANTHROPIC_API_KEY` is set, you can use Claude instead:

```bash
export ANTHROPIC_API_KEY="your-key"
export AI_CEO_MODEL="claude-opus-4-1-20250805"
ai-ceo cycle --brain anthropic --input "Design the next 90 days of company expansion."
```

In `auto` mode, the runtime now prefers Anthropic first, then OpenAI, then the heuristic fallback.

## Discord Agent Runtime

You can attach a persistent agent to a Discord bot persona so it can think through the same queue-and-memory system used by the CLI runtime.

1. Put your secrets in `.env.local`:

```bash
ANTHROPIC_API_KEY=your-key
DISCORD_BOT_TOKEN=your-discord-token
AI_CEO_MODEL=claude-opus-4-1-20250805
AI_CEO_DISCORD_AGENT_ID=ryan_whitaker
AI_CEO_DISCORD_AGENT_NAME=Ryan Whitaker
AI_CEO_DISCORD_AGENT_ROLE=CEO
AI_CEO_DISCORD_AGENT_MANDATE=Lead AI Inc, make high-leverage decisions, and coordinate the company through Discord.
AI_CEO_DISCORD_SYSTEM_PROMPT_FILE=prompts/ryan_whitaker.txt
AI_CEO_AUTONOMOUS_ENABLED=true
AI_CEO_AUTONOMOUS_INTERVAL_SECONDS=300
AI_CEO_DISCORD_UPDATES_CHANNEL=ceo-updates
```

Store the persona prompt in a versioned file such as [prompts/ryan_whitaker.txt](/Users/grantcho/Documents/AIInc/prompts/ryan_whitaker.txt). On startup, the Discord runtime loads that file and refreshes the saved agent prompt automatically.

2. Initialize the company once if you have not already:

```bash
ai-ceo init \
  --company "AI Inc" \
  --objective "Build the most successful company in the world by creating compounding AI products, teams, and market advantages."
```

3. Start the Discord runtime:

```bash
ai-ceo-discord
```

Behavior:

- on first boot, the runtime creates the configured Discord-backed agent if it does not already exist,
- when someone DMs the bot or mentions it in a server, that message is queued into the agent's inbox,
- the agent is processed through the normal `Brain` abstraction,
- created agents are mirrored into Discord channels under the `agents` category, and
- if `AI_CEO_AUTONOMOUS_ENABLED=true`, the CEO also runs on a fixed interval without needing human prompts and posts cycle updates to the configured updates channel.

## What "Permanent Agent Creation" Means Here

When an agent is created, it is persisted in the agent registry with:

- `creator_type`,
- `creator_id`,
- `parent_agent_id`,
- role and mandate,
- system prompt,
- status and versioning metadata.

That means the agent survives restarts and can be addressed later by humans, the CEO, or other agents.

## Important Limits

- The scaffold stores reflection summaries, not hidden chain-of-thought.
- The runtime is not yet distributed across multiple machines or workers.
- SQLite is a solid starting point for local development, but a production swarm at real scale would likely move queueing and registry operations to dedicated infrastructure.
- Agents are persistent logical workers; they are not always-on independent OS processes by default.
- The dashboard is a local browser UI over the same SQLite state, so it is great for observing the swarm but not meant to be the final production control plane.

## Verification

Run the built-in tests with:

```bash
python3 -m unittest discover -s tests
```
