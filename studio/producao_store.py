"""Estado de produção separado dos projetos/avaliações antigos. SQLite transacional."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS producoes(id TEXT PRIMARY KEY, body TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS eventos(
                id INTEGER PRIMARY KEY, producao TEXT NOT NULL, criado TEXT NOT NULL,
                tipo TEXT NOT NULL, body TEXT NOT NULL);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def list(self) -> list[dict]:
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM producoes ORDER BY rowid DESC")]

    def get(self, id: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT body FROM producoes WHERE id=?", (id,)).fetchone()
        if not row:
            raise ValueError("Produção não encontrada.")
        return json.loads(row[0])

    def create(self, body: dict) -> dict:
        body = {**body, "versao": 1, "atualizado": agora()}
        with self.connection() as db:
            db.execute("INSERT INTO producoes VALUES (?,?)", (body["id"], json.dumps(body, ensure_ascii=False)))
        return body

    def save(self, body: dict, expected: int | None = None) -> dict:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM producoes WHERE id=?", (body["id"],)).fetchone()
            if not row:
                raise ValueError("Produção não encontrada.")
            version = json.loads(row[0])["versao"]
            if expected is not None and version != expected:
                raise ValueError("A produção mudou em outra janela. Recarregue antes de salvar.")
            body = {**body, "versao": version + 1, "atualizado": agora()}
            db.execute("UPDATE producoes SET body=? WHERE id=?", (json.dumps(body, ensure_ascii=False), body["id"]))
        return body

    def event(self, id: str, type: str, body: dict) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO eventos(producao,criado,tipo,body) VALUES (?,?,?,?)",
                       (id, agora(), type, json.dumps(body, ensure_ascii=False)))

    def events(self, id: str) -> list[dict]:
        with self.connection() as db:
            return [{"criado": r[0], "tipo": r[1], **json.loads(r[2])} for r in db.execute(
                "SELECT criado,tipo,body FROM eventos WHERE producao=? ORDER BY id", (id,))]
