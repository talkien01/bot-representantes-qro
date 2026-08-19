"""Bot de soporte + verificación previa de Telegram para capacitación RG/RC.

La mesa de ayuda existente se conserva en ``bot.py``. Esta entrada agrega una
Fase 0 basada en un padrón de convocados: cada persona introduce su código único
y el bot vincula ese registro con su cuenta de Telegram.
"""
import logging
import warnings

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import bot as soporte
import verification_db as vdb

log = logging.getLogger("bot_verificacion")
logging.getLogger("httpx").setLevel(logging.WARNING)  # evita imprimir URLs con BOT_TOKEN
warnings.filterwarnings("ignore", message=r"If 'per_message=False'.*", category=UserWarning)
HTML = ParseMode.HTML

VER_CODIGO, VER_CONFIRMACION = range(100, 102)


def esc(x) -> str:
    import html
    return html.escape(str(x)) if x is not None else ""


def menu_no_verificado() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ INICIAR VERIFICACIÓN", callback_data="ver:iniciar")],
        [InlineKeyboardButton("🆘 Necesito ayuda", callback_data="go:ayuda")],
    ])


async def bienvenida_verificacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entrada principal: usuarios ya verificados pasan al menú normal de soporte."""
    u = update.effective_user
    if u and await vdb.esta_verificado(u.id):
        await vdb.tocar(u.id)
        return await soporte.start(update, context)

    txt = (
        "👋 <b>Bienvenido al Bot de Soporte de Acción Electoral Querétaro.</b>\n\n"
        "Antes de participar en la capacitación necesitamos comprobar que "
        "<b>Telegram funciona correctamente en tu teléfono</b> y vincular tu cuenta "
        "con la lista de personas convocadas.\n\n"
        "Este proceso toma menos de 2 minutos.\n\n"
        "💡 <b>Telegram es gratuito.</b> No necesitas contratar Telegram Premium para usar AcciónMX.\n\n"
        "Ten a la mano tu <b>código de convocatoria</b> y presiona el botón para comenzar."
    )
    dest = update.message or (update.callback_query and update.callback_query.message)
    await dest.reply_text(txt, parse_mode=HTML, reply_markup=menu_no_verificado())


async def verificar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("convocado_id", None)
    context.user_data.pop("codigo_verificacion", None)
    if update.callback_query:
        await update.callback_query.answer()
        dest = update.callback_query.message
    else:
        dest = update.message

    u = update.effective_user
    existente = await vdb.obtener_por_telegram(u.id)
    if existente and existente.get("telegram_verificado"):
        await dest.reply_text(
            "✅ <b>Tu Telegram ya está verificado.</b>\n\n"
            f"<b>Código:</b> <code>{esc(existente['codigo_verificacion'])}</code>\n"
            f"<b>Nombre:</b> {esc(existente['nombre_completo'])}\n"
            f"<b>Municipio:</b> {esc(existente['municipio'])}\n"
            f"<b>Fecha:</b> {existente['fecha_verificacion']:%d/%m/%Y %H:%M}\n\n"
            "Ya estás listo para la capacitación.",
            parse_mode=HTML,
        )
        return ConversationHandler.END

    await dest.reply_text(
        "✅ <b>Verificación de Telegram</b>\n\n"
        "Escribe tu <b>código de convocatoria</b>.\n\n"
        "Ejemplo: <code>COR-00015</code>\n\n"
        "El código aparece en la lista o mensaje de convocatoria que te proporciona tu coordinación.",
        parse_mode=HTML,
    )
    return VER_CODIGO


async def paso_ver_codigo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    codigo = vdb.normalizar_codigo(update.message.text)
    row = await vdb.obtener_codigo(codigo)
    if not row:
        await update.message.reply_text(
            "❌ <b>No encontré ese código.</b>\n\n"
            "Revísalo e inténtalo nuevamente. Escríbelo completo, por ejemplo "
            "<code>COR-00015</code>.\n\n"
            "Si no tienes código, usa /cancelar y solicita apoyo a tu coordinación.",
            parse_mode=HTML,
        )
        return VER_CODIGO

    u = update.effective_user
    if row.get("telegram_id") and row["telegram_id"] != u.id:
        await update.message.reply_text(
            "⚠️ <b>Ese código ya está vinculado a otra cuenta de Telegram.</b>\n\n"
            "Por seguridad no puedo reutilizarlo. Solicita apoyo con /ayuda.",
            parse_mode=HTML,
        )
        return ConversationHandler.END

    if row.get("telegram_verificado") and row.get("telegram_id") == u.id:
        await update.message.reply_text(
            "✅ Este código ya está verificado con tu cuenta.\n"
            "Usa /miverificacion para consultar tus datos."
        )
        return ConversationHandler.END

    context.user_data["convocado_id"] = row["id"]
    context.user_data["codigo_verificacion"] = row["codigo_verificacion"]

    cargo = row.get("cargo") or "—"
    seccion = row.get("seccion") or "—"
    await update.message.reply_text(
        "🔎 <b>Encontré tu registro.</b>\n\n"
        f"<b>Código:</b> <code>{esc(row['codigo_verificacion'])}</code>\n"
        f"<b>Nombre:</b> {esc(row['nombre_completo'])}\n"
        f"<b>Municipio:</b> {esc(row['municipio'])}\n"
        f"<b>Cargo:</b> {esc(cargo)}\n"
        f"<b>Sección:</b> {esc(seccion)}\n\n"
        "¿Estos datos corresponden a ti?",
        parse_mode=HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ SÍ, SOY YO", callback_data="ver:si")],
            [InlineKeyboardButton("❌ NO SON MIS DATOS", callback_data="ver:no")],
        ]),
    )
    return VER_CONFIRMACION


async def paso_ver_confirmacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "ver:no":
        context.user_data.pop("convocado_id", None)
        context.user_data.pop("codigo_verificacion", None)
        await q.edit_message_text(
            "Verificación cancelada. No se vinculó ninguna cuenta.\n\n"
            "Revisa tu código y usa /verificar para intentar nuevamente."
        )
        return ConversationHandler.END

    convocado_id = context.user_data.get("convocado_id")
    if not convocado_id:
        await q.message.reply_text("No pude recuperar tu registro. Usa /verificar para comenzar otra vez.")
        return ConversationHandler.END

    u = update.effective_user
    try:
        row = await vdb.vincular_convocado(
            convocado_id=convocado_id,
            telegram_id=u.id,
            username=u.username,
            telegram_nombre=u.full_name,
        )
    except Exception as exc:
        log.exception("Error vinculando convocado %s: %s", convocado_id, exc)
        await q.edit_message_text(
            "⚠️ No pude completar la verificación. Puede existir otra vinculación con tu cuenta. "
            "Solicita apoyo con /ayuda."
        )
        return ConversationHandler.END

    context.user_data.pop("convocado_id", None)
    context.user_data.pop("codigo_verificacion", None)

    if not row:
        await q.edit_message_text(
            "⚠️ Este código ya quedó asociado a otra cuenta. Solicita apoyo con /ayuda."
        )
        return ConversationHandler.END

    await q.edit_message_text(
        "✅ <b>TELEGRAM VERIFICADO CORRECTAMENTE</b>\n\n"
        "Tu cuenta quedó vinculada con la lista oficial de convocados.\n\n"
        f"<b>Código:</b> <code>{esc(row['codigo_verificacion'])}</code>\n"
        f"<b>Nombre:</b> {esc(row['nombre_completo'])}\n"
        f"<b>Municipio:</b> {esc(row['municipio'])}\n\n"
        "Ya estás listo para participar en la capacitación de Acción Electoral.",
        parse_mode=HTML,
    )

    usuario = f"@{u.username}" if u.username else "sin username"
    for admin_id in soporte.ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                "✅ <b>Convocado verificado en Telegram</b>\n\n"
                f"<b>Código:</b> <code>{esc(row['codigo_verificacion'])}</code>\n"
                f"<b>Nombre:</b> {esc(row['nombre_completo'])}\n"
                f"<b>Municipio:</b> {esc(row['municipio'])}\n"
                f"<b>Cargo:</b> {esc(row.get('cargo') or '—')}\n"
                f"<b>Usuario:</b> {esc(usuario)}\n"
                f"<b>Telegram ID:</b> <code>{u.id}</code>",
                parse_mode=HTML,
            )
        except Exception as exc:
            log.warning("No pude avisar verificación a admin %s: %s", admin_id, exc)

    await q.message.reply_text(
        "¿Necesitas algo más?",
        reply_markup=soporte._menu_bienvenida(),
    )
    return ConversationHandler.END


async def mi_verificacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = await vdb.obtener_por_telegram(update.effective_user.id)
    if not row or not row.get("telegram_verificado"):
        await update.message.reply_text(
            "⚠️ Aún no has completado la verificación. Usa /verificar para comenzar."
        )
        return
    await update.message.reply_text(
        "✅ <b>Telegram verificado</b>\n\n"
        f"Código: <code>{esc(row['codigo_verificacion'])}</code>\n"
        f"Nombre: {esc(row['nombre_completo'])}\n"
        f"Municipio: {esc(row['municipio'])}\n"
        f"Cargo: {esc(row.get('cargo') or '—')}\n"
        f"Fecha: {row['fecha_verificacion']:%d/%m/%Y %H:%M}",
        parse_mode=HTML,
    )


async def verificados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not soporte.es_admin(update):
        return
    filas = await vdb.listar_verificados(50)
    if not filas:
        await update.message.reply_text("Todavía no hay convocados verificados.")
        return
    lineas = [
        f"✅ <code>{esc(r['codigo_verificacion'])}</code> — {esc(r['nombre_completo'])} — {esc(r['municipio'])}"
        for r in filas
    ]
    await update.message.reply_text(
        f"<b>Últimos {len(filas)} convocados verificados:</b>\n\n" + "\n".join(lineas),
        parse_mode=HTML,
    )


async def pendientes_verificacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not soporte.es_admin(update):
        return
    filas = await vdb.listar_pendientes(50)
    if not filas:
        await update.message.reply_text("🎉 No hay convocados pendientes de verificar.")
        return
    lineas = [
        f"⏳ <code>{esc(r['codigo_verificacion'])}</code> — {esc(r['nombre_completo'])} — {esc(r['municipio'])}"
        for r in filas
    ]
    await update.message.reply_text(
        f"<b>{len(filas)} pendientes (máximo 50):</b>\n\n" + "\n".join(lineas),
        parse_mode=HTML,
    )


async def resumen_verificacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not soporte.es_admin(update):
        return
    general = await vdb.resumen_general()
    total = general["total"] or 0
    ver = general["verificados"] or 0
    pen = general["pendientes"] or 0
    pct = (ver / total * 100) if total else 0
    filas = await vdb.resumen_municipio()
    lineas = []
    for r in filas:
        p = (r["verificados"] / r["total"] * 100) if r["total"] else 0
        lineas.append(
            f"{esc(r['municipio'])}: <b>{r['verificados']}/{r['total']}</b> ({p:.1f}%) — pendientes {r['pendientes']}"
        )
    detalle = "\n".join(lineas) if lineas else "Aún no se ha cargado el padrón."
    await update.message.reply_text(
        "📊 <b>Control de verificación</b>\n\n"
        f"Convocados: <b>{total}</b>\n"
        f"Telegram verificado: <b>{ver}</b>\n"
        f"Pendientes: <b>{pen}</b>\n"
        f"Avance: <b>{pct:.1f}%</b>\n\n"
        f"<b>Por municipio:</b>\n{detalle}",
        parse_mode=HTML,
    )


async def export_verificacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not soporte.es_admin(update):
        return
    filas = await vdb.todas()
    if not filas:
        await update.message.reply_text("No hay convocados que exportar.")
        return
    data = vdb.csv_bytes(filas)
    await update.message.reply_document(data, caption=f"{len(filas)} convocados")


async def texto_suelto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if u and await vdb.esta_verificado(u.id):
        await vdb.tocar(u.id)
        await soporte.start(update, context)
    else:
        await bienvenida_verificacion(update, context)


async def post_init(app: Application):
    await soporte.db.init_db()
    await vdb.init_db()
    log.info("Bases de datos listas.")
    await app.bot.set_my_commands([
        BotCommand("start", "Inicio"),
        BotCommand("verificar", "Verificar mi Telegram con mi código"),
        BotCommand("miverificacion", "Consultar mi verificación"),
        BotCommand("ayuda", "Levantar un ticket de soporte"),
        BotCommand("estatus", "Consultar un folio"),
        BotCommand("mis", "Mis tickets"),
        BotCommand("cancelar", "Cancelar captura en curso"),
    ])


async def post_shutdown(app: Application):
    await soporte.db.close_db()
    await vdb.close_db()


def main():
    app = (
        Application.builder()
        .token(soporte.BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    verificacion = ConversationHandler(
        entry_points=[
            CommandHandler("verificar", verificar),
            CallbackQueryHandler(verificar, pattern=r"^ver:iniciar$"),
        ],
        states={
            VER_CODIGO: [MessageHandler(filters.TEXT & ~filters.COMMAND, paso_ver_codigo)],
            VER_CONFIRMACION: [CallbackQueryHandler(paso_ver_confirmacion, pattern=r"^ver:(si|no)$")],
        },
        fallbacks=[CommandHandler("cancelar", soporte.cancelar)],
    )

    soporte_wizard = ConversationHandler(
        entry_points=[
            CommandHandler("ayuda", soporte.ayuda),
            CallbackQueryHandler(soporte.ayuda, pattern=r"^go:ayuda$"),
        ],
        states={
            soporte.MUNICIPIO: [CallbackQueryHandler(soporte.paso_municipio, pattern=r"^com:")],
            soporte.CATEGORIA: [CallbackQueryHandler(soporte.paso_categoria, pattern=r"^cat:")],
            soporte.DESCRIPCION: [MessageHandler(filters.TEXT & ~filters.COMMAND, soporte.paso_descripcion)],
            soporte.EVIDENCIA: [
                MessageHandler(filters.PHOTO, soporte.paso_evidencia_foto),
                MessageHandler(filters.Document.IMAGE, soporte.paso_evidencia_doc),
                MessageHandler(filters.TEXT & ~filters.COMMAND, soporte.paso_evidencia_texto),
            ],
            soporte.CONFIRMA: [CallbackQueryHandler(soporte.paso_confirma, pattern=r"^conf:")],
        },
        fallbacks=[CommandHandler("cancelar", soporte.cancelar)],
    )

    app.add_handler(CommandHandler("start", bienvenida_verificacion))
    app.add_handler(verificacion)
    app.add_handler(soporte_wizard)
    app.add_handler(CommandHandler("miverificacion", mi_verificacion))
    app.add_handler(CommandHandler("estatus", soporte.estatus))
    app.add_handler(CommandHandler("mis", soporte.mis))
    app.add_handler(CommandHandler("pendientes", soporte.pendientes))
    app.add_handler(CommandHandler("detalle", soporte.detalle))
    app.add_handler(CommandHandler("actualizar", soporte.actualizar))
    app.add_handler(CommandHandler("resumen", soporte.resumen_cmd))
    app.add_handler(CommandHandler("export", soporte.export))
    app.add_handler(CommandHandler("verificados", verificados))
    app.add_handler(CommandHandler("pendientes_verificacion", pendientes_verificacion))
    app.add_handler(CommandHandler("resumen_verificacion", resumen_verificacion))
    app.add_handler(CommandHandler("export_verificacion", export_verificacion))
    app.add_handler(CallbackQueryHandler(soporte.menu_go, pattern=r"^go:(estatus|mis)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, texto_suelto))

    async def on_error(update, context):
        log.exception("Excepción en un handler", exc_info=context.error)

    app.add_error_handler(on_error)
    log.info("Bot soporte + padrón + verificación iniciando (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
