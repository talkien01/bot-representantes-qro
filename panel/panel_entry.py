"""Punto de entrada del panel extendido.

Escapa las llaves del CSS agregado por ``panel_convocados`` porque la plantilla
base usa ``str.format`` para insertar el contenido de cada página. También evita
que una reimportación con celdas vacías borre estados ya gestionados en el sistema.
"""
import panel_convocados as ext

app = ext.app

_css_lines = [
    "nav { margin-left:auto; display:flex; gap:14px; flex-wrap:wrap; }",
    "nav a { color:#fff; font-weight:600; font-size:14px; }",
    ".ok { color:#15803d; font-weight:700; }",
    ".warn { color:#b45309; font-weight:700; }",
    ".danger { color:#b91c1c; font-weight:700; }",
    ".actions { display:flex; gap:10px; flex-wrap:wrap; margin:0 0 16px; }",
    ".actions a { background:#0b5cab; color:#fff; padding:9px 13px; border-radius:8px; font-weight:600; }",
    ".progress { height:10px; background:#e5e7eb; border-radius:999px; overflow:hidden; min-width:110px; }",
    ".progress span { display:block; height:100%; background:#16a34a; }",
]
for line in _css_lines:
    ext.base.PAGE = ext.base.PAGE.replace(line, line.replace("{", "{{").replace("}", "}}"))

# Si un Excel se vuelve a importar sin estados, conservar los valores existentes.
_guardar_original = ext.guardar_registro

def guardar_registro_preservando(conn, rec):
    existente = ext.buscar_existente(conn, rec)
    if existente:
        rec = dict(rec)
        if not ext.txt(rec.get("ESTADO_CONVOCATORIA")):
            rec["ESTADO_CONVOCATORIA"] = existente.get("estado_convocatoria")
        if not ext.txt(rec.get("ESTADO_CAPACITACION")):
            rec["ESTADO_CAPACITACION"] = existente.get("estado_capacitacion")
        if not ext.txt(rec.get("CLAVE_EXTERNA")) and existente.get("clave_externa"):
            rec["CLAVE_EXTERNA"] = existente.get("clave_externa")
    return _guardar_original(conn, rec)

ext.guardar_registro = guardar_registro_preservando
