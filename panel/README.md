# Panel web administrativo — Mesa de ayuda

Panel web para ver y atender los tickets sin usar Telegram. Lee y escribe en la **misma base Postgres** que el bot, muestra la **evidencia** (descargándola de Telegram con el mismo token) y, al cambiar un estado, **notifica al comité** por Telegram automáticamente.

## Qué incluye
- Tablero con contadores por estado (Total, Abiertos, Recibido, En atención, Resuelto, Escalado, Cerrado).
- Tabla de tickets con **filtros** por estado y municipio.
- Detalle de cada ticket: descripción, quién reporta, historial, **evidencia (imagen)** y formulario para **cambiar el estado + nota**.
- Botón **Exportar CSV**.
- **Login** con usuario y contraseña (HTTP Basic).

## Despliegue en Easypanel (segundo servicio)

El panel vive en la subcarpeta `panel/` del mismo repo. Se despliega como un servicio App aparte.

1. En tu proyecto de Easypanel: **+ Service → App**.
2. Nombre: `panel`.
3. **Source**: GitHub → el mismo repo `bot-representantes-qro`, rama `main`.
4. **Build**: Dockerfile. En **Build Context / Directory** pon `panel` (para que use `panel/Dockerfile`).
   - Si tu versión de Easypanel no tiene "Build Context", usa el campo **Dockerfile Path** = `panel/Dockerfile`.
5. **Environment** (variables):
   ```
   DATABASE_URL=postgresql://usuario:password@postgres:5432/base   (la misma del bot)
   BOT_TOKEN=el_mismo_token_del_bot
   PANEL_USER=el_usuario_que_quieras
   PANEL_PASSWORD=una_contraseña_fuerte
   ```
6. **Domains / Ports**: el panel escucha en el puerto **8080**. Agrega un dominio (Easypanel te da uno gratis tipo `panel-xxxx.easypanel.host` con HTTPS) apuntando al puerto 8080.
7. **Deploy**. Entra al dominio → te pide usuario/contraseña (los de `PANEL_USER`/`PANEL_PASSWORD`).

> Importante: como el panel sí se expone a internet (a diferencia del bot), la contraseña es tu única barrera. Usa una larga y única, y compártela solo con quien atienda soporte.

## Metabase (reportes y gráficas, sin código)

Para tableros visuales (tickets por municipio, por estado, tiempos de respuesta):

1. En Easypanel: **+ Service → Templates** → busca **Metabase** → instálalo (un clic).
2. Ábrelo, crea tu cuenta de administrador.
3. **Add a database → PostgreSQL** y conéctalo a tu Postgres:
   - Host: `postgres` (nombre del servicio), Puerto: `5432`
   - Base, usuario y contraseña: los mismos del bot.
4. Metabase lee la tabla `tickets` e `historial`. Crea preguntas/gráficas y agrúpalas en un Dashboard.

Metabase es **solo lectura para tu operación**: sirve para ver y reportar, no para cambiar estados (eso se hace en el panel o en Telegram).

## Resumen de servicios en Easypanel
- `postgres` — base de datos (ya lo tienes)
- `bot` — bot de Telegram (ya lo tienes)
- `panel` — este panel web (nuevo)
- `metabase` — reportes (opcional)

Todos comparten la misma base Postgres.
