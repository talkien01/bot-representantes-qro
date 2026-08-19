"""Bot de soporte + verificación previa de Telegram para capacitación RG/RC.

Mantiene intacta la mesa de ayuda existente (bot.py) y agrega una Fase 0:
verificar que el usuario ya puede interactuar correctamente con Telegram.
"""
import csv
import html
import io
import logging

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
HTML = ParseMode.HTML

VER_MUNICIPIO, VER_CONFIRMACION = range(100, 102)


def esc(x) -> str:
    return html.escape(str(x)) if x is not None else ""


def menu_no_verificado() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ INICIAR VERIFICACIÓN", callback_data="ver:iniciar")],
        [InlineKeyboardButton("🆘 Necesito ayuda", callback_data="go:ayuda")],
    ])


def teclado_municipios() -> InlineKeyboardMarkup:
    filas, fila = [], []
    for i, nombre in enumerate(soporte.COMITES):
        fila.append(InlineKeyboardButton(nombre, callback_data=f"vermun:{i}"))
        if len(fila) == 2:
            filas.append(fila)
            fila = []
    if fila:
        filas.append(fila)
    return InlineKeyboardMarkup(filas)


async def bienvenida_verificacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entrada principal: si ya está verificado, muestra la mesa de ayuda normal."""
    u = update.effective_user
    if u and await vdb.esta_verificado(u.id):
        await vdb.tocar(u.id)
        return await soporte.start(update, context)

    txt = (
        "👋 <b>Bienvenido al Bot de Soporte de Acción Electoral Querétaro.</b>\n\n"
        "Antes de participar en la capacitación necesitamos comprobar que "
        "<b>Telegram funciona correctamente en tu teléfono</b>.\n\n"
        "Este proceso toma menos de 2 minutos.\n\n"
        "💡 <b>Telegram es gratuito.</b> No necesitas contratar Telegram Premium para usar AcciónMX.\n\n"
        "Presiona el botón para comenzar."
    )
    dest = update.message or (update.callback_query and update.callback_query.message)
    await dest.reply_text(txt, parse_mode=HTML, reply_markup=menu_no_verificado())


async def verificar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("ver_municipio", None)
    if update.callback_query:
        await update.callback_query.answer()
        dest = update.callback_query.message
    else:
        dest = update.message

    u = update.effective_user
    if await vdb.esta_verificado(u.id):
        row = await vdb.obtener(u.id)
        await dest.reply_text(
            "✅ <b>Tu Telegram ya está verificado.</b>\n\n"
            f"Nombre: {esc(row['nombre'])}\n"
            f"Municipio: {esc(row['municipio'])}\n"
            f"Fecha: {row['fecha_verificacion']:%d/%m/%Y %H:%M}\n\n"
            "Ya estás listo para la capacitación.",
            parse_mode=HTML,
        )
        return ConversationHandler.END

    await dest.reply_text(
        "✅ <b>Verificación de Telegram</b>\n\n"
        "Paso 1 de 2: selecciona tu <b>municipio</b>.",
        parse_mode=HTML,
        reply_markup=teclado_municipios(),
    )
    return VER_MUNICIPIO


async def paso_ver_municipio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    idx = int(q.data.split(":")[1])
    municipio = soporte.COMITES[idx]
    context.user_data["ver_municipio"] = municipio

    await q.edit_message_text(
        f"Municipio: <b>{esc(municipio)}</b>",
        parse_mode=HTML,
    )
    await q.message.reply_text(
        "Paso 2 de 2:\n\n"
        "Si puedes leer este mensaje y tocar el botón de abajo, "
        "tu Telegram está funcionando correctamente.\n\n"
        "Presiona <b>Confirmar</b> para terminar.",
        parse_mode=HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ CONFIRMAR QUE VEO ESTE MENSAJE", callback_data="ver:confirmar")],
            [InlineKeyboardButton("↩️ Cambiar municipio", callback_data="ver:cambiar")],
        ]),
    )
    return VER_CONFIRMACION


async def paso_ver_confirmacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "ver:cambiar":
        await q.message.reply_text(
            "Selecciona nuevamente tu municipio:",
            reply_markup=teclado_municipios(),
        )
        return VER_MUNICIPIO

    u = update.effective_user
    municipio = context.user_data.get("ver_municipio")
    if not municipio:
        await q.message.reply_text("No pude recuperar el municipio. Usa /verificar para comenzar otra vez.")
        return ConversationHandler.END

    row = await vdb.guardar_verificacion(
        telegram_id=u.id,
        chat_id=update.effective_chat.id,
        username=u.username,
        nombre=u.full_name,
        municipio=municipio,
    )
    context.user_data.pop("ver_municipio", None)

    await q.edit_message_text(
        "✅ <b>TELEGRAM VERIFICADO CORRECTAMENTE</b>\n\n"
        "Tu cuenta está funcionando y ya estás listo para participar en la capacitación de Acción Electoral.\n\n"
        f"<b>Nombre:</b> {esc(row['nombre'])}\n"
        f"<b>Municipio:</b> {esc(row['municipio'])}\n\n"
        "A partir de ahora también puedes usar este bot cuando necesites soporte técnico.",
        parse_mode=HTML,
    )

    # Aviso a soporte para que pueda llevar el control previo de participantes.
    usuario = f"@{u.username}" if u.username else "sin username"
    for admin_id in soporte.ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                "✅ <b>Nuevo usuario verificado en Telegram</b>\n\n"
                f"<b>Nombre:</b> {esc(u.full_name)}\n"
                f"<b>Municipio:</b> {esc(municipio)}\n"
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
    u = update.effective_user
    row = await vdb.obtener(u.id)
    if not row or row.get("estado") != "VERIFICADO":
        await update.message.reply_text(
            "⚠️ Aún no has completado la verificación. Usa /verificar para comenzar."
        )
        return
    await update.message.reply_text(
        "✅ <b>Telegram verificado</b>\n\n"
        f"Nombre: {esc(row['nombre'])}\n"
        f"Municipio: {esc(row['municipio'])}\n"
        f"Fecha: {row['fecha_verificacion']:%d/%m/%Y %H:%M}",
        parse_mode=HTML,
    )


async def verificados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not soporte.es_admin(update):
        return
    filas = await vdb.listar(50)
    if not filas:
        await update.message.reply_text("Todavía no hay usuarios verificados.")
        return
    lineas = [
        f"✅ {esc(r['nombre'])} — {esc(r['municipio'])}"
        + (f" — @{esc(r['username'])}" if r.get("username") else "")
        for r in filas
    ]
    await update.message.reply_text(
        f"<b>Últimos {len(filas)} usuarios verificados:</b>\n\n" + "\n".join(lineas),
        parse_mode=HTML,
    )


async def resumen_verificacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not soporte.es_admin(update):
        return
    filas = await vdb.resumen_municipio()
    total = sum(r["n"] for r in filas)
    if not filas:
        await update.message.reply_text("Todavía no hay usuarios verificados.")
        return
    lineas = [f"{esc(r['municipio'])}: <b>{r['n']}</b>" for r in filas]
    await update.message.reply_text(
        f"✅ <b>Telegram verificado: {total}</b>\n\n" + "\n".join(lineas),
        parse_mode=HTML,
    )


async def export_verificacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not soporte.es_admin(update):
        return
    filas = await vdb.todas()
    if not filas:
        await update.message.reply_text("No hay usuarios verificados que exportar.")
        return
    data = vdb.csv_bytes(filas)
    await update.message.reply_document(data, caption=f"{len(filas)} usuarios verificados")


async def texto_suelto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mantiene el comportamiento amigable del bot según el estado de verificación."""
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
        BotCommand("verificar", "Verificar que Telegram funciona"),
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
            VER_MUNICIPIO: [CallbackQueryHandler(paso_ver_municipio, pattern=r"^vermun:")],
            VER_CONFIRMACION: [CallbackQueryHandler(paso_ver_confirmacion, pattern=r"^ver:(confirmar|cambiar)$")],
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
    app.add_handler(CommandHandler("resumen_verificacion", resumen_verificacion))
    app.add_handler(CommandHandler("export_verificacion", export_verificacion))
    app.add_handler(CallbackQueryHandler(soporte.menu_go, pattern=r"^go:(estatus|mis)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, texto_suelto))

    async def on_error(update, context):
        log.exception("Excepción en un handler", exc_info=context.error)

    app.add_error_handler(on_error)

    log.info("Bot soporte + verificación iniciando (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
