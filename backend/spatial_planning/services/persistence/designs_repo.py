import json
import sqlite3

from spatial_planning.errors import DESIGN_NOT_FOUND, STORAGE_ERROR, AppError
from spatial_planning.services.persistence.db import get_conn, new_id


def save_design(name: str, payload: dict, total_price: int, item_count: int) -> str:
    design_id = new_id()
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO designs (id, name, payload_json, total_price, item_count) VALUES (?,?,?,?,?)",
                (design_id, name, json.dumps(payload), total_price, item_count),
            )
    except sqlite3.Error as err:
        raise AppError(code=STORAGE_ERROR, message="Could not save the design.", status_code=500) from err
    return design_id


def get_design(design_id: str) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM designs WHERE id = ?", (design_id,)).fetchone()
    if row is None:
        raise AppError(code=DESIGN_NOT_FOUND, message="This saved design does not exist.", status_code=404)
    return {
        "design_id": row["id"],
        "name": row["name"],
        "total_price": row["total_price"],
        "item_count": row["item_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        **json.loads(row["payload_json"]),
    }


def list_designs(limit: int = 20, offset: int = 0) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, total_price, item_count, created_at "
            "FROM designs ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [
        {
            "design_id": r["id"],
            "name": r["name"],
            "total_price": r["total_price"],
            "item_count": r["item_count"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
