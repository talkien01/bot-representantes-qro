-- Esquema de base de datos: Bot de solicitudes de representantes (PAN Querétaro)
-- Se ejecuta automáticamente al arrancar el bot (db.py), pero puedes correrlo manualmente.

CREATE TABLE IF NOT EXISTS solicitudes (
    id              SERIAL PRIMARY KEY,
    folio           TEXT UNIQUE,
    chat_id         BIGINT NOT NULL,          -- chat de Telegram del solicitante
    solicitante     TEXT,                      -- nombre/username de Telegram
    comite          TEXT NOT NULL,             -- comité distrital/municipal
    tipo_movimiento TEXT NOT NULL,             -- ALTA | BAJA | SUSTITUCION
    tipo_rep        TEXT NOT NULL,             -- GENERAL | CASILLA
    nombre          TEXT NOT NULL,             -- nombre del representante
    clave_elector   TEXT,
    casilla_ruta    TEXT,                      -- casilla o ruta asignada
    observaciones   TEXT,
    estado          TEXT NOT NULL DEFAULT 'RECIBIDA',
    -- RECIBIDA | EN_PROCESO | PROCESADA | CONFIRMADA | RECHAZADA
    nota_admin      TEXT,
    creada_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizada_en  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS historial (
    id            SERIAL PRIMARY KEY,
    solicitud_id  INTEGER NOT NULL REFERENCES solicitudes(id) ON DELETE CASCADE,
    estado        TEXT NOT NULL,
    nota          TEXT,
    actor         TEXT,                        -- quién hizo el cambio
    fecha         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_solicitudes_estado ON solicitudes(estado);
CREATE INDEX IF NOT EXISTS idx_solicitudes_chat   ON solicitudes(chat_id);
CREATE INDEX IF NOT EXISTS idx_solicitudes_comite ON solicitudes(comite);
