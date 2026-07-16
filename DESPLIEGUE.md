# Guía de despliegue — Bot Representantes PAN Querétaro

Progreso:
- [x] Paso 1 — Bot creado en @BotFather (token guardado)
- [x] Paso 2 — ID de Telegram obtenido (@userinfobot)
- [ ] Paso 3 — Subir código a GitHub (usuario: talkien01)
- [ ] Paso 4 — Postgres en Easypanel
- [ ] Paso 5 — App del bot en Easypanel + variables de entorno
- [ ] Paso 6 — Probar /nueva y compartir a comités

---

## Paso 3 — Subir a GitHub

### Opción A: por la web (sin instalar nada)
1. Entra a https://github.com/new
2. Repository name: `bot-representantes-qro`
3. Marca **Private**. No agregues README (ya hay uno).
4. Create repository.
5. En la página del repo vacío: **uploading an existing file**.
6. Arrastra TODOS los archivos de la carpeta `bot-representantes-qro`
   EXCEPTO: `bot-rep-qro.zip`, la carpeta `__pycache__` y cualquier `.env`.
   (Sí incluye: bot.py, db.py, schema.sql, requirements.txt, Dockerfile, README.md, .gitignore, DESPLIEGUE.md)
7. Commit changes.

### Opción B: con Git instalado (terminal, dentro de la carpeta del proyecto)
```
git init
git add .
git commit -m "Bot de solicitudes de representantes - version inicial"
git branch -M main
git remote add origin https://github.com/talkien01/bot-representantes-qro.git
git push -u origin main
```
(El .gitignore ya evita subir .env, __pycache__ y el zip.)

---

## Paso 4 — Postgres en Easypanel
1. En tu proyecto de Easypanel: **+ Service → Postgres**.
2. Nombre del servicio: `postgres` (o el que quieras; anótalo).
3. Anota: usuario, contraseña y nombre de la base.
4. El bot crea las tablas solo al arrancar (no hay que correr SQL a mano).

## Paso 5 — App del bot en Easypanel
1. **+ Service → App**.
2. Source: **GitHub** → conecta tu cuenta talkien01 → elige el repo `bot-representantes-qro` → rama `main`.
3. Build: **Dockerfile** (ya incluido en el repo).
4. Pestaña **Environment** → agrega estas 3 variables:
   ```
   BOT_TOKEN=el_token_de_botfather
   DATABASE_URL=postgresql://USUARIO:PASSWORD@postgres:5432/NOMBRE_BASE
   ADMIN_IDS=tu_id_de_telegram
   ```
   - Reemplaza USUARIO, PASSWORD y NOMBRE_BASE con lo del Paso 4.
   - El host (`postgres`) es el nombre del servicio Postgres del Paso 4.
   - Para varios admins: `ADMIN_IDS=111,222`
5. **Deploy**. Usa polling: NO necesita dominio ni puerto expuesto.
6. Revisa **Logs**: debe decir `Base de datos lista` y `Bot iniciando (polling)...`.

## Paso 6 — Probar
1. Abre tu bot en Telegram (t.me/TU_USERNAME_BOT) y manda `/start`.
2. Manda `/nueva` y captura una solicitud de prueba → debe darte un folio.
3. Como admin, prueba `/pendientes`, `/actualizar FOLIO PROCESADA`, `/export`.
4. Cuando funcione, comparte el link del bot en el grupo de WhatsApp de los comités.

## Seguridad
- El token y la contraseña van SOLO en las variables de entorno de Easypanel, nunca en el repo.
- El repo debe ser PRIVADO.
- Activa backups del servicio Postgres en Easypanel.
