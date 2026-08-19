"""Persistencia para la verificación previa de usuarios de Telegram.

Usa el mismo DATABASE_URL del bot de soporte, pero mantiene una tabla separada
para no alterar la operación existente de tickets.
"""
import csv
import io
import os

from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

DATABASE_URL = os.environ["DATABASE_URL"]

pool: AsyncConnectionPool | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS telegram_verificaciones (
    id                SERIAL PRIMARY KEY,
    telegram_id       BIGINT UNIQUE NOT NULL,
    chat_id           BIGINT NOT NULL,
    username          TEXT,
    nombre            TEXT NOT NULL,
    municipio         TEXT NOT NULL,
    estado            TEXT NOT NULL DEFAULT 'VERIFICADO',
    fecha_verificacion TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultima_interaccion TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_verif_municipio
    ON telegram_verificaciones(municipio);
CREATE INDEX IF NOT EXISTS idx_verif_estado
    ON telegram_verificaciones(estado);
"""


async def init_db():
    global pool
    pool = AsyncConnectionPool(DATABASE_URL, min_size=1, max_size=3, open=False)
    await pool.open()
    async with pool.connection() as conn:
        await conn.execute(SCHEMA)


async def close_db():
    if pool:
        await pool.close()


async def obtener(telegram_id: int) -> dict | None:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT * FROM telegram_verificaciones WHERE telegram_id = %s",
            (telegram_id,),
        )
        return await cur.fetchone()


async def esta_verificado(telegram_id: int) -> bool:
    row = await obtener(telegram_id)
    return bool(row and row.get("estado") == "VERIFICADO")


async def guardar_verificacion(*, telegram_id: int, chat_id: int, username: str | None,
                                nombre: str, municipio: str) -> dict:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            """
            INSERT INTO telegram_verificaciones
                (telegram_id, chat_id, username, nombre, municipio, estado,
                 fecha_verificacion, ultima_interaccion)
            VALUES (%s, %s, %s, %s, %s, 'VERIFICADO', now(), now())
            ON CONFLICT (telegram_id) DO UPDATE SET
                chat_id = EXCLUDED.chat_id,
                username = EXCLUDED.username,
                nombre = EXCLUDED.nombre,
                municipio = EXCLUDED.municipio,
                estado = 'VERIFICADO',
                fecha_verificacion = now(),
                ultima_interaccion = now()
            RETURNING *
            """,
            (telegram_id, chat_id, username, nombre, municipio),
        )
        return await cur.fetchone()


async def tocar(telegram_id: int):
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE telegram_verificaciones SET ultima_interaccion = now() WHERE telegram_id = %s",
            (telegram_id,),
        )


async def listar(limite: int = 100) -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            """
            SELECT * FROM telegram_verificaciones
            WHERE estado = 'VERIFICADO'
            ORDER BY fecha_verificacion DESC
            LIMIT %s
            """,
            (limite,),
        )
        return await cur.fetchall()


async def resumen_municipio() -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            """
            SELECT municipio, count(*) AS n
            FROM telegram_verificaciones
            WHERE estado = 'VERIFICADO'
            GROUP BY municipio
            ORDER BY municipio
            """
        )
        return await cur.fetchall()


async def todas() -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT * FROM telegram_verificaciones ORDER BY fecha_verificacion DESC"
        )
        return await cur.fetchall()


def csv_bytes(filas: list[dict]) -> io.BytesIO:
    buf = io.StringIO()
    if filas:
        campos = list(filas[0].keys())
        writer = csv.DictWriter(buf, fieldnames=campos)
        writer.writeheader()
        writer.writerows(filas)
    data = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    data.name = "telegram_verificados.csv"
    return data
