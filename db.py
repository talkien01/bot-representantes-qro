"""Capa de acceso a datos (Postgres) para el bot de representantes."""
import os
from datetime import datetime

from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

DATABASE_URL = os.environ["DATABASE_URL"]

pool: AsyncConnectionPool | None = None

ESTADOS = ["RECIBIDA", "EN_PROCESO", "PROCESADA", "CONFIRMADA", "RECHAZADA"]
ESTADOS_ABIERTOS = ["RECIBIDA", "EN_PROCESO", "PROCESADA"]

ESTADO_EMOJI = {
    "RECIBIDA": "📥",
    "EN_PROCESO": "⚙️",
    "PROCESADA": "📤",
    "CONFIRMADA": "✅",
    "RECHAZADA": "❌",
}


async def init_db():
    """Crea el pool y asegura el esquema."""
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


def _folio(sol_id: int) -> str:
    return f"QRO-{datetime.now():%y%m}-{sol_id:04d}"


async def crear_solicitud(data: dict) -> dict:
    """Inserta una solicitud, genera folio y registra historial. Devuelve la fila."""
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            """
            INSERT INTO solicitudes
              (chat_id, solicitante, comite, tipo_movimiento, tipo_rep,
               nombre, clave_elector, casilla_ruta, observaciones)
            VALUES (%(chat_id)s, %(solicitante)s, %(comite)s, %(tipo_movimiento)s,
                    %(tipo_rep)s, %(nombre)s, %(clave_elector)s, %(casilla_ruta)s,
                    %(observaciones)s)
            RETURNING id
            """,
            data,
        )
        row = await cur.fetchone()
        sol_id = row["id"]
        folio = _folio(sol_id)
        await conn.execute(
            "UPDATE solicitudes SET folio = %s WHERE id = %s", (folio, sol_id)
        )
        await conn.execute(
            "INSERT INTO historial (solicitud_id, estado, actor) VALUES (%s, 'RECIBIDA', %s)",
            (sol_id, data.get("solicitante")),
        )
        cur = await conn.execute("SELECT * FROM solicitudes WHERE id = %s", (sol_id,))
        return await cur.fetchone()


async def obtener_por_folio(folio: str) -> dict | None:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT * FROM solicitudes WHERE upper(folio) = upper(%s)", (folio,)
        )
        return await cur.fetchone()


async def solicitudes_de_chat(chat_id: int, limite: int = 10) -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT * FROM solicitudes WHERE chat_id = %s ORDER BY id DESC LIMIT %s",
            (chat_id, limite),
        )
        return await cur.fetchall()


async def pendientes() -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT * FROM solicitudes WHERE estado = ANY(%s) ORDER BY id",
            (ESTADOS_ABIERTOS,),
        )
        return await cur.fetchall()


async def actualizar_estado(folio: str, estado: str, nota: str | None, actor: str) -> dict | None:
    """Cambia el estado, guarda historial y devuelve la fila actualizada."""
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            """
            UPDATE solicitudes
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
                "INSERT INTO historial (solicitud_id, estado, nota, actor) VALUES (%s, %s, %s, %s)",
                (row["id"], estado, nota, actor),
            )
        return row


async def historial_de(sol_id: int) -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT * FROM historial WHERE solicitud_id = %s ORDER BY fecha", (sol_id,)
        )
        return await cur.fetchall()


async def todas() -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute("SELECT * FROM solicitudes ORDER BY id")
        return await cur.fetchall()


async def resumen() -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT estado, count(*) AS n FROM solicitudes GROUP BY estado ORDER BY estado"
        )
        return await cur.fetchall()
