"""Punto de entrada del panel extendido.

Escapa las llaves del CSS agregado por ``panel_convocados`` porque la plantilla
base usa ``str.format`` para insertar el contenido de cada página.
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
