import json
import base64
from io import BytesIO

import azure.functions as func
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.lib import colors

from .nomina_logic import process

def _build_pdf_for_worker(worker_dict, company):
    """
    Genera un PDF (una página) con la tabla de 'Registro de Jornadas' para un trabajador.
    Devuelve (filename, pdf_bytes).
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm, topMargin=14*mm, bottomMargin=14*mm
    )

    styles = getSampleStyleSheet()
    h = ParagraphStyle('h',
        parent=styles['Heading2'], alignment=TA_LEFT, fontSize=14, leading=16, spaceAfter=4)
    k = ParagraphStyle('k', parent=styles['Normal'], fontSize=8.8, leading=10, spaceAfter=1)
    cell = ParagraphStyle('cell', parent=styles['Normal'], fontSize=9.5, leading=11, alignment=TA_CENTER)
    cell_left = ParagraphStyle('cell_l', parent=cell, alignment=TA_LEFT)

    empresa = company.get('empresa', '') or ''
    cif = company.get('cif', '') or ''
    centro = company.get('centro_trabajo', '') or ''
    ccc = company.get('ccc', '') or ''

    trabajador = worker_dict['trabajador']
    mes = worker_dict['mes']
    anio = worker_dict['anio']
    days = worker_dict['days']
    t_f = worker_dict['totales']['fichaje']
    t_p = worker_dict['totales']['productividad']

    header = [
        Paragraph("<b>REGISTRO DE JORNADAS</b>", h),
        Paragraph(f"<b>Empresa:</b> {empresa}", k),
        Paragraph(f"<b>C.I.F./N.I.F.:</b> {cif}", k),
        Paragraph(f"<b>Centro trabajo:</b> {centro}", k),
        Paragraph(f"<b>C.C.C.:</b> {ccc}", k),
        Spacer(1, 4*mm),  # espacio reducido como pediste
        Paragraph(f"<b>Trabajador/a:</b> {trabajador} &nbsp;&nbsp;&nbsp; "
                  f"<b>Mes:</b> {mes} &nbsp;&nbsp;&nbsp; <b>Año:</b> {anio}", k),
        Spacer(1, 2*mm)
    ]

    # Cabecera de tabla
    data = [
        [
            Paragraph("<b>Día del mes</b>", cell),
            Paragraph("<b>Horas</b>", cell),
            Paragraph("<b>Productividad</b>", cell),
            Paragraph("<b>Total</b>", cell),
            Paragraph("<b>Firma</b>", cell),
        ]
    ]

    # Filas (día → “LUNES 3”)
    for d in days:
        dia_text = f"{d['dia']} {int(d['fecha'][-2:])}"  # YYYY-MM-DD → últimos 2 dígitos = día
        total = (d['fichaje'] or 0) + (d['productividad'] or 0)
        data.append([
            Paragraph(dia_text, cell_left),
            Paragraph(f"{d['fichaje']:.2f}".rstrip('0').rstrip('.'), cell),
            Paragraph(f"{d['productividad']:.2f}".rstrip('0').rstrip('.'), cell),
            Paragraph(f"{total:.2f}".rstrip('0').rstrip('.'), cell),
            Paragraph("", cell),
        ])

    # Totales
    total_total = t_f + t_p
    data.append([
        Paragraph("<b>TOTALES DEL MES:</b>", cell_left),
        Paragraph(f"<b>{t_f:.2f}".rstrip('0').rstrip('.') + "</b>", cell),
        Paragraph(f"<b>{t_p:.2f}".rstrip('0').rstrip('.') + "</b>", cell),
        Paragraph(f"<b>{total_total:.2f}".rstrip('0').rstrip('.') + "</b>", cell),
        Paragraph("", cell),
    ])

    col_widths = [85*mm, 25*mm, 25*mm, 25*mm, 20*mm]

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('ALIGN', (1,1), (-2,-2), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
        ('BACKGROUND', (0,-1), (-1,-1), colors.whitesmoke),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
    ]))

    # Nota + firmas
    nota = Paragraph(
        "Registro basado en la obligación establecida en el art. 35.5 del Texto Refundido del Estatuto de Trabajadores "
        "(RDL 2/2015 de 23 de octubre).<br/>"
        "NOTA: Cuando en las horas normales aparezcan 7 horas, se descuenta media hora de descanso por comida.",
        ParagraphStyle('nota', parent=styles['Normal'], fontSize=7.6, leading=9, alignment=TA_LEFT, spaceBefore=6)
    )

    firmas_table = Table([
        ["", ""],
        [Paragraph("Recibido por el trabajador", cell), Paragraph("Firma de la empresa", cell)]
    ], colWidths=[90*mm, 90*mm], rowHeights=[18*mm, None])
    firmas_table.setStyle(TableStyle([
        ('BOX', (0,0), (0,0), 0.7, colors.black),
        ('BOX', (1,0), (1,0), 0.7, colors.black),
        ('ALIGN', (0,1), (-1,1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,0), 2),
    ]))

    elements = header + [table, nota, Spacer(1, 4*mm), firmas_table]
    doc.build(elements)
    pdf_bytes = buf.getvalue()
    buf.close()

    safe_worker = "".join([c if c.isalnum() or c in ('_', '-') else '_' for c in trabajador])
    filename = f"Registro_Jornadas_{safe_worker}_{anio}_{mes}.pdf"
    return filename, pdf_bytes

def main(req: func.HttpRequest) -> func.HttpResponse:
    # Leer entrada
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse("Invalid JSON", status_code=400)

    # Compatibilidad: records / items; start/end directamente o dentro de range
    records = body.get("records") or body.get("items") or []
    start_date = (body.get("range") or {}).get("start") or body.get("start_date")
    end_date = (body.get("range") or {}).get("end") or body.get("end_date")
    tz = body.get("timezone", "Europe/Madrid")
    selected_worker = body.get("worker_filter")
    flexible = body.get("descanso_flexible_periods", [{"start":"2025-02-15","end":"2025-06-15"}])
    enforce_sunday_rest = bool(body.get("enforce_sunday_rest", True))
    company = body.get("company", {})  # {empresa, cif, centro_trabajo, ccc}

    if not start_date or not end_date:
        return func.HttpResponse("Missing start/end date", status_code=400)

    # Procesar
    try:
        result = process(records, start_date, end_date, tz, selected_worker, flexible, enforce_sunday_rest)
    except Exception as e:
        return func.HttpResponse(f"Processing error: {e}", status_code=500)

    # Generar PDFs (uno por worker)
    pdfs = []
    for w in result.get('workers', []):
        fname, pdf_bytes = _build_pdf_for_worker(w, company)
        pdfs.append({
            "worker": w['trabajador'],
            "filename": fname,
            "content_base64": base64.b64encode(pdf_bytes).decode('ascii')
        })

    payload = {
        "ok": True,
        "summary": result.get('totales_globales', {}),
        "result": result,
        "pdfs": pdfs
    }
    return func.HttpResponse(json.dumps(payload, ensure_ascii=False), mimetype="application/json")
