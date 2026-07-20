-- Esquema de base de datos: Mesa de ayuda (help desk) de representantes — PAN Querétaro
-- Los comités dan de alta a sus RG/RC en la plataforma oficial; este bot registra
-- TICKETS de soporte cuando algo les falla. Se ejecuta solo al arrancar (db.py).

CREATE TABLE IF NOT EXISTS tickets (
    id                SERIAL PRIMARY KEY,
    folio             TEXT UNIQUE,
    chat_id           BIGINT NOT NULL,        -- chat de Telegram de quien reporta
    solicitante       TEXT,                    -- nombre/username de Telegram
    comite            TEXT NOT NULL,           -- municipio
    categoria         TEXT NOT NULL,           -- tipo de problema (ver CATEGORIAS)
    descripcion       TEXT NOT NULL,           -- descripción del problema
    evidencia_file_id TEXT,                    -- file_id de la captura en Telegram (opcional)
    estado            TEXT NOT NULL DEFAULT 'RECIBIDO',
    -- RECIBIDO | EN_ATENCION | RESUELTO | ESCALADO | CERRADO
    nota_admin        TEXT,
    creada_en         TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizada_en    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS historial (
    id         SERIAL PRIMARY KEY,
    ticket_id  INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    estado     TEXT NOT NULL,
    nota       TEXT,
    actor      TEXT,
    fecha      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tickets_estado ON tickets(estado);
CREATE INDEX IF NOT EXISTS idx_tickets_chat   ON tickets(chat_id);
CREATE INDEX IF NOT EXISTS idx_tickets_comite ON tickets(comite);
