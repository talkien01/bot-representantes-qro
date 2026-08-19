"""Persistencia del padrón de convocados y verificación de Telegram.

El padrón ``convocados`` es la fuente oficial de control. Cada persona recibe un
código único; el bot vincula ese registro con su cuenta de Telegram al verificar.
La tabla ``telegram_verificaciones`` se conserva por compatibilidad con las
primeras pruebas, pero ya no se usa como fuente de verdad.
"""
import csv
import io
import os

from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

DATABASE_URL = os.environ["DATABASE_URL"]
pool: AsyncConnectionPool | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS convocados (
    id                   BIGSERIAL PRIMARY KEY,
    clave_externa        TEXT,
    codigo_verificacion  TEXT UNIQUE,
    nombre_completo      TEXT NOT NULL,
    municipio            TEXT NOT NULL,
    telefono             TEXT,
    cargo                TEXT,
    seccion              TEXT,
    correo               TEXT,
    estado_convocatoria  TEXT NOT NULL DEFAULT 'Convocado',
    observaciones        TEXT,
    telegram_id          BIGINT,
    telegram_username    TEXT,
    telegram_nombre      TEXT,
    telegram_verificado  BOOLEAN NOT NULL DEFAULT FALSE,
    fecha_verificacion   TIMESTAMPTZ,
    ultima_interaccion   TIMESTAMPTZ,
    estado_capacitacion  TEXT NOT NULL DEFAULT 'Pendiente',
    creado_en            TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_convocados_telegram_unique
    ON convocados(telegram_id) WHERE telegram_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_convocados_municipio ON convocados(municipio);
CREATE INDEX IF NOT EXISTS idx_convocados_verificado ON convocados(telegram_verificado);
CREATE INDEX IF NOT EXISTS idx_convocados_codigo_upper ON convocados(upper(codigo_verificacion));

-- Tabla de la primera prueba; se mantiene para no perder datos históricos.
CREATE TABLE IF NOT EXISTS telegram_verificaciones (
    id                 SERIAL PRIMARY KEY,
    telegram_id        BIGINT UNIQUE NOT NULL,
    chat_id            BIGINT NOT NULL,
    username           TEXT,
    nombre             TEXT NOT NULL,
    municipio          TEXT NOT NULL,
    estado             TEXT NOT NULL DEFAULT 'VERIFICADO',
    fecha_verificacion TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultima_interaccion TIMESTAMPTZ NOT NULL DEFAULT now()
);
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


def normalizar_codigo(codigo: str) -> str:
    return "".join((codigo or "").strip().upper().split())


async def obtener_por_telegram(telegram_id: int) -> dict | None:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT * FROM convocados WHERE telegram_id = %s",
            (telegram_id,),
        )
        return await cur.fetchone()


async def esta_verificado(telegram_id: int) -> bool:
    row = await obtener_por_telegram(telegram_id)
    return bool(row and row.get("telegram_verificado"))


async def obtener_codigo(codigo: str) -> dict | None:
    codigo = normalizar_codigo(codigo)
    if not codigo:
        return None
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT * FROM convocados WHERE upper(codigo_verificacion) = %s",
            (codigo,),
        )
        return await cur.fetchone()


async def vincular_convocado(*, convocado_id: int, telegram_id: int,
                             username: str | None, telegram_nombre: str) -> dict | None:
    """Vincula un convocado con Telegram si el código no pertenece a otra cuenta."""
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            """
            UPDATE convocados
               SET telegram_id = %s,
                   telegram_username = %s,
                   telegram_nombre = %s,
                   telegram_verificado = TRUE,
                   fecha_verificacion = COALESCE(fecha_verificacion, now()),
                   ultima_interaccion = now(),
                   actualizado_en = now()
             WHERE id = %s
               AND (telegram_id IS NULL OR telegram_id = %s)
            RETURNING *
            """,
            (telegram_id, username, telegram_nombre, convocado_id, telegram_id),
        )
        return await cur.fetchone()


async def tocar(telegram_id: int):
    async with pool.connection() as conn:
        await conn.execute(
            """UPDATE convocados
                  SET ultima_interaccion = now(), actualizado_en = now()
                WHERE telegram_id = %s""",
            (telegram_id,),
        )


async def listar_verificados(limite: int = 100) -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            """
            SELECT * FROM convocados
             WHERE telegram_verificado = TRUE
             ORDER BY fecha_verificacion DESC NULLS LAST, id
             LIMIT %s
            """,
            (limite,),
        )
        return await cur.fetchall()


async def listar_pendientes(limite: int = 100) -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            """
            SELECT * FROM convocados
             WHERE telegram_verificado = FALSE
             ORDER BY municipio, nombre_completo
             LIMIT %s
            """,
            (limite,),
        )
        return await cur.fetchall()


async def resumen_general() -> dict:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE telegram_verificado) AS verificados,
                   count(*) FILTER (WHERE NOT telegram_verificado) AS pendientes
              FROM convocados
            """
        )
        return await cur.fetchone()


async def resumen_municipio() -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            """
            SELECT municipio,
                   count(*) AS total,
                   count(*) FILTER (WHERE telegram_verificado) AS verificados,
                   count(*) FILTER (WHERE NOT telegram_verificado) AS pendientes
              FROM convocados
             GROUP BY municipio
             ORDER BY municipio
            """
        )
        return await cur.fetchall()


async def todas() -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT * FROM convocados ORDER BY municipio, nombre_completo"
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
    data.name = "control_convocados_telegram.csv"
    return data
