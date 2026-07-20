"""
Bot de Telegram — Mesa de ayuda (help desk) de representantes
PAN Querétaro. Corre 24/7 en Docker (Easypanel) con Postgres.

Los comités dan de alta a sus RG/RC directamente en la plataforma oficial.
Este bot NO hace las altas: registra TICKETS de soporte cuando algo les falla
(no pueden dar de alta un RG, la ruta no es válida, error del sistema, ayuda con RC).

Comandos de comités:
  /ayuda     - levantar un ticket de soporte → genera folio
  /estatus   - consultar el estado de un folio
  /mis       - ver mis últimos tickets
  /cancelar  - cancelar la captura en curso

Comandos de administrador (IDs en ADMIN_IDS):
  /pendientes            - tickets abiertos
  /detalle FOLIO         - ficha completa + historial + evidencia
  /actualizar FOLIO ESTADO [nota]  - cambia estado y notifica al comité
  /resumen               - conteo por estado
  /export                - CSV con todo
"""
import csv
import html
import io
import logging
import os

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
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
MUNICIPIO, CATEGORIA, DESCRIPCION, EVIDENCIA, CONFIRMA = range(5)

SALTAR = "-"  # texto para omitir un campo opcional
HTML = ParseMode.HTML

# Municipios de Querétaro (18). Para cambiar a distritos, edita esta lista.
COMITES = [
    "Amealco de Bonfil", "Arroyo Seco", "Cadereyta de Montes", "Colón",
    "Corregidora", "El Marqués", "Ezequiel Montes", "Huimilpan",
    "Jalpan de Serra", "Landa de Matamoros", "Pedro Escobedo", "Peñamiller",
    "Pinal de Amoles", "Querétaro", "San Joaquín", "San Juan del Río",
    "Tequisquiapan", "Tolimán",
]


def esc(x) -> str:
    return html.escape(str(x)) if x is not None else ""


def es_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id in ADMIN_IDS


async def _enviar_evidencia(bot, chat_id: int, file_id: str, caption: str):
    """Reenvía la evidencia sea foto o archivo (prueba foto y cae a documento)."""
    try:
        await bot.send_photo(chat_id, file_id, caption=caption)
    except Exception:
        await bot.send_document(chat_id, file_id, caption=caption)


def ficha(s: dict) -> str:
    e = db.ESTADO_EMOJI.get(s["estado"], "")
    cat = db.CAT_LABEL.get(s["categoria"], s["categoria"])
    lineas = [
        f"<b>Folio:</b> <code>{esc(s['folio'])}</code>",
        f"<b>Estado:</b> {e} {esc(s['estado'])}",
        f"<b>Municipio:</b> {esc(s['comite'])}",
        f"<b>Problema:</b> {esc(cat)}",
        f"<b>Descripción:</b> {esc(s['descripcion'])}",
    ]
    if s.get("evidencia_file_id"):
        lineas.append("<b>Evidencia:</b> 📎 adjunta")
    if s.get("nota_admin"):
        lineas.append(f"<b>Nota de soporte:</b> {esc(s['nota_admin'])}")
    lineas.append(f"<b>Reportado:</b> {s['creada_en']:%d/%m/%Y %H:%M}")
    return "\n".join(lineas)


# ---------- bienvenida ----------

def _menu_bienvenida() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆘 Necesito ayuda", callback_data="go:ayuda")],
        [InlineKeyboardButton("🔎 Consultar folio", callback_data="go:estatus"),
         InlineKeyboardButton("📋 Mis tickets", callback_data="go:mis")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bienvenida. Se dispara con /start y con cualquier saludo/texto suelto."""
    txt = (
        "👋 <b>¡Hola! Bienvenido a la mesa de ayuda.</b>\n\n"
        "Soy el bot de <b>soporte</b> para representantes del PAN Querétaro. "
        "Las altas de tus <b>RG</b> y <b>RC</b> las haces tú directo en la plataforma oficial; "
        "yo estoy aquí para <b>ayudarte cuando algo falla</b>: no te deja dar de alta un RG, "
        "la ruta marca error, la plataforma no responde, o necesitas apoyo con tus RC.\n\n"
        "<b>¿Cómo funciona?</b>\n"
        "1️⃣ Toca <b>🆘 Necesito ayuda</b> (o escribe /ayuda).\n"
        "2️⃣ Elige tu municipio, el tipo de problema y descríbelo (puedes adjuntar una captura).\n"
        "3️⃣ Recibes un <b>folio</b> y te aviso aquí en cuanto tu caso avance o se resuelva.\n\n"
        "Consulta cuando quieras con <b>/estatus</b> + tu folio."
    )
    if es_admin(update):
        txt += (
            "\n\n🛠 <b>Administrador (soporte):</b>\n"
            "/pendientes — tickets abiertos\n"
            "/detalle FOLIO — ficha, historial y evidencia\n"
            "/actualizar FOLIO ESTADO [nota] — cambia estado y notifica\n"
            "/resumen — conteo por estado\n"
            "/export — CSV completo\n"
            f"\nEstados: {esc(', '.join(db.ESTADOS))}"
        )
    dest = update.message or (update.callback_query and update.callback_query.message)
    await dest.reply_text(txt, parse_mode=HTML, reply_markup=_menu_bienvenida())


async def menu_go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "go:estatus":
        await q.message.reply_text("Escribe: /estatus seguido de tu folio.\nEjemplo: /estatus QRO-2607-0001")
    elif q.data == "go:mis":
        await mis(update, context)


# ---------- consultas ----------

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
    filas = await db.tickets_de_chat(update.effective_chat.id)
    if not filas:
        await dest.reply_text("No tienes tickets registrados. Usa /ayuda para levantar uno.")
        return
    lineas = [
        f"{db.ESTADO_EMOJI.get(s['estado'],'')} <code>{esc(s['folio'])}</code> — "
        f"{esc(db.CAT_LABEL.get(s['categoria'], s['categoria']))} — {esc(s['estado'])}"
        for s in filas
    ]
    await dest.reply_text("\n".join(lineas), parse_mode=HTML)


# ---------- wizard /ayuda ----------

def _teclado_comites() -> InlineKeyboardMarkup:
    filas, fila = [], []
    for i, nombre in enumerate(COMITES):
        fila.append(InlineKeyboardButton(nombre, callback_data=f"com:{i}"))
        if len(fila) == 2:
            filas.append(fila)
            fila = []
    if fila:
        filas.append(fila)
    return InlineKeyboardMarkup(filas)


def _teclado_categorias() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=f"cat:{code}")] for code, label in db.CATEGORIAS]
    )


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        dest = update.callback_query.message
    else:
        dest = update.message
    await dest.reply_text(
        "🆘 Vamos a levantar tu ticket.\n\nPrimero, ¿de qué <b>municipio</b> reportas?",
        parse_mode=HTML,
        reply_markup=_teclado_comites(),
    )
    return MUNICIPIO


async def paso_municipio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    idx = int(q.data.split(":")[1])
    context.user_data["comite"] = COMITES[idx]
    await q.edit_message_text(f"Municipio: <b>{esc(COMITES[idx])}</b>", parse_mode=HTML)
    await q.message.reply_text("¿Qué tipo de problema tienes?", reply_markup=_teclado_categorias())
    return CATEGORIA


async def paso_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    code = q.data.split(":")[1]
    context.user_data["categoria"] = code
    await q.edit_message_text(f"Problema: <b>{esc(db.CAT_LABEL.get(code, code))}</b>", parse_mode=HTML)
    await q.message.reply_text(
        "Describe el problema con el mayor detalle posible "
        "(qué intentabas hacer, qué mensaje te aparece, nombre/clave del representante si aplica):"
    )
    return DESCRIPCION


async def paso_descripcion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["descripcion"] = update.message.text.strip()
    await update.message.reply_text(
        "📸 Adjunta una <b>foto o captura</b> del problema.\n"
        "Toca el clip 📎 y elige <b>Cámara</b> para tomarla en el momento, "
        "o <b>Galería</b> si ya la tienes.\n"
        f"Si no tienes evidencia, escribe «{SALTAR}» para continuar.",
        parse_mode=HTML,
    )
    return EVIDENCIA


async def paso_evidencia_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Foto tomada con cámara o enviada desde galería (comprimida)
    context.user_data["evidencia_file_id"] = update.message.photo[-1].file_id
    return await _mostrar_confirmacion(update, context)


async def paso_evidencia_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Captura enviada como archivo/imagen (sin comprimir, típico en computadora)
    context.user_data["evidencia_file_id"] = update.message.document.file_id
    return await _mostrar_confirmacion(update, context)


async def paso_evidencia_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["evidencia_file_id"] = None
    return await _mostrar_confirmacion(update, context)


async def _mostrar_confirmacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data
    resumen = (
        "Confirma tu ticket:\n\n"
        f"<b>Municipio:</b> {esc(d['comite'])}\n"
        f"<b>Problema:</b> {esc(db.CAT_LABEL.get(d['categoria'], d['categoria']))}\n"
        f"<b>Descripción:</b> {esc(d['descripcion'])}\n"
        f"<b>Evidencia:</b> {'📎 adjunta' if d.get('evidencia_file_id') else '— sin captura'}"
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
        await q.edit_message_text("Ticket cancelado. Usa /ayuda para empezar de nuevo.")
        return ConversationHandler.END

    u = update.effective_user
    data = dict(context.user_data)
    data["chat_id"] = update.effective_chat.id
    data["solicitante"] = f"{u.full_name} (@{u.username})" if u.username else u.full_name
    data.setdefault("evidencia_file_id", None)
    try:
        s = await db.crear_ticket(data)
    except Exception as e:
        log.exception("Error al crear ticket: %s", e)
        await q.edit_message_text(
            "⚠️ Ocurrió un error al guardar tu ticket. Vuelve a intentar con /ayuda "
            "en un momento. Si sigue fallando, avísale al soporte."
        )
        return ConversationHandler.END
    context.user_data.clear()

    await q.edit_message_text(
        f"✅ Ticket registrado.\n\n<b>Tu folio es:</b> <code>{esc(s['folio'])}</code>\n\n"
        "Guárdalo para dar seguimiento con /estatus. Te avisaré aquí en cuanto tu caso avance.",
        parse_mode=HTML,
    )

    # avisar a soporte (admins), reenviando la evidencia si la hay
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"🆘 Nuevo ticket <code>{esc(s['folio'])}</code> de {esc(data['solicitante'])}\n\n" + ficha(s),
                parse_mode=HTML,
            )
            if s.get("evidencia_file_id"):
                await _enviar_evidencia(context.bot, admin_id, s["evidencia_file_id"],
                                        f"Evidencia de {s['folio']}")
        except Exception as e:
            log.warning("No pude avisar al admin %s: %s", admin_id, e)
    return ConversationHandler.END


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Captura cancelada.")
    return ConversationHandler.END


# ---------- comandos de administrador (soporte) ----------

async def pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_admin(update):
        return
    filas = await db.pendientes()
    if not filas:
        await update.message.reply_text("🎉 No hay tickets pendientes.")
        return
    lineas = [
        f"{db.ESTADO_EMOJI.get(s['estado'],'')} <code>{esc(s['folio'])}</code> — {esc(s['comite'])} — "
        f"{esc(db.CAT_LABEL.get(s['categoria'], s['categoria']))} — {esc(s['estado'])}"
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
    txt = ficha(s) + f"\n<b>Reporta:</b> {esc(s['solicitante'])}\n\n<b>Historial:</b>\n"
    txt += "\n".join(
        f"• {h['fecha']:%d/%m %H:%M} — {esc(h['estado'])}" + (f" ({esc(h['nota'])})" if h["nota"] else "")
        for h in hist
    )
    await update.message.reply_text(txt, parse_mode=HTML)
    if s.get("evidencia_file_id"):
        try:
            await _enviar_evidencia(context.bot, update.effective_chat.id,
                                    s["evidencia_file_id"], "Evidencia adjunta")
        except Exception as e:
            log.warning("No pude reenviar evidencia de %s: %s", s["folio"], e)


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
    try:
        msg = f"{e} Tu ticket <code>{esc(s['folio'])}</code> cambió a <b>{esc(estado)}</b>."
        if nota:
            msg += f"\nNota de soporte: {esc(nota)}"
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
        f"<b>Resumen ({total} tickets):</b>\n\n" + "\n".join(lineas), parse_mode=HTML
    )


async def export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_admin(update):
        return
    filas = await db.todas()
    if not filas:
        await update.message.reply_text("No hay tickets que exportar.")
        return
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(filas[0].keys()))
    w.writeheader()
    w.writerows(filas)
    data = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    data.name = "tickets.csv"
    await update.message.reply_document(data, caption=f"{len(filas)} tickets")


# ---------- arranque ----------

async def post_init(app: Application):
    await db.init_db()
    log.info("Base de datos lista.")
    await app.bot.set_my_commands([
        BotCommand("ayuda", "Levantar un ticket de soporte"),
        BotCommand("estatus", "Consultar un folio"),
        BotCommand("mis", "Mis tickets"),
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
            CommandHandler("ayuda", ayuda),
            CallbackQueryHandler(ayuda, pattern=r"^go:ayuda$"),
        ],
        states={
            MUNICIPIO: [CallbackQueryHandler(paso_municipio, pattern=r"^com:")],
            CATEGORIA: [CallbackQueryHandler(paso_categoria, pattern=r"^cat:")],
            DESCRIPCION: [MessageHandler(filters.TEXT & ~filters.COMMAND, paso_descripcion)],
            EVIDENCIA: [
                MessageHandler(filters.PHOTO, paso_evidencia_foto),
                MessageHandler(filters.Document.IMAGE, paso_evidencia_doc),
                MessageHandler(filters.TEXT & ~filters.COMMAND, paso_evidencia_texto),
            ],
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
    app.add_handler(CallbackQueryHandler(menu_go, pattern=r"^go:(estatus|mis)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start))

    async def on_error(update, context):
        log.exception("Excepción en un handler", exc_info=context.error)

    app.add_error_handler(on_error)

    log.info("Bot iniciando (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
