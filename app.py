import os
import json
from flask import Flask, request, jsonify
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials

app = Flask(__name__)

def conectar_sheets():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    
    if "GOOGLE_CREDENTIALS" in os.environ:
        credentials_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
        creds = Credentials.from_service_account_info(credentials_dict, scopes=scope)
        client = gspread.authorize(creds)
    else:
        client = gspread.service_account(filename="credentials.json")
        
    spreadsheet = client.open("Control de Inventario 2026-1")
    return spreadsheet

@app.route("/api/producto", methods=["POST"])
def gestionar_producto():
    datos = request.json
    if not datos:
        return jsonify({"status": "error", "mensaje": "No se recibieron datos JSON."}), 400

    accion = datos.get("accion") 
    codigo_raw = datos.get("codigo")
    
    if not codigo_raw:
        return jsonify({"status": "error", "mensaje": "El código es obligatorio."}), 400
        
    codigo = str(codigo_raw).strip().zfill(3)
    
    try:
        spreadsheet = conectar_sheets()
        hoja_productos = spreadsheet.worksheet("Productos 2026-1")
        hoja_movimientos = spreadsheet.worksheet("Movimientos 2026-1")
        
        productos = hoja_productos.get_all_records()
        
        
        if accion == "nuevo":
            descripcion = datos.get("descripcion")
            precio = datos.get("precio")
            existencia = int(datos.get("existencia", 0))
            
            for p in productos:
                if str(p.get("Codigo", "")).strip().zfill(3) == codigo:
                    return jsonify({"status": "error", "mensaje": f"El código {codigo} ya existe."}), 400
            
            hoja_productos.append_row([codigo, descripcion, float(precio), existencia])
            
            fecha_hoy = datetime.now().strftime("%d/%m/%Y")
            hoja_movimientos.append_row([fecha_hoy, codigo, existencia, "Creación Inicial"])
            
            return jsonify({"status": "exito", "mensaje": f"Zapato {descripcion} creado correctamente."})

       
        elif accion == "movimiento":
            cantidad = int(datos.get("cantidad", 0))
            tipo_op = datos.get("tipo") # "Entrada" o "Salida"
            
            encontrado = False
            fila_idx = 2 
            
            for p in productos:
                if str(p.get("Codigo", "")).strip().zfill(3) == codigo:
                    encontrado = True
                    stock_actual = int(p.get("Inventario", 0))
                    nombre_desc = p.get("Descripcion", "")
                    break
                fila_idx += 1
                
            if not encontrado:
                return jsonify({"status": "error", "mensaje": f"El código {codigo} no existe en el sistema."}), 404
            
           
            if tipo_op == "Entrada":
                nuevo_stock = stock_actual + cantidad
            else: 
                nuevo_stock = stock_actual - cantidad
                if nuevo_stock < 0:
                    nuevo_stock = 0 
            
            
            hoja_productos.update_cell(fila_idx, 4, nuevo_stock)
            
            
            fecha_hoy = datetime.now().strftime("%d/%m/%Y")
            hoja_movimientos.append_row([fecha_hoy, codigo, cantidad, tipo_op])
            
            return jsonify({
                "status": "exito", 
                "mensaje": f"{tipo_op} de {cantidad} en [{codigo}] {nombre_desc}. Stock actual: {nuevo_stock}"
            })
        else:
            return jsonify({"status": "error", "mensaje": "Acción no reconocida."}), 400

    except Exception as e:
        return jsonify({"status": "error", "mensaje": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)