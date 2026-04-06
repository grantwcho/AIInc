from __future__ import annotations

import asyncio
import os

from .brain import resolve_brain
from .engine import CEOEngine
from .store import MemoryStore
from .utils import load_env_file, load_text_file


DEFAULT_PERSONA_PROMPT = (
    "You are Ryan Whitaker, the CEO of AI Inc. You are sharp, high-agency, warm, concise, "
    "commercially minded, and action oriented. Speak like a real founder-operator texting from "
    "their phone, not like an assistant writing a report. When humans message you in Discord, "
    "reply in first person, sound natural, make decisions when appropriate, delegate clearly, "
    "and keep the company objective in view."
)


def _resolve_prompt_path() -> str:
    return os.getenv(
        "AI_CEO_DISCORD_SYSTEM_PROMPT_FILE",
        os.path.join("prompts", "ryan_whitaker.txt"),
    )


def _load_persona_prompt() -> str:
    prompt_path = _resolve_prompt_path()
    if os.path.exists(prompt_path):
        return load_text_file(prompt_path)
    return os.getenv("AI_CEO_DISCORD_SYSTEM_PROMPT", DEFAULT_PERSONA_PROMPT)


def _clean_discord_content(message: object, client_user_id: int) -> str:
    content = str(getattr(message, "content", "") or "").strip()
    mention_tokens = {
        f"<@{client_user_id}>",
        f"<@!{client_user_id}>",
    }
    for token in mention_tokens:
        content = content.replace(token, "").strip()
    return content


def _render_report_reply(report: dict) -> str:
    direct_response = str(report.get("direct_response", "")).strip()
    if direct_response:
        return direct_response

    lines = []
    summary = str(report.get("summary", "")).strip()
    if summary:
        lines.append(summary)

    deliverables = [str(item).strip() for item in report.get("deliverables", []) if str(item).strip()]
    if deliverables:
        lines.append("")
        lines.extend(f"- {item}" for item in deliverables[:5])

    needs = [str(item).strip() for item in report.get("needs", []) if str(item).strip()]
    if needs:
        lines.append("")
        lines.append("Needs:")
        lines.extend(f"- {item}" for item in needs[:3])

    payload = "\n".join(lines).strip()
    return payload or "I processed that and updated my queue."


def _ensure_agent(engine: CEOEngine, store: MemoryStore, model_name: str) -> str:
    agent_id = os.getenv("AI_CEO_DISCORD_AGENT_ID", "ryan_whitaker")
    name = os.getenv("AI_CEO_DISCORD_AGENT_NAME", "Ryan Whitaker")
    role = os.getenv("AI_CEO_DISCORD_AGENT_ROLE", "CEO")
    mandate = os.getenv(
        "AI_CEO_DISCORD_AGENT_MANDATE",
        "Lead AI Inc, make high-leverage decisions, and coordinate the company through Discord.",
    )
    system_prompt = _load_persona_prompt()
    metadata = {
        "surface": "discord",
        "prompt_file": _resolve_prompt_path(),
    }

    existing = store.get_agent(agent_id)
    if existing is not None:
        existing.name = name
        existing.role = role
        existing.mandate = mandate
        existing.system_prompt = system_prompt
        existing.model = model_name or existing.model
        existing.metadata = {**existing.metadata, **metadata}
        store.upsert_agent(existing)
        return agent_id

    engine.create_agent(
        agent_id=agent_id,
        name=name,
        role=role,
        mandate=mandate,
        system_prompt=system_prompt,
        creator_type="human",
        creator_id="discord_setup",
        model=model_name,
        metadata=metadata,
    )
    return agent_id


async def run_discord_bot() -> None:
    load_env_file()

    token = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Set DISCORD_BOT_TOKEN in .env.local before starting the Discord bot.")

    db_path = os.getenv("AI_CEO_DB", "state/ai_ceo.sqlite3")
    brain_mode = os.getenv("AI_CEO_DISCORD_BRAIN", "anthropic")
    model_name = os.getenv(
        "AI_CEO_DISCORD_MODEL",
        os.getenv("AI_CEO_MODEL", os.getenv("ANTHROPIC_MODEL", "claude-opus-4-1-20250805")),
    )

    store = MemoryStore(db_path=db_path)
    if store.load_objective() is None:
        raise RuntimeError(
            "Initialize the company first with `ai-ceo init --company ... --objective ...`."
        )
    engine = CEOEngine(store=store, brain=resolve_brain(brain_mode, model=model_name))
    agent_id = _ensure_agent(engine=engine, store=store, model_name=model_name)

    try:
        import discord
    except ImportError as exc:
        raise RuntimeError(
            "The discord.py package is not installed. Install dependencies before starting the bot."
        ) from exc

    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    intents.messages = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        print(f"Discord agent online as {client.user} for agent {agent_id}")

    @client.event
    async def on_message(message: discord.Message) -> None:
        if client.user is None:
            return
        if message.author.bot:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        mentioned = client.user in getattr(message, "mentions", [])
        if not is_dm and not mentioned:
            return

        content = _clean_discord_content(message=message, client_user_id=client.user.id)
        if not content:
            return

        sender_id = f"discord:{message.author.id}"
        subject = f"Discord message from {message.author.display_name}"
        body = (
            f"Discord context\n"
            f"- author: {message.author.display_name}\n"
            f"- channel: {getattr(message.channel, 'id', 'dm')}\n"
            f"- guild: {getattr(getattr(message, 'guild', None), 'name', 'DM')}\n\n"
            "Reply to this person naturally, like a real CEO messaging them directly in Discord. "
            "Do not describe your response in third person and do not output a status report.\n\n"
            f"Message:\n{content}"
        )

        engine.send_message(
            recipient_agent_id=agent_id,
            subject=subject,
            body=body,
            sender_type="human",
            sender_id=sender_id,
            thread_id=str(message.channel.id),
        )

        async with message.channel.typing():
            reports = await asyncio.to_thread(
                engine.process_agent_queue,
                f"Discord inbound from {message.author.display_name}",
                None,
                1,
            )

        report = next((item for item in reports if item.get("agent_id") == agent_id), None)
        if report is None:
            await message.reply("I logged that, but I did not generate a reply.")
            return

        reply = _render_report_reply(report)
        await message.reply(reply, mention_author=False)

    await client.start(token)


def main() -> None:
    asyncio.run(run_discord_bot())
