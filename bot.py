"""
Bot de Telegram — Control de solicitudes de representantes generales y de casilla
PAN Querétaro. Corre 24/7 en Docker (Easypanel) con Postgres.

Comandos de comités:
  /nueva     - registrar una solicitud (alta/baja/sustitución) → genera folio
  /estatus   - consultar el estado de un folio
  /mis       - ver mis últimas solicitudes
  /cancelar  - cancelar la captura en curso

Comandos de administrador (IDs en ADMIN_IDS):
  /pendientes            - solicitudes abiertas
  /detalle FOLIO         - ficha completa + historial
  /actualizar FOLIO ESTADO [nota]  - cambia estado y notifica al comité
  /resumen               - conteo por estado
  /export                - CSV con todo
"""
import csv
import html
import io
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x}

# Estados del wizard
COMITE, MOV, REP, NOMBRE, CLAVE, CASILLA, OBS, CONFIRMA = range(8)

SALTAR = "-"  # texto para omitir un campo opcional

# Comités municipales de Querétaro (18 municipios).
# Para cambiar a distritos, solo edita esta lista.
COMITES = [
    "Amealco de Bonfil", "Arroyo Seco", "Cadereyta de Montes", "Colón",
    "Corregidora", "El Marqués", "Ezequiel Montes", "Huimilpan",
    "Jalpan de Serra", "Landa de Matamoros", "Pedro Escobedo", "Peñamiller",
    "Pinal de Amoles", "Querétaro", "San Joaquín", "San Juan del Río",
    "Tequisquiapan", "Tolimán",
]

HTML = ParseMode.HTML


def esc(x) -> str:
    """Escapa texto para HTML de Telegram. Evita romper el formato con < > &."""
    return html.escape(str(x)) if x is not None else ""


def es_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id in ADMIN_IDS


def ficha(s: dict) -> str:
    e = db.ESTADO_EMOJI.get(s["estado"], "")
    lineas = [
        f"<b>Folio:</b> <code>{esc(s['folio'])}</code>",
        f"<b>Estado:</b> {e} {esc(s['estado'])}",
        f"<b>Comité:</b> {esc(s['comite'])}",
        f"<b>Movimiento:</b> {esc(s['tipo_movimiento'])} — Rep. {esc(s['tipo_rep'])}",
        f"<b>Nombre:</b> {esc(s['nombre'])}",
    ]
    if s.get("clave_elector"):
        lineas.append(f"<b>Clave de elector:</b> {esc(s['clave_elector'])}")
    if s.get("casilla_ruta"):
        lineas.append(f"<b>Casilla/Ruta:</b> {esc(s['casilla_ruta'])}")
    if s.get("observaciones"):
        lineas.append(f"<b>Observaciones:</b> {esc(s['observaciones'])}")
    if s.get("nota_admin"):
        lineas.append(f"<b>Nota del CDE:</b> {esc(s['nota_admin'])}")
    lineas.append(f"<b>Recibida:</b> {s['creada_en']:%d/%m/%Y %H:%M}")
    return "\n".join(lineas)


# ---------- comandos generales ----------

def _menu_bienvenida() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Nueva solicitud", callback_data="go:nueva")],
        [InlineKeyboardButton("🔎 Consultar folio", callback_data="go:estatus"),
         InlineKeyboardButton("📋 Mis solicitudes", callback_data="go:mis")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bienvenida. Se dispara con /start y también con cualquier saludo/texto suelto."""
    txt = (
        "👋 <b>¡Hola! Bienvenido.</b>\n\n"
        "Soy el bot de <b>solicitudes de representantes</b> del PAN Querétaro. "
        "Aquí los comités registran <b>altas, bajas y sustituciones</b> de representantes "
        "generales y de casilla, y cada solicitud recibe un <b>folio</b> para darle seguimiento.\n\n"
        "<b>¿Cómo funciona?</b>\n"
        "1️⃣ Toca <b>📝 Nueva solicitud</b> (o escribe /nueva).\n"
        "2️⃣ Elige tu municipio y responde unas preguntas cortas.\n"
        "3️⃣ Recibes tu folio y te aviso aquí en cuanto avance tu trámite.\n\n"
        "También puedes escribir <b>/estatus</b> con tu folio para consultar en cualquier momento."
    )
    if es_admin(update):
        txt += (
            "\n\n🛠 <b>Administrador:</b>\n"
            "/pendientes — solicitudes abiertas\n"
            "/detalle FOLIO — ficha e historial\n"
            "/actualizar FOLIO ESTADO [nota] — cambia estado y notifica\n"
            "/resumen — conteo por estado\n"
            "/export — CSV completo\n"
            f"\nEstados válidos: {esc(', '.join(db.ESTADOS))}"
        )
    dest = update.message or (update.callback_query and update.callback_query.message)
    await dest.reply_text(txt, parse_mode=HTML, reply_markup=_menu_bienvenida())


async def menu_go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botones de la bienvenida que no arrancan el wizard (estatus / mis)."""
    q = update.callback_query
    await q.answer()
    if q.data == "go:estatus":
        await q.message.reply_text("Escribe: /estatus seguido de tu folio.\nEjemplo: /estatus QRO-2607-0001")
    elif q.data == "go:mis":
        await mis(update, context)


async def estatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        s = await db.obtener_por_folio(context.args[0])
        if not s:
            await update.message.reply_text("No encontré ese folio. Verifica que esté completo, ej. QRO-2607-0001")
            return
        await update.message.reply_text(ficha(s), parse_mode=HTML)
    else:
        await update.message.reply_text("Uso: /estatus QRO-2607-0001")


async def mis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dest = update.message or (update.callback_query and update.callback_query.message)
    filas = await db.solicitudes_de_chat(update.effective_chat.id)
    if not filas:
        await dest.reply_text("No tienes solicitudes registradas. Usa /nueva para crear una.")
        return
    lineas = [
        f"{db.ESTADO_EMOJI.get(s['estado'],'')} <code>{esc(s['folio'])}</code> — "
        f"{esc(s['tipo_movimiento'])} {esc(s['tipo_rep'])} — {esc(s['nombre'])} — {esc(s['estado'])}"
        for s in filas
    ]
    await dest.reply_text("\n".join(lineas), parse_mode=HTML)


# ---------- wizard /nueva ----------

def _teclado_comites() -> InlineKeyboardMarkup:
    """Botones de comités en 2 columnas (usa el índice para evitar textos largos)."""
    filas, fila = [], []
    for i, nombre in enumerate(COMITES):
        fila.append(InlineKeyboardButton(nombre, callback_data=f"com:{i}"))
        if len(fila) == 2:
            filas.append(fila)
            fila = []
    if fila:
        filas.append(fila)
    return InlineKeyboardMarkup(filas)


async def nueva(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        dest = update.callback_query.message
    else:
        dest = update.message
    await dest.reply_text(
        "📝 Nueva solicitud.\n\nSelecciona el <b>comité municipal</b>:",
        parse_mode=HTML,
        reply_markup=_teclado_comites(),
    )
    return COMITE


async def paso_comite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    idx = int(q.data.split(":")[1])
    context.user_data["comite"] = COMITES[idx]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬆️ Alta", callback_data="mov:ALTA"),
         InlineKeyboardButton("⬇️ Baja", callback_data="mov:BAJA"),
         InlineKeyboardButton("🔁 Sustitución", callback_data="mov:SUSTITUCION")],
    ])
    await q.edit_message_text(f"Comité: <b>{esc(COMITES[idx])}</b>", parse_mode=HTML)
    await q.message.reply_text("¿Qué tipo de movimiento es?", reply_markup=kb)
    return MOV


async def paso_mov(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["tipo_movimiento"] = q.data.split(":")[1]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚗 General (RG)", callback_data="rep:GENERAL"),
         InlineKeyboardButton("🗳 De casilla (RC)", callback_data="rep:CASILLA")],
    ])
    await q.edit_message_text("¿Tipo de representante?")
    await q.message.reply_text("Elige:", reply_markup=kb)
    return REP


async def paso_rep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["tipo_rep"] = q.data.split(":")[1]
    await q.edit_message_text("Nombre completo del representante:")
    return NOMBRE


async def paso_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nombre"] = update.message.text.strip()
    await update.message.reply_text(f"Clave de elector (o «{SALTAR}» para omitir):")
    return CLAVE


async def paso_clave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    context.user_data["clave_elector"] = None if t == SALTAR else t.upper()
    await update.message.reply_text(f"Casilla o ruta asignada (o «{SALTAR}» para omitir):")
    return CASILLA


async def paso_casilla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    context.user_data["casilla_ruta"] = None if t == SALTAR else t
    await update.message.reply_text(f"Observaciones (o «{SALTAR}» si no hay):")
    return OBS


async def paso_obs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    context.user_data["observaciones"] = None if t == SALTAR else t
    d = context.user_data
    resumen = (
        "Confirma la solicitud:\n\n"
        f"<b>Comité:</b> {esc(d['comite'])}\n"
        f"<b>Movimiento:</b> {esc(d['tipo_movimiento'])} — Rep. {esc(d['tipo_rep'])}\n"
        f"<b>Nombre:</b> {esc(d['nombre'])}\n"
        f"<b>Clave de elector:</b> {esc(d.get('clave_elector') or '—')}\n"
        f"<b>Casilla/Ruta:</b> {esc(d.get('casilla_ruta') or '—')}\n"
        f"<b>Observaciones:</b> {esc(d.get('observaciones') or '—')}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Enviar", callback_data="conf:si"),
         InlineKeyboardButton("❌ Cancelar", callback_data="conf:no")],
    ])
    await update.message.reply_text(resumen, parse_mode=HTML, reply_markup=kb)
    return CONFIRMA


async def paso_confirma(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "conf:no":
        context.user_data.clear()
        await q.edit_message_text("Solicitud cancelada. Usa /nueva para empezar de nuevo.")
        return ConversationHandler.END

    u = update.effective_user
    data = dict(context.user_data)
    data["chat_id"] = update.effective_chat.id
    data["solicitante"] = f"{u.full_name} (@{u.username})" if u.username else u.full_name
    s = await db.crear_solicitud(data)
    context.user_data.clear()

    await q.edit_message_text(
        f"✅ Solicitud registrada.\n\n<b>Tu folio es:</b> <code>{esc(s['folio'])}</code>\n\n"
        "Guárdalo para dar seguimiento con /estatus. Te notificaré aquí cada cambio de estado.",
        parse_mode=HTML,
    )

    # avisar a los administradores
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"📥 Nueva solicitud <code>{esc(s['folio'])}</code> de {esc(data['solicitante'])}\n\n" + ficha(s),
                parse_mode=HTML,
            )
        except Exception as e:
            log.warning("No pude avisar al admin %s: %s", admin_id, e)
    return ConversationHandler.END


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Captura cancelada.")
    return ConversationHandler.END


# ---------- comandos de administrador ----------

async def pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_admin(update):
        return
    filas = await db.pendientes()
    if not filas:
        await update.message.reply_text("🎉 No hay solicitudes pendientes.")
        return
    lineas = [
        f"{db.ESTADO_EMOJI.get(s['estado'],'')} <code>{esc(s['folio'])}</code> — {esc(s['comite'])} — "
        f"{esc(s['tipo_movimiento'])} {esc(s['tipo_rep'])} — {esc(s['nombre'])} — {esc(s['estado'])}"
        for s in filas
    ]
    await update.message.reply_text(
        f"<b>{len(filas)} pendientes:</b>\n\n" + "\n".join(lineas), parse_mode=HTML
    )


async def detalle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /detalle QRO-2607-0001")
        return
    s = await db.obtener_por_folio(context.args[0])
    if not s:
        await update.message.reply_text("Folio no encontrado.")
        return
    hist = await db.historial_de(s["id"])
    txt = ficha(s) + f"\n<b>Solicitante:</b> {esc(s['solicitante'])}\n\n<b>Historial:</b>\n"
    txt += "\n".join(
        f"• {h['fecha']:%d/%m %H:%M} — {esc(h['estado'])}" + (f" ({esc(h['nota'])})" if h["nota"] else "")
        for h in hist
    )
    await update.message.reply_text(txt, parse_mode=HTML)


async def actualizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_admin(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Uso: /actualizar QRO-2607-0001 ESTADO [nota]\n"
            f"Estados: {', '.join(db.ESTADOS)}"
        )
        return
    folio, estado = context.args[0], context.args[1].upper()
    nota = " ".join(context.args[2:]) or None
    if estado not in db.ESTADOS:
        await update.message.reply_text(f"Estado inválido. Usa: {', '.join(db.ESTADOS)}")
        return
    actor = update.effective_user.full_name
    s = await db.actualizar_estado(folio, estado, nota, actor)
    if not s:
        await update.message.reply_text("Folio no encontrado.")
        return
    e = db.ESTADO_EMOJI.get(estado, "")
    await update.message.reply_text(
        f"{e} <code>{esc(s['folio'])}</code> → <b>{esc(estado)}</b>", parse_mode=HTML
    )
    # notificar al solicitante
    try:
        msg = f"{e} Tu solicitud <code>{esc(s['folio'])}</code> cambió a <b>{esc(estado)}</b>."
        if nota:
            msg += f"\nNota: {esc(nota)}"
        await context.bot.send_message(s["chat_id"], msg, parse_mode=HTML)
    except Exception as ex:
        log.warning("No pude notificar al solicitante de %s: %s", folio, ex)
        await update.message.reply_text("⚠️ No pude notificar al solicitante (quizá bloqueó el bot).")


async def resumen_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_admin(update):
        return
    filas = await db.resumen()
    total = sum(r["n"] for r in filas)
    lineas = [f"{db.ESTADO_EMOJI.get(r['estado'],'')} {esc(r['estado'])}: <b>{r['n']}</b>" for r in filas]
    await update.message.reply_text(
        f"<b>Resumen ({total} solicitudes):</b>\n\n" + "\n".join(lineas), parse_mode=HTML
    )


async def export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_admin(update):
        return
    filas = await db.todas()
    if not filas:
        await update.message.reply_text("No hay solicitudes que exportar.")
        return
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(filas[0].keys()))
    w.writeheader()
    w.writerows(filas)
    data = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    data.name = "solicitudes.csv"
    await update.message.reply_document(data, caption=f"{len(filas)} solicitudes")


# ---------- arranque ----------

async def post_init(app: Application):
    await db.init_db()
    log.info("Base de datos lista.")
    # Menú azul de comandos (botón "/" junto al teclado)
    from telegram import BotCommand
    await app.bot.set_my_commands([
        BotCommand("nueva", "Registrar una solicitud"),
        BotCommand("estatus", "Consultar un folio"),
        BotCommand("mis", "Mis solicitudes"),
        BotCommand("cancelar", "Cancelar captura en curso"),
        BotCommand("start", "Ayuda / inicio"),
    ])


async def post_shutdown(app: Application):
    await db.close_db()


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    wizard = ConversationHandler(
        entry_points=[
            CommandHandler("nueva", nueva),
            CallbackQueryHandler(nueva, pattern=r"^go:nueva$"),
        ],
        states={
            COMITE: [CallbackQueryHandler(paso_comite, pattern=r"^com:")],
            MOV: [CallbackQueryHandler(paso_mov, pattern=r"^mov:")],
            REP: [CallbackQueryHandler(paso_rep, pattern=r"^rep:")],
            NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, paso_nombre)],
            CLAVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, paso_clave)],
            CASILLA: [MessageHandler(filters.TEXT & ~filters.COMMAND, paso_casilla)],
            OBS: [MessageHandler(filters.TEXT & ~filters.COMMAND, paso_obs)],
            CONFIRMA: [CallbackQueryHandler(paso_confirma, pattern=r"^conf:")],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(wizard)
    app.add_handler(CommandHandler("estatus", estatus))
    app.add_handler(CommandHandler("mis", mis))
    app.add_handler(CommandHandler("pendientes", pendientes))
    app.add_handler(CommandHandler("detalle", detalle))
    app.add_handler(CommandHandler("actualizar", actualizar))
    app.add_handler(CommandHandler("resumen", resumen_cmd))
    app.add_handler(CommandHandler("export", export))
    # Botones de la bienvenida (estatus / mis)
    app.add_handler(CallbackQueryHandler(menu_go, pattern=r"^go:(estatus|mis)$"))
    # Cualquier saludo o texto suelto fuera del wizard → muestra la bienvenida
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start))

    log.info("Bot iniciando (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
