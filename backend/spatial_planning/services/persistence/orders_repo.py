import json
import sqlite3

from spatial_planning.errors import ORDER_NOT_FOUND, STORAGE_ERROR, AppError
from spatial_planning.services.persistence.db import get_conn, new_id


def create_order(
    lines: list[dict],
    contact: dict,
    total: int,
    currency: str,
    display_total: int,
    eta_days: int,
    design_id: str | None,
) -> dict:
    order_id = f"ZRY-{new_id(8).upper()}"
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO orders (id, design_id, lines_json, contact_json, total, currency, "
                "display_total, eta_days, status) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    order_id, design_id, json.dumps(lines), json.dumps(contact),
                    total, currency, display_total, eta_days, "mock_confirmed",
                ),
            )
            row = conn.execute("SELECT created_at FROM orders WHERE id = ?", (order_id,)).fetchone()
    except sqlite3.Error as err:
        raise AppError(code=STORAGE_ERROR, message="Could not record the order.", status_code=500) from err
    return {
        "order_id": order_id,
        "status": "mock_confirmed",
        "total": total,
        "currency": currency,
        "display_total": display_total,
        "eta_days": eta_days,
        "lines": lines,
        "created_at": row["created_at"],
    }


def get_order(order_id: str) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        raise AppError(code=ORDER_NOT_FOUND, message="Order not found.", status_code=404)
    return {
        "order_id": row["id"],
        "status": row["status"],
        "total": row["total"],
        "currency": row["currency"],
        "display_total": row["display_total"],
        "eta_days": row["eta_days"],
        "lines": json.loads(row["lines_json"]),
        "created_at": row["created_at"],
    }
