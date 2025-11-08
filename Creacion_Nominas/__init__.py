import json
import logging
import azure.functions as func

from .nomina_logic import process  # importa tu lógica

def _bad_request(msg: str, extra=None):
    body = {"ok": False, "error": msg}
    if extra is not None:
        body["details"] = extra
    return func.HttpResponse(
        json.dumps(body, ensure_ascii=False),
        status_code=400,
        mimetype="application/json",
    )

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Creacion_Nominas HTTP trigger ejecutado.")

    # Leer body JSON
    try:
        data = req.get_json()
    except ValueError:
        return _bad_request("El cuerpo debe ser JSON válido.")

    # Validaciones mínimas
    if not isinstance(data, dict):
        return _bad_request("El cuerpo JSON debe ser un objeto.")

    records = data.get("records")
    start_date = data.get("start_date")
    end_date = data.get("end_date")

    if not isinstance(records, list):
        return _bad_request("Falta 'records' (lista de registros).")
    if not start_date or not end_date:
        return _bad_request("Faltan 'start_date' y/o 'end_date'.")

    # Parámetros opcionales
    tz = data.get("tz", "Europe/Madrid")
    selected_worker = data.get("selected_worker")
    flexible_rest_periods = data.get("flexible_rest_periods")  # lista de {start, end}
    enforce_sunday_rest = data.get("enforce_sunday_rest", True)

    try:
        result = process(
            records=records,
            start_date=start_date,
            end_date=end_date,
            tz=tz,
            selected_worker=selected_worker,
            flexible_rest_periods=flexible_rest_periods,
            enforce_sunday_rest=bool(enforce_sunday_rest),
        )
    except Exception as e:
        logging.exception("Error ejecutando la lógica de nóminas")
        return func.HttpResponse(
            json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
            status_code=500,
            mimetype="application/json",
        )

    # Respuesta OK
    return func.HttpResponse(
        json.dumps({"ok": True, "result": result}, ensure_ascii=False),
        status_code=200,
        mimetype="application/json",
    )
