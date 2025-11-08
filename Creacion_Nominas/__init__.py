import json
import logging
import azure.functions as func

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Creacion_Nominas HTTP trigger ejecutado.")

    # Soporta GET y POST
    name = req.params.get("name")
    if not name:
        try:
            body = req.get_json()
            name = body.get("name") if isinstance(body, dict) else None
        except ValueError:
            name = None

    payload = {
        "ok": True,
        "message": f"Hola {name or 'mundo'} 👋",
        "hint": "Envía {\"name\": \"TuNombre\"} en el body o ?name=TuNombre"
    }

    return func.HttpResponse(
        json.dumps(payload, ensure_ascii=False),
        status_code=200,
        mimetype="application/json"
    )
