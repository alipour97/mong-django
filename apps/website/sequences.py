"""
PostgreSQL id counters that fell behind their tables.

Rows imported with their own ids (Dadehfa imports, restored dumps, one-off
scripts) leave the table's counter where it was, and the next new row collides
("duplicate key value violates unique constraint …_pkey"). This moves each
counter past the table's largest id. A counter already ahead is left alone, so
ids of deleted rows are never given out again.
"""
from __future__ import annotations

from django.db import connection


def move_past_ids(models) -> list[str]:
    """Moves the counters of these models' tables; returns the tables that were behind."""
    if connection.vendor != "postgresql":
        return []
    moved = []
    with connection.cursor() as cursor:
        for model in models:
            meta = model._meta
            pk = meta.pk
            if not meta.managed or meta.proxy or pk is None or pk.get_internal_type() not in (
                "AutoField", "BigAutoField", "SmallAutoField",
            ):
                continue
            table, column = meta.db_table, pk.column
            cursor.execute("SELECT pg_get_serial_sequence(%s, %s)", [connection.ops.quote_name(table), column])
            sequence = cursor.fetchone()[0]
            if not sequence:
                continue
            cursor.execute(f"SELECT MAX({connection.ops.quote_name(column)}) FROM {connection.ops.quote_name(table)}")
            largest = cursor.fetchone()[0]
            cursor.execute(f"SELECT last_value, is_called FROM {sequence}")
            last, called = cursor.fetchone()
            given = last if called else last - 1
            if largest is not None and largest > given:
                cursor.execute("SELECT setval(%s, %s)", [sequence, largest])
                moved.append(f"{table}: {given} → {largest}")
    return moved
