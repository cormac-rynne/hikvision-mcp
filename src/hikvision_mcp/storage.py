from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from .errors import error
from .models import ChangeProposal

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS change_proposals (
  id TEXT PRIMARY KEY,
  camera_alias TEXT NOT NULL,
  operation TEXT NOT NULL,
  request_json TEXT NOT NULL,
  current_semantic_json TEXT NOT NULL,
  current_raw TEXT,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS changes (
  id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL,
  camera_alias TEXT NOT NULL,
  operation TEXT NOT NULL,
  before_semantic_json TEXT NOT NULL,
  after_semantic_json TEXT NOT NULL,
  before_raw TEXT,
  after_raw TEXT,
  rollback_supported INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  result TEXT NOT NULL,
  error_code TEXT,
  FOREIGN KEY(proposal_id) REFERENCES change_proposals(id)
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL,
  client_name TEXT,
  camera_alias TEXT,
  tool TEXT NOT NULL,
  permission_level INTEGER NOT NULL,
  action TEXT NOT NULL,
  approval_required INTEGER NOT NULL,
  approval_result TEXT,
  result TEXT NOT NULL,
  error_code TEXT,
  duration_ms INTEGER,
  metadata_json TEXT NOT NULL
);
"""


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        def run() -> None:
            with self._connect() as connection:
                connection.executescript(SCHEMA)
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (1, ?)",
                    (datetime.now(UTC).isoformat(),),
                )

        await asyncio.to_thread(run)

    async def create_proposal(
        self,
        *,
        camera: str,
        operation: str,
        request: dict[str, object],
        current_semantic: dict[str, object],
        current_raw: str | None,
        ttl_seconds: int,
    ) -> ChangeProposal:
        now = datetime.now(UTC)
        proposal = ChangeProposal(
            id=f"chg_{uuid.uuid4().hex}",
            camera_alias=camera,
            operation=operation,
            request=request,
            current_semantic=current_semantic,
            current_raw=current_raw,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            status="pending",
        )

        def run() -> None:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO change_proposals
                    (id,camera_alias,operation,request_json,current_semantic_json,current_raw,
                     created_at,expires_at,status) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        proposal.id,
                        camera,
                        operation,
                        _json(request),
                        _json(current_semantic),
                        current_raw,
                        now.isoformat(),
                        proposal.expires_at.isoformat(),
                        proposal.status,
                    ),
                )

        await asyncio.to_thread(run)
        return proposal

    async def get_proposal(self, proposal_id: str) -> ChangeProposal:
        def run() -> sqlite3.Row | None:
            with self._connect() as connection:
                return cast(
                    sqlite3.Row | None,
                    connection.execute(
                        "SELECT * FROM change_proposals WHERE id=?", (proposal_id,)
                    ).fetchone(),
                )

        row = await asyncio.to_thread(run)
        if row is None:
            raise error(
                "approval_expired", "Change proposal was not found", proposal_id=proposal_id
            )
        proposal = ChangeProposal(
            id=row["id"],
            camera_alias=row["camera_alias"],
            operation=row["operation"],
            request=json.loads(row["request_json"]),
            current_semantic=json.loads(row["current_semantic_json"]),
            current_raw=row["current_raw"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            status=row["status"],
        )
        if proposal.status == "pending" and proposal.expires_at < datetime.now(UTC):
            await self.set_proposal_status(proposal_id, "expired")
            raise error("approval_expired", "Change proposal has expired", proposal_id=proposal_id)
        return proposal

    async def set_proposal_status(self, proposal_id: str, status: str) -> None:
        def run() -> None:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE change_proposals SET status=? WHERE id=?", (status, proposal_id)
                )

        await asyncio.to_thread(run)

    async def record_change(
        self,
        *,
        proposal: ChangeProposal,
        before_semantic: dict[str, object],
        after_semantic: dict[str, object],
        before_raw: str | None,
        after_raw: str | None,
        rollback_supported: bool,
    ) -> str:
        change_id = f"change_{uuid.uuid4().hex}"

        def run() -> None:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO changes
                    (id,proposal_id,camera_alias,operation,before_semantic_json,
                     after_semantic_json,before_raw,after_raw,rollback_supported,
                     created_at,result,error_code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        change_id,
                        proposal.id,
                        proposal.camera_alias,
                        proposal.operation,
                        _json(before_semantic),
                        _json(after_semantic),
                        before_raw,
                        after_raw,
                        int(rollback_supported),
                        datetime.now(UTC).isoformat(),
                        "success",
                        None,
                    ),
                )
                connection.execute(
                    "UPDATE change_proposals SET status='applied' WHERE id=?", (proposal.id,)
                )

        await asyncio.to_thread(run)
        return change_id

    async def get_change(self, change_id: str) -> dict[str, Any]:
        def run() -> sqlite3.Row | None:
            with self._connect() as connection:
                return cast(
                    sqlite3.Row | None,
                    connection.execute("SELECT * FROM changes WHERE id=?", (change_id,)).fetchone(),
                )

        row = await asyncio.to_thread(run)
        if row is None:
            raise error("rollback_unavailable", "Change was not found", change_id=change_id)
        return self._change_dict(row)

    async def history(self, camera: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        def run() -> list[sqlite3.Row]:
            with self._connect() as connection:
                if camera:
                    return connection.execute(
                        """SELECT * FROM changes WHERE camera_alias=?
                        ORDER BY created_at DESC LIMIT ?""",
                        (camera, limit),
                    ).fetchall()
                return connection.execute(
                    "SELECT * FROM changes ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()

        return [self._change_dict(row) for row in await asyncio.to_thread(run)]

    @staticmethod
    def _change_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "proposal_id": row["proposal_id"],
            "camera": row["camera_alias"],
            "operation": row["operation"],
            "before": json.loads(row["before_semantic_json"]),
            "after": json.loads(row["after_semantic_json"]),
            "before_raw": row["before_raw"],
            "after_raw": row["after_raw"],
            "rollback_supported": bool(row["rollback_supported"]),
            "created_at": row["created_at"],
            "result": row["result"],
            "error_code": row["error_code"],
        }

    async def audit(
        self,
        *,
        camera: str | None,
        tool: str,
        permission_level: int,
        action: str,
        approval_required: bool,
        approval_result: str | None,
        result: str,
        error_code: str | None = None,
        duration_ms: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        def run() -> None:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO audit_log
                    (timestamp,client_name,camera_alias,tool,permission_level,action,
                     approval_required,approval_result,result,error_code,duration_ms,metadata_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        datetime.now(UTC).isoformat(),
                        None,
                        camera,
                        tool,
                        permission_level,
                        action,
                        int(approval_required),
                        approval_result,
                        result,
                        error_code,
                        duration_ms,
                        _json(metadata or {}),
                    ),
                )

        await asyncio.to_thread(run)
