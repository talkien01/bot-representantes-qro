"""Capa de acceso a datos (Postgres) para la mesa de ayuda de representantes."""
import os
from datetime import datetime

from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

DATABASE_URL = os.environ["DATABASE_URL"]

pool: AsyncConnectionPool | None = None

ESTADOS = ["RECIBIDO", "EN_ATENCION", "RESUELTO", "ESCALADO", "CERRADO"]
ESTADOS_ABIERTOS = ["RECIBIDO", "EN_ATENCION", "ESCALADO"]

ESTADO_EMOJI = {
    "RECIBIDO": "📥",
    "EN_ATENCION": "🛠",
    "RESUELTO": "✅",
    "ESCALADO": "⏫",
    "CERRADO": "🔒",
}

# Categorías de problema: (código, etiqueta visible)
CATEGORIAS = [
    ("RG", "No puedo dar de alta un RG"),
    ("RUTA", "Ruta no válida / problema de ruta"),
    ("SISTEMA", "Error del sistema / plataforma"),
    ("RC", "Ayuda para dar de alta un RC"),
    ("OTRO", "Otro"),
]
CAT_LABEL = {c: l for c, l in CATEGORIAS}


async def init_db():
    global pool
    pool = AsyncConnectionPool(DATABASE_URL, min_size=1, max_size=5, open=False)
    await pool.open()
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        schema = f.read()
    async with pool.connection() as conn:
        await conn.execute(schema)


async def close_db():
    if pool:
        await pool.close()


def _folio(ticket_id: int) -> str:
    return f"QRO-{datetime.now():%y%m}-{ticket_id:04d}"


async def crear_ticket(data: dict) -> dict:
    """Inserta un ticket, genera folio y registra historial. Devuelve la fila."""
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            """
            INSERT INTO tickets
              (chat_id, solicitante, comite, categoria, descripcion, evidencia_file_id)
            VALUES (%(chat_id)s, %(solicitante)s, %(comite)s, %(categoria)s,
                    %(descripcion)s, %(evidencia_file_id)s)
            RETURNING id
            """,
            data,
        )
        row = await cur.fetchone()
        tid = row["id"]
        folio = _folio(tid)
        await conn.execute("UPDATE tickets SET folio = %s WHERE id = %s", (folio, tid))
        await conn.execute(
            "INSERT INTO historial (ticket_id, estado, actor) VALUES (%s, 'RECIBIDO', %s)",
            (tid, data.get("solicitante")),
        )
        cur = await conn.execute("SELECT * FROM tickets WHERE id = %s", (tid,))
        return await cur.fetchone()


async def obtener_por_folio(folio: str) -> dict | None:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT * FROM tickets WHERE upper(folio) = upper(%s)", (folio,)
        )
        return await cur.fetchone()


async def tickets_de_chat(chat_id: int, limite: int = 10) -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT * FROM tickets WHERE chat_id = %s ORDER BY id DESC LIMIT %s",
            (chat_id, limite),
        )
        return await cur.fetchall()


async def pendientes() -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT * FROM tickets WHERE estado = ANY(%s) ORDER BY id",
            (ESTADOS_ABIERTOS,),
        )
        return await cur.fetchall()


async def actualizar_estado(folio: str, estado: str, nota: str | None, actor: str) -> dict | None:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            """
            UPDATE tickets
               SET estado = %s,
                   nota_admin = COALESCE(%s, nota_admin),
                   actualizada_en = now()
             WHERE upper(folio) = upper(%s)
            RETURNING *
            """,
            (estado, nota, folio),
        )
        row = await cur.fetchone()
        if row:
            await conn.execute(
                "INSERT INTO historial (ticket_id, estado, nota, actor) VALUES (%s, %s, %s, %s)",
                (row["id"], estado, nota, actor),
            )
        return row


async def historial_de(ticket_id: int) -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT * FROM historial WHERE ticket_id = %s ORDER BY fecha", (ticket_id,)
        )
        return await cur.fetchall()


async def todas() -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute("SELECT * FROM tickets ORDER BY id")
        return await cur.fetchall()


async def resumen() -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT estado, count(*) AS n FROM tickets GROUP BY estado ORDER BY estado"
        )
        return await cur.fetchall()
