"""
Panel web administrativo — Mesa de ayuda de representantes (PAN Querétaro).

Lee y actualiza los mismos tickets que el bot de Telegram (misma base Postgres).
Muestra la evidencia (que vive en Telegram) descargándola con el BOT_TOKEN.
Al cambiar un estado desde el panel, notifica al comité por Telegram.

Variables de entorno:
  DATABASE_URL    - misma cadena que usa el bot
  BOT_TOKEN       - mismo token del bot (para ver evidencia y notificar)
  PANEL_USER      - usuario para entrar al panel
  PANEL_PASSWORD  - contraseña para entrar al panel
"""
import os
import secrets
from datetime import datetime

import httpx
import psycopg
from psycopg.rows import dict_row
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

DATABASE_URL = os.environ["DATABASE_URL"]
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
PANEL_USER = os.environ.get("PANEL_USER", "admin")
PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "cambia-esto")

ESTADOS = ["RECIBIDO", "EN_ATENCION", "RESUELTO", "ESCALADO", "CERRADO"]
ESTADOS_ABIERTOS = ["RECIBIDO", "EN_ATENCION", "ESCALADO"]
ESTADO_COLOR = {
    "RECIBIDO": "#2563eb", "EN_ATENCION": "#d97706", "RESUELTO": "#16a34a",
    "ESCALADO": "#dc2626", "CERRADO": "#6b7280",
}
CAT_LABEL = {
    "RG": "No puedo dar de alta un RG",
    "RUTA": "Ruta no válida / problema de ruta",
    "SISTEMA": "Error del sistema / plataforma",
    "RC": "Ayuda para dar de alta un RC",
    "OTRO": "Otro",
}

app = FastAPI(title="Mesa de ayuda — PAN Querétaro")
security = HTTPBasic()


def auth(cred: HTTPBasicCredentials = Depends(security)):
    ok_u = secrets.compare_digest(cred.username, PANEL_USER)
    ok_p = secrets.compare_digest(cred.password, PANEL_PASSWORD)
    if not (ok_u and ok_p):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autorizado",
            headers={"WWW-Authenticate": "Basic"},
        )
    return cred.username


def db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def h(x) -> str:
    """Escapa para HTML."""
    import html
    return html.escape(str(x)) if x is not None else ""


PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mesa de ayuda — PAN Querétaro</title>
<style>
  :root {{ --pan:#0b5cab; --bg:#f4f6f9; }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:system-ui,Segoe UI,Roboto,sans-serif; margin:0; background:var(--bg); color:#111; }}
  header {{ background:var(--pan); color:#fff; padding:14px 22px; display:flex; align-items:center; gap:12px; }}
  header h1 {{ font-size:18px; margin:0; }}
  .wrap {{ max-width:1100px; margin:22px auto; padding:0 16px; }}
  .cards {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:18px; }}
  .card {{ background:#fff; border-radius:10px; padding:12px 16px; box-shadow:0 1px 3px rgba(0,0,0,.08); min-width:120px; }}
  .card b {{ font-size:22px; display:block; }}
  form.filtros {{ background:#fff; padding:12px; border-radius:10px; margin-bottom:16px; display:flex; gap:10px; flex-wrap:wrap; align-items:end; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
  label {{ font-size:12px; color:#555; display:block; margin-bottom:3px; }}
  select,input,button {{ padding:8px 10px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; }}
  button {{ background:var(--pan); color:#fff; border:none; cursor:pointer; }}
  table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:10px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
  th,td {{ text-align:left; padding:10px 12px; border-bottom:1px solid #eef2f7; font-size:14px; }}
  th {{ background:#eef2f7; font-size:12px; text-transform:uppercase; letter-spacing:.03em; color:#555; }}
  tr:hover td {{ background:#f8fafc; }}
  a {{ color:var(--pan); text-decoration:none; }}
  .badge {{ color:#fff; padding:2px 9px; border-radius:999px; font-size:12px; font-weight:600; }}
  .box {{ background:#fff; border-radius:10px; padding:20px; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
  .row {{ display:flex; gap:8px; margin:6px 0; }} .row b {{ min-width:130px; color:#555; }}
  img.evi {{ max-width:100%; border-radius:8px; border:1px solid #e2e8f0; margin-top:8px; }}
  .hist {{ font-size:13px; color:#444; }} .hist li {{ margin:3px 0; }}
  .muted {{ color:#888; }}
</style></head><body>
<header><h1>🆘 Mesa de ayuda — Representantes PAN Querétaro</h1></header>
<div class="wrap">{body}</div></body></html>"""


def badge(estado: str) -> str:
    return f'<span class="badge" style="background:{ESTADO_COLOR.get(estado,"#555")}">{h(estado)}</span>'


@app.get("/", response_class=HTMLResponse)
def index(request: Request, estado: str = "", comite: str = "", _: str = Depends(auth)):
    where, params = [], []
    if estado:
        where.append("estado = %s"); params.append(estado)
    if comite:
        where.append("comite = %s"); params.append(comite)
    sql = "SELECT * FROM tickets"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
        conteo = conn.execute(
            "SELECT estado, count(*) n FROM tickets GROUP BY estado"
        ).fetchall()
        municipios = conn.execute(
            "SELECT DISTINCT comite FROM tickets ORDER BY comite"
        ).fetchall()

    por = {r["estado"]: r["n"] for r in conteo}
    abiertos = sum(por.get(e, 0) for e in ESTADOS_ABIERTOS)
    cards = f'<div class="card"><b>{sum(por.values())}</b>Total</div>' \
            f'<div class="card"><b style="color:#d97706">{abiertos}</b>Abiertos</div>'
    for e in ESTADOS:
        cards += f'<div class="card"><b style="color:{ESTADO_COLOR[e]}">{por.get(e,0)}</b>{e}</div>'

    opt_estado = '<option value="">Todos</option>' + "".join(
        f'<option value="{e}"{" selected" if e==estado else ""}>{e}</option>' for e in ESTADOS
    )
    opt_com = '<option value="">Todos</option>' + "".join(
        f'<option value="{h(m["comite"])}"{" selected" if m["comite"]==comite else ""}>{h(m["comite"])}</option>'
        for m in municipios
    )
    filtros = f"""<form class="filtros" method="get">
      <div><label>Estado</label><select name="estado">{opt_estado}</select></div>
      <div><label>Municipio</label><select name="comite">{opt_com}</select></div>
      <button type="submit">Filtrar</button>
      <a href="/" style="align-self:center">Limpiar</a>
      <a href="/export" style="align-self:center; margin-left:auto">⬇️ Exportar CSV</a>
    </form>"""

    filas = ""
    for r in rows:
        evi = "📎" if r.get("evidencia_file_id") else ""
        filas += f"""<tr>
          <td><a href="/ticket/{h(r['folio'])}">{h(r['folio'])}</a></td>
          <td>{h(r['comite'])}</td>
          <td>{h(CAT_LABEL.get(r['categoria'], r['categoria']))} {evi}</td>
          <td>{badge(r['estado'])}</td>
          <td class="muted">{r['creada_en']:%d/%m %H:%M}</td>
          <td>{h(r['solicitante'])}</td>
        </tr>"""
    if not rows:
        filas = '<tr><td colspan="6" class="muted">Sin tickets con estos filtros.</td></tr>'

    tabla = f"""<table><thead><tr>
      <th>Folio</th><th>Municipio</th><th>Problema</th><th>Estado</th><th>Fecha</th><th>Reporta</th>
    </tr></thead><tbody>{filas}</tbody></table>"""

    body = f'<div class="cards">{cards}</div>{filtros}{tabla}'
    return PAGE.format(body=body)


@app.get("/ticket/{folio}", response_class=HTMLResponse)
def ver(folio: str, _: str = Depends(auth)):
    with db() as conn:
        t = conn.execute("SELECT * FROM tickets WHERE folio=%s", (folio,)).fetchone()
        if not t:
            return HTMLResponse(PAGE.format(body='<div class="box">Folio no encontrado. <a href="/">Volver</a></div>'))
        hist = conn.execute(
            "SELECT * FROM historial WHERE ticket_id=%s ORDER BY fecha", (t["id"],)
        ).fetchall()

    evi = f'<div class="row"><b>Evidencia</b><div><img class="evi" src="/evidencia/{h(folio)}"></div></div>' \
        if t.get("evidencia_file_id") else '<div class="row"><b>Evidencia</b><span class="muted">— sin captura</span></div>'

    hist_html = "".join(
        f'<li>{x["fecha"]:%d/%m %H:%M} — {badge(x["estado"])}'
        + (f' · {h(x["nota"])}' if x["nota"] else "") + "</li>"
        for x in hist
    )
    opciones = "".join(
        f'<option value="{e}"{" selected" if e==t["estado"] else ""}>{e}</option>' for e in ESTADOS
    )
    body = f"""<p><a href="/">← Volver a la lista</a></p>
    <div class="box">
      <h2>Folio {h(t['folio'])} &nbsp; {badge(t['estado'])}</h2>
      <div class="row"><b>Municipio</b>{h(t['comite'])}</div>
      <div class="row"><b>Problema</b>{h(CAT_LABEL.get(t['categoria'], t['categoria']))}</div>
      <div class="row"><b>Descripción</b>{h(t['descripcion'])}</div>
      <div class="row"><b>Reporta</b>{h(t['solicitante'])}</div>
      <div class="row"><b>Reportado</b>{t['creada_en']:%d/%m/%Y %H:%M}</div>
      {f'<div class="row"><b>Nota soporte</b>{h(t["nota_admin"])}</div>' if t.get('nota_admin') else ''}
      {evi}
      <hr>
      <h3>Actualizar estado</h3>
      <form method="post" action="/ticket/{h(folio)}/estado">
        <div class="row"><b>Nuevo estado</b><select name="estado">{opciones}</select></div>
        <div class="row"><b>Nota (opcional)</b><input name="nota" style="flex:1" placeholder="Se envía al comité"></div>
        <button type="submit">Guardar y notificar</button>
      </form>
      <hr>
      <h3>Historial</h3>
      <ul class="hist">{hist_html}</ul>
    </div>"""
    return PAGE.format(body=body)


@app.post("/ticket/{folio}/estado")
async def cambiar(folio: str, estado: str = Form(...), nota: str = Form(""), _: str = Depends(auth)):
    if estado not in ESTADOS:
        raise HTTPException(400, "Estado inválido")
    nota = nota.strip() or None
    with db() as conn:
        t = conn.execute(
            """UPDATE tickets SET estado=%s, nota_admin=COALESCE(%s,nota_admin),
               actualizada_en=now() WHERE folio=%s RETURNING *""",
            (estado, nota, folio),
        ).fetchone()
        if t:
            conn.execute(
                "INSERT INTO historial (ticket_id, estado, nota, actor) VALUES (%s,%s,%s,'panel')",
                (t["id"], estado, nota),
            )
    # notificar al comité por Telegram
    if t and BOT_TOKEN:
        try:
            msg = f"Tu ticket {t['folio']} cambió a {estado}."
            if nota:
                msg += f"\nNota de soporte: {nota}"
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                             json={"chat_id": t["chat_id"], "text": msg})
        except Exception:
            pass
    return RedirectResponse(f"/ticket/{folio}", status_code=303)


@app.get("/evidencia/{folio}")
async def evidencia(folio: str, _: str = Depends(auth)):
    with db() as conn:
        t = conn.execute("SELECT evidencia_file_id FROM tickets WHERE folio=%s", (folio,)).fetchone()
    if not t or not t["evidencia_file_id"] or not BOT_TOKEN:
        raise HTTPException(404, "Sin evidencia")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
                        params={"file_id": t["evidencia_file_id"]})
        path = r.json()["result"]["file_path"]
        img = await c.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}")
    ctype = "image/jpeg"
    if path.lower().endswith(".png"):
        ctype = "image/png"
    return Response(content=img.content, media_type=ctype)


@app.get("/export")
def export(_: str = Depends(auth)):
    import csv, io
    with db() as conn:
        rows = conn.execute("SELECT * FROM tickets ORDER BY id").fetchall()
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    data = buf.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(data), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tickets.csv"},
    )


@app.get("/health")
def health():
    return {"ok": True}
