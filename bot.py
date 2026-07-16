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


def es_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id in ADMIN_IDS


def ficha(s: dict) -> str:
    e = db.ESTADO_EMOJI.get(s["estado"], "")
    lineas = [
        f"*Folio:* `{s['folio']}`",
        f"*Estado:* {e} {s['estado']}",
        f"*Comité:* {s['comite']}",
        f"*Movimiento:* {s['tipo_movimiento']} — Rep. {s['tipo_rep']}",
        f"*Nombre:* {s['nombre']}",
    ]
    if s.get("clave_elector"):
        lineas.append(f"*Clave de elector:* {s['clave_elector']}")
    if s.get("casilla_ruta"):
        lineas.append(f"*Casilla/Ruta:* {s['casilla_ruta']}")
    if s.get("observaciones"):
        lineas.append(f"*Observaciones:* {s['observaciones']}")
    if s.get("nota_admin"):
        lineas.append(f"*Nota del CDE:* {s['nota_admin']}")
    lineas.append(f"*Recibida:* {s['creada_en']:%d/%m/%Y %H:%M}")
    return "\n".join(lineas)


# ---------- comandos generales ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "👋 Hola, soy el bot de *solicitudes de representantes* del PAN Querétaro.\n\n"
        "📝 /nueva — registrar alta, baja o sustitución (te doy un folio)\n"
        "🔎 /estatus — consultar un folio\n"
        "📋 /mis — tus últimas solicitudes\n"
        "✖️ /cancelar — cancelar la captura en curso"
    )
    if es_admin(update):
        txt += (
            "\n\n🛠 *Administrador:*\n"
            "/pendientes — solicitudes abiertas\n"
            "/detalle FOLIO — ficha e historial\n"
            "/actualizar FOLIO ESTADO \\[nota] — cambia estado y notifica\n"
            "/resumen — conteo por estado\n"
            "/export — CSV completo\n"
            f"\nEstados válidos: {', '.join(db.ESTADOS)}"
        )
    await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)


async def estatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        s = await db.obtener_por_folio(context.args[0])
        if not s:
            await update.message.reply_text("No encontré ese folio. Verifica que esté completo, ej. QRO-2607-0001")
            return
        await update.message.reply_text(ficha(s), parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("Uso: /estatus QRO-2607-0001")


async def mis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    filas = await db.solicitudes_de_chat(update.effective_chat.id)
    if not filas:
        await update.message.reply_text("No tienes solicitudes registradas. Usa /nueva para crear una.")
        return
    lineas = [
        f"{db.ESTADO_EMOJI.get(s['estado'],'')} `{s['folio']}` — {s['tipo_movimiento']} {s['tipo_rep']} — {s['nombre']} — {s['estado']}"
        for s in filas
    ]
    await update.message.reply_text("\n".join(lineas), parse_mode=ParseMode.MARKDOWN)


# ---------- wizard /nueva ----------

async def nueva(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "📝 Nueva solicitud.\n\n¿De qué *comité* (distrital o municipal) es la solicitud?",
        parse_mode=ParseMode.MARKDOWN,
    )
    return COMITE


async def paso_comite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["comite"] = update.message.text.strip()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬆️ Alta", callback_data="mov:ALTA"),
         InlineKeyboardButton("⬇️ Baja", callback_data="mov:BAJA"),
         InlineKeyboardButton("🔁 Sustitución", callback_data="mov:SUSTITUCION")],
    ])
    await update.message.reply_text("¿Qué tipo de movimiento es?", reply_markup=kb)
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
        f"*Comité:* {d['comite']}\n"
        f"*Movimiento:* {d['tipo_movimiento']} — Rep. {d['tipo_rep']}\n"
        f"*Nombre:* {d['nombre']}\n"
        f"*Clave de elector:* {d.get('clave_elector') or '—'}\n"
        f"*Casilla/Ruta:* {d.get('casilla_ruta') or '—'}\n"
        f"*Observaciones:* {d.get('observaciones') or '—'}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Enviar", callback_data="conf:si"),
         InlineKeyboardButton("❌ Cancelar", callback_data="conf:no")],
    ])
    await update.message.reply_text(resumen, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
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
        f"✅ Solicitud registrada.\n\n*Tu folio es:* `{s['folio']}`\n\n"
        "Guárdalo para dar seguimiento con /estatus. Te notificaré aquí cada cambio de estado.",
        parse_mode=ParseMode.MARKDOWN,
    )

    # avisar a los administradores
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"📥 Nueva solicitud `{s['folio']}` de {data['solicitante']}\n\n" + ficha(s),
                parse_mode=ParseMode.MARKDOWN,
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
        f"{db.ESTADO_EMOJI.get(s['estado'],'')} `{s['folio']}` — {s['comite']} — "
        f"{s['tipo_movimiento']} {s['tipo_rep']} — {s['nombre']} — {s['estado']}"
        for s in filas
    ]
    await update.message.reply_text(
        f"*{len(filas)} pendientes:*\n\n" + "\n".join(lineas), parse_mode=ParseMode.MARKDOWN
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
    txt = ficha(s) + f"\n*Solicitante:* {s['solicitante']}\n\n*Historial:*\n"
    txt += "\n".join(
        f"• {h['fecha']:%d/%m %H:%M} — {h['estado']}" + (f" ({h['nota']})" if h["nota"] else "")
        for h in hist
    )
    await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)


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
    await update.message.reply_text(f"{e} `{s['folio']}` → *{estado}*", parse_mode=ParseMode.MARKDOWN)
    # notificar al solicitante
    try:
        msg = f"{e} Tu solicitud `{s['folio']}` cambió a *{estado}*."
        if nota:
            msg += f"\nNota: {nota}"
        await context.bot.send_message(s["chat_id"], msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as ex:
        log.warning("No pude notificar al solicitante de %s: %s", folio, ex)
        await update.message.reply_text("⚠️ No pude notificar al solicitante (quizá bloqueó el bot).")


async def resumen_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_admin(update):
        return
    filas = await db.resumen()
    total = sum(r["n"] for r in filas)
    lineas = [f"{db.ESTADO_EMOJI.get(r['estado'],'')} {r['estado']}: *{r['n']}*" for r in filas]
    await update.message.reply_text(
        f"*Resumen ({total} solicitudes):*\n\n" + "\n".join(lineas), parse_mode=ParseMode.MARKDOWN
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
        entry_points=[CommandHandler("nueva", nueva)],
        states={
            COMITE: [MessageHandler(filters.TEXT & ~filters.COMMAND, paso_comite)],
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

    log.info("Bot iniciando (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
