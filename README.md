# Mesa de ayuda de representantes — PAN Querétaro

Bot de Telegram tipo **help desk**: los comités municipales dan de alta a sus representantes generales (RG) y de casilla (RC) **directamente en la plataforma oficial**; este bot **no hace las altas**, sino que registra **tickets de soporte** cuando algo les falla (no pueden dar de alta un RG, la ruta no es válida, error del sistema, ayuda con RC).

Cada ticket recibe un **folio** (`QRO-AAMM-0001`), queda en Postgres con historial y evidencia opcional, y quien reporta recibe notificación automática en cada cambio de estado.

## Flujo

1. El comité escribe cualquier mensaje ("hola") o `/ayuda` → wizard: municipio → tipo de problema → descripción → captura opcional (cámara o galería) → recibe su folio.
2. Tú (soporte) recibes el ticket al instante, con la evidencia si la adjuntaron.
3. Atiendes: `/actualizar QRO-2607-0001 EN_ATENCION` → el comité recibe la notificación.
4. Estados: `RECIBIDO → EN_ATENCION → RESUELTO` (o `ESCALADO` / `CERRADO`).

## Comandos

| Comando | Quién | Descripción |
|---|---|---|
| `/ayuda` | Comités | Levantar un ticket de soporte, genera folio |
| `/estatus FOLIO` | Comités | Consultar estado |
| `/mis` | Comités | Últimos 10 tickets propios |
| `/pendientes` | Soporte | Tickets abiertos |
| `/detalle FOLIO` | Soporte | Ficha completa + historial + evidencia |
| `/actualizar FOLIO ESTADO [nota]` | Soporte | Cambia estado y notifica al comité |
| `/resumen` | Soporte | Conteo por estado |
| `/export` | Soporte | CSV con todo (ábrelo en Excel) |

El bot también responde a cualquier saludo con una bienvenida y botones (🆘 Necesito ayuda, 🔎 Consultar folio, 📋 Mis tickets), así los comités operan sin teclear comandos.

## Categorías de problema

Se configuran en `db.py` (lista `CATEGORIAS`): no puedo dar de alta un RG, ruta no válida, error del sistema/plataforma, ayuda para dar de alta un RC, y otro.

## Evidencia (fotos/capturas)

En el paso de evidencia, Telegram ofrece **Cámara** (tomar la foto en el momento) o **Galería**. El bot acepta fotos y también imágenes enviadas como archivo. La evidencia se guarda referenciada en Telegram y soporte la ve con `/detalle`.

## Despliegue en Easypanel (Hostinger)

### 1. Crear el bot en Telegram
1. Habla con **@BotFather** → `/newbot` → copia el **token**.
2. Habla con **@userinfobot** para obtener tu **ID numérico** (para `ADMIN_IDS`).

### 2. Postgres en Easypanel
1. **+ Service → Postgres**. Anota usuario, contraseña, base y nombre del servicio.
2. El bot crea las tablas solo al arrancar.

### 3. La app del bot
1. **+ Service → App**, fuente GitHub (repo conectado), build por **Dockerfile**.
2. Variables de entorno:
   ```
   BOT_TOKEN=el_token_de_botfather
   DATABASE_URL=postgresql://usuario:password@nombre-servicio-postgres:5432/base
   ADMIN_IDS=tu_id_de_telegram
   ```
3. Deploy. Usa *polling*: no necesita dominio ni puerto expuesto.
4. Logs deben decir `Base de datos lista` y `Bot iniciando (polling)...`.

### 4. Distribuir a los comités
Comparte `t.me/TuBot` en el grupo de WhatsApp: "Si tienes problemas para dar de alta a tus RG/RC, entra al bot y escribe /ayuda; te damos folio y seguimiento."

## Buenas prácticas de operación

- **Todo por ticket**: si te piden ayuda por WhatsApp/llamada, pídeles que lo metan al bot. El folio es tu respaldo y evita perder casos.
- **Cierra el ciclo**: no dejes tickets en `EN_ATENCION`; pásalos a `RESUELTO` o `CERRADO`.
- **Escala con nota**: `/actualizar FOLIO ESCALADO se reportó a sistemas del CDE`.
- **Export periódico**: `/export` como respaldo y reporte al CDE.
- **Nota importante**: el bot da soporte, no sustituye la captura oficial; recuérdaselo a los comités para deslindar responsabilidad.

## Respaldo de la base
Activa los backups del servicio Postgres en Easypanel. Como mínimo, corre `/export` seguido.
