import os
import json
import queue
import threading
from datetime import datetime

from flask import Flask, request, jsonify
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# ---------------- Conexión a Google Sheets ----------------
def conectar_sheets():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    if "GOOGLE_CREDENTIALS" in os.environ:
        credentials_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
        creds = Credentials.from_service_account_info(credentials_dict, scopes=scope)
        client = gspread.authorize(creds)
    else:
        client = gspread.service_account(filename="credentials.json")

    return client.open("Control de Inventario 2026-1")


# ---------------- Cola de escritura en segundo plano ----------------
cola = queue.Queue()
lock = threading.Lock()
usados = set()      # códigos conocidos (incluye los apartados en cola)
cargado = False


def worker():
    while True:
        tarea = cola.get()
        try:
            tarea()
        except Exception as e:
            print("Error en cola:", e)
        finally:
            cola.task_done()


threading.Thread(target=worker, daemon=True).start()


def refrescar_usados(productos):
    for p in productos:
        c = str(p.get("Codigo", "")).strip()
        if c.isdigit():
            usados.add(int(c))


def siguiente_libre():
    n = (max(usados) if usados else 0) + 1
    while n in usados:
        n += 1
    return n


# ---------------- Endpoint ----------------
@app.route("/api/producto", methods=["POST"])
def gestionar_producto():
    global cargado

    datos = request.json
    if not datos:
        return jsonify({"status": "error", "mensaje": "No se recibieron datos JSON."}), 400

    accion = datos.get("accion")
    codigo_raw = datos.get("codigo")

    if accion == "movimiento" and not codigo_raw:
        return jsonify({"status": "error", "mensaje": "El código es obligatorio."}), 400

    try:
        # Carga inicial de códigos (solo la primera vez)
        if not cargado:
            ss = conectar_sheets()
            productos = ss.worksheet("Productos 2026-1").get_all_records()
            with lock:
                refrescar_usados(productos)
                cargado = True

        # ---------- NUEVO ----------
        if accion == "nuevo":
            descripcion = str(datos.get("descripcion"))
            precio = float(datos.get("precio"))
            existencia = int(datos.get("existencia", 0))

            with lock:
                if codigo_raw:
                    n = int(str(codigo_raw).strip())
                    if n in usados:
                        return jsonify({
                            "status": "error",
                            "mensaje": f"El código {str(n).zfill(3)} ya existe."
                        }), 400
                else:
                    n = siguiente_libre()
                usados.add(n)  # apartado al instante
            codigo = str(n).zfill(3)

            def tarea():
                ss = conectar_sheets()
                ss.worksheet("Productos 2026-1").append_row(
                    [codigo, descripcion, precio, existencia]
                )
                ss.worksheet("Movimientos 2026-1").append_row(
                    [datetime.now().strftime("%d/%m/%Y"), codigo, existencia, "Creación Inicial"]
                )

            cola.put(tarea)

            return jsonify({
                "status": "exito",
                "codigo": codigo,
                "mensaje": f"✅ {descripcion} creado con código {codigo}"
            })

        # ---------- MOVIMIENTO ----------
        elif accion == "movimiento":
            cantidad = int(datos.get("cantidad", 0))
            tipo_op = datos.get("tipo")  # "Entrada" o "Salida"
            codigo = str(codigo_raw).strip().zfill(3)

            if int(codigo) not in usados:
                return jsonify({
                    "status": "error",
                    "mensaje": f"El código {codigo} no existe."
                }), 404

            def tarea():
                ss = conectar_sheets()
                hp = ss.worksheet("Productos 2026-1")
                hm = ss.worksheet("Movimientos 2026-1")

                fila = 2
                stock = None
                for p in hp.get_all_records():
                    if str(p.get("Codigo", "")).strip().zfill(3) == codigo:
                        stock = int(p.get("Inventario", 0))
                        break
                    fila += 1

                if stock is None:
                    print(f"Código {codigo} aún no está en la hoja")
                    return

                if tipo_op == "Entrada":
                    nuevo = stock + cantidad
                else:
                    nuevo = max(0, stock - cantidad)

                hp.update_cell(fila, 4, nuevo)
                hm.append_row(
                    [datetime.now().strftime("%d/%m/%Y"), codigo, cantidad, tipo_op]
                )

            cola.put(tarea)

            return jsonify({
                "status": "exito",
                "mensaje": f"✅ {tipo_op} de {cantidad} en [{codigo}]"
            })

        # ---------- CÓDIGOS DISPONIBLES ----------
        elif accion == "obtenercodigo":
            ss = conectar_sheets()
            productos = ss.worksheet("Productos 2026-1").get_all_records()

            with lock:
                refrescar_usados(productos)  # verifica contra la hoja real
                ordenados = sorted(usados)
                siguiente = siguiente_libre()

            return jsonify({
                "status": "exito",
                "codigos": [str(c).zfill(3) for c in ordenados],
                "ultimo_codigo": str(ordenados[-1] if ordenados else 0).zfill(3),
                "siguiente_codigo": str(siguiente).zfill(3)
            })

        return jsonify({"status": "error", "mensaje": "Acción no reconocida."}), 400

    except Exception as e:
        return jsonify({"status": "error", "mensaje": str(e)}), 500

@app.route("/version", methods=["GET"])
def version():
    return "v2-cola"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
