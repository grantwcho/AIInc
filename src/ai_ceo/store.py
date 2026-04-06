from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    AgentSpec,
    DecisionPlan,
    MemoryNote,
    MessagePlan,
    ObjectiveState,
    WorkItemPlan,
)
from .utils import make_id, utc_now


class MemoryStore:
    def __init__(self, db_path: str = "state/ai_ceo.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.fts_enabled = False
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS objective_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    company_name TEXT NOT NULL,
                    ultimate_objective TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    operating_principles TEXT NOT NULL,
                    last_self_prompt TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cycles (
                    cycle_id TEXT PRIMARY KEY,
                    trigger_text TEXT NOT NULL,
                    reflection_summary TEXT NOT NULL,
                    self_prompt TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    mandate TEXT NOT NULL,
                    system_prompt TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_focus TEXT NOT NULL,
                    success_metric TEXT NOT NULL,
                    parent_agent_id TEXT NOT NULL,
                    creator_type TEXT NOT NULL,
                    creator_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS work_items (
                    work_item_id TEXT PRIMARY KEY,
                    owner_agent_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    requested_by_type TEXT NOT NULL,
                    requested_by_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    sender_type TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    recipient_agent_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT PRIMARY KEY,
                    cycle_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    expected_impact TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_agent_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    importance INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_agents_status_updated
                ON agents(status, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_work_items_owner_status
                ON work_items(owner_agent_id, status, created_at);

                CREATE INDEX IF NOT EXISTS idx_work_items_status
                ON work_items(status, created_at);

                CREATE INDEX IF NOT EXISTS idx_messages_recipient_status
                ON messages(recipient_agent_id, status, created_at);

                CREATE INDEX IF NOT EXISTS idx_messages_status
                ON messages(status, created_at);
                """
            )

            self._ensure_column(
                conn, "agents", "creator_type", "TEXT NOT NULL DEFAULT 'ceo'"
            )
            self._ensure_column(
                conn, "agents", "creator_id", "TEXT NOT NULL DEFAULT 'ceo'"
            )
            self._ensure_column(conn, "agents", "model", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(
                conn, "agents", "metadata", "TEXT NOT NULL DEFAULT '{}'"
            )
            self._ensure_column(
                conn,
                "work_items",
                "requested_by_type",
                "TEXT NOT NULL DEFAULT 'ceo'",
            )
            self._ensure_column(
                conn,
                "work_items",
                "requested_by_id",
                "TEXT NOT NULL DEFAULT 'ceo'",
            )

            try:
                conn.executescript(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                    USING fts5(title, content, tags, content='memories', content_rowid='id');

                    CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                      INSERT INTO memories_fts(rowid, title, content, tags)
                      VALUES (new.id, new.title, new.content, new.tags);
                    END;

                    CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                      INSERT INTO memories_fts(memories_fts, rowid, title, content, tags)
                      VALUES ('delete', old.id, old.title, old.content, old.tags);
                    END;

                    CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                      INSERT INTO memories_fts(memories_fts, rowid, title, content, tags)
                      VALUES ('delete', old.id, old.title, old.content, old.tags);
                      INSERT INTO memories_fts(rowid, title, content, tags)
                      VALUES (new.id, new.title, new.content, new.tags);
                    END;
                    """
                )
                self.fts_enabled = True
            except sqlite3.OperationalError:
                self.fts_enabled = False

    def _ensure_column(
        self, conn: sqlite3.Connection, table_name: str, column_name: str, definition: str
    ) -> None:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(%s)" % table_name).fetchall()
        }
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def bootstrap_objective(
        self,
        company_name: str,
        ultimate_objective: str,
        strategy: Optional[str] = None,
        operating_principles: Optional[List[str]] = None,
        last_self_prompt: str = "",
    ) -> ObjectiveState:
        existing = self.load_objective()
        if existing is not None:
            return existing

        objective = ObjectiveState(
            company_name=company_name,
            ultimate_objective=ultimate_objective,
            strategy=strategy
            or (
                "Pursue compounding advantages in product, distribution, and talent. "
                "Use fast feedback loops and institutional memory to stay ahead."
            ),
            operating_principles=operating_principles
            or [
                "Protect the ultimate objective from drift.",
                "Prefer strategies that compound over time.",
                "Write down important decisions and use them in future cycles.",
                "Create specialist agents only when they increase leverage.",
                "Trade speed for quality only when compounding value justifies it.",
            ],
            last_self_prompt=last_self_prompt
            or "What is the highest-leverage move that compounds our advantage this cycle?",
        )
        self.save_objective(objective)
        self.record_memory(
            source_agent_id="ceo",
            note=MemoryNote(
                title="Founding objective",
                content=ultimate_objective,
                category="org",
                importance=10,
                tags=["objective", company_name.lower().replace(" ", "_")],
            ),
        )
        return objective

    def save_objective(self, objective: ObjectiveState) -> None:
        objective.updated_at = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO objective_state (
                    id, company_name, ultimate_objective, strategy,
                    operating_principles, last_self_prompt, updated_at
                )
                VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    company_name = excluded.company_name,
                    ultimate_objective = excluded.ultimate_objective,
                    strategy = excluded.strategy,
                    operating_principles = excluded.operating_principles,
                    last_self_prompt = excluded.last_self_prompt,
                    updated_at = excluded.updated_at
                """,
                (
                    objective.company_name,
                    objective.ultimate_objective,
                    objective.strategy,
                    json.dumps(objective.operating_principles),
                    objective.last_self_prompt,
                    objective.updated_at,
                ),
            )

    def load_objective(self) -> Optional[ObjectiveState]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM objective_state WHERE id = 1").fetchone()
        if row is None:
            return None
        return ObjectiveState(
            company_name=row["company_name"],
            ultimate_objective=row["ultimate_objective"],
            strategy=row["strategy"],
            operating_principles=json.loads(row["operating_principles"]),
            last_self_prompt=row["last_self_prompt"],
            updated_at=row["updated_at"],
        )

    def record_cycle(
        self, trigger_text: str, reflection_summary: str, self_prompt: str
    ) -> str:
        cycle_id = make_id("cycle")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cycles (
                    cycle_id, trigger_text, reflection_summary, self_prompt, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (cycle_id, trigger_text, reflection_summary, self_prompt, utc_now()),
            )
        return cycle_id

    def record_memory(self, source_agent_id: str, note: MemoryNote) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memories (
                    source_agent_id, category, title, content, tags, importance, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_agent_id,
                    note.category,
                    note.title,
                    note.content,
                    json.dumps(note.tags),
                    note.importance,
                    utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def recent_memories(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memories
                ORDER BY created_at DESC, importance DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._memory_row_to_dict(row) for row in rows]

    def search_memories(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        if not query.strip():
            return self.recent_memories(limit=limit)

        with self._connect() as conn:
            if self.fts_enabled:
                try:
                    rows = conn.execute(
                        """
                        SELECT m.*
                        FROM memories_fts
                        JOIN memories AS m ON m.id = memories_fts.rowid
                        WHERE memories_fts MATCH ?
                        ORDER BY m.importance DESC, m.created_at DESC
                        LIMIT ?
                        """,
                        (query, limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            else:
                rows = []

            if not rows:
                like_term = f"%{query}%"
                rows = conn.execute(
                    """
                    SELECT * FROM memories
                    WHERE title LIKE ? OR content LIKE ?
                    ORDER BY importance DESC, created_at DESC
                    LIMIT ?
                    """,
                    (like_term, like_term, limit),
                ).fetchall()
        return [self._memory_row_to_dict(row) for row in rows]

    def upsert_agent(self, agent: AgentSpec) -> AgentSpec:
        existing = self.get_agent(agent.agent_id)
        if existing is not None:
            agent.created_at = existing.created_at
            agent.version = existing.version + 1
            if not agent.creator_type:
                agent.creator_type = existing.creator_type
            if not agent.creator_id:
                agent.creator_id = existing.creator_id
            if not agent.parent_agent_id:
                agent.parent_agent_id = existing.parent_agent_id
            if not agent.model:
                agent.model = existing.model
            if not agent.metadata:
                agent.metadata = existing.metadata
        agent.updated_at = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agents (
                    agent_id, name, role, mandate, system_prompt, status, current_focus,
                    success_metric, parent_agent_id, creator_type, creator_id, model,
                    metadata, version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    name = excluded.name,
                    role = excluded.role,
                    mandate = excluded.mandate,
                    system_prompt = excluded.system_prompt,
                    status = excluded.status,
                    current_focus = excluded.current_focus,
                    success_metric = excluded.success_metric,
                    parent_agent_id = excluded.parent_agent_id,
                    creator_type = excluded.creator_type,
                    creator_id = excluded.creator_id,
                    model = excluded.model,
                    metadata = excluded.metadata,
                    version = excluded.version,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    agent.agent_id,
                    agent.name,
                    agent.role,
                    agent.mandate,
                    agent.system_prompt,
                    agent.status,
                    agent.current_focus,
                    agent.success_metric,
                    agent.parent_agent_id,
                    agent.creator_type,
                    agent.creator_id,
                    agent.model,
                    json.dumps(agent.metadata),
                    agent.version,
                    agent.created_at,
                    agent.updated_at,
                ),
            )
        return agent

    def get_agent(self, agent_id: str) -> Optional[AgentSpec]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
            ).fetchone()
        if row is None:
            return None
        return self._agent_row_to_model(row)

    def list_agents(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        creator_type: Optional[str] = None,
    ) -> List[AgentSpec]:
        query = "SELECT * FROM agents WHERE 1=1"
        params: List[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if creator_type:
            query += " AND creator_type = ?"
            params.append(creator_type)
        query += " ORDER BY updated_at DESC, name ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._agent_row_to_model(row) for row in rows]

    def terminate_agent(self, agent_id: str, reason: str) -> Optional[AgentSpec]:
        agent = self.get_agent(agent_id)
        if agent is None:
            return None
        agent.status = "terminated"
        agent.current_focus = reason or "Terminated by supervisor."
        return self.upsert_agent(agent)

    def summarize_agents(self, limit: int = 20, status: Optional[str] = "active") -> List[Dict[str, Any]]:
        return [agent.to_dict() for agent in self.list_agents(status=status, limit=limit)]

    def list_agent_queue_summaries(
        self,
        status: Optional[str] = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT
                a.*,
                COALESCE(w.queued_work_items, 0) AS queued_work_items,
                COALESCE(m.queued_messages, 0) AS queued_messages
            FROM agents AS a
            LEFT JOIN (
                SELECT owner_agent_id, COUNT(*) AS queued_work_items
                FROM work_items
                WHERE status = 'queued'
                GROUP BY owner_agent_id
            ) AS w ON w.owner_agent_id = a.agent_id
            LEFT JOIN (
                SELECT recipient_agent_id, COUNT(*) AS queued_messages
                FROM messages
                WHERE status = 'queued'
                GROUP BY recipient_agent_id
            ) AS m ON m.recipient_agent_id = a.agent_id
            WHERE 1 = 1
        """
        params: List[Any] = []
        if status:
            query += " AND a.status = ?"
            params.append(status)
        query += """
            ORDER BY
                (COALESCE(w.queued_work_items, 0) + COALESCE(m.queued_messages, 0)) DESC,
                a.updated_at DESC,
                a.name ASC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        payload: List[Dict[str, Any]] = []
        for row in rows:
            item = self._agent_row_to_model(row).to_dict()
            item["queued_work_items"] = int(row["queued_work_items"])
            item["queued_messages"] = int(row["queued_messages"])
            payload.append(item)
        return payload

    def list_runnable_agents(self, limit: int = 25) -> List[AgentSpec]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT a.*
                FROM agents AS a
                JOIN (
                    SELECT agent_id, MIN(next_event_at) AS next_event_at
                    FROM (
                        SELECT owner_agent_id AS agent_id, MIN(created_at) AS next_event_at
                        FROM work_items
                        WHERE status = 'queued'
                        GROUP BY owner_agent_id

                        UNION ALL

                        SELECT recipient_agent_id AS agent_id, MIN(created_at) AS next_event_at
                        FROM messages
                        WHERE status = 'queued'
                        GROUP BY recipient_agent_id
                    ) AS queue_events
                    GROUP BY agent_id
                ) AS runnable ON runnable.agent_id = a.agent_id
                WHERE a.status = 'active'
                ORDER BY runnable.next_event_at ASC, a.updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._agent_row_to_model(row) for row in rows]

    def create_work_item(self, plan: WorkItemPlan) -> str:
        work_item_id = make_id("work")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO work_items (
                    work_item_id, owner_agent_id, title, description, priority,
                    requested_by_type, requested_by_id, status, resolution,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', '', ?, ?)
                """,
                (
                    work_item_id,
                    plan.owner_agent_id,
                    plan.title,
                    plan.description,
                    plan.priority,
                    plan.requested_by_type,
                    plan.requested_by_id,
                    now,
                    now,
                ),
            )
        return work_item_id

    def list_work_items(
        self,
        owner_agent_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM work_items WHERE 1=1"
        params: List[Any] = []
        if owner_agent_id:
            query += " AND owner_agent_id = ?"
            params.append(owner_agent_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def claim_work_items(self, owner_agent_id: str, limit: int = 25) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM work_items
                WHERE owner_agent_id = ? AND status = 'queued'
                ORDER BY
                    CASE priority
                        WHEN 'high' THEN 0
                        WHEN 'medium' THEN 1
                        ELSE 2
                    END,
                    created_at ASC
                LIMIT ?
                """,
                (owner_agent_id, limit),
            ).fetchall()
            ids = [row["work_item_id"] for row in rows]
            if ids:
                conn.executemany(
                    """
                    UPDATE work_items
                    SET status = 'in_progress', updated_at = ?
                    WHERE work_item_id = ?
                    """,
                    [(utc_now(), item_id) for item_id in ids],
                )
        return [dict(row) for row in rows]

    def close_work_items(
        self, work_item_ids: List[str], status: str, resolution: str
    ) -> None:
        if not work_item_ids:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                UPDATE work_items
                SET status = ?, resolution = ?, updated_at = ?
                WHERE work_item_id = ?
                """,
                [
                    (status, resolution, utc_now(), work_item_id)
                    for work_item_id in work_item_ids
                ],
            )

    def enqueue_message(self, message: MessagePlan) -> str:
        message_id = make_id("msg")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (
                    message_id, sender_type, sender_id, recipient_agent_id, subject,
                    body, thread_id, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    message_id,
                    message.sender_type,
                    message.sender_id,
                    message.recipient_agent_id,
                    message.subject,
                    message.body,
                    message.thread_id,
                    now,
                    now,
                ),
            )
        return message_id

    def list_messages(
        self,
        recipient_agent_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM messages WHERE 1=1"
        params: List[Any] = []
        if recipient_agent_id:
            query += " AND recipient_agent_id = ?"
            params.append(recipient_agent_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def recent_messages(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM messages
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def claim_messages(self, recipient_agent_id: str, limit: int = 25) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE recipient_agent_id = ? AND status = 'queued'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (recipient_agent_id, limit),
            ).fetchall()
            ids = [row["message_id"] for row in rows]
            if ids:
                conn.executemany(
                    """
                    UPDATE messages
                    SET status = 'in_progress', updated_at = ?
                    WHERE message_id = ?
                    """,
                    [(utc_now(), item_id) for item_id in ids],
                )
        return [dict(row) for row in rows]

    def close_messages(self, message_ids: List[str], status: str = "delivered") -> None:
        if not message_ids:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                UPDATE messages
                SET status = ?, updated_at = ?
                WHERE message_id = ?
                """,
                [(status, utc_now(), message_id) for message_id in message_ids],
            )

    def record_decision(
        self, cycle_id: str, agent_id: str, decision: DecisionPlan
    ) -> str:
        decision_id = make_id("decision")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO decisions (
                    decision_id, cycle_id, agent_id, title, summary, rationale,
                    expected_impact, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    cycle_id,
                    agent_id,
                    decision.title,
                    decision.summary,
                    decision.rationale,
                    decision.expected_impact,
                    utc_now(),
                ),
            )
        return decision_id

    def recent_decisions(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM decisions
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_cycles(self, limit: int = 5) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM cycles
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_work_items(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM work_items
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def system_overview(self) -> Dict[str, int]:
        with self._connect() as conn:
            total_agents = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
            active_agents = conn.execute(
                "SELECT COUNT(*) FROM agents WHERE status = 'active'"
            ).fetchone()[0]
            queued_work_items = conn.execute(
                "SELECT COUNT(*) FROM work_items WHERE status = 'queued'"
            ).fetchone()[0]
            queued_messages = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE status = 'queued'"
            ).fetchone()[0]
        return {
            "total_agents": int(total_agents),
            "active_agents": int(active_agents),
            "queued_work_items": int(queued_work_items),
            "queued_messages": int(queued_messages),
        }

    def _agent_row_to_model(self, row: sqlite3.Row) -> AgentSpec:
        metadata = row["metadata"] if "metadata" in row.keys() else "{}"
        try:
            parsed_metadata = json.loads(metadata) if metadata else {}
        except json.JSONDecodeError:
            parsed_metadata = {}

        creator_type = row["creator_type"] if "creator_type" in row.keys() else "ceo"
        creator_id = row["creator_id"] if "creator_id" in row.keys() else "ceo"
        model = row["model"] if "model" in row.keys() else ""

        return AgentSpec(
            agent_id=row["agent_id"],
            name=row["name"],
            role=row["role"],
            mandate=row["mandate"],
            system_prompt=row["system_prompt"],
            status=row["status"],
            current_focus=row["current_focus"],
            success_metric=row["success_metric"],
            parent_agent_id=row["parent_agent_id"],
            creator_type=creator_type,
            creator_id=creator_id,
            model=model,
            metadata=parsed_metadata,
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _memory_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        payload = dict(row)
        payload["tags"] = json.loads(payload["tags"])
        return payload
