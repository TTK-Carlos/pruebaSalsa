
import json
import azure.functions as func
from .nomina_logic import process

def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse("Invalid JSON", status_code=400)

    records = body.get("items", [])
    start_date = (body.get("range") or {}).get("start") or body.get("start_date")
    end_date = (body.get("range") or {}).get("end") or body.get("end_date")
    tz = body.get("timezone", "Europe/Madrid")
    selected_worker = body.get("worker_filter")
    flexible = body.get("descanso_flexible_periods", [{"start":"2025-02-15","end":"2025-06-15"}])
    enforce_sunday_rest = bool(body.get("enforce_sunday_rest", True))

    if not start_date or not end_date:
        return func.HttpResponse("Missing start/end date", status_code=400)

    try:
        result = process(records, start_date, end_date, tz, selected_worker, flexible, enforce_sunday_rest)
    except Exception as e:
        return func.HttpResponse(f"Processing error: {e}", status_code=500)

    return func.HttpResponse(json.dumps(result, ensure_ascii=False), mimetype="application/json")
