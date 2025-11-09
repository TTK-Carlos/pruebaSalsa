# nomina_logic.py
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from collections import defaultdict
import math

DOW = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
MONTH = {
    1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio',
    7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
}

def _h(v):
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(',', '.'))
    except Exception:
        return 0.0

def _dt(s):
    if isinstance(s, datetime):
        return s
    s = str(s).strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    for fmt in ('%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d', '%d-%m-%Y'):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return datetime.fromisoformat(s)

def local_date(x, tz='Europe/Madrid'):
    z = ZoneInfo(tz)
    dt = _dt(x)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo('UTC'))
    return dt.astimezone(z).date()

def dr(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)

def wb(d: date):
    s = d - timedelta(days=d.weekday())
    e = s + timedelta(days=6)
    return s, e

def in_period(d, periods):
    if not periods:
        return False
    for p in periods:
        try:
            s = _dt(p['start']).date()
            e = _dt(p['end']).date()
        except Exception:
            continue
        d_md = (d.month, d.day)
        s_md = (s.month, s.day)
        e_md = (e.month, e.day)
        if s_md <= e_md:
            if s_md <= d_md <= e_md:
                return True
        else:
            if d_md >= s_md or d_md <= e_md:
                return True
    return False

def r2(x):
    return math.floor(x * 100 + 0.5) / 100.0

def process(records, start_date, end_date, tz='Europe/Madrid', selected_worker=None,
            flexible_rest_periods=None, enforce_sunday_rest=True):

    start = _dt(start_date).date()
    end = _dt(end_date).date()

    # Normalizar y filtrar
    rows = []
    for r in records:
        try:
            f = local_date(r.get('FECHA'), tz)
        except Exception:
            continue
        if not (start <= f <= end):
            continue
        name = r.get('TRABAJADOR') or r.get('trabajador') or r.get('Trabajador') or ''
        wid = r.get('trabajador_id')
        if selected_worker not in (None, ''):
            if isinstance(selected_worker, (int, float)):
                if wid != selected_worker:
                    continue
            else:
                if str(name).strip().lower() != str(selected_worker).strip().lower():
                    continue
        cat = str(r.get('CATEGORIA') or r.get('CATEGORÍA') or r.get('categoria') or '').upper()
        cat = 'PRODUCTIVIDAD' if 'PROD' in cat else 'FICHAJE'
        rows.append({
            'trabajador': name,
            'trabajador_id': wid,
            'categoria': cat,
            'horas': _h(r.get('HORAS') or r.get('horas')),
            'fecha': f
        })

    by = defaultdict(list)
    for x in rows:
        key = x['trabajador'] or f"ID:{x['trabajador_id']}"
        by[key].append(x)

    out = {'workers': []}
    total_f_global = 0.0
    total_p_global = 0.0

    for worker, items in by.items():
        days = {
            d: {'fichaje': 0.0, 'prod': 0.0, 'aj': 0.0, 'nota': [], 'dia': DOW[d.weekday()], 'fecha': d.isoformat()}
            for d in dr(start, end)
        }

        for it in items:
            d = it['fecha']
            if it['categoria'] == 'FICHAJE':
                days[d]['fichaje'] += it['horas']
            else:
                days[d]['prod'] += it['horas']

        pool = {d: r2(v['prod']) for d, v in days.items()}

        def take(amt, prefer=None):
            rem = amt
            got = 0.0
            logs = []
            order = [prefer] if prefer else []
            order += [d for d in sorted(pool.keys()) if d != prefer]
            for d in order:
                if rem <= 0:
                    break
                av = pool.get(d, 0.0)
                if av <= 0:
                    continue
                t = min(rem, av)
                pool[d] = r2(av - t)
                rem = r2(rem - t)
                got = r2(got + t)
                logs.append({'from': d.isoformat(), 'hours': t})
            return got, logs, rem

        transfers = []

        # 1) Top-up a 7h
        for d in sorted(days.keys()):
            flex = in_period(d, flexible_rest_periods)
            if enforce_sunday_rest and d.weekday() == 6 and not flex:
                continue
            fc = r2(days[d]['fichaje'])
            if fc >= 7.0:
                continue
            need = r2(7.0 - fc)
            got, logs, rem = take(need, prefer=d)
            if got > 0:
                days[d]['fichaje'] = r2(days[d]['fichaje'] + got)
                days[d]['aj'] = r2(days[d]['aj'] + got)
                transfers.append({'to': d.isoformat(), 'hours': got, 'from_parts': logs, 'reason': 'Topup <7h'})

        # 2) Completar 6 días/semana con 7h
        seen = set()
        weeks = []
        for d in sorted(days.keys()):
            w = wb(d)
            if w not in seen:
                seen.add(w)
                weeks.append(w)

        for s, e in weeks:
            semana_dias = [d for d in dr(s, e) if d in days]
            if not semana_dias:
                continue
            flex = any(in_period(d, flexible_rest_periods) for d in semana_dias)
            worked = [d for d in semana_dias
                      if r2(days[d]['fichaje']) > 0 and not (enforce_sunday_rest and d.weekday() == 6 and not flex)]
            if len(worked) >= 6:
                continue
            need = 6 - len(worked)
            cand = [d for d in semana_dias
                    if r2(days[d]['fichaje']) == 0 and not (enforce_sunday_rest and d.weekday() == 6 and not flex)]
            for d in cand:
                if need <= 0 or r2(sum(pool.values())) < 7.0:
                    break
                got, logs, rem = take(7.0, None)
                if got >= 7.0 - 1e-6:
                    days[d]['fichaje'] = r2(days[d]['fichaje'] + got)
                    days[d]['aj'] = r2(days[d]['aj'] + got)
                    days[d]['nota'].append('Día generado para completar 6 días de trabajo')
                    transfers.append({'to': d.isoformat(), 'hours': got, 'from_parts': logs, 'reason': 'Completar 6 días'})
                    need -= 1

        tf = 0.0
        tp = 0.0
        avisos = []
        wdays = []
        for d in sorted(days.keys()):
            flex = in_period(d, flexible_rest_periods)
            if enforce_sunday_rest and d.weekday() == 6 and not flex and r2(days[d]['fichaje']) > 0:
                avisos.append(f'Domingo {d.isoformat()} con fichaje fuera de periodo flexible')
            prod_final = r2(pool.get(d, 0.0))
            fich_final = r2(days[d]['fichaje'])
            wdays.append({
                'fecha': d.isoformat(),
                'dia': DOW[d.weekday()].upper(),
                'fichaje': fich_final,
                'productividad': prod_final,
                'ajuste_desde_productividad': r2(days[d]['aj']),
                'notas': ''
            })
            tf += fich_final
            tp += prod_final

        total_f_global += r2(tf)
        total_p_global += r2(tp)

        out['workers'].append({
            'trabajador': worker,
            'mes': MONTH[start.month],
            'anio': start.year,
            'days': wdays,
            'totales': {'fichaje': r2(tf), 'productividad': r2(tp)},
            'transferencias': transfers,
            'avisos': [],
            'html': ''  # (dejado vacío; usaremos PDF)
        })

    out['totales_globales'] = {'fichaje': r2(total_f_global), 'productividad': r2(total_p_global)}
    return out
