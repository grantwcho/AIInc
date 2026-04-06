from __future__ import annotations

import asyncio
import os
import re
import traceback
from typing import Any, Dict, List, Optional

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


def _slugify_channel_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower().replace("_", "-"))
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return (slug or "agent")[:90]


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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


def _format_agent_report_for_channel(report: Dict[str, Any]) -> str:
    lines = [f"**{report.get('agent_name', report.get('agent_id', 'Agent'))}**"]
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

    return "\n".join(lines).strip()


def _format_cycle_summary(result: Any, non_ceo_reports: List[Dict[str, Any]]) -> str:
    created_agents = [
        action.get("name") or action.get("agent_id")
        for action in [item.to_dict() for item in result.applied_agent_actions]
        if action.get("action") == "create"
    ]
    queued_work = len(result.queued_work_items)
    processed = len(non_ceo_reports)

    lines = [result.reflection_summary.strip() or "I ran a company cycle."]
    if created_agents:
        lines.append("")
        lines.append(f"Created agents: {', '.join(created_agents[:6])}")
    lines.append("")
    lines.append(
        f"Queued {queued_work} work item(s) and processed {processed} non-CEO agent cycle(s)."
    )
    return "\n".join(lines).strip()


def _format_admin_dm(result: Any, non_ceo_reports: List[Dict[str, Any]]) -> str:
    created_agents = [
        action.get("name") or action.get("agent_id")
        for action in [item.to_dict() for item in result.applied_agent_actions]
        if action.get("action") == "create"
    ]
    lines = [
        "Ryan CEO update",
        result.reflection_summary.strip() or "I ran a company cycle.",
        "",
        f"Self-prompt: {result.self_prompt.strip() or 'n/a'}",
    ]
    if created_agents:
        lines.append(f"Created agents: {', '.join(created_agents[:6])}")
    if result.recorded_decisions:
        lines.append("Top decisions:")
        for item in result.recorded_decisions[:3]:
            lines.append(f"- {item.title}: {item.summary}")
    if non_ceo_reports:
        lines.append("Active agent reports:")
        for report in non_ceo_reports[:5]:
            lines.append(
                f"- {report.get('agent_name', report.get('agent_id', 'Agent'))}: {report.get('summary', '')}"
            )
    return "\n".join(lines).strip()


def _format_boot_dm(interval_seconds: int) -> str:
    return (
        "Ryan CEO autonomous loop is online.\n"
        f"Interval: {interval_seconds} seconds.\n"
        f"Guild: {os.getenv('AI_CEO_DISCORD_GUILD_ID', '(auto)')}\n"
        f"Admin user: {os.getenv('AI_CEO_DISCORD_ADMIN_USER_ID', '(unset)')}"
    )


def _autonomous_trigger() -> str:
    return os.getenv(
        "AI_CEO_AUTONOMOUS_TRIGGER",
        (
            "Run the next highest-leverage CEO cycle. Decide what the company should do next, "
            "create or update agents if needed, delegate work, and push the business toward "
            "product-market fit, growth, revenue, and durable advantage."
        ),
    ).strip()


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


def _resolve_home_guild(client: Any) -> Optional[Any]:
    configured = os.getenv("AI_CEO_DISCORD_GUILD_ID", "").strip()
    if configured:
        try:
            guild_id = int(configured)
        except ValueError:
            guild_id = 0
        if guild_id:
            return client.get_guild(guild_id)
    return client.guilds[0] if getattr(client, "guilds", None) else None


async def _ensure_agent_category(guild: Any) -> Optional[Any]:
    category_name = os.getenv("AI_CEO_DISCORD_AGENT_CATEGORY", "agents")
    existing = next(
        (channel for channel in getattr(guild, "categories", []) if channel.name.lower() == category_name.lower()),
        None,
    )
    if existing is not None:
        return existing
    return await guild.create_category(category_name)


async def _ensure_agent_channel(guild: Any, category: Any, agent_id: str, agent_name: str) -> Any:
    desired_name = _slugify_channel_name(agent_id)
    for channel in getattr(guild, "text_channels", []):
        if channel.name == desired_name:
            return channel

    topic = f"{agent_name} | {agent_id}"
    return await guild.create_text_channel(desired_name, category=category, topic=topic)


async def _ensure_updates_channel(guild: Any) -> Any:
    channel_name = _slugify_channel_name(
        os.getenv("AI_CEO_DISCORD_UPDATES_CHANNEL", "ceo-updates")
    )
    for channel in getattr(guild, "text_channels", []):
        if channel.name == channel_name:
            return channel
    return await guild.create_text_channel(channel_name)


async def _publish_agent_report_to_guild(guild: Any, report: Dict[str, Any]) -> None:
    category = await _ensure_agent_category(guild)
    if category is None:
        return
    channel = await _ensure_agent_channel(
        guild=guild,
        category=category,
        agent_id=str(report.get("agent_id", "agent")),
        agent_name=str(report.get("agent_name", report.get("agent_id", "Agent"))),
    )
    await channel.send(_format_agent_report_for_channel(report))


async def _ensure_created_agent_channels(guild: Any, store: MemoryStore, result: Any) -> None:
    category = await _ensure_agent_category(guild)
    if category is None:
        return
    for action in result.applied_agent_actions:
        if action.action != "create":
            continue
        agent = store.get_agent(action.agent_id)
        if agent is None:
            continue
        channel = await _ensure_agent_channel(guild, category, agent.agent_id, agent.name)
        await channel.send(
            f"Booting up **{agent.name}**.\nRole: {agent.role}\nMandate: {agent.mandate}"
        )


async def _run_company_loop(engine: CEOEngine, trigger: str, max_passes: int = 6) -> Dict[str, Any]:
    result = await asyncio.to_thread(engine.run_cycle, trigger, 25)
    all_reports = list(result.agent_reports)

    for pass_index in range(max_passes - 1):
        reports = await asyncio.to_thread(
            engine.process_agent_queue,
            f"{trigger} | follow-up pass {pass_index + 1}",
            None,
            25,
        )
        if not reports:
            break
        all_reports.extend(reports)

    return {"cycle_result": result, "reports": all_reports}


async def _publish_company_loop(
    *,
    client: Any,
    store: MemoryStore,
    agent_id: str,
    loop_result: Dict[str, Any],
    reply_channel: Optional[Any] = None,
) -> None:
    result = loop_result["cycle_result"]
    reports = loop_result["reports"]
    guild = _resolve_home_guild(client)
    non_ceo_reports = [item for item in reports if item.get("agent_id") != agent_id]

    if guild is not None:
        await _ensure_created_agent_channels(guild, store, result)
        for item in non_ceo_reports:
            await _publish_agent_report_to_guild(guild, item)
        if non_ceo_reports:
            updates_channel = reply_channel or await _ensure_updates_channel(guild)
            await updates_channel.send(_format_cycle_summary(result, non_ceo_reports))

    await _send_admin_dm(client, _format_admin_dm(result, non_ceo_reports))


async def _resolve_admin_user(client: Any) -> Optional[Any]:
    raw = os.getenv("AI_CEO_DISCORD_ADMIN_USER_ID", "").strip()
    if not raw:
        return None
    try:
        user_id = int(raw)
    except ValueError:
        return None

    cached = client.get_user(user_id)
    if cached is not None:
        return cached
    try:
        return await client.fetch_user(user_id)
    except Exception as exc:
        print(f"Failed to fetch Discord admin user {user_id}: {exc}")
        return None


async def _send_admin_dm(client: Any, content: str) -> None:
    if not content.strip():
        return
    admin_user = await _resolve_admin_user(client)
    if admin_user is None:
        return
    try:
        channel = admin_user.dm_channel or await admin_user.create_dm()
        await channel.send(content[:1900])
    except Exception as exc:
        print(f"Failed to DM Discord admin: {exc}")


async def _autonomous_ceo_loop(client: Any, engine: CEOEngine, store: MemoryStore, agent_id: str) -> None:
    interval_seconds = max(30, int(os.getenv("AI_CEO_AUTONOMOUS_INTERVAL_SECONDS", "300")))
    run_immediately = _env_flag("AI_CEO_AUTONOMOUS_RUN_ON_BOOT", default=True)
    cycle_lock: asyncio.Lock = client.autonomous_cycle_lock

    print(
        "Autonomous CEO loop configured:",
        {
            "enabled": True,
            "run_immediately": run_immediately,
            "interval_seconds": interval_seconds,
            "guild_id": os.getenv("AI_CEO_DISCORD_GUILD_ID", ""),
            "admin_user_id": os.getenv("AI_CEO_DISCORD_ADMIN_USER_ID", ""),
        },
    )
    await _send_admin_dm(client, _format_boot_dm(interval_seconds))

    if not run_immediately:
        await asyncio.sleep(interval_seconds)

    while not client.is_closed():
        try:
            async with cycle_lock:
                print("Autonomous CEO cycle starting")
                loop_result = await _run_company_loop(
                    engine=engine,
                    trigger=_autonomous_trigger(),
                )
                result = loop_result["cycle_result"]
                reports = loop_result["reports"]
                print(
                    "Autonomous CEO cycle completed",
                    {
                        "cycle_id": result.cycle_id,
                        "created_agents": [
                            action.agent_id
                            for action in result.applied_agent_actions
                            if action.action == "create"
                        ],
                        "recorded_decisions": len(result.recorded_decisions),
                        "queued_work_items": len(result.queued_work_items),
                        "reports": len(reports),
                    },
                )
                await _publish_company_loop(
                    client=client,
                    store=store,
                    agent_id=agent_id,
                    loop_result=loop_result,
                )
        except Exception as exc:
            print(f"Autonomous CEO loop failed: {exc}")
            print(traceback.format_exc())
            await _send_admin_dm(client, f"Ryan CEO loop hit an error:\n{exc}")
        await asyncio.sleep(interval_seconds)


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
    client.autonomous_cycle_lock = asyncio.Lock()
    client.autonomous_task = None

    @client.event
    async def on_ready() -> None:
        print(f"Discord agent online as {client.user} for agent {agent_id}")
        if _env_flag("AI_CEO_AUTONOMOUS_ENABLED", default=False) and client.autonomous_task is None:
            client.autonomous_task = asyncio.create_task(
                _autonomous_ceo_loop(client=client, engine=engine, store=store, agent_id=agent_id)
            )

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

        async with client.autonomous_cycle_lock:
            async with message.channel.typing():
                loop_result = await _run_company_loop(
                    engine=engine,
                    trigger=f"Discord inbound from {message.author.display_name}: {content}",
                )

        reports = loop_result["reports"]
        report = next((item for item in reports if item.get("agent_id") == agent_id), None)
        if report is None:
            await message.reply("I logged that, but I did not generate a reply.")
            return

        await _publish_company_loop(
            client=client,
            store=store,
            agent_id=agent_id,
            loop_result=loop_result,
            reply_channel=message.channel if message.guild is not None else None,
        )

        reply = _render_report_reply(report)
        await message.reply(reply, mention_author=False)

    await client.start(token)


def main() -> None:
    asyncio.run(run_discord_bot())
