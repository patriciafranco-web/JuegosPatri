import csv
import io
import json
import os
import random
import re
import shutil
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
import uuid
from functools import wraps

import anthropic
import requests
from flask import (
    Flask, Response, jsonify, redirect, render_template,
    render_template_string, request, send_file, send_from_directory,
    session, url_for
)
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "juegos-patri-clave-secreta-2026")

ID_INSTANCE = os.environ.get("ID_INSTANCE", "710722800257").strip()
API_TOKEN_INSTANCE = os.environ.get("API_TOKEN_INSTANCE", "5c2bc8276faf4842a7aa71d55b5d569f8a3d841ec9f24301aa").strip()
API_URL = "https://7107.api.greenapi.com"

# Configuración segura de Anthropic Claude desde variables de entorno
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
client_anthropic = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# Credenciales de acceso para el módulo Cobrador
COBRADOR_USER = os.environ.get("COBRADOR_USER", "cobrador")
COBRADOR_PASS = os.environ.get("COBRADOR_PASS", "cobro2026")

ADMIN_USERS = {
    "patriciafranco": "Patri2026*Secure$",
    "edgarfranco": "Patri2026*Secure$",
}

CARPETA_DISCO = "/varidata"
CARPETA_LOCAL = "."

if os.path.exists(CARPETA_DISCO):
    CARPETA_DATOS = CARPETA_DISCO
else:
    CARPETA_DATOS = CARPETA_LOCAL
    try:
        os.makedirs(CARPETA_DISCO, exist_ok=True)
        if os.path.exists(CARPETA_DISCO):
            CARPETA_DATOS = CARPETA_DISCO
    except Exception:
        pass

DB_PATH = os.path.join(CARPETA_DATOS, "juegos_patri.db")
CARPETA_RESPALDOS = os.path.join(CARPETA_DATOS, "respaldos")
os.makedirs(CARPETA_RESPALDOS, exist_ok=True)
BACKUP_PATH = os.path.join(CARPETA_RESPALDOS, "juegos_patri_respaldo.db")
JP_UPLOAD_DIR = os.path.join(CARPETA_DATOS, "uploads_jp")
os.makedirs(JP_UPLOAD_DIR, exist_ok=True)

bloqueo_compra = threading.Lock()
SESIONES_WHATSAPP = {}

NOMBRES_DEFECTO_30 = [
    "JORGELINA", "ANGELICA", "DIANA", "DOROTEA", "MERCEDES", "JOANA",
    "CLOTILDE", "REGINA", "INES", "SORAIDA", "RUTY", "ADRIANA",
    "FATIMA", "ENEIDE", "HELENA", "NILZA", "GISEL", "CLAUDELINA",
    "ANDRESA", "RAMONA", "NELIDA", "ANDREA", "IVONE", "DEISI",
    "KATIA", "CARLINA", "ESTELA", "LIDIA", "DALVA", "SANDRA"
]


def formatear_telefono(telefono):
    tel_limpio = "".join(filter(str.isdigit, str(telefono)))
    if len(tel_limpio) == 10 and tel_limpio.startswith("0"):
        tel_limpio = "595" + tel_limpio[1:]
    elif len(tel_limpio) == 9 and tel_limpio.startswith("9"):
        tel_limpio = "595" + tel_limpio
    return tel_limpio


def obtener_credenciales(datos_webhook=None):
    id_inst = ID_INSTANCE
    token_inst = API_TOKEN_INSTANCE
    if datos_webhook and "instanceData" in datos_webhook:
        id_webhook = str(datos_webhook["instanceData"].get("idInstance", "")).strip()
        if id_webhook:
            id_inst = id_webhook
    return id_inst, token_inst


def enviar_mensaje_whatsapp(telefono, texto, id_inst=None, token_inst=None):
    id_usar = id_inst or ID_INSTANCE
    token_usar = token_inst or API_TOKEN_INSTANCE
    tel_formateado = formatear_telefono(telefono)
    url = f"{API_URL}/waInstance{id_usar}/sendMessage/{token_usar}"
    payload = {"chatId": f"{tel_formateado}@c.us", "message": texto}
    try:
        res = requests.post(url, json=payload, timeout=12)
        print(f"📩 [TEXTO a {tel_formateado}] Status: {res.status_code} | Resp: {res.text}")
    except Exception as e:
        print(f"❌ Error enviando mensaje Green API: {e}")


def enviar_flyer_local_whatsapp(telefono, caption, id_inst=None, token_inst=None):
    id_usar = id_inst or ID_INSTANCE
    token_usar = token_inst or API_TOKEN_INSTANCE
    tel_formateado = formatear_telefono(telefono)

    ruta_jpeg = os.path.join(app.root_path, "static", "flyer_sorteo.jpeg")
    ruta_jpg = os.path.join(app.root_path, "static", "flyer_sorteo.jpg")
    ruta_final = ruta_jpeg if os.path.exists(ruta_jpeg) else ruta_jpg

    if os.path.exists(ruta_final):
        url_up = f"{API_URL}/waInstance{id_usar}/sendFileByUpload/{token_usar}"
        payload = {"chatId": f"{tel_formateado}@c.us", "caption": caption}
        try:
            with open(ruta_final, "rb") as f:
                files = [("file", ("flyer_juegos_patri.jpg", f.read(), "image/jpeg"))]
            res = requests.post(url_up, data=payload, files=files, timeout=20)
            print(f"📸 [FLYER a {tel_formateado}] Status: {res.status_code} | Resp: {res.text}")
            if res.status_code == 200:
                return
        except Exception as e:
            print(f"❌ Error subiendo flyer local: {e}")

    enviar_mensaje_whatsapp(telefono, caption, id_inst, token_inst)


def enviar_ticket_directo(telefono, boleto_id, host_url, caption, sorteo_id=None):
    tel_formateado = formatear_telefono(telefono)
    enviar_mensaje_whatsapp(telefono, "✅ *¡Pago verificado en BNF!* Generando tu boleto oficial con QR...")

    output = crear_imagen_boleto_memoria(boleto_id, host_url, sorteo_id=sorteo_id)
    if not output:
        return

    url_up = f"{API_URL}/waInstance{ID_INSTANCE}/sendFileByUpload/{API_TOKEN_INSTANCE}"
    payload = {"chatId": f"{tel_formateado}@c.us", "caption": caption}
    files = [("file", (f"ticket_{boleto_id}.png", output.getvalue(), "image/png"))]

    try:
        res = requests.post(url_up, data=payload, files=files, timeout=20)
        print(f"🎟️ [TICKET] Status: {res.status_code} | Resp: {res.text}")
    except Exception as e:
        print(f"❌ Error subiendo ticket directamente: {e}")


def respaldar_base_datos():
    try:
        if os.path.exists(DB_PATH) and DB_PATH != BACKUP_PATH:
            shutil.copy2(DB_PATH, BACKUP_PATH)
    except Exception as e:
        print(f"⚠️ Error al respaldar DB: {e}")


def get_db():
    if not os.path.exists(DB_PATH) and os.path.exists(BACKUP_PATH):
        try:
            shutil.copy2(BACKUP_PATH, DB_PATH)
        except Exception:
            pass
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
    except Exception:
        pass
    return conn


def obtener_siguiente_lote(cursor):
    lote_row = cursor.execute("SELECT valor FROM config WHERE clave = 'lote_contador'").fetchone()
    max_lote = cursor.execute("SELECT COALESCE(MAX(lote_id), 0) FROM boletos").fetchone()[0]
    current_lote = max(int(lote_row["valor"]) if lote_row else 1, max_lote + 1)
    cursor.execute("INSERT OR REPLACE INTO config (clave, valor) VALUES ('lote_contador', ?)", (str(current_lote + 1),))
    return current_lote


def asignar_numeros_libres(cursor, sorteo_id, cantidad):
    nuevos_boletos_ids = []
    for _ in range(cantidad):
        num_boleto = None
        while num_boleto is None:
            liberado = cursor.execute(
                "SELECT numero FROM numeros_liberados WHERE sorteo_id = ? ORDER BY numero ASC LIMIT 1",
                (sorteo_id,)
            ).fetchone()
            if liberado:
                cand = liberado["numero"]
                cursor.execute(
                    "DELETE FROM numeros_liberados WHERE sorteo_id = ? AND numero = ?",
                    (sorteo_id, cand)
                )
                ocupado = cursor.execute(
                    "SELECT 1 FROM boletos WHERE id = ? AND sorteo_id = ?",
                    (cand, sorteo_id)
                ).fetchone()
                if not ocupado and cand not in nuevos_boletos_ids:
                    num_boleto = cand
            else:
                cont_row = cursor.execute(
                    "SELECT valor FROM config WHERE clave = ?",
                    (f"contador_{sorteo_id}",)
                ).fetchone()
                cand = int(cont_row["valor"]) if cont_row else 1
                while (
                    cursor.execute(
                        "SELECT 1 FROM boletos WHERE id = ? AND sorteo_id = ?",
                        (cand, sorteo_id)
                    ).fetchone()
                    or cand in nuevos_boletos_ids
                ):
                    cand += 1
                cursor.execute(
                    "INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)",
                    (f"contador_{sorteo_id}", str(cand + 1))
                )
                num_boleto = cand
        nuevos_boletos_ids.append(num_boleto)
    return nuevos_boletos_ids


def init_db():
    if not os.path.exists(DB_PATH) and os.path.exists(BACKUP_PATH):
        try:
            shutil.copy2(BACKUP_PATH, DB_PATH)
        except Exception:
            pass

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sorteos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            precio INTEGER NOT NULL,
            limite_boletos INTEGER NOT NULL,
            estado TEXT NOT NULL,
            imagen_nombre TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS boletos (
            id INTEGER,
            sorteo_id INTEGER,
            lote_id INTEGER,
            nombre TEXT,
            telefono TEXT,
            cedula TEXT,
            cantidad_lote INTEGER,
            imagen_comprobante TEXT,
            metodo_pago TEXT,
            detalle_pago TEXT,
            estado TEXT,
            impreso INTEGER,
            es_juego_loco INTEGER DEFAULT 0,
            vendedor TEXT DEFAULT 'Directo',
            PRIMARY KEY (id, sorteo_id)
        )
    """)

    columnas_boletos = [col["name"] for col in cursor.execute("PRAGMA table_info(boletos)").fetchall()]
    if "es_juego_loco" not in columnas_boletos:
        cursor.execute("ALTER TABLE boletos ADD COLUMN es_juego_loco INTEGER DEFAULT 0")
    if "vendedor" not in columnas_boletos:
        cursor.execute("ALTER TABLE boletos ADD COLUMN vendedor TEXT DEFAULT 'Directo'")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            telefono TEXT PRIMARY KEY,
            nombre TEXT,
            cedula TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            clave TEXT PRIMARY KEY,
            valor TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS numeros_liberados (
            sorteo_id INTEGER,
            numero INTEGER,
            PRIMARY KEY (sorteo_id, numero)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raspaditas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            premio TEXT NOT NULL,
            precio INTEGER NOT NULL,
            nombre_ganador TEXT NOT NULL,
            revelado INTEGER DEFAULT 0,
            estado TEXT DEFAULT 'Activa',
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raspadita_casillas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raspadita_id INTEGER NOT NULL,
            nombre_casilla TEXT NOT NULL,
            comprador_nombre TEXT DEFAULT '',
            comprador_telefono TEXT DEFAULT '',
            comprador_cedula TEXT DEFAULT '',
            estado TEXT DEFAULT 'Libre',
            raspado INTEGER DEFAULT 0,
            FOREIGN KEY (raspadita_id) REFERENCES raspaditas(id) ON DELETE CASCADE
        )
    """)

    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM sorteos")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO sorteos (id, titulo, precio, limite_boletos, estado, imagen_nombre)
            VALUES (1, 'Sorteo Juegos Patri: 1° Mesa de Billar • 2° Speaker', 2000, 6500, 'Activo', 'flyer_sorteo.jpeg')
        """)

    conn.commit()

    cursor.execute("SELECT valor FROM config WHERE clave = 'contador_1'")
    if not cursor.fetchone():
        cursor.execute("INSERT OR REPLACE INTO config (clave, valor) VALUES ('contador_1', '1')")
        conn.commit()

    cursor.execute("SELECT valor FROM config WHERE clave = 'lote_contador'")
    if not cursor.fetchone():
        cursor.execute("INSERT OR REPLACE INTO config (clave, valor) VALUES ('lote_contador', '1')")
        conn.commit()

    conn.close()
    respaldar_base_datos()


def jp_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("jp_logged_in"):
            if request.path.startswith("/api/jp/"):
                return jsonify({"error": "No autorizado"}), 401
            return redirect(url_for("jp_login", next=request.full_path))
        return f(*args, **kwargs)
    return decorated


def jp_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("jp_logged_in"):
            if request.path.startswith("/api/jp/"):
                return jsonify({"error": "No autorizado"}), 401
            return redirect(url_for("jp_login", next=request.full_path))
        if session.get("jp_role") != "admin":
            return redirect(url_for("vista_cobrador"))
        return f(*args, **kwargs)
    return decorated


def _jp_buscar_coords(texto):
    if not texto:
        return None, None
    texto = urllib.parse.unquote(texto)
    patrones = [
        r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)",
        r"@(-?\d+\.\d+),(-?\d+\.\d+)",
        r"[?&](?:q|ll|query)=(-?\d+\.\d+),\s*(-?\d+\.\d+)",
        r"/search/(-?\d+\.\d+),\s*\+?(-?\d+\.\d+)",
        r"(-?\d{1,2}\.\d{4,}),\s*(-?\d{1,3}\.\d{4,})",
    ]
    for p in patrones:
        m = re.search(p, texto)
        if m:
            lat, lng = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
    return None, None


def jp_extraer_coords_maps(url):
    url = (url or "").strip()
    if not url:
        return None, None
    lat, lng = _jp_buscar_coords(url)
    if lat is not None:
        return lat, lng
    if url.startswith("http://") or url.startswith("https://"):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                final_url = resp.geturl()
                lat, lng = _jp_buscar_coords(final_url)
                if lat is not None:
                    return lat, lng
                html = resp.read(50000).decode("utf-8", errors="ignore")
                lat, lng = _jp_buscar_coords(html)
                if lat is not None:
                    return lat, lng
        except Exception:
            pass
    return None, None


def init_jp_cobrador_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS jp_clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mesa_num TEXT NOT NULL,
            senor TEXT NOT NULL,
            ciudad TEXT DEFAULT '',
            calle TEXT DEFAULT '',
            lugar TEXT DEFAULT '',
            ci TEXT DEFAULT '',
            tarifa INTEGER DEFAULT 1000,
            maps_url TEXT DEFAULT '',
            lat REAL DEFAULT NULL,
            lng REAL DEFAULT NULL,
            notas TEXT DEFAULT '',
            activo INTEGER DEFAULT 1,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS jp_lecturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            reloj INTEGER NOT NULL,
            cant_jug INTEGER DEFAULT 0,
            total_gs INTEGER DEFAULT 0,
            entrega INTEGER DEFAULT 0,
            saldo_resultante INTEGER DEFAULT 0,
            observacion TEXT DEFAULT '',
            FOREIGN KEY (cliente_id) REFERENCES jp_clientes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS jp_gastos_gira (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            categoria TEXT NOT NULL,
            ciudad TEXT DEFAULT '',
            monto INTEGER DEFAULT 0,
            descripcion TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS jp_fotos_cliente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'Reloj',
            archivo TEXT NOT NULL,
            fecha TEXT NOT NULL,
            observacion TEXT DEFAULT '',
            FOREIGN KEY (cliente_id) REFERENCES jp_clientes(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_jp_clientes_busqueda ON jp_clientes(mesa_num, senor, ciudad, lugar);
        CREATE INDEX IF NOT EXISTS idx_jp_lecturas_cliente ON jp_lecturas(cliente_id, id);
    """)
    conn.commit()
    conn.close()
    respaldar_base_datos()


def jp_recalcular_cadena(conn, cliente_id):
    cliente = conn.execute("SELECT tarifa FROM jp_clientes WHERE id = ?", (cliente_id,)).fetchone()
    if not cliente:
        return
    tarifa = cliente["tarifa"]
    filas = conn.execute(
        "SELECT id, reloj, cant_jug, entrega FROM jp_lecturas WHERE cliente_id = ? ORDER BY id ASC",
        (cliente_id,)
    ).fetchall()
    saldo_acum = 0
    for idx, f in enumerate(filas):
        if idx == 0:
            cant = f["cant_jug"] if f["cant_jug"] > 0 else 0
        else:
            anterior = filas[idx - 1]["reloj"]
            cant = max(0, f["reloj"] - anterior)
        total = cant * tarifa
        saldo_acum = saldo_acum + total - (f["entrega"] or 0)
        conn.execute(
            "UPDATE jp_lecturas SET cant_jug = ?, total_gs = ?, saldo_resultante = ? WHERE id = ?",
            (cant, total, saldo_acum, f["id"])
        )


init_db()
init_jp_cobrador_db()

DOBLE_ACCESO_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Doble Acceso — Juegos Patri</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-900 min-h-screen flex items-center justify-center p-4">
  <div class="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 space-y-5 text-center">
    <div>
      <div class="inline-block bg-emerald-600 text-white font-black px-3 py-1.5 rounded-xl text-lg mb-2">JP</div>
      <h1 class="text-xl font-black text-slate-900">JUEGOS PATRI</h1>
      <p class="text-xs text-slate-500">Elige el módulo al que deseas ingresar</p>
    </div>

    <div class="space-y-3">
      <a href="/" class="block w-full bg-amber-500 hover:bg-amber-400 text-slate-950 font-black py-3.5 px-4 rounded-xl shadow">
        🎟️ Módulo de Sorteo
      </a>
      <a href="/raspadita" class="block w-full bg-purple-600 hover:bg-purple-500 text-white font-black py-3.5 px-4 rounded-xl shadow">
        🎲 Raspadita de Nombres (Juego Loco)
      </a>
      <a href="/cobrador/duena" class="block w-full bg-slate-900 hover:bg-slate-800 text-amber-400 font-black py-3.5 px-4 rounded-xl shadow">
        👑 Modo Dueña (Mesas y Rutas)
      </a>
      <a href="/cobrador" class="block w-full bg-emerald-600 hover:bg-emerald-500 text-white font-black py-3.5 px-4 rounded-xl shadow">
        🎱 Modo Cobrador
      </a>
      <a href="/cobrador/qr-etiquetas" class="block w-full bg-sky-600 hover:bg-sky-500 text-white font-extrabold py-2.5 px-4 rounded-xl text-xs">
        🖨️ Imprimir Etiquetas QR por Mesa
      </a>
    </div>
  </div>
</body>
</html>
"""

JP_LOGIN_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Acceso — Juegos Patri</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-900 min-h-screen flex items-center justify-center p-4">
  <div class="bg-white rounded-2xl shadow-2xl max-w-sm w-full p-6 space-y-5">
    <div class="text-center">
      <div class="inline-block bg-emerald-600 text-white font-black px-3 py-1.5 rounded-xl text-lg mb-2">JP</div>
      <h1 class="text-xl font-black text-slate-900">ACCESO MESAS — JUEGOS PATRI</h1>
      <p class="text-xs text-slate-500">Ingreso para Dueña / Admin y Cobrador</p>
    </div>
    {% if error %}
      <div class="bg-rose-50 border border-rose-200 text-rose-700 text-xs font-bold p-2.5 rounded-lg text-center">{{ error }}</div>
    {% endif %}
    <form method="POST" class="space-y-3 text-sm">
      <div>
        <label class="block text-xs font-bold text-slate-700 mb-1">Usuario</label>
        <input name="username" required autofocus class="w-full px-3 py-2.5 border border-slate-300 rounded-lg" placeholder="patriciafranco o cobrador" />
      </div>
      <div>
        <label class="block text-xs font-bold text-slate-700 mb-1">Contraseña</label>
        <input name="password" type="password" required class="w-full px-3 py-2.5 border border-slate-300 rounded-lg" placeholder="••••••••" />
      </div>
      <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-extrabold py-3 rounded-lg shadow">
        Ingresar
      </button>
    </form>
  </div>
</body>
</html>
"""

JP_QR_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Etiquetas QR por Mesa — Juegos Patri</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
  <style>
    @media print {
      .no-print { display: none !important; }
      body { background: #ffffff !important; padding: 0 !important; }
      .etiqueta-card { break-inside: avoid; page-break-inside: avoid; box-shadow: none !important; border: 1.5px solid #0f172a !important; }
    }
  </style>
</head>
<body class="bg-slate-100 text-slate-900 min-h-screen p-4">
  <div class="max-w-5xl mx-auto space-y-4">
    <div class="no-print bg-white p-4 rounded-2xl border border-slate-200 shadow-sm flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-lg font-black text-slate-900">Etiquetas QR por Mesa — Juegos Patri</h1>
        <p class="text-xs text-slate-500">Cada QR abre directo la carga de esa mesa en <code>/cobrador?mesa=...</code></p>
      </div>
      <div class="flex items-center gap-2">
        <a href="/cobrador/duena" class="bg-slate-900 hover:bg-slate-800 text-amber-400 text-xs font-extrabold px-3.5 py-2.5 rounded-xl">
          👑 Modo Dueña
        </a>
        <a href="/cobrador" class="bg-slate-200 hover:bg-slate-300 text-slate-900 text-xs font-extrabold px-3.5 py-2.5 rounded-xl">
          ← Cobrador
        </a>
        <button type="button" onclick="window.print()" class="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-black px-4 py-2.5 rounded-xl shadow">
          🖨️ Imprimir todas las etiquetas
        </button>
      </div>
    </div>

    <div id="grid-qr" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3"></div>
  </div>

  <script>
    const mesas = {{ mesas | tojson }};
    const baseUrl = window.location.origin;
    const grid = document.getElementById('grid-qr');

    if (!mesas.length) {
      grid.innerHTML = '<div class="col-span-full bg-white p-6 rounded-2xl text-center text-sm text-slate-500 border">No hay mesas activas para generar etiquetas.</div>';
    } else {
      mesas.forEach((m, idx) => {
        const mesaNum = String(m.mesa_num || '').trim();
        const urlDestino = `${baseUrl}/cobrador?mesa=${encodeURIComponent(mesaNum)}`;
        const qrId = `qr-box-${idx}`;

        const card = document.createElement('div');
        card.className = 'etiqueta-card bg-white p-3.5 rounded-2xl border border-slate-300 shadow-sm flex flex-col items-center text-center space-y-2';
        card.innerHTML = `
          <div class="w-full flex items-center justify-between text-[10px] font-black uppercase text-slate-500 border-b pb-1.5">
            <span>JUEGOS PATRI</span>
            <span class="bg-slate-900 text-white px-2 py-0.5 rounded text-xs">MESA ${mesaNum}</span>
          </div>
          <div id="${qrId}" class="py-1 flex items-center justify-center"></div>
          <div class="w-full">
            <p class="font-extrabold text-xs text-slate-900 truncate">${m.senor || ''}</p>
            <p class="text-[11px] text-slate-500 truncate">${m.ciudad || ''}${m.lugar ? ' • ' + m.lugar : ''}</p>
          </div>
        `;
        grid.appendChild(card);

        new QRCode(document.getElementById(qrId), {
          text: urlDestino,
          width: 132,
          height: 132,
          correctLevel: QRCode.CorrectLevel.M
        });
      });
    }
  </script>
</body>
</html>
"""


def verificar_admin(data):
    data = data or {}
    return data.get("usuario") in ADMIN_USERS and ADMIN_USERS[data.get("usuario")] == data.get("password")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/admin")
def admin_panel():
    return render_template("admin.html")


@app.route("/raspadita")
def vista_raspadita():
    return render_template("raspadita.html")


@app.route("/ruleta")
def vista_ruleta():
    solo_juego_loco = request.args.get("juego_loco") == "1"
    sorteo_id = request.args.get("sorteo_id", type=int)

    conn = get_db()
    sql = "SELECT id, nombre FROM boletos WHERE estado = 'Aprobado'"
    params = []
    if solo_juego_loco:
        sql += " AND es_juego_loco = 1"
    if sorteo_id:
        sql += " AND sorteo_id = ?"
        params.append(sorteo_id)
    sql += " ORDER BY id ASC"

    boletos_aprobados = conn.execute(sql, params).fetchall()
    conn.close()
    participantes = [{"id": b["id"], "nombre": b["nombre"]} for b in boletos_aprobados]
    return render_template("ruleta.html", participantes=json.dumps(participantes))


@app.route("/api/top-compradores", methods=["GET"])
def obtener_top_compradores():
    conn = get_db()
    query = """
        SELECT nombre, cedula, telefono, COUNT(id) as total_boletos
        FROM boletos
        WHERE estado = 'Aprobado'
        GROUP BY telefono
        ORDER BY total_boletos DESC
        LIMIT 5
    """
    top = conn.execute(query).fetchall()
    conn.close()
    return jsonify([dict(t) for t in top]), 200


@app.route("/api/admin/difusion-masiva", methods=["POST"])
def admin_difusion_masiva():
    data = request.json or {}
    if not verificar_admin(data):
        return jsonify({"error": "No autorizado"}), 401

    mensaje_difusion = data.get("mensaje", "").strip()
    if not mensaje_difusion:
        return jsonify({"error": "El mensaje no puede estar vacío"}), 400

    conn = get_db()
    clientes = conn.execute("SELECT telefono FROM clientes").fetchall()
    conn.close()

    enviados = 0
    for c in clientes:
        tel = c["telefono"]
        try:
            enviar_mensaje_whatsapp(tel, f"📢 *AVISO OFICIAL - JUEGOS PATRI*\n\n{mensaje_difusion}")
            enviados += 1
            time.sleep(0.4)
        except Exception as e:
            print(f"Error enviando a {tel}: {e}")

    return jsonify({"mensaje": f"¡Difusión enviada con éxito a {enviados} clientes!"}), 200


@app.route("/api/sorteos", methods=["GET"])
def obtener_sorteos():
    conn = get_db()
    sorteos = conn.execute("SELECT * FROM sorteos WHERE estado = 'Activo'").fetchall()

    resultado = []
    for s in sorteos:
        s_dict = dict(s)
        vendidos = conn.execute("SELECT COUNT(*) FROM boletos WHERE sorteo_id = ? AND estado = 'Aprobado'", (s["id"],)).fetchone()[0]
        s_dict["boletos_vendidos"] = vendidos
        resultado.append(s_dict)

    conn.close()
    return jsonify({"sorteos": resultado})


@app.route("/api/comprar", methods=["POST"])
def comprar():
    try:
        data = request.json or {}
        sorteo_id = int(data.get("sorteo_id", 1))
        nombre = str(data.get("nombre", "")).strip()
        telefono = str(data.get("telefono", "")).strip()
        cedula = str(data.get("cedula", "")).strip()
        cantidad = int(data.get("cantidad", 1))
        metodo_pago = data.get("metodo_pago", "Transferencia BNF")
        detalle_pago = data.get("detalle_pago", "BNF Patricia Franco")
        es_juego_loco = 1 if data.get("es_juego_loco") in (1, True, "1", "true") else 0
        vendedor = str(data.get("vendedor", "Directo")).strip() or "Directo"

        if not nombre or not telefono or not cedula or cantidad < 1:
            return jsonify({"error": "Todos los campos son obligatorios."}), 400

        with bloqueo_compra:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO clientes (telefono, nombre, cedula) VALUES (?, ?, ?)",
                (telefono, nombre, cedula)
            )
            sorteo = cursor.execute(
                "SELECT * FROM sorteos WHERE id = ? AND estado = 'Activo'",
                (sorteo_id,)
            ).fetchone()
            if not sorteo:
                conn.close()
                return jsonify({"error": "El sorteo seleccionado ya no está activo."}), 400

            total_activos = cursor.execute(
                "SELECT COUNT(*) FROM boletos WHERE sorteo_id = ?",
                (sorteo_id,)
            ).fetchone()[0]
            if (total_activos + cantidad) > sorteo["limite_boletos"]:
                conn.close()
                return jsonify({"error": "No hay suficientes boletos disponibles."}), 400

            current_lote = obtener_siguiente_lote(cursor)
            nuevos_boletos_ids = asignar_numeros_libres(cursor, sorteo_id, cantidad)

            for num_boleto in nuevos_boletos_ids:
                cursor.execute("""
                    INSERT INTO boletos (id, sorteo_id, lote_id, nombre, telefono, cedula, cantidad_lote, imagen_comprobante, metodo_pago, detalle_pago, estado, impreso, es_juego_loco, vendedor)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pendiente', 0, ?, ?)
                """, (num_boleto, sorteo_id, current_lote, nombre, telefono, cedula, cantidad, "", metodo_pago, detalle_pago, es_juego_loco, vendedor))

            conn.commit()
            conn.close()
            respaldar_base_datos()

        rango_str = (
            f"#{str(nuevos_boletos_ids[0]).zfill(5)}"
            if len(nuevos_boletos_ids) == 1
            else f"#{str(nuevos_boletos_ids[0]).zfill(5)} al #{str(nuevos_boletos_ids[-1]).zfill(5)}"
        )

        return jsonify({
            "mensaje": "¡Reserva registrada con éxito en Juegos Patri!",
            "rango": rango_str,
            "lote_id": current_lote
        }), 200
    except Exception as e:
        print(f"❌ ERROR REAL EN /api/comprar: {e}")
        return jsonify({"error": f"Error interno al reservar: {str(e)}"}), 500


@app.route("/api/subir-comprobante", methods=["POST"])
def subir_comprobante():
    data = request.json or {}
    lote_id = data.get("lote_id")
    imagen_comprobante = data.get("imagen_comprobante", "")

    if not lote_id or not imagen_comprobante:
        return jsonify({"error": "Faltan datos."}), 400

    with bloqueo_compra:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE boletos SET imagen_comprobante = ? WHERE lote_id = ?", (imagen_comprobante, lote_id))
        conn.commit()
        conn.close()
        respaldar_base_datos()

    return jsonify({"mensaje": "¡Comprobante adjuntado correctamente!"}), 200


@app.route("/api/webhook/whatsapp", methods=["POST"])
def webhook_whatsapp():
    datos = request.json
    if not datos:
        return jsonify({"status": "ignored"}), 200

    tipo_webhook = datos.get("typeWebhook", "")
    if tipo_webhook and tipo_webhook != "incomingMessageReceived":
        return jsonify({"status": "ignored_type"}), 200

    try:
        id_inst, token_inst = obtener_credenciales(datos)
        senderData = datos.get("senderData", {})
        messageData = datos.get("messageData", {})
        chat_id = senderData.get("chatId", "")
        if not chat_id and "chatData" in datos:
            chat_id = datos.get("chatData", {}).get("chatId", "")

        telefono = chat_id.split("@")[0] if "@" in chat_id else str(chat_id)
        tipo_mensaje = messageData.get("typeMessage", "")
        es_imagen = (
            "fileMessageData" in messageData or "imageMessageData" in messageData
            or "jpeg" in tipo_mensaje.lower() or "image" in tipo_mensaje.lower()
        )

        mensaje = ""
        if "textMessageData" in messageData:
            mensaje = messageData["textMessageData"].get("textMessage", "")
        elif "extendedTextMessageData" in messageData:
            mensaje = messageData["extendedTextMessageData"].get("text", "")

        if telefono and not mensaje and not es_imagen:
            mensaje = "hola"
        if not telefono:
            return jsonify({"status": "ok"}), 200

        mensaje_lower = mensaje.lower().strip()

        if telefono not in SESIONES_WHATSAPP:
            SESIONES_WHATSAPP[telefono] = {"paso": "INICIO", "datos": {}}

        sesion = SESIONES_WHATSAPP[telefono]
        paso = sesion["paso"]

        conn = get_db()
        sorteo = conn.execute("SELECT * FROM sorteos WHERE estado = 'Activo' ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()

        if "hola" in mensaje_lower or paso == "INICIO":
            sesion["paso"] = "ESPERANDO_COMBO"
            precio_unitario = sorteo["precio"] if sorteo else 2000

            caption = (
                f"¡Hola! Bienvenido a *JUEGOS PATRI* 🍀🎱\n"
                f"🏆 *1° Premio:* Mesa de Billar\n"
                f"🔊 *2° Premio:* Speaker\n"
                f"⚡ *¡Además, tenemos Juegos Locos activos!* 🎲\n"
                f"*(Valor unitario: {precio_unitario:,} Gs. c/u)*\n\n"
                f"🔥 *¡APROVECHA NUESTROS COMBOS O ELIGE TU CANTIDAD:* \n\n"
                f"1️⃣ *Combo 1:* 10.000 Gs. = 6 boletas *(¡1 de regalo!)*\n"
                f"2️⃣ *Combo 2:* 20.000 Gs. = 13 boletas *(¡El más pedido! ⭐)*\n"
                f"3️⃣ *Combo 3:* 45.000 Gs. = 30 boletas *(¡Super combo! 🚀)*\n\n"
                f"👉 *(Responde con 1, 2, 3 o escribe directamente la cantidad exacta de boletas que deseas comprar)*"
            )
            enviar_flyer_local_whatsapp(telefono, caption, id_inst, token_inst)

        elif paso == "ESPERANDO_COMBO" and mensaje.isdigit():
            opcion = int(mensaje)
            precio_unitario = sorteo["precio"] if sorteo else 2000

            if opcion == 1:
                cantidad = 6
                total = 10000
                nombre_combo = "Combo 1 (6 boletas)"
            elif opcion == 2:
                cantidad = 13
                total = 20000
                nombre_combo = "Combo 2 (13 boletas)"
            elif opcion == 3:
                cantidad = 30
                total = 45000
                nombre_combo = "Combo 3 (30 boletas)"
            elif opcion > 0:
                cantidad = opcion
                total = cantidad * precio_unitario
                nombre_combo = f"Personalizado ({cantidad} boletas)"
            else:
                enviar_mensaje_whatsapp(telefono, "❌ Cantidad inválida. Por favor, escribe un número mayor a 0.", id_inst, token_inst)
                return jsonify({"status": "ok"}), 200

            sesion["datos"]["cantidad"] = cantidad
            sesion["datos"]["nombre_combo"] = nombre_combo

            sesion["paso"] = "ESPERANDO_DATOS_CLIENTE"
            enviar_mensaje_whatsapp(
                telefono,
                f"🎟️ Has elegido: *{nombre_combo}*\nTotal a transferir: *{total:,} Gs.*\n\n"
                "🏦 *Datos para el pago (BNF):*\n🔸 *Titular:* Patricia Franco\n🔸 *Cuenta / Alias:* 0981047851\n🔸 *Banco:* BNF\n\n"
                "📝 Por favor, escribe tu *Nombre completo* y tu *Cédula* separados por un espacio (Ej: Juan Pérez 1234567).",
                id_inst, token_inst
            )

        elif paso == "ESPERANDO_DATOS_CLIENTE" and ("," in mensaje or " " in mensaje):
            if "," in mensaje:
                partes = mensaje.split(",")
            else:
                partes = mensaje.rsplit(" ", 1)

            nombre_cliente = partes[0].strip()
            cedula_cliente = partes[1].strip()

            sesion["datos"]["nombre"] = nombre_cliente
            sesion["datos"]["cedula"] = cedula_cliente

            with bloqueo_compra:
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO clientes (telefono, nombre, cedula) VALUES (?, ?, ?)", (telefono, nombre_cliente, cedula_cliente))

                sorteo_id = sorteo["id"] if sorteo else 1
                cantidad = sesion["datos"]["cantidad"]

                current_lote = obtener_siguiente_lote(cursor)
                nuevos_boletos_ids = asignar_numeros_libres(cursor, sorteo_id, cantidad)

                numeros_str = []
                for num_boleto in nuevos_boletos_ids:
                    cursor.execute("""
                        INSERT INTO boletos (id, sorteo_id, lote_id, nombre, telefono, cedula, cantidad_lote, imagen_comprobante, metodo_pago, detalle_pago, estado, impreso, es_juego_loco, vendedor)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pendiente', 0, 0, 'WhatsApp Bot')
                    """, (num_boleto, sorteo_id, current_lote, nombre_cliente, telefono, cedula_cliente, cantidad, "", "WhatsApp / BNF", "Transferencia BNF"))
                    numeros_str.append(str(num_boleto).zfill(5))

                conn.commit()
                conn.close()
                respaldar_base_datos()

            sesion["datos"]["lote_id"] = current_lote
            sesion["datos"]["numeros"] = numeros_str

            sesion["paso"] = "ESPERANDO_COMPROBANTE"
            enviar_mensaje_whatsapp(
                telefono,
                f"✅ Datos guardados:\n👤 *Nombre:* {nombre_cliente}\n🆔 *CI:* {cedula_cliente}\n🎟️ *Tus números:* {', '.join(numeros_str)}\n\n"
                "📸 Ahora, por favor **enviá la foto del comprobante de pago (BNF)** para finalizar y asegurar tu participación en los Juegos Locos.",
                id_inst, token_inst
            )

        elif paso == "ESPERANDO_COMPROBANTE" and es_imagen:
            file_data = messageData.get("fileMessageData", {})
            download_url = file_data.get("downloadUrl", "")
            current_lote = sesion["datos"].get("lote_id")

            if current_lote:
                with bloqueo_compra:
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute("UPDATE boletos SET imagen_comprobante = ? WHERE lote_id = ?", (download_url, current_lote))
                    conn.commit()
                    conn.close()
                    respaldar_base_datos()

            enviar_mensaje_whatsapp(
                telefono,
                "🔍 *¡Comprobante recibido con éxito!*\n\nUn administrador verificará tu pago en BNF y te enviará tu boleto oficial con QR. ¡Muchas gracias!",
                id_inst, token_inst
            )
            sesion["paso"] = "INICIO"

        else:
            if client_anthropic:
                prompt_asistente = f"""
                Eres el asistente virtual experto de 'Juegos Patri'. El usuario ha escrito un mensaje libre: "{mensaje}".

                Analiza si el mensaje contiene una intención de compra o reserva de boletos (buscando la cantidad de boletos, el nombre de la persona y su número de cédula).

                Responde ÚNICAMENTE en formato JSON estricto (sin texto adicional fuera del JSON) con las siguientes llaves:
- "es_compra": true si menciona cantidad y datos para comprar, false si es una duda general.
- "cantidad": número entero de boletos que desea (si pide un combo, calcula el total de boletos).
- "nombre": nombre completo extraído del mensaje (o null si no está).
- "cedula": número de cédula extraído del mensaje (o null si no está).
- "respuesta_texto": un mensaje amable para WhatsApp guiando al usuario o confirmando su pedido.
                """
                try:
                    message = client_anthropic.messages.create(
                        model="claude-sonnet-4-5",
                        max_tokens=300,
                        messages=[{"role": "user", "content": prompt_asistente}]
                    )

                    texto_res = ""
                    for content_block in message.content:
                        if hasattr(content_block, "text"):
                            texto_res += content_block.text

                    datos_ia = json.loads(texto_res.strip().replace("```json", "").replace("```", ""))

                    if datos_ia.get("es_compra") and datos_ia.get("cantidad") and datos_ia.get("nombre") and datos_ia.get("cedula"):
                        cantidad = int(datos_ia.get("cantidad"))
                        nombre_cliente = str(datos_ia.get("nombre")).strip()
                        cedula_cliente = str(datos_ia.get("cedula")).strip()

                        with bloqueo_compra:
                            conn = get_db()
                            cursor = conn.cursor()
                            cursor.execute("INSERT OR REPLACE INTO clientes (telefono, nombre, cedula) VALUES (?, ?, ?)", (telefono, nombre_cliente, cedula_cliente))

                            sorteo_id = sorteo["id"] if sorteo else 1
                            precio_unitario = sorteo["precio"] if sorteo else 2000
                            total_a_pagar = cantidad * precio_unitario

                            current_lote = obtener_siguiente_lote(cursor)
                            nuevos_boletos_ids = asignar_numeros_libres(cursor, sorteo_id, cantidad)

                            numeros_str = []
                            for num_boleto in nuevos_boletos_ids:
                                cursor.execute("""
                                    INSERT INTO boletos (id, sorteo_id, lote_id, nombre, telefono, cedula, cantidad_lote, imagen_comprobante, metodo_pago, detalle_pago, estado, impreso, es_juego_loco, vendedor)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pendiente', 0, 0, 'WhatsApp IA')
                                """, (num_boleto, sorteo_id, current_lote, nombre_cliente, telefono, cedula_cliente, cantidad, "", "WhatsApp / BNF", "Transferencia BNF"))
                                numeros_str.append(str(num_boleto).zfill(5))

                            conn.commit()
                            conn.close()
                            respaldar_base_datos()

                        sesion["datos"]["lote_id"] = current_lote
                        sesion["paso"] = "ESPERANDO_COMPROBANTE"

                        enviar_mensaje_whatsapp(
                            telefono,
                            f"🤖 *¡Pedido procesado por IA con éxito!*\n\n"
                            f"👤 *Nombre:* {nombre_cliente}\n"
                            f"🆔 *CI:* {cedula_cliente}\n"
                            f"🎟️ *Tus números:* {', '.join(numeros_str)}\n"
                            f"💰 *Total a transferir:* {total_a_pagar:,} Gs.\n\n"
                            "🏦 *Datos para el pago (BNF):*\n🔸 *Titular:* Patricia Franco\n🔸 *Cuenta / Alias:* 0981047851\n\n"
                            "📸 Ahora, por favor **enviá la foto del comprobante de pago** para finalizar.",
                            id_inst, token_inst
                        )
                    else:
                        enviar_mensaje_whatsapp(telefono, datos_ia.get("respuesta_texto", "¡Hola! Escribe 'Hola' para ver los combos disponibles."), id_inst, token_inst)

                except Exception as e:
                    print(f"❌ Error Claude procesamiento IA: {e}")
                    enviar_mensaje_whatsapp(telefono, "Por favor, selecciona una opción válida del menú (1, 2 o 3) o escribe 'Hola' para ver los combos.", id_inst, token_inst)
            else:
                enviar_mensaje_whatsapp(telefono, "Por favor, responde con el número de la opción deseada o escribe 'Hola' para ver el menú principal.", id_inst, token_inst)

    except Exception as e:
        print(f"❌ Error procesando webhook: {e}")

    return jsonify({"status": "ok"}), 200


def crear_imagen_boleto_memoria(boleto_id, host_url, sorteo_id=None):
    conn = get_db()
    if sorteo_id:
        boleto = conn.execute("SELECT * FROM boletos WHERE id = ? AND sorteo_id = ?", (boleto_id, sorteo_id)).fetchone()
    else:
        boleto = conn.execute("SELECT * FROM boletos WHERE id = ? ORDER BY sorteo_id DESC LIMIT 1", (boleto_id,)).fetchone()

    if not boleto:
        conn.close()
        return None
    sorteo = conn.execute("SELECT titulo FROM sorteos WHERE id = ?", (boleto["sorteo_id"],)).fetchone()
    conn.close()

    sorteo_titulo = sorteo["titulo"] if sorteo else "Juegos Patri"

    ancho, alto = 420, 580
    img = Image.new("RGB", (ancho, alto), color="white")
    d = ImageDraw.Draw(img)

    try:
        font_titulo = ImageFont.truetype("arial.ttf", 20)
        font_texto = ImageFont.truetype("arial.ttf", 14)
        font_grande = ImageFont.truetype("arial.ttf", 26)
    except Exception:
        font_titulo = ImageFont.load_default()
        font_texto = ImageFont.load_default()
        font_grande = ImageFont.load_default()

    d.text((ancho / 2, 25), "JUEGOS PATRI", fill="black", anchor="mm", font=font_titulo)
    d.line([(20, 45), (ancho - 20, 45)], fill="black", width=2)
    d.text((20, 65), f"CLIENTE: {boleto['nombre'].upper()}", fill="black", font=font_texto)
    d.text((20, 90), f"CI: {boleto['cedula']} | TEL: {boleto['telefono']}", fill="black", font=font_texto)
    d.line([(20, 115), (ancho - 20, 115)], fill="black", width=1)
    d.text((20, 130), f"EDICION: {sorteo_titulo[:35]}", fill="black", font=font_texto)
    d.text((20, 155), f"PAGO: {boleto['metodo_pago']}", fill="black", font=font_texto)
    d.line([(20, 180), (ancho - 20, 180)], fill="black", width=1)
    d.text((ancho / 2, 210), f"NRO: #{str(boleto['id']).zfill(5)}", fill="black", anchor="mm", font=font_grande)
    d.line([(20, 240), (ancho - 20, 240)], fill="black", width=1)

    url_segura = host_url.rstrip("/").replace("http://", "https://")
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=180x180&data={url_segura}/validar/{boleto['id']}?sorteo_id={boleto['sorteo_id']}"

    try:
        res_qr = requests.get(qr_url)
        if res_qr.status_code == 200:
            qr_img = Image.open(io.BytesIO(res_qr.content)).resize((150, 150))
            img.paste(qr_img, (int((ancho - 150) / 2), 255))
    except Exception:
        pass

    output = io.BytesIO()
    img.save(output, format="PNG")
    output.seek(0)
    return output


@app.route("/api/ticket-imagen/<int:boleto_id>")
def obtener_ticket_imagen(boleto_id):
    sorteo_id = request.args.get("sorteo_id", type=int)
    output = crear_imagen_boleto_memoria(boleto_id, request.host_url, sorteo_id=sorteo_id)
    if not output:
        return "Boleto no encontrado", 404
    return send_file(output, mimetype="image/png")


@app.route("/validar/<int:boleto_id>")
def validar_boleto_qr(boleto_id):
    sorteo_id = request.args.get("sorteo_id", type=int)
    conn = get_db()
    if sorteo_id:
        boleto = conn.execute("SELECT * FROM boletos WHERE id = ? AND sorteo_id = ?", (boleto_id, sorteo_id)).fetchone()
    else:
        boleto = conn.execute("SELECT * FROM boletos WHERE id = ? ORDER BY sorteo_id DESC LIMIT 1", (boleto_id,)).fetchone()

    if not boleto:
        conn.close()
        return "<h3>Boleto no encontrado</h3>", 404
    sorteo = conn.execute("SELECT * FROM sorteos WHERE id = ?", (boleto["sorteo_id"],)).fetchone()
    conn.close()

    estado_color = "text-emerald-400 bg-emerald-500/10 border-emerald-500/30" if boleto["estado"] == "Aprobado" else "text-amber-400 bg-amber-500/10 border-amber-500/30"

    return f"""
        <!DOCTYPE html>
        <html lang="es">
        <head><meta charset="UTF-8"><title>Validación de Boleto - Juegos Patri</title><script src="https://cdn.tailwindcss.com"></script></head>
        <body class="bg-slate-900 text-white flex items-center justify-center min-h-screen p-4 font-sans">
            <div class="bg-slate-800 p-8 rounded-2xl shadow-2xl border border-slate-700 max-w-md w-full space-y-6 text-center">
                <h1 class="text-xl font-black text-amber-400">JUEGOS PATRI</h1>
                <span class="text-3xl font-black text-amber-400 block">#{str(boleto['id']).zfill(5)}</span>
                <p class="text-sm font-bold">{sorteo['titulo'] if sorteo else 'Sorteo'}</p>
                <p class="text-xs text-slate-300">Cliente: {boleto['nombre']} (CI: {boleto['cedula']})</p>
                <span class="inline-block px-4 py-1.5 rounded-xl text-xs font-bold border {estado_color}">Estado: {boleto['estado']}</span>
            </div>
        </body>
        </html>
    """


@app.route("/api/admin/datos", methods=["POST"])
def admin_datos():
    if not verificar_admin(request.json):
        return jsonify({"error": "No autorizado"}), 401

    with bloqueo_compra:
        conn_fix = get_db()
        sorteos = conn_fix.execute("SELECT * FROM sorteos").fetchall()
        boletos = conn_fix.execute("SELECT * FROM boletos ORDER BY sorteo_id ASC, id ASC").fetchall()
        total_clientes = conn_fix.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]

        top = conn_fix.execute("""
            SELECT nombre, telefono, cedula, COUNT(id) as total_boletos, SUM(cantidad_lote) as total_invertido
            FROM boletos
            WHERE estado = 'Aprobado'
            GROUP BY telefono
            ORDER BY total_boletos DESC
            LIMIT 5
        """).fetchall()

        vendedores = conn_fix.execute("""
            SELECT vendedor, COUNT(id) as total_boletos, SUM(CASE WHEN estado='Aprobado' THEN 1 ELSE 0 END) as aprobados
            FROM boletos
            GROUP BY vendedor
        """).fetchall()

        rasp = conn_fix.execute("SELECT * FROM raspaditas WHERE estado = 'Activa' ORDER BY id DESC LIMIT 1").fetchone()
        rasp_data = None
        if rasp:
            casillas = conn_fix.execute(
                "SELECT * FROM raspadita_casillas WHERE raspadita_id = ? ORDER BY id ASC",
                (rasp["id"],)
            ).fetchall()
            rasp_data = {
                "id": rasp["id"],
                "titulo": rasp["titulo"],
                "premio": rasp["premio"],
                "precio": rasp["precio"],
                "revelado": bool(rasp["revelado"]),
                "nombre_ganador": rasp["nombre_ganador"],
                "casillas": [dict(c) for c in casillas]
            }

        conn_fix.close()

    return jsonify({
        "sorteos": [dict(s) for s in sorteos],
        "boletos": [dict(b) for b in boletos],
        "total_clientes": total_clientes,
        "top_compradores": [dict(t) for t in top],
        "reporte_vendedores": [dict(v) for v in vendedores],
        "raspadita": rasp_data
    })


@app.route("/api/admin/crear-sorteo", methods=["POST"])
def admin_crear_sorteo():
    data = request.json or {}
    if not verificar_admin(data):
        return jsonify({"error": "No autorizado"}), 401
    with bloqueo_compra:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO sorteos (titulo, precio, limite_boletos, estado, imagen_nombre)
            VALUES (?, ?, ?, 'Activo', 'flyer_sorteo.jpeg')
        """, (data.get("titulo"), int(data.get("precio", 2000)), int(data.get("limite_boletos", 6500))))
        nuevo_id = cursor.lastrowid
        cursor.execute("INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)", (f"contador_{nuevo_id}", "1"))
        conn.commit()
        nuevo_sorteo = dict(cursor.execute("SELECT * FROM sorteos WHERE id = ?", (nuevo_id,)).fetchone())
        conn.close()
        respaldar_base_datos()
    return jsonify({"mensaje": "¡Sorteo creado con éxito en Juegos Patri!", "sorteo": nuevo_sorteo})


@app.route("/api/admin/finalizar-sorteo/<int:sorteo_id>", methods=["POST"])
def admin_finalizar_sorteo(sorteo_id):
    data = request.json or {}
    if not verificar_admin(data):
        return jsonify({"error": "No autorizado"}), 401
    with bloqueo_compra:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE sorteos SET estado = 'Finalizado' WHERE id = ?", (sorteo_id,))
        conn.commit()
        conn.close()
        respaldar_base_datos()
    return jsonify({"mensaje": "¡Sorteo finalizado con éxito!"}), 200


@app.route("/api/admin/aprobar-lote/<int:lote_id>", methods=["POST"])
def admin_aprobar_lote(lote_id):
    if not verificar_admin(request.json):
        return jsonify({"error": "No autorizado"}), 401
    host_actual = request.host_url
    with bloqueo_compra:
        conn = get_db()
        cursor = conn.cursor()
        boletos_lote = cursor.execute("SELECT * FROM boletos WHERE lote_id = ? AND estado = 'Pendiente'", (lote_id,)).fetchall()

        if not boletos_lote:
            conn.close()
            return jsonify({"error": "Lote no encontrado o ya aprobado"}), 404

        cursor.execute("UPDATE boletos SET estado = 'Aprobado', impreso = 0 WHERE lote_id = ?", (lote_id,))
        conn.commit()
        conn.close()
        respaldar_base_datos()

        for b in boletos_lote:
            conn2 = get_db()
            sorteo = conn2.execute("SELECT * FROM sorteos WHERE id = ?", (b["sorteo_id"],)).fetchone()
            conn2.close()
            precio = sorteo["precio"] if sorteo else 2000
            titulo = sorteo["titulo"] if sorteo else "Juegos Patri"
            caption = f"✨ *¡Pago Verificado en BNF y Boleto Emitido!*\n\nCLIENTE: {b['nombre']}\nCI: {b['cedula']}\nEDICION: {titulo}\nVALOR: Gs. {precio:,}\nNRO: #{str(b['id']).zfill(5)}\n\n🍀 *¡Participas automáticamente en los Juegos Locos de Juegos Patri!*"
            enviar_ticket_directo(b["telefono"], b["id"], host_actual, caption, sorteo_id=b["sorteo_id"])

    return jsonify({"mensaje": f"¡Lote aprobado con éxito ({len(boletos_lote)} boletos)!"}), 200


@app.route("/api/admin/cargar-manual-silencioso", methods=["POST"])
def admin_cargar_manual_silencioso():
    data = request.json or {}
    if not verificar_admin(data):
        return jsonify({"error": "No autorizado"}), 401

    sorteo_id = int(data.get("sorteo_id", 1))
    nombre = data.get("nombre")
    telefono = data.get("telefono", "0000000000")
    cedula = data.get("cedula", "0000000")
    cantidad = int(data.get("cantidad", 1))
    inicio_personalizado = data.get("inicio_personalizado")

    if not nombre or cantidad < 1:
        return jsonify({"error": "El nombre y la cantidad son obligatorios."}), 400

    with bloqueo_compra:
        conn = get_db()
        cursor = conn.cursor()

        current_lote = obtener_siguiente_lote(cursor)

        nuevos_boletos_ids = []
        if inicio_personalizado is not None and str(inicio_personalizado).strip() != "":
            num_actual = int(inicio_personalizado)
            for _ in range(cantidad):
                nuevos_boletos_ids.append(num_actual)
                num_actual += 1
        else:
            nuevos_boletos_ids = asignar_numeros_libres(cursor, sorteo_id, cantidad)

        max_num = max(nuevos_boletos_ids)
        cont_row = cursor.execute("SELECT valor FROM config WHERE clave = ?", (f"contador_{sorteo_id}",)).fetchone()
        actual_cont = int(cont_row["valor"]) if cont_row else 1
        if max_num >= actual_cont:
            cursor.execute("INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)", (f"contador_{sorteo_id}", str(max_num + 1)))

        for num_boleto in nuevos_boletos_ids:
            cursor.execute("""
                INSERT OR REPLACE INTO boletos (id, sorteo_id, lote_id, nombre, telefono, cedula, cantidad_lote, imagen_comprobante, metodo_pago, detalle_pago, estado, impreso, es_juego_loco, vendedor)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Carga Manual', 'Manual (Silencioso)', 'Carga interna', 'Aprobado', 0, 0, 'Carga Manual')
            """, (num_boleto, sorteo_id, current_lote, nombre, telefono, cedula, cantidad))

        conn.commit()
        conn.close()
        respaldar_base_datos()

    return jsonify({"mensaje": f"¡{cantidad} boletos agregados (del #{nuevos_boletos_ids[0]} al #{nuevos_boletos_ids[-1]}) y listos para imprimir!"}), 200


@app.route("/api/admin/eliminar-lote/<int:lote_id>", methods=["POST"])
def admin_eliminar_lote(lote_id):
    data = request.json or {}
    if not verificar_admin(data):
        return jsonify({"error": "No autorizado"}), 401

    with bloqueo_compra:
        conn = get_db()
        cursor = conn.cursor()
        boletos_a_eliminar = cursor.execute("SELECT * FROM boletos WHERE lote_id = ? AND estado = 'Pendiente'", (lote_id,)).fetchall()

        if not boletos_a_eliminar:
            conn.close()
            return jsonify({"error": "Lote no encontrado."}), 404

        sorteo_id = boletos_a_eliminar[0]["sorteo_id"]
        for b in boletos_a_eliminar:
            cursor.execute("INSERT OR IGNORE INTO numeros_liberados (sorteo_id, numero) VALUES (?, ?)", (sorteo_id, b["id"]))

        cursor.execute("DELETE FROM boletos WHERE lote_id = ? AND estado = 'Pendiente'", (lote_id,))
        conn.commit()
        conn.close()
        respaldar_base_datos()

    return jsonify({"mensaje": f"¡Lote #{lote_id} eliminado y números liberados!"}), 200


# ==========================================
# RUTAS DE RASPADITA DE NOMBRES
# ==========================================
@app.route("/api/raspadita/activa", methods=["GET"])
def api_raspadita_activa():
    conn = get_db()
    rasp = conn.execute("SELECT * FROM raspaditas WHERE estado = 'Activa' ORDER BY id DESC LIMIT 1").fetchone()
    if not rasp:
        conn.close()
        return jsonify({"activa": False}), 200

    casillas = conn.execute(
        "SELECT id, nombre_casilla, comprador_nombre, estado, raspado FROM raspadita_casillas WHERE raspadita_id = ? ORDER BY id ASC",
        (rasp["id"],)
    ).fetchall()
    conn.close()

    return jsonify({
        "activa": True,
        "id": rasp["id"],
        "titulo": rasp["titulo"],
        "premio": rasp["premio"],
        "precio": rasp["precio"],
        "revelado": bool(rasp["revelado"]),
        "nombre_ganador": rasp["nombre_ganador"] if rasp["revelado"] else "OCULTO HASTA COMPLETAR",
        "casillas": [dict(c) for c in casillas]
    }), 200


@app.route("/api/raspadita/reservar", methods=["POST"])
def api_raspadita_reservar():
    data = request.json or {}
    casilla_id = int(data.get("casilla_id", 0))
    nombre = str(data.get("nombre", "")).strip()
    telefono = str(data.get("telefono", "")).strip()
    cedula = str(data.get("cedula", "")).strip()

    if not casilla_id or not nombre or not telefono:
        return jsonify({"error": "Completa tu nombre y teléfono para reservar el casillero."}), 400

    with bloqueo_compra:
        conn = get_db()
        cursor = conn.cursor()
        casilla = cursor.execute("SELECT * FROM raspadita_casillas WHERE id = ?", (casilla_id,)).fetchone()
        if not casilla:
            conn.close()
            return jsonify({"error": "Casillero no encontrado."}), 404
        if casilla["estado"] != "Libre":
            conn.close()
            return jsonify({"error": "Ese nombre ya fue reservado por otra persona."}), 400

        cursor.execute("""
            UPDATE raspadita_casillas
            SET comprador_nombre = ?, comprador_telefono = ?, comprador_cedula = ?, estado = 'Pendiente', raspado = 1
            WHERE id = ?
        """, (nombre, telefono, cedula, casilla_id))
        conn.commit()
        conn.close()
        respaldar_base_datos()

    return jsonify({
        "ok": True,
        "mensaje": f"¡Reservaste el nombre {casilla['nombre_casilla']}! Envía tu comprobante del BNF para confirmar."
    }), 200


@app.route("/api/admin/raspadita/crear", methods=["POST"])
def admin_raspadita_crear():
    data = request.json or {}
    if not verificar_admin(data):
        return jsonify({"error": "No autorizado"}), 401

    titulo = str(data.get("titulo") or "Raspadita de Nombres - Juego Loco").strip()
    premio = str(data.get("premio") or "60.000 Gs. en efectivo").strip()
    precio = int(data.get("precio") or 5000)
    cantidad = int(data.get("cantidad") or 20)
    nombres_custom = data.get("nombres")

    if isinstance(nombres_custom, list) and len(nombres_custom) >= 5:
        lista_nombres = [str(n).strip().upper() for n in nombres_custom if str(n).strip()]
    else:
        lista_nombres = NOMBRES_DEFECTO_30[:max(10, min(cantidad, 30))]

    ganador_secreto = random.choice(lista_nombres)

    with bloqueo_compra:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE raspaditas SET estado = 'Finalizada' WHERE estado = 'Activa'")
        cursor.execute("""
            INSERT INTO raspaditas (titulo, premio, precio, nombre_ganador, revelado, estado)
            VALUES (?, ?, ?, ?, 0, 'Activa')
        """, (titulo, premio, precio, ganador_secreto))
        rasp_id = cursor.lastrowid

        for nom in lista_nombres:
            cursor.execute("""
                INSERT INTO raspadita_casillas (raspadita_id, nombre_casilla, estado, raspado)
                VALUES (?, ?, 'Libre', 0)
            """, (rasp_id, nom))

        conn.commit()
        conn.close()
        respaldar_base_datos()

    return jsonify({"ok": True, "mensaje": f"Cartilla creada con {len(lista_nombres)} nombres.", "raspadita_id": rasp_id}), 200


@app.route("/api/admin/raspadita/aprobar-casilla/<int:casilla_id>", methods=["POST"])
def admin_raspadita_aprobar(casilla_id):
    data = request.json or {}
    if not verificar_admin(data):
        return jsonify({"error": "No autorizado"}), 401

    with bloqueo_compra:
        conn = get_db()
        conn.execute("UPDATE raspadita_casillas SET estado = 'Aprobado' WHERE id = ?", (casilla_id,))
        conn.commit()
        conn.close()
        respaldar_base_datos()
    return jsonify({"ok": True, "mensaje": "Casilla aprobada."}), 200


@app.route("/api/admin/raspadita/liberar-casilla/<int:casilla_id>", methods=["POST"])
def admin_raspadita_liberar(casilla_id):
    data = request.json or {}
    if not verificar_admin(data):
        return jsonify({"error": "No autorizado"}), 401

    with bloqueo_compra:
        conn = get_db()
        conn.execute("""
            UPDATE raspadita_casillas
            SET comprador_nombre = '', comprador_telefono = '', comprador_cedula = '', estado = 'Libre', raspado = 0
            WHERE id = ?
        """, (casilla_id,))
        conn.commit()
        conn.close()
        respaldar_base_datos()
    return jsonify({"ok": True, "mensaje": "Casilla liberada nuevamente."}), 200


@app.route("/api/admin/raspadita/revelar/<int:raspadita_id>", methods=["POST"])
def admin_raspadita_revelar(raspadita_id):
    data = request.json or {}
    if not verificar_admin(data):
        return jsonify({"error": "No autorizado"}), 401

    with bloqueo_compra:
        conn = get_db()
        conn.execute("UPDATE raspaditas SET revelado = 1 WHERE id = ?", (raspadita_id,))
        rasp = conn.execute("SELECT nombre_ganador FROM raspaditas WHERE id = ?", (raspadita_id,)).fetchone()
        conn.commit()
        conn.close()
        respaldar_base_datos()
    return jsonify({"ok": True, "nombre_ganador": rasp["nombre_ganador"] if rasp else ""}), 200


# ==========================================
# RUTAS DE IMPRESIÓN TÉRMICA LOCAL
# ==========================================
@app.route("/api/pendientes-impresion", methods=["GET"])
def obtener_pendientes_impresion():
    conn = get_db()
    boletos_aprobados = conn.execute("SELECT * FROM boletos WHERE estado = 'Aprobado' AND impreso = 0 ORDER BY sorteo_id ASC, id ASC").fetchall()

    pendientes = []
    for b in boletos_aprobados:
        sorteo = conn.execute("SELECT titulo FROM sorteos WHERE id = ?", (b["sorteo_id"],)).fetchone()
        pendientes.append({
            "id": b["id"],
            "sorteo_id": b["sorteo_id"],
            "lote_id": b["lote_id"],
            "sorteo_titulo": sorteo["titulo"] if sorteo else "Sorteo",
            "nombre": b["nombre"],
            "cedula": b["cedula"],
            "telefono": b["telefono"],
            "numero_asignado": str(b["id"]).zfill(5)
        })
    conn.close()
    return jsonify(pendientes), 200


@app.route("/api/marcar-impreso/<int:boleto_id>", methods=["POST"])
def marcar_como_impreso(boleto_id):
    sorteo_id = request.args.get("sorteo_id", type=int)
    conn = get_db()
    if sorteo_id:
        conn.execute("UPDATE boletos SET impreso = 1 WHERE id = ? AND sorteo_id = ?", (boleto_id, sorteo_id))
    else:
        conn.execute("UPDATE boletos SET impreso = 1 WHERE id = ?", (boleto_id,))
    conn.commit()
    conn.close()
    respaldar_base_datos()
    return jsonify({"status": "success"}), 200


@app.route("/api/reimprimir/<int:boleto_id>", methods=["POST"])
def api_reimprimir(boleto_id):
    data = request.json or {}
    if not verificar_admin(data):
        return jsonify({"error": "No autorizado"}), 401
    sorteo_id = data.get("sorteo_id")
    conn = get_db()
    if sorteo_id:
        conn.execute("UPDATE boletos SET impreso = 0 WHERE id = ? AND sorteo_id = ?", (boleto_id, sorteo_id))
    else:
        conn.execute("UPDATE boletos SET impreso = 0 WHERE id = ?", (boleto_id,))
    conn.commit()
    conn.close()
    respaldar_base_datos()
    return jsonify({"mensaje": f"Boleto #{boleto_id} reenviado a la impresora."}), 200


@app.route("/api/admin/limpiar-pruebas", methods=["POST"])
def limpiar_pruebas():
    data = request.json or {}
    if not verificar_admin(data):
        return jsonify({"error": "No autorizado"}), 401
    with bloqueo_compra:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM boletos")
        cursor.execute("DELETE FROM numeros_liberados")
        cursor.execute("UPDATE config SET valor = '1' WHERE clave LIKE 'contador_%'")
        cursor.execute("UPDATE config SET valor = '1' WHERE clave = 'lote_contador'")
        conn.commit()
        conn.close()
        respaldar_base_datos()
    return jsonify({"mensaje": "¡Sistema de Juegos Patri reiniciado a cero!"}), 200


@app.route("/impresion")
def vista_impresion_web():
    return render_template("impresion.html")


@app.route("/acceso")
def doble_acceso():
    return render_template_string(DOBLE_ACCESO_HTML)


@app.route("/cobrador/login", methods=["GET", "POST"])
def jp_login():
    error = None
    next_url = request.args.get("next") or ""
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "").strip()
        es_admin = u in ADMIN_USERS and ADMIN_USERS[u] == p
        es_cobrador = u == COBRADOR_USER and p == COBRADOR_PASS
        if es_admin or es_cobrador:
            session["jp_logged_in"] = True
            session["jp_role"] = "admin" if es_admin else "cobrador"
            destino_defecto = url_for("jp_duena_panel") if es_admin else url_for("vista_cobrador")
            if next_url.startswith("/") and next_url not in ("/cobrador", "/cobrador/"):
                return redirect(next_url)
            return redirect(destino_defecto)
        error = "Usuario o contraseña incorrectos"
    return render_template_string(JP_LOGIN_HTML, error=error)


@app.route("/cobrador/logout")
def jp_logout():
    session.pop("jp_logged_in", None)
    session.pop("jp_role", None)
    return redirect(url_for("jp_login"))


@app.route("/cobrador")
@jp_login_required
def vista_cobrador():
    return render_template("cobrador.html")


@app.route("/cobrador/duena")
@jp_admin_required
def jp_duena_panel():
    return render_template("duena_mesas.html")


@app.route("/cobrador/qr-etiquetas")
@jp_login_required
def jp_qr_etiquetas():
    conn = get_db()
    mesas = [
        dict(r) for r in conn.execute(
            """SELECT id, mesa_num, senor, ciudad, lugar
               FROM jp_clientes
               WHERE activo = 1
               ORDER BY CAST(mesa_num AS INTEGER) ASC, mesa_num ASC"""
        ).fetchall()
    ]
    conn.close()
    return render_template_string(JP_QR_HTML, mesas=mesas)


@app.route("/uploads/jp/<path:filename>")
@jp_login_required
def jp_servir_foto(filename):
    return send_from_directory(JP_UPLOAD_DIR, filename)


@app.route("/api/jp/clientes", methods=["GET", "POST"])
@jp_login_required
def jp_clientes_api():
    if request.method == "GET":
        q = request.args.get("q", "").strip()
        ciudad = request.args.get("ciudad", "").strip()

        sql = """
            SELECT c.*,
                   COALESCE((SELECT reloj FROM jp_lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), 0) AS ultimo_reloj,
                   COALESCE((SELECT fecha FROM jp_lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), '') AS ultima_fecha,
                   COALESCE((SELECT saldo_resultante FROM jp_lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), 0) AS saldo_actual
            FROM jp_clientes c
            WHERE c.activo = 1
        """
        params = []
        if q:
            sql += " AND (c.mesa_num LIKE ? OR c.senor LIKE ? OR c.lugar LIKE ? OR c.calle LIKE ? OR c.ciudad LIKE ?)"
            like = f"%{q}%"
            params.extend([like, like, like, like, like])
        if ciudad:
            sql += " AND c.ciudad = ?"
            params.append(ciudad)

        sql += " ORDER BY CAST(c.mesa_num AS INTEGER) ASC, c.mesa_num ASC"

        conn = get_db()
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        ciudades = [
            r["ciudad"] for r in conn.execute(
                "SELECT DISTINCT ciudad FROM jp_clientes WHERE activo = 1 AND ciudad != '' ORDER BY ciudad"
            ).fetchall()
        ]
        conn.close()
        return jsonify({"clientes": rows, "ciudades": ciudades})

    data = request.json or {}
    maps_url = (data.get("maps_url") or "").strip()
    lat, lng = jp_extraer_coords_maps(maps_url)
    if lat is None and data.get("lat") not in (None, "") and data.get("lng") not in (None, ""):
        try:
            lat = float(data["lat"])
            lng = float(data["lng"])
            if not maps_url:
                maps_url = f"https://www.google.com/maps?q={lat},{lng}"
        except ValueError:
            lat, lng = None, None

    with bloqueo_compra:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO jp_clientes (mesa_num, senor, ciudad, calle, lugar, ci, tarifa, maps_url, lat, lng, notas)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(data.get("mesa_num", "")).strip(),
                str(data.get("senor", "")).strip(),
                str(data.get("ciudad", "")).strip(),
                str(data.get("calle", "")).strip(),
                str(data.get("lugar", "")).strip(),
                str(data.get("ci", "")).strip(),
                int(data.get("tarifa", 1000) or 1000),
                maps_url,
                lat,
                lng,
                str(data.get("notas", "")).strip()
            )
        )
        cid = cursor.lastrowid
        reloj_inicial = data.get("reloj_inicial")
        if reloj_inicial not in (None, ""):
            cursor.execute(
                "INSERT INTO jp_lecturas (cliente_id, fecha, reloj, cant_jug, total_gs, entrega, saldo_resultante) VALUES (?, ?, ?, 0, 0, 0, 0)",
                (cid, data.get("fecha_inicial") or time.strftime("%Y-%m-%d"), int(reloj_inicial))
            )
        conn.commit()
        conn.close()
        respaldar_base_datos()

    return jsonify({"ok": True, "id": cid})


@app.route("/api/jp/clientes/<int:cid>", methods=["PUT", "DELETE"])
@jp_admin_required
def jp_cliente_detalle_api(cid):
    with bloqueo_compra:
        conn = get_db()
        cursor = conn.cursor()
        cli = cursor.execute("SELECT id FROM jp_clientes WHERE id = ?", (cid,)).fetchone()
        if not cli:
            conn.close()
            return jsonify({"error": "Mesa no encontrada"}), 404

        if request.method == "DELETE":
            data = request.json or {}
            motivo = str(data.get("motivo") or "Mesa entregada / baja").strip()
            cursor.execute(
                """UPDATE jp_clientes
                   SET activo = 0,
                       notas = CASE WHEN notas = '' THEN ? ELSE notas || ' | ' || ? END
                   WHERE id = ?""",
                (motivo, motivo, cid),
            )
            conn.commit()
            conn.close()
            respaldar_base_datos()
            return jsonify({"ok": True})

        data = request.json or {}
        maps_url = (data.get("maps_url") or "").strip()
        lat, lng = jp_extraer_coords_maps(maps_url)
        cursor.execute(
            """UPDATE jp_clientes
               SET mesa_num = ?, senor = ?, ciudad = ?, calle = ?, lugar = ?, ci = ?,
                   tarifa = ?, maps_url = ?,
                   lat = COALESCE(?, lat), lng = COALESCE(?, lng), notas = ?
               WHERE id = ?""",
            (
                str(data.get("mesa_num", "")).strip(),
                str(data.get("senor", "")).strip(),
                str(data.get("ciudad", "")).strip(),
                str(data.get("calle", "")).strip(),
                str(data.get("lugar", "")).strip(),
                str(data.get("ci", "")).strip(),
                int(data.get("tarifa", 1000) or 1000),
                maps_url,
                lat,
                lng,
                str(data.get("notas", "")).strip(),
                cid,
            )
        )
        jp_recalcular_cadena(conn, cid)
        conn.commit()
        conn.close()
        respaldar_base_datos()

    return jsonify({"ok": True})


@app.route("/api/jp/clientes/<int:cid>/lecturas", methods=["GET"])
@jp_login_required
def jp_cliente_lecturas_api(cid):
    conn = get_db()
    rows = [
        dict(r) for r in conn.execute(
            "SELECT * FROM jp_lecturas WHERE cliente_id = ? ORDER BY id DESC",
            (cid,)
        ).fetchall()
    ]
    conn.close()
    return jsonify({"lecturas": rows})


@app.route("/api/jp/clientes/<int:cid>/fotos", methods=["GET"])
@jp_login_required
def jp_cliente_fotos_api(cid):
    conn = get_db()
    rows = [
        dict(r) for r in conn.execute(
            "SELECT id, cliente_id, tipo, archivo, fecha, observacion FROM jp_fotos_cliente WHERE cliente_id = ? ORDER BY id DESC",
            (cid,)
        ).fetchall()
    ]
    conn.close()
    fotos = [
        {
            **r,
            "url": url_for("jp_servir_foto", filename=r["archivo"])
        }
        for r in rows
    ]
    return jsonify({"fotos": fotos})


@app.route("/api/jp/importar-clientes", methods=["POST"])
@jp_admin_required
def jp_importar_clientes():
    items = request.json or []
    if not isinstance(items, list):
        return jsonify({"error": "Formato inválido"}), 400

    importados = 0
    omitidos = 0

    with bloqueo_compra:
        conn = get_db()
        cursor = conn.cursor()

        for item in items:
            mesa_num = str(item.get("mesa_num") or "").strip()
            senor = str(item.get("senor") or "").strip()
            if not mesa_num or not senor:
                omitidos += 1
                continue

            existe = cursor.execute(
                "SELECT id FROM jp_clientes WHERE activo = 1 AND mesa_num = ? AND LOWER(senor) = LOWER(?)",
                (mesa_num, senor)
            ).fetchone()
            if existe:
                omitidos += 1
                continue

            cursor.execute(
                """INSERT INTO jp_clientes (mesa_num, senor, ciudad, calle, lugar, ci, tarifa, maps_url, lat, lng, notas)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mesa_num,
                    senor,
                    str(item.get("ciudad") or "").strip(),
                    str(item.get("calle") or "").strip(),
                    str(item.get("lugar") or "").strip(),
                    str(item.get("ci") or "").strip(),
                    int(item.get("tarifa") or 1000),
                    str(item.get("maps_url") or "").strip(),
                    item.get("lat"),
                    item.get("lng"),
                    str(item.get("notas") or "").strip(),
                )
            )
            cid = cursor.lastrowid

            reloj_ini = int(item.get("ultimo_reloj") or 0)
            saldo_ini = int(item.get("saldo_actual") or 0)
            fecha_ini = str(item.get("ultima_fecha") or time.strftime("%Y-%m-%d"))

            if reloj_ini > 0 or saldo_ini != 0:
                cursor.execute(
                    """INSERT INTO jp_lecturas (cliente_id, fecha, reloj, cant_jug, total_gs, entrega, saldo_resultante, observacion)
                       VALUES (?, ?, ?, 0, 0, 0, ?, 'Migración inicial desde local')""",
                    (cid, fecha_ini, reloj_ini, saldo_ini)
                )

            importados += 1

        conn.commit()
        conn.close()
        respaldar_base_datos()

    return jsonify({"ok": True, "importados": importados, "omitidos": omitidos})


@app.route("/api/jp/cobrador/cargar", methods=["POST"])
@jp_login_required
def jp_cobrador_cargar():
    cid = int(request.form.get("cliente_id"))
    fecha = request.form.get("fecha") or time.strftime("%Y-%m-%d")
    reloj = int(request.form.get("reloj"))
    entrega = int(request.form.get("entrega") or 0)
    obs = (request.form.get("observacion") or "").strip()
    lat = (request.form.get("lat") or "").strip()
    lng = (request.form.get("lng") or "").strip()

    with bloqueo_compra:
        conn = get_db()
        ultima = conn.execute(
            "SELECT reloj FROM jp_lecturas WHERE cliente_id = ? ORDER BY id DESC LIMIT 1", (cid,)
        ).fetchone()
        if ultima and reloj < ultima["reloj"]:
            conn.close()
            return jsonify({"error": f"El reloj ({reloj}) no puede ser menor al anterior ({ultima['reloj']})"}), 400

        conn.execute(
            "INSERT INTO jp_lecturas (cliente_id, fecha, reloj, entrega, observacion) VALUES (?, ?, ?, ?, ?)",
            (cid, fecha, reloj, entrega, obs)
        )
        jp_recalcular_cadena(conn, cid)

        archivo = request.files.get("foto")
        if archivo and archivo.filename:
            ext = os.path.splitext(archivo.filename)[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                ext = ".jpg"
            nombre_unico = f"cli{cid}_{uuid.uuid4().hex[:10]}{ext}"
            archivo.save(os.path.join(JP_UPLOAD_DIR, nombre_unico))
            conn.execute(
                "INSERT INTO jp_fotos_cliente (cliente_id, tipo, archivo, fecha, observacion) VALUES (?, ?, ?, ?, ?)",
                (cid, "Reloj", nombre_unico, fecha, f"Reloj {reloj} (Cobrador)")
            )

        if lat and lng:
            cli = conn.execute("SELECT maps_url, lat, lng FROM jp_clientes WHERE id = ?", (cid,)).fetchone()
            if cli and (cli["lat"] is None or cli["lng"] is None):
                url_maps = f"https://www.google.com/maps?q={lat},{lng}"
                conn.execute(
                    "UPDATE jp_clientes SET lat=?, lng=?, maps_url=CASE WHEN maps_url='' THEN ? ELSE maps_url END WHERE id=?",
                    (float(lat), float(lng), url_maps, cid)
                )

        nueva = dict(conn.execute(
            "SELECT * FROM jp_lecturas WHERE cliente_id = ? ORDER BY id DESC LIMIT 1", (cid,)
        ).fetchone())
        conn.commit()
        conn.close()
        respaldar_base_datos()

    return jsonify({"ok": True, "lectura": nueva})


@app.route("/api/jp/cobrador/rendicion", methods=["GET"])
@jp_login_required
def jp_cobrador_rendicion():
    hoy = time.strftime("%Y-%m-%d")
    conn = get_db()
    cobros = [dict(r) for r in conn.execute("""
        SELECT l.id, l.fecha, l.reloj, l.cant_jug, l.total_gs, l.entrega, l.saldo_resultante, l.observacion,
               c.mesa_num, c.senor, c.ciudad
        FROM jp_lecturas l
        JOIN jp_clientes c ON c.id = l.cliente_id
        WHERE l.fecha = ?
        ORDER BY l.id DESC
    """, (hoy,)).fetchall()]

    gastos = [dict(r) for r in conn.execute(
        "SELECT * FROM jp_gastos_gira WHERE fecha = ? ORDER BY id DESC", (hoy,)
    ).fetchall()]
    conn.close()

    total_cobrado = sum(c["entrega"] for c in cobros)
    total_gastos = sum(g["monto"] for g in gastos)
    return jsonify({
        "fecha": hoy,
        "total_cobrado": total_cobrado,
        "total_gastos": total_gastos,
        "neto_a_rendir": total_cobrado - total_gastos,
        "cobros": cobros,
        "gastos": gastos
    })


@app.route("/api/jp/gastos", methods=["POST"])
@jp_login_required
def jp_agregar_gasto():
    data = request.json or {}
    with bloqueo_compra:
        conn = get_db()
        conn.execute(
            "INSERT INTO jp_gastos_gira (fecha, categoria, ciudad, monto, descripcion) VALUES (?, ?, ?, ?, ?)",
            (
                data.get("fecha") or time.strftime("%Y-%m-%d"),
                str(data.get("categoria", "Combustible")).strip(),
                str(data.get("ciudad", "")).strip(),
                int(data.get("monto") or 0),
                str(data.get("descripcion", "")).strip()
            )
        )
        conn.commit()
        conn.close()
        respaldar_base_datos()
    return jsonify({"ok": True})


if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 5000))
    es_nube = bool(os.environ.get("RENDER") or os.environ.get("PORT"))
    app.run(host="0.0.0.0", port=puerto, debug=not es_nube)
