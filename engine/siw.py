"""SIW v2 XAUUSD M5 engine - stdlib-only port of fx-research/siw_v2_20261104/siw.py.
Bar L = CONFIRM bar; entry = open of L+1. Deterministic, no AI."""
from datetime import datetime, timedelta, timezone

P = dict(modes='abc', star_body_max=0.40, pin_wick_min=0.50, pin_body_max=0.35, wick_tol=0.30,
         engulf_tol=0.10, leg_lookback=12, max_ext=10.0, dedupe=3,
         sl=10.0, tp=20.0, exit_bars=2, cost=0.28)  # exit v4 (2026-11-04): SL $10, TP $20 cap, close at close of L+2 (10 min)

def ema(xs, span):
    a = 2.0 / (span + 1); out = []; v = None
    for x in xs:
        v = x if v is None else a * x + (1 - a) * v
        out.append(v)
    return out

def add_emas(bars):
    c = [b['c'] for b in bars]
    for b, x, y in zip(bars, ema(c, 21), ema(c, 55)):
        b['e21'], b['e55'] = x, y
    return bars

def _shape(b):
    rng = max(b['h'] - b['l'], 1e-9); top, bot = max(b['o'], b['c']), min(b['o'], b['c'])
    return abs(b['c'] - b['o']) / rng, (b['h'] - top) / rng, (bot - b['l']) / rng, top, bot

def rej(b, pv, d, p):
    bp, uw, lw, top, bot = _shape(b); ptop, pbot = max(pv['o'], pv['c']), min(pv['o'], pv['c'])
    if d == 'S':
        if uw >= p['pin_wick_min'] and bp <= p['pin_body_max']: return 'PIN'
        if bp <= p['star_body_max'] and bot >= ptop - p['wick_tol'] and top <= pv['h'] + p['wick_tol'] and pv['h'] > ptop: return 'STAR'
    else:
        if lw >= p['pin_wick_min'] and bp <= p['pin_body_max']: return 'PIN'
        if bp <= p['star_body_max'] and top <= pbot + p['wick_tol'] and bot >= pv['l'] - p['wick_tol'] and pbot > pv['l']: return 'STAR'
    return None

def engulf(b, pv, d, t):
    if d == 'S': return b['c'] < b['o'] and pv['c'] > pv['o'] and b['o'] >= pv['c'] - t and b['c'] <= pv['o'] + t
    return b['c'] > b['o'] and pv['c'] < pv['o'] and b['o'] <= pv['c'] + t and b['c'] >= pv['o'] - t

def classify(bars, i, d, p):
    L, p1, p2 = bars[i], bars[i-1], bars[i-2]
    colour = (L['c'] < L['o']) if d == 'S' else (L['c'] > L['o'])
    if 'a' in p['modes']:
        k = rej(L, p1, d, p)
        if k: return 'A_' + k
    if 'b' in p['modes'] and engulf(L, p1, d, p['engulf_tol']): return 'B_ENGULF'
    if 'c' in p['modes'] and colour:
        k = rej(p1, p2, d, p)
        if k: return 'C_' + k
    return None

def detect(bars, p=None, include_last=False, start=60):
    """bars: list of dicts t(ms UTC),o,h,l,c oldest first, with e21/e55. include_last=True lets the
    newest closed bar be L (live mode; entry then = next bar open, estimated by close(L))."""
    p = dict(P, **(p or {})); out = []; last = {'S': -99, 'B': -99}
    end = len(bars) if include_last else len(bars) - 1
    for i in range(max(start, p['leg_lookback']), end):
        L = bars[i]; d = 'B' if L['e21'] > L['e55'] else 'S'
        k = classify(bars, i, d, p)
        if not k: continue
        w = bars[i - p['leg_lookback'] + 1:i + 1]
        dist = (max(b['h'] for b in w) - L['c']) if d == 'S' else (L['c'] - min(b['l'] for b in w))
        if dist > p['max_ext']: continue
        if i - last[d] < p['dedupe']: continue
        last[d] = i
        nxt = bars[i+1] if i + 1 < len(bars) else None
        entry = round(nxt['o'] if nxt else L['c'], 2); sg = 1 if d == 'B' else -1
        out.append(dict(i=i, t=L['t'], dir=d, kind=k, entry=entry, entry_est=nxt is None,
                        sl=round(entry - sg*p['sl'], 2), tp=round(entry + sg*p['tp'], 2), leg_dist=round(dist, 2)))
    return out

# ---- time helpers ----
def _nth_sunday(y, m, n):
    d = datetime(y, m, 1); d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)

def us_dst(utc_dt):
    """US DST: 2nd Sun Mar 2:00 local -> 1st Sun Nov 2:00 local (approx 7:00/6:00 UTC ET)."""
    y = utc_dt.year; s = _nth_sunday(y, 3, 2) + timedelta(hours=7); e = _nth_sunday(y, 11, 1) + timedelta(hours=6)
    return s <= utc_dt.replace(tzinfo=None) < e

def to_ict(t_ms): return datetime.fromtimestamp(t_ms/1000, timezone.utc).replace(tzinfo=None) + timedelta(hours=7)
def to_srv(t_ms):
    u = datetime.fromtimestamp(t_ms/1000, timezone.utc).replace(tzinfo=None)
    return u + timedelta(hours=3 if us_dst(u) else 2)

PAT_TH = {'A_PIN': 'A พินบาร์', 'A_STAR': 'A เนื้อเล็กในไส้', 'B_ENGULF': 'B กลืนกิน', 'C_PIN': 'C พิน+ยืนยันสี', 'C_STAR': 'C สตาร์+ยืนยันสี'}

def message(s):
    d = 'ขาย (SELL)' if s['dir'] == 'S' else 'ซื้อ (BUY)'
    est = '≈' if s.get('entry_est') else ''
    return (f"🔷 SIW {d} {s['kind']} ({PAT_TH.get(s['kind'], '')})\n"
            f"แท่งคอนเฟิร์ม: {to_ict(s['t']):%d/%m %H:%M} ไทย | {to_srv(s['t']):%H:%M} MT5\n"
            f"เข้า: {est}{s['entry']:.2f}  SL {s['sl']:.2f}  TP {s['tp']:.2f}\n"
            f"ปิดตามเวลา: {to_ict(s['t'] + 900_000):%H:%M} ไทย | {to_srv(s['t'] + 900_000):%H:%M} MT5 (10 นาทีหลังเข้า, ปิดแท่งที่ 2)\n"
            f"Exit v4: SL $10 / TP $20 / 10 นาที อะไรถึงก่อน | Dukascopy BID (~+$1.5 vs IC) | แจ้งเตือนเท่านั้น")

# ---- live status + outcomes (UI) ----
def outcome_v4(bars, s, p=None):
    """Exit v4: entry = open of L+1; over bars L+1, L+2: SL (checked first) then TP; else close of L+2.
    Gap through a level fills at bar open. None if L+2 hasn't closed yet. Mirrors research siw.outcome_v4."""
    p = dict(P, **(p or {})); i = s['i']; sg = 1 if s['dir'] == 'B' else -1; n = p['exit_bars']
    if i + n >= len(bars): return None
    e = bars[i+1]['o']; stop = e - sg*p['sl']; tp = e + sg*p['tp']
    for j in range(i+1, i+1+n):
        b = bars[j]
        if (b['l'] <= stop) if sg > 0 else (b['h'] >= stop):
            x = b['o'] if (j > i+1 and ((b['o'] < stop) if sg > 0 else (b['o'] > stop))) else stop
            return dict(pnl=round(sg*(x - e) - p['cost'], 2), how='SL')
        if (b['h'] >= tp) if sg > 0 else (b['l'] <= tp):
            x = b['o'] if (j > i+1 and ((b['o'] > tp) if sg > 0 else (b['o'] < tp))) else tp
            return dict(pnl=round(sg*(x - e) - p['cost'], 2), how='TP')
    return dict(pnl=round(sg*(bars[i+n]['c'] - e) - p['cost'], 2), how='10m')

def _why_wait(bars, p):
    i = len(bars) - 1; L = bars[i]; d = 'B' if L['e21'] > L['e55'] else 'S'
    k = classify(bars, i, d, p); w = bars[i - p['leg_lookback'] + 1:i + 1]
    dist = (max(b['h'] for b in w) - L['c']) if d == 'S' else (L['c'] - min(b['l'] for b in w))
    side = 'ขาย' if d == 'S' else 'ซื้อ'
    if not k: return [f"เทรนด์{'ขาลง' if d == 'S' else 'ขาขึ้น'} → รอเฉพาะสัญญาณ{side}",
                      f"แท่งล่าสุดยังไม่มีรูปแบบกลับตัว (พินบาร์ / สตาร์ / กลืนกิน) ฝั่ง{side}"]
    if dist > p['max_ext']: return [f"มีรูปแบบ {k} แต่ราคาวิ่งไกลจากจุดสุดขา ${dist:.2f} (> ${p['max_ext']:.0f}) — ไม่ไล่ราคา"]
    return [f"มีรูปแบบ {k} แต่ติดกฎกันสัญญาณซ้ำ ({p['dedupe']} แท่ง)"]

def status(bars, sigs, forming=None, now_ms=None, p=None):
    """bars: closed bars with EMAs. sigs: detect(bars, include_last=True). forming: current unclosed bar dict or None."""
    p = dict(P, **(p or {})); L = bars[-1]; newest = L['t']
    d = 'B' if L['e21'] > L['e55'] else 'S'; slope = L['e55'] - bars[-4]['e55']
    base = dict(trend=d, trend_th='ขาขึ้น' if d == 'B' else 'ขาลง', e21=round(L['e21'], 2), e55=round(L['e55'], 2),
                e55_slope=round(slope, 3), gap=round(L['e21'] - L['e55'], 2))
    if now_ms and now_ms - newest > 40 * 60_000:
        return dict(base, state='CLOSED', label='ตลาดปิด / ไม่มีข้อมูลใหม่', reasons=[f"แท่งล่าสุด {to_ict(newest):%d/%m %H:%M} ไทย"])
    if sigs and newest - sigs[-1]['t'] <= 2 * 300_000:
        s = sigs[-1]; ent = to_ict(s['t'] + 300_000)
        return dict(base, state='BUY' if s['dir'] == 'B' else 'SELL', label='ซื้อได้' if s['dir'] == 'B' else 'ขายได้',
                    kind=s['kind'], kind_th=PAT_TH.get(s['kind'], ''), entry=s['entry'], sl=s['sl'], tp=s['tp'],
                    confirm_ict=f"{to_ict(s['t']):%H:%M}", entry_ict=f"{ent:%H:%M}",
                    exit_ict=f"{ent + timedelta(minutes=10):%H:%M}", entry_srv=f"{to_srv(s['t'] + 300_000):%H:%M}",
                    exit_srv=f"{to_srv(s['t'] + 900_000):%H:%M}", confirm_srv=f"{to_srv(s['t']):%H:%M}",
                    bars_ago=(newest - s['t']) // 300_000,
                    reasons=[f"สัญญาณ {s['kind']} ({PAT_TH.get(s['kind'], '')}) แท่งคอนเฟิร์ม {to_ict(s['t']):%H:%M} ไทย",
                             f"Exit v4: SL $10 / TP $20 / ปิดตามเวลา {ent + timedelta(minutes=10):%H:%M} ไทย ({to_srv(s['t'] + 900_000):%H:%M} MT5) อะไรถึงก่อน"])
    if forming:
        fb = add_emas([dict(b) for b in bars] + [dict(forming)])
        fs = detect(fb, p, include_last=True, start=len(fb) - 1)
        if fs and fs[-1]['i'] == len(fb) - 1:
            f = fs[-1]
            return dict(base, state='PREP', label='เตรียมตัว', kind=f['kind'], dir=f['dir'],
                        reasons=[f"แท่งที่ยังไม่ปิดกำลังเป็นรูปแบบ {f['kind']} ฝั่ง{'ซื้อ' if f['dir'] == 'B' else 'ขาย'} — รอแท่งปิด {to_ict(forming['t'] + 300_000):%H:%M}"])
    return dict(base, state='WAIT', label='รอ', reasons=_why_wait(bars, p))
