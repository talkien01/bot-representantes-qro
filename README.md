# Bot de solicitudes de representantes — PAN Querétaro

Bot de Telegram para que los comités distritales/municipales registren solicitudes de **alta, baja o sustitución** de representantes generales y de casilla. Cada solicitud recibe un **folio** (`QRO-AAMM-0001`), queda en Postgres con historial, y el comité recibe notificación automática en cada cambio de estado.

## Flujo

1. El comité envía `/nueva` al bot → wizard guiado (comité, movimiento, tipo de rep., nombre, clave de elector, casilla/ruta, observaciones) → recibe su folio.
2. Tú (admin) recibes aviso inmediato de cada solicitud nueva.
3. La procesas en el sistema del INE y actualizas: `/actualizar QRO-2607-0001 PROCESADA` → el comité recibe la notificación.
4. Estados: `RECIBIDA → EN_PROCESO → PROCESADA → CONFIRMADA` (o `RECHAZADA` con nota).

## Comandos

| Comando | Quién | Descripción |
|---|---|---|
| `/nueva` | Comités | Registrar solicitud, genera folio |
| `/estatus FOLIO` | Comités | Consultar estado |
| `/mis` | Comités | Últimas 10 solicitudes propias |
| `/pendientes` | Admin | Solicitudes abiertas |
| `/detalle FOLIO` | Admin | Ficha completa + historial |
| `/actualizar FOLIO ESTADO [nota]` | Admin | Cambia estado y notifica al comité |
| `/resumen` | Admin | Conteo por estado |
| `/export` | Admin | CSV con todo (ábrelo en Excel) |

## Despliegue en Easypanel (Hostinger)

### 1. Crear el bot en Telegram
1. Habla con **@BotFather** → `/newbot` → nombre y username → copia el **token**.
2. Habla con **@userinfobot** para obtener tu **ID numérico** (para `ADMIN_IDS`).

### 2. Postgres en Easypanel
1. En tu proyecto de Easypanel: **+ Service → Postgres**.
2. Anota usuario, contraseña y el hostname interno (normalmente el nombre del servicio).
3. Crea la base `representantes` (o usa la default). El bot crea las tablas solo al arrancar.

### 3. La app del bot
1. **+ Service → App**, fuente: sube este código a un repo Git (GitHub) y conéctalo, o usa "Upload".
2. Build: **Dockerfile** (ya incluido).
3. Variables de entorno (pestaña *Environment*):
   ```
   BOT_TOKEN=el_token_de_botfather
   DATABASE_URL=postgresql://usuario:password@nombre-servicio-postgres:5432/representantes
   ADMIN_IDS=tu_id_de_telegram
   ```
4. Deploy. El bot usa *polling*, así que **no necesita dominio ni puerto expuesto**.
5. Revisa los logs: debe decir `Base de datos lista` y `Bot iniciando (polling)...`.

### 4. Distribuir a los comités
Comparte el link `t.me/TuBot` en el grupo de WhatsApp de los comités con un mini instructivo: "Para altas/bajas de representantes, entra al bot, manda /nueva y guarda tu folio."

## Buenas prácticas de operación

- **Nada sin folio**: si te piden algo por WhatsApp/llamada, pídeles que lo metan al bot (o mételo tú con /nueva). El folio es tu respaldo.
- **Cierra el ciclo**: no dejes solicitudes en `PROCESADA`; confirma en el sistema del INE y pásalas a `CONFIRMADA`.
- **Rechazos siempre con nota**: `/actualizar FOLIO RECHAZADA falta clave de elector`.
- **Export semanal**: `/export` y guarda el CSV como respaldo/reporte al CDE.
- **Plazos del INE**: ten a la mano las fechas límite de sustitución de representantes; revisa `/pendientes` a diario conforme se acerque el corte.

## Respaldo de la base

En Easypanel el servicio de Postgres tiene opción de backups; actívala. Como mínimo, corre `/export` periódicamente.
