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

EMPLOYEE_TOKEN_RE = re.compile(r"^EMPLOYEE_(\d+)_DISCORD_BOT_TOKEN$")


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


def _ceo_discord_token() -> str:
    return (
        os.getenv("CEO_DISCORD_BOT_TOKEN")
        or os.getenv("DISCORD_BOT_TOKEN")
        or os.getenv("DISCORD_TOKEN")
        or ""
    ).strip()


def _discover_employee_slots() -> List[Dict[str, str]]:
    slots: List[Dict[str, str]] = []
    for name, value in os.environ.items():
        match = EMPLOYEE_TOKEN_RE.match(name)
        token = str(value or "").strip()
        if match is None or not token:
            continue
        index = int(match.group(1))
        slots.append(
            {
                "slot_id": f"employee_{index}",
                "token_env": name,
                "token": token,
                "index": str(index),
            }
        )
    slots.sort(key=lambda item: int(item["index"]))
    return slots


def _assigned_employee_slot(agent: Optional[Any]) -> str:
    if agent is None:
        return ""
    metadata = getattr(agent, "metadata", {}) or {}
    return str(metadata.get("discord_employee_slot", "")).strip()


def _assigned_agent_for_slot(store: MemoryStore, slot_id: str) -> Optional[Any]:
    if not slot_id:
        return None
    for agent in store.list_agents(status="active", limit=500):
        if _assigned_employee_slot(agent) == slot_id:
            return agent
    return None


def _assign_employee_slots(
    store: MemoryStore,
    ceo_agent_id: str,
    employee_slots: List[Dict[str, str]],
) -> List[str]:
    if not employee_slots:
        return []

    slot_lookup = {item["slot_id"]: item for item in employee_slots}
    active_agents = sorted(
        store.list_agents(status="active", limit=500),
        key=lambda item: (item.created_at, item.name.lower(), item.agent_id),
    )

    used_slots = set()
    pending_updates = []
    newly_assigned: List[str] = []
    unassigned_agents = []

    for agent in active_agents:
        if agent.agent_id == ceo_agent_id:
            continue
        slot_id = _assigned_employee_slot(agent)
        if slot_id and slot_id in slot_lookup and slot_id not in used_slots:
            used_slots.add(slot_id)
            continue
        if slot_id:
            metadata = dict(agent.metadata)
            metadata.pop("discord_employee_slot", None)
            metadata.pop("discord_employee_token_env", None)
            agent.metadata = metadata
            pending_updates.append(agent)
        unassigned_agents.append(agent)

    available_slots = [item for item in employee_slots if item["slot_id"] not in used_slots]
    for agent in unassigned_agents:
        if not available_slots:
            break
        slot = available_slots.pop(0)
        metadata = dict(agent.metadata)
        metadata["discord_employee_slot"] = slot["slot_id"]
        metadata["discord_employee_token_env"] = slot["token_env"]
        agent.metadata = metadata
        pending_updates.append(agent)
        newly_assigned.append(agent.agent_id)

    for agent in pending_updates:
        store.upsert_agent(agent)

    return newly_assigned


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


def _format_execution_summary(reports: List[Dict[str, Any]]) -> str:
    lines = ["Ryan execution update"]
    for report in reports[:5]:
        agent_name = str(report.get("agent_name", report.get("agent_id", "Agent"))).strip()
        summary = str(report.get("summary", "")).strip() or "Processed work."
        lines.append(f"- {agent_name}: {summary}")
    return "\n".join(lines).strip()


def _format_boot_dm(idle_ceo_seconds: int, poll_seconds: int) -> str:
    return (
        "Ryan CEO reactive loop is online.\n"
        f"Idle strategy threshold: {idle_ceo_seconds} seconds.\n"
        f"Idle poll: {poll_seconds} seconds.\n"
        f"Guild: {os.getenv('AI_CEO_DISCORD_GUILD_ID', '(auto)')}\n"
        f"Admin user: {os.getenv('AI_CEO_DISCORD_ADMIN_USER_ID', '(unset)')}"
    )


def _autonomous_timeout_seconds() -> int:
    return max(30, int(os.getenv("AI_CEO_AUTONOMOUS_TIMEOUT_SECONDS", "180")))


def _queue_batch_size() -> int:
    return max(1, int(os.getenv("AI_CEO_AUTONOMOUS_QUEUE_BATCH_SIZE", "1")))


def _ceo_agent_batch_size() -> int:
    return max(1, int(os.getenv("AI_CEO_AUTONOMOUS_CEO_AGENT_BATCH_SIZE", "2")))


def _ceo_follow_up_passes() -> int:
    return max(1, int(os.getenv("AI_CEO_AUTONOMOUS_CEO_FOLLOWUP_PASSES", "2")))


def _reactive_poll_seconds() -> int:
    return max(1, int(os.getenv("AI_CEO_AUTONOMOUS_IDLE_POLL_SECONDS", "3")))


def _idle_ceo_seconds() -> int:
    raw = os.getenv(
        "AI_CEO_AUTONOMOUS_IDLE_CEO_SECONDS",
        os.getenv("AI_CEO_AUTONOMOUS_INTERVAL_SECONDS", "300"),
    )
    return max(15, int(raw))


def _cycle_has_momentum(loop_result: Dict[str, Any]) -> bool:
    result = loop_result["cycle_result"]
    reports = loop_result["reports"]
    if result.applied_agent_actions:
        return True
    if result.recorded_decisions:
        return True
    if result.queued_work_items:
        return True
    if result.queued_messages:
        return True
    if reports:
        return True
    return False


def _snapshot_signature(store: MemoryStore) -> tuple:
    overview = store.system_overview()
    recent_cycle = store.recent_cycles(limit=1)
    recent_decision = store.recent_decisions(limit=1)
    recent_message = store.recent_messages(limit=1)
    recent_work = store.recent_work_items(limit=1)
    runnable = store.list_runnable_agents(limit=10)
    return (
        overview["queued_work_items"],
        overview["queued_messages"],
        tuple(agent.agent_id for agent in runnable),
        recent_cycle[0]["cycle_id"] if recent_cycle else "",
        recent_decision[0]["decision_id"] if recent_decision else "",
        recent_message[0]["message_id"] if recent_message else "",
        recent_work[0]["work_item_id"] if recent_work else "",
        recent_work[0]["updated_at"] if recent_work else "",
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


async def _ensure_message_channel(guild: Any) -> Any:
    channel_name = _slugify_channel_name(
        os.getenv(
            "AI_CEO_DISCORD_MESSAGE_CHANNEL",
            os.getenv("AI_CEO_DISCORD_UPDATES_CHANNEL", "ceo-thoughts"),
        )
    )
    for channel in getattr(guild, "text_channels", []):
        if channel.name == channel_name:
            return channel
    return await guild.create_text_channel(channel_name)


async def _resolve_channel_for_client(client: Any, channel_id: int) -> Optional[Any]:
    channel = client.get_channel(channel_id)
    if channel is not None:
        return channel
    try:
        return await client.fetch_channel(channel_id)
    except Exception:
        return None


def _client_for_agent(root_client: Any, store: MemoryStore, agent_id: str) -> Any:
    if not agent_id or agent_id == getattr(root_client, "ceo_agent_id", ""):
        return root_client
    agent = store.get_agent(agent_id)
    slot_id = _assigned_employee_slot(agent)
    employee_client = getattr(root_client, "employee_clients", {}).get(slot_id)
    if employee_client is not None and getattr(employee_client, "user", None) is not None:
        return employee_client
    return root_client


async def _send_as_agent(
    root_client: Any,
    store: MemoryStore,
    agent_id: str,
    channel_id: int,
    content: str,
) -> None:
    sender_client = _client_for_agent(root_client, store, agent_id)
    channel = await _resolve_channel_for_client(sender_client, channel_id)
    if channel is None and sender_client is not root_client:
        channel = await _resolve_channel_for_client(root_client, channel_id)
    if channel is None:
        return
    try:
        await channel.send(content[:1900])
    except Exception:
        if sender_client is root_client:
            raise
        fallback = await _resolve_channel_for_client(root_client, channel_id)
        if fallback is not None:
            await fallback.send(content[:1900])


async def _sync_employee_identity(employee_client: Any, store: MemoryStore) -> None:
    slot_id = str(getattr(employee_client, "employee_slot_id", "")).strip()
    if not slot_id or getattr(employee_client, "user", None) is None:
        return
    guild = _resolve_home_guild(employee_client)
    if guild is None:
        return

    assigned_agent = _assigned_agent_for_slot(store, slot_id)
    desired_nick = (
        (assigned_agent.name if assigned_agent is not None else slot_id.replace("_", " ").title())[:32]
    )
    try:
        member = guild.get_member(employee_client.user.id)
        if member is None:
            member = await guild.fetch_member(employee_client.user.id)
        current_nick = getattr(member, "nick", None) or ""
        if current_nick != desired_nick:
            await member.edit(nick=desired_nick, reason="AI CEO employee assignment sync")
    except Exception as exc:
        print(f"Failed to sync employee bot identity for {slot_id}: {exc}")


async def _sync_all_employee_identities(root_client: Any, store: MemoryStore) -> None:
    for employee_client in getattr(root_client, "employee_clients", {}).values():
        await _sync_employee_identity(employee_client, store)


def _format_internal_message(
    sender_name: str,
    recipient_name: str,
    subject: str,
    body: str,
) -> str:
    lines = [f"To {recipient_name}"]
    if subject.strip():
        lines.append(f"Subject: {subject.strip()}")
    if body.strip():
        lines.append(body.strip())
    return "\n".join(lines).strip()


async def _publish_internal_messages(
    *,
    root_client: Any,
    store: MemoryStore,
    guild: Any,
    sender_agent_id: str,
    sender_name: str,
    messages: List[Dict[str, Any]],
) -> None:
    if not messages:
        return
    channel = await _ensure_message_channel(guild)
    for message in messages[:10]:
        recipient_agent_id = str(message.get("recipient_agent_id", "")).strip()
        recipient_agent = store.get_agent(recipient_agent_id) if recipient_agent_id else None
        recipient_name = (
            recipient_agent.name
            if recipient_agent is not None
            else (recipient_agent_id or "the team")
        )
        content = _format_internal_message(
            sender_name=sender_name,
            recipient_name=recipient_name,
            subject=str(message.get("subject", "")),
            body=str(message.get("body", "")),
        )
        await _send_as_agent(root_client, store, sender_agent_id, channel.id, content)


async def _publish_agent_report_to_guild(root_client: Any, store: MemoryStore, guild: Any, report: Dict[str, Any]) -> None:
    category = await _ensure_agent_category(guild)
    if category is None:
        return
    channel = await _ensure_agent_channel(
        guild=guild,
        category=category,
        agent_id=str(report.get("agent_id", "agent")),
        agent_name=str(report.get("agent_name", report.get("agent_id", "Agent"))),
    )
    await _send_as_agent(
        root_client,
        store,
        str(report.get("agent_id", "")),
        channel.id,
        _format_agent_report_for_channel(report),
    )


async def _ensure_created_agent_channels(root_client: Any, guild: Any, store: MemoryStore, result: Any) -> None:
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
        await _send_as_agent(
            root_client,
            store,
            agent.agent_id,
            channel.id,
            f"Booting up **{agent.name}**.\nRole: {agent.role}\nMandate: {agent.mandate}"
        )


async def _ensure_report_created_agent_channels(
    root_client: Any,
    guild: Any,
    store: MemoryStore,
    reports: List[Dict[str, Any]],
) -> None:
    category = await _ensure_agent_category(guild)
    if category is None:
        return
    for report in reports:
        for action in report.get("applied_agent_actions", []):
            if str(action.get("action", "")).strip().lower() != "create":
                continue
            agent_id = str(action.get("agent_id", "")).strip()
            agent = store.get_agent(agent_id)
            if agent is None:
                continue
            channel = await _ensure_agent_channel(guild, category, agent.agent_id, agent.name)
            await _send_as_agent(
                root_client,
                store,
                agent.agent_id,
                channel.id,
                f"Booting up **{agent.name}**.\nRole: {agent.role}\nMandate: {agent.mandate}",
            )


async def _run_company_loop(engine: CEOEngine, trigger: str) -> Dict[str, Any]:
    result = await asyncio.to_thread(engine.run_cycle, trigger, _ceo_agent_batch_size())
    all_reports = list(result.agent_reports)

    for pass_index in range(_ceo_follow_up_passes() - 1):
        reports = await asyncio.to_thread(
            engine.process_agent_queue,
            f"{trigger} | follow-up pass {pass_index + 1}",
            None,
            _queue_batch_size(),
        )
        if not reports:
            break
        all_reports.extend(reports)

    return {"cycle_result": result, "reports": all_reports}


async def _run_queue_reaction(engine: CEOEngine, trigger: str) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(engine.process_agent_queue, trigger, None, _queue_batch_size())


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
    _assign_employee_slots(store, agent_id, getattr(client, "employee_slots", []))
    await _sync_all_employee_identities(client, store)

    if guild is not None:
        await _ensure_created_agent_channels(client, guild, store, result)
        await _publish_internal_messages(
            root_client=client,
            store=store,
            guild=guild,
            sender_agent_id=agent_id,
            sender_name=store.get_agent(agent_id).name if store.get_agent(agent_id) is not None else "Ryan Whitaker",
            messages=[item.to_dict() for item in result.queued_messages],
        )
        for item in non_ceo_reports:
            await _publish_agent_report_to_guild(client, store, guild, item)
            await _publish_internal_messages(
                root_client=client,
                store=store,
                guild=guild,
                sender_agent_id=str(item.get("agent_id", "")),
                sender_name=str(item.get("agent_name", item.get("agent_id", "Agent"))),
                messages=list(item.get("queued_outbound_messages", [])),
            )
        if non_ceo_reports:
            updates_channel = reply_channel or await _ensure_updates_channel(guild)
            await updates_channel.send(_format_cycle_summary(result, non_ceo_reports))

    await _send_admin_dm(client, _format_admin_dm(result, non_ceo_reports))


async def _publish_queue_reports(
    *,
    client: Any,
    store: MemoryStore,
    reports: List[Dict[str, Any]],
) -> None:
    if not reports:
        return

    guild = _resolve_home_guild(client)
    _assign_employee_slots(store, getattr(client, "ceo_agent_id", ""), getattr(client, "employee_slots", []))
    await _sync_all_employee_identities(client, store)
    if guild is not None:
        updates_channel = await _ensure_updates_channel(guild)
        await updates_channel.send(_format_execution_summary(reports))
        await _ensure_report_created_agent_channels(client, guild, store, reports)
        for item in reports:
            await _publish_agent_report_to_guild(client, store, guild, item)
            await _publish_internal_messages(
                root_client=client,
                store=store,
                guild=guild,
                sender_agent_id=str(item.get("agent_id", "")),
                sender_name=str(item.get("agent_name", item.get("agent_id", "Agent"))),
                messages=list(item.get("queued_outbound_messages", [])),
            )

    await _send_admin_dm(
        client,
        _format_execution_summary(reports),
        dedupe_key=f"execution:{'|'.join(str(item.get('agent_id', '')) for item in reports[:5])}:{len(reports)}",
    )


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


async def _send_admin_dm(client: Any, content: str, dedupe_key: str = "") -> None:
    if not content.strip():
        return
    if dedupe_key and getattr(client, "last_admin_dm_key", "") == dedupe_key:
        return
    admin_user = await _resolve_admin_user(client)
    if admin_user is None:
        return
    try:
        channel = admin_user.dm_channel or await admin_user.create_dm()
        await channel.send(content[:1900])
        if dedupe_key:
            client.last_admin_dm_key = dedupe_key
        else:
            client.last_admin_dm_key = ""
    except Exception as exc:
        print(f"Failed to DM Discord admin: {exc}")


async def _autonomous_ceo_loop(client: Any, engine: CEOEngine, store: MemoryStore, agent_id: str) -> None:
    idle_ceo_seconds = _idle_ceo_seconds()
    poll_seconds = _reactive_poll_seconds()
    timeout_seconds = _autonomous_timeout_seconds()
    run_immediately = _env_flag("AI_CEO_AUTONOMOUS_RUN_ON_BOOT", default=True)
    momentum_sleep_seconds = max(
        1, int(os.getenv("AI_CEO_AUTONOMOUS_MOMENTUM_SLEEP_SECONDS", "3"))
    )
    max_continuous_cycles = max(
        1, int(os.getenv("AI_CEO_AUTONOMOUS_MAX_CONTINUOUS_CYCLES", "25"))
    )
    cycle_lock: asyncio.Lock = client.autonomous_cycle_lock
    continuous_cycles = 0
    loop = asyncio.get_running_loop()
    last_ceo_cycle_at = 0.0
    last_signature = _snapshot_signature(store)
    force_ceo_cycle = run_immediately

    print(
        "Reactive CEO loop configured:",
        {
            "enabled": True,
            "run_immediately": run_immediately,
            "idle_ceo_seconds": idle_ceo_seconds,
            "poll_seconds": poll_seconds,
            "momentum_sleep_seconds": momentum_sleep_seconds,
            "max_continuous_cycles": max_continuous_cycles,
            "timeout_seconds": timeout_seconds,
            "guild_id": os.getenv("AI_CEO_DISCORD_GUILD_ID", ""),
            "admin_user_id": os.getenv("AI_CEO_DISCORD_ADMIN_USER_ID", ""),
        },
    )
    await _send_admin_dm(client, _format_boot_dm(idle_ceo_seconds, poll_seconds), dedupe_key="boot")

    while not client.is_closed():
        next_sleep_seconds = poll_seconds
        phase = "idle"
        try:
            signature = _snapshot_signature(store)
            state_changed = signature != last_signature
            last_signature = signature
            async with cycle_lock:
                handled_cycle = False
                has_runnable_work = bool(store.list_runnable_agents(limit=1))
                if has_runnable_work:
                    phase = "queue"
                    print("Reactive queue pass starting")
                    reports = await asyncio.wait_for(
                        _run_queue_reaction(
                            engine=engine,
                            trigger="Reactive queue processing",
                        ),
                        timeout=timeout_seconds,
                    )
                    if reports:
                        print("Reactive queue pass completed", {"reports": len(reports)})
                        await _publish_queue_reports(client=client, store=store, reports=reports)
                        last_signature = _snapshot_signature(store)
                        next_sleep_seconds = momentum_sleep_seconds
                        handled_cycle = True

                should_run_ceo = (
                    not handled_cycle
                    and (
                        force_ceo_cycle
                        or (state_changed and not has_runnable_work)
                        or ((loop.time() - last_ceo_cycle_at) >= idle_ceo_seconds and not has_runnable_work)
                    )
                )

                if not should_run_ceo and not handled_cycle:
                    print(f"Reactive CEO loop idle; polling again in {poll_seconds} seconds")
                    next_sleep_seconds = poll_seconds
                    handled_cycle = True

                if should_run_ceo:
                    phase = "ceo_cycle"
                    print("Reactive CEO cycle starting")
                    loop_result = await asyncio.wait_for(
                        _run_company_loop(
                            engine=engine,
                            trigger=_autonomous_trigger(),
                        ),
                        timeout=timeout_seconds,
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
                    last_ceo_cycle_at = loop.time()
                    force_ceo_cycle = False
                    last_signature = _snapshot_signature(store)
                    if _cycle_has_momentum(loop_result) and continuous_cycles < max_continuous_cycles:
                        continuous_cycles += 1
                        print(f"Reactive CEO loop continuing immediately (cycle streak {continuous_cycles})")
                        next_sleep_seconds = momentum_sleep_seconds
                    else:
                        continuous_cycles = 0
                        next_sleep_seconds = poll_seconds
        except asyncio.TimeoutError:
            message = (
                f"Ryan {phase.replace('_', ' ')} timed out after {timeout_seconds} seconds.\n"
                f"Model: {os.getenv('AI_CEO_DISCORD_MODEL') or os.getenv('AI_CEO_MODEL', '(unset)')}\n"
                "Recommendation: use a faster model for the autonomous loop."
            )
            print(message)
            await _send_admin_dm(
                client,
                message,
                dedupe_key=f"timeout:{phase}:{timeout_seconds}:{os.getenv('AI_CEO_DISCORD_MODEL') or os.getenv('AI_CEO_MODEL', '(unset)')}",
            )
            continuous_cycles = 0
            next_sleep_seconds = poll_seconds
        except Exception as exc:
            print(f"Autonomous CEO loop failed: {exc}")
            print(traceback.format_exc())
            await _send_admin_dm(
                client,
                f"Ryan CEO loop hit an error:\n{exc}",
                dedupe_key=f"error:{type(exc).__name__}:{str(exc)}",
            )
            continuous_cycles = 0
            next_sleep_seconds = poll_seconds
        print(f"Reactive CEO loop sleeping for {next_sleep_seconds} seconds")
        await asyncio.sleep(next_sleep_seconds)


async def run_discord_bot() -> None:
    load_env_file()

    token = _ceo_discord_token()
    if not token:
        raise RuntimeError(
            "Set CEO_DISCORD_BOT_TOKEN in .env.local before starting the Discord bot."
        )

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
    employee_slots = _discover_employee_slots()
    _assign_employee_slots(store, agent_id, employee_slots)

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
    client.last_admin_dm_key = ""
    client.employee_slots = employee_slots
    client.employee_clients = {}
    client.ceo_agent_id = agent_id

    @client.event
    async def on_ready() -> None:
        print(f"Discord agent online as {client.user} for agent {agent_id}")
        await _sync_all_employee_identities(client, store)
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

    def _build_employee_client(slot: Dict[str, str]) -> Any:
        employee_client = discord.Client(intents=intents)
        employee_client.employee_slot_id = slot["slot_id"]

        @employee_client.event
        async def on_ready() -> None:
            print(
                f"Discord employee bot online as {employee_client.user} for slot {slot['slot_id']}"
            )
            await _sync_employee_identity(employee_client, store)

        @employee_client.event
        async def on_message(message: discord.Message) -> None:
            if employee_client.user is None:
                return
            if message.author.bot:
                return

            assigned_agent = _assigned_agent_for_slot(store, slot["slot_id"])
            if assigned_agent is None:
                return

            is_dm = isinstance(message.channel, discord.DMChannel)
            mentioned = employee_client.user in getattr(message, "mentions", [])
            if not is_dm and not mentioned:
                return

            content = _clean_discord_content(message=message, client_user_id=employee_client.user.id)
            if not content:
                return

            sender_id = f"discord:{message.author.id}"
            subject = f"Discord message for {assigned_agent.name} from {message.author.display_name}"
            body = (
                f"Discord context\n"
                f"- author: {message.author.display_name}\n"
                f"- channel: {getattr(message.channel, 'id', 'dm')}\n"
                f"- guild: {getattr(getattr(message, 'guild', None), 'name', 'DM')}\n\n"
                f"You are replying as {assigned_agent.name}. Reply naturally like a real teammate in Discord. "
                "Use first person and do not output a status report.\n\n"
                f"Message:\n{content}"
            )

            engine.send_message(
                recipient_agent_id=assigned_agent.agent_id,
                subject=subject,
                body=body,
                sender_type="human",
                sender_id=sender_id,
                thread_id=str(message.channel.id),
            )

            async with client.autonomous_cycle_lock:
                async with message.channel.typing():
                    reports = await _run_queue_reaction(
                        engine=engine,
                        trigger=f"Discord inbound for {assigned_agent.name} from {message.author.display_name}: {content}",
                    )

            report = next(
                (item for item in reports if item.get("agent_id") == assigned_agent.agent_id),
                None,
            )
            if report is None:
                await message.reply("I logged that, but I did not generate a reply.")
                return

            await _publish_queue_reports(client=client, store=store, reports=reports)
            await message.reply(_render_report_reply(report), mention_author=False)

        return employee_client

    for slot in employee_slots:
        client.employee_clients[slot["slot_id"]] = _build_employee_client(slot)

    tasks = [asyncio.create_task(client.start(token))]
    for slot in employee_slots:
        tasks.append(
            asyncio.create_task(client.employee_clients[slot["slot_id"]].start(slot["token"]))
        )

    await asyncio.gather(*tasks)


def main() -> None:
    asyncio.run(run_discord_bot())
