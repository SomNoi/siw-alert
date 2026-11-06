"""SIW v6 XAUUSD M5 detector and Exit v7 outcomes. Watch-only; never places orders."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN

P = dict(
    ema_fast=21,
    ema_slow=55,
    pin_wick_min=0.50,
    pin_body_max=0.40,
    fresh_ks=(10, 5),
    sl_cap=8.0,
    tp=20.0,
    exit_bars=2,  # L+1 and L+2; time exit at close of L+2
    cost=0.28,    # per 0.01 lot, used only for offline outcome checks
)


def _round2(value):
    """Round from a decimal string to avoid binary-float one-cent display drift."""
    return float(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN))


def ema(xs, span):
    a = 2.0 / (span + 1)
    out, value = [], None
    for x in xs:
        value = x if value is None else a * x + (1 - a) * value
        out.append(value)
    return out


def add_emas(bars):
    closes = [b['c'] for b in bars]
    fast, slow = ema(closes, P['ema_fast']), ema(closes, P['ema_slow'])
    for b, e21, e55 in zip(bars, fast, slow):
        b['e21'], b['e55'] = e21, e55
    return bars


def _shape(b):
    rng = max(b['h'] - b['l'], 1e-9)
    top, bottom = max(b['o'], b['c']), min(b['o'], b['c'])
    return (abs(b['c'] - b['o']) / rng,
            (b['h'] - top) / rng,
            (bottom - b['l']) / rng)


def _is_red(b):
    return b['c'] < b['o']


def _is_green(b):
    return b['c'] > b['o']


def is_pin(bar, direction, p=None):
    p = dict(P, **(p or {}))
    body, upper_wick, lower_wick = _shape(bar)
    wick = lower_wick if direction == 'B' else upper_wick
    epsilon = 1e-12
    return wick + epsilon >= p['pin_wick_min'] and body <= p['pin_body_max'] + epsilon


def is_engulf(bar, previous, direction):
    """Strict body engulf with zero tolerance; L-1 and L must be opposite colours."""
    if direction == 'B':
        return (_is_green(bar) and _is_red(previous)
                and bar['o'] <= previous['c']
                and bar['c'] >= previous['o'])
    return (_is_red(bar) and _is_green(previous)
            and bar['o'] >= previous['c']
            and bar['c'] <= previous['o'])


def classify(bars, i, direction, p=None):
    """Return PIN or ENG if L-1 is the required pullback and L is a v6 signal."""
    if i < 1:
        return None
    p = dict(P, **(p or {}))
    previous, signal = bars[i - 1], bars[i]
    pullback = _is_red(previous) if direction == 'B' else _is_green(previous)
    if not pullback:
        return None
    # When both definitions happen to fit, v6's reference implementation prefers PIN.
    if is_pin(signal, direction, p):
        return 'PIN'
    if is_engulf(signal, previous, direction):
        return 'ENG'
    return None


def fresh_tag(bars, i, direction, p=None):
    """Return K10/K5 when set L-1..L makes a fresh extreme vs the preceding K bars."""
    p = dict(P, **(p or {}))
    current = bars[i - 1:i + 1]
    if len(current) != 2:
        return None
    for k in p['fresh_ks']:
        start, stop = i - 1 - k, i - 1
        reference = bars[start:stop]
        if start < 0 or len(reference) != k:
            continue
        if direction == 'B':
            fresh = min(b['l'] for b in current) <= min(b['l'] for b in reference)
        else:
            fresh = max(b['h'] for b in current) >= max(b['h'] for b in reference)
        if fresh:
            return f'K{k}'
    return None


def structural_sl(bars, i, direction):
    pair = bars[i - 1:i + 1]
    if direction == 'B':
        return min(b['l'] for b in pair)
    return max(b['h'] for b in pair)


def _skip_reason(entry, stop, direction, p):
    sg = 1 if direction == 'B' else -1
    distance = sg * (entry - stop)
    if distance <= 0.01:
        return 'entry gapped through structural SL' if distance < 0 else 'SL distance <= $0.01'
    if distance > p['sl_cap']:
        return f"SL distance > ${p['sl_cap']:.0f}"
    return None


def dedupe_signals(signals):
    """For same-side signals on consecutive bars, keep only the later one."""
    out = []
    for j, signal in enumerate(signals):
        nxt = signals[j + 1] if j + 1 < len(signals) else None
        if (nxt and nxt['i'] == signal['i'] + 1 and nxt['dir'] == signal['dir']):
            continue
        kept = dict(signal)
        prev = signals[j - 1] if j else None
        if prev and prev['i'] == signal['i'] - 1 and prev['dir'] == signal['dir']:
            kept['replaces_t'] = prev['t']
        out.append(kept)
    return out


def detect(bars, p=None, include_last=False, start=60, entry_open=None):
    """Detect v6 signals on oldest-first bars. `entry_open` may be the forming L+1 open."""
    p = dict(P, **(p or {}))
    end = len(bars) if include_last else len(bars) - 1
    raw = []
    for i in range(max(start, 11), end):
        signal = bars[i]
        if signal['e21'] > signal['e55']:
            direction = 'B'
        elif signal['e21'] < signal['e55']:
            direction = 'S'
        else:
            continue
        kind = classify(bars, i, direction, p)
        if not kind:
            continue
        k_tag = fresh_tag(bars, i, direction, p)
        if not k_tag:
            continue

        next_bar = bars[i + 1] if i + 1 < len(bars) else None
        if next_bar:
            entry, entry_est = next_bar['o'], False
        elif i == len(bars) - 1 and entry_open is not None:
            entry, entry_est = float(entry_open), False
        else:
            entry, entry_est = signal['c'], True

        stop = structural_sl(bars, i, direction)
        sg = 1 if direction == 'B' else -1
        distance = sg * (entry - stop)
        reason = _skip_reason(entry, stop, direction, p)
        lookback = bars[max(0, i - 11):i + 1]
        leg_dist = (max(b['h'] for b in lookback) - signal['c'] if direction == 'S'
                    else signal['c'] - min(b['l'] for b in lookback))
        raw.append(dict(
            i=i, t=signal['t'], dir=direction, kind=kind, k_tag=k_tag,
            entry=_round2(entry), entry_est=entry_est,
            sl=stop, sl_dist=_round2(distance), tp=_round2(entry + sg * p['tp']),
            skip=reason is not None, skip_reason=reason,
            leg_dist=_round2(leg_dist),
        ))
    return dedupe_signals(raw)


# ---- Time helpers: ICT UTC+7 and MT5 server time using US DST ----
def _nth_sunday(year, month, n):
    d = datetime(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def us_dst(utc_dt):
    """US DST boundaries, expressed as 07:00/06:00 UTC on the transition Sundays."""
    year = utc_dt.year
    start = _nth_sunday(year, 3, 2) + timedelta(hours=7)
    end = _nth_sunday(year, 11, 1) + timedelta(hours=6)
    value = utc_dt.replace(tzinfo=None)
    return start <= value < end


def to_ict(t_ms):
    return datetime.fromtimestamp(t_ms / 1000, timezone.utc).replace(tzinfo=None) + timedelta(hours=7)


def to_srv(t_ms):
    utc = datetime.fromtimestamp(t_ms / 1000, timezone.utc).replace(tzinfo=None)
    return utc + timedelta(hours=3 if us_dst(utc) else 2)


PAT_TH = {'PIN': 'พินบาร์', 'ENG': 'แท่งกลืนกิน'}


def message(signal):
    side = 'ขาย (SELL)' if signal['dir'] == 'S' else 'ซื้อ (BUY)'
    update = 'อัปเดต · แทนสัญญาณแท่งก่อนหน้า\n' if signal.get('replaces_t') else ''
    prefix = '≈' if signal.get('entry_est') else ''
    header = f"🔷 SIW {side} {signal['kind']} {signal['k_tag']} ({PAT_TH[signal['kind']]})"
    times = (f"แท่งคอนเฟิร์ม: {to_ict(signal['t']):%d/%m %H:%M} ไทย | "
             f"{to_srv(signal['t']):%H:%M} MT5")
    if signal.get('skip'):
        return (f"{header} — ข้ามสัญญาณ\n{update}{times}\n"
                f"เหตุผล: {signal.get('skip_reason') or 'ไม่ผ่านกฎ Exit v7'}\n"
                "ไม่มีรายการเข้าเทรด · ระบบแจ้งเตือนเท่านั้น")
    exit_ict, exit_srv = to_ict(signal['t'] + 900_000), to_srv(signal['t'] + 900_000)
    return (f"{header}\n{update}{times}\n"
            f"เข้า: {prefix}{_round2(signal['entry']):.2f}  SL {_round2(signal['sl']):.2f}  TP {_round2(signal['tp']):.2f}\n"
            f"ปิดตามเวลา: {exit_ict:%H:%M} ไทย | {exit_srv:%H:%M} MT5 "
            "(ปิดที่แท่ง L+2; 10 นาทีหลังเข้า)\n"
            "Exit v7: SL โครงสร้าง; หากระยะ > $8 หรือราคา gap ผ่าน SL ให้ข้าม; TP $20 "
            "| Dukascopy BID (~+$1.5 เทียบ IC Markets) | แจ้งเตือนเท่านั้น")


def outcome_v7(bars, signal, p=None):
    """Historical outcome for L+1/L+2. Stop is checked before TP; gaps fill at bar open."""
    p = dict(P, **(p or {}))
    if signal.get('skip'):
        return dict(skip=True, reason=signal.get('skip_reason'))
    i, direction = signal['i'], signal['dir']
    if i + 2 >= len(bars):
        return None
    entry = bars[i + 1]['o']
    stop = structural_sl(bars, i, direction)
    reason = _skip_reason(entry, stop, direction, p)
    if reason:
        return dict(skip=True, reason=reason)
    sg = 1 if direction == 'B' else -1
    tp = entry + sg * p['tp']
    for j in range(i + 1, i + 3):
        bar = bars[j]
        stop_hit = bar['l'] <= stop if sg > 0 else bar['h'] >= stop
        if stop_hit:
            price = stop
            if j > i + 1 and (bar['o'] < stop if sg > 0 else bar['o'] > stop):
                price = bar['o']
            return dict(pnl=round(sg * (price - entry) - p['cost'], 2), how='SL')
        tp_hit = bar['h'] >= tp if sg > 0 else bar['l'] <= tp
        if tp_hit:
            price = tp
            if j > i + 1 and (bar['o'] > tp if sg > 0 else bar['o'] < tp):
                price = bar['o']
            return dict(pnl=round(sg * (price - entry) - p['cost'], 2), how='TP')
    return dict(pnl=round(sg * (bars[i + 2]['c'] - entry) - p['cost'], 2), how='TIME')


def _why_wait(bars, p):
    i = len(bars) - 1
    last = bars[i]
    if last['e21'] == last['e55']:
        return ['EMA21 เท่ากับ EMA55 — ยังไม่มีทิศทางตามกฎ']
    direction = 'B' if last['e21'] > last['e55'] else 'S'
    side = 'ซื้อ' if direction == 'B' else 'ขาย'
    if i < 1 or not (_is_red(bars[i - 1]) if direction == 'B' else _is_green(bars[i - 1])):
        return [f'แท่งก่อนหน้าล่าสุดยังไม่ใช่ pullback ฝั่ง{side}']
    kind = classify(bars, i, direction, p)
    if not kind:
        return [f'แท่งปิดล่าสุดยังไม่เข้า PIN หรือ ENG ฝั่ง{side}']
    tag = fresh_tag(bars, i, direction, p)
    if not tag:
        return ['ชุดแท่ง L-1..L ยังไม่ทำ fresh extreme อย่างน้อย K5']
    return [f'พบ {kind} {tag} แต่สัญญาณอยู่นอกช่วงแจ้งเตือนล่าสุด']


def status(bars, signals, forming=None, now_ms=None, p=None):
    p = dict(P, **(p or {}))
    if not bars:
        return dict(state='STALE', label='ไม่มีข้อมูล', reasons=['ยังไม่มีแท่งราคา'])
    last = bars[-1]
    direction = 'B' if last['e21'] > last['e55'] else ('S' if last['e21'] < last['e55'] else None)
    trend_th = 'ขาขึ้น' if direction == 'B' else ('ขาลง' if direction == 'S' else 'ไม่ชัด')
    slope = last['e55'] - bars[-4]['e55'] if len(bars) >= 4 else 0.0
    base = dict(trend=direction, trend_th=trend_th, e21=round(last['e21'], 2),
                e55=round(last['e55'], 2), e55_slope=round(slope, 3),
                gap=round(last['e21'] - last['e55'], 2))
    age = now_ms - (last['t'] + 300_000) if now_ms is not None else 0
    if now_ms is not None and age > 40 * 60_000:
        return dict(base, state='CLOSED', label='ตลาดปิด / ไม่มีข้อมูลใหม่',
                    reasons=[f"แท่งล่าสุด {to_ict(last['t']):%d/%m %H:%M} ไทย"])
    if now_ms is not None and age > 15 * 60_000:
        return dict(base, state='STALE', label='ข้อมูลล่าช้า',
                    reasons=[f"แท่งล่าสุด {to_ict(last['t']):%d/%m %H:%M} ไทย — งดแจ้งสัญญาณจากข้อมูลเก่า"])

    if signals:
        signal = signals[-1]
        is_recent = last['t'] - signal['t'] <= 2 * 300_000
        is_fresh = now_ms is None or now_ms - (signal['t'] + 300_000) <= 15 * 60_000
        if is_recent and is_fresh:
            if signal.get('skip'):
                return dict(base, state='SKIP', label='ข้ามสัญญาณ', kind=signal['kind'],
                            k_tag=signal['k_tag'], reasons=[signal.get('skip_reason') or 'ไม่ผ่านกฎ Exit v7'])
            entry_time = to_ict(signal['t'] + 300_000)
            exit_time = to_ict(signal['t'] + 900_000)
            return dict(base,
                state='BUY' if signal['dir'] == 'B' else 'SELL',
                label='สัญญาณซื้อ' if signal['dir'] == 'B' else 'สัญญาณขาย',
                kind=signal['kind'], kind_th=PAT_TH[signal['kind']], k_tag=signal['k_tag'],
                entry=signal['entry'], entry_est=signal.get('entry_est', False),
                sl=round(signal['sl'], 2), sl_dist=signal['sl_dist'], tp=signal['tp'],
                confirm_ict=f"{to_ict(signal['t']):%H:%M}",
                entry_ict=f"{entry_time:%H:%M}", exit_ict=f"{exit_time:%H:%M}",
                entry_srv=f"{to_srv(signal['t'] + 300_000):%H:%M}",
                exit_srv=f"{to_srv(signal['t'] + 900_000):%H:%M}",
                confirm_srv=f"{to_srv(signal['t']):%H:%M}",
                bars_ago=(last['t'] - signal['t']) // 300_000,
                reasons=[f"{signal['kind']} {signal['k_tag']} · แท่งคอนเฟิร์ม {to_ict(signal['t']):%H:%M} ไทย",
                         f"Exit v7: SL โครงสร้าง ระยะ ${signal['sl_dist']:.2f} · TP $20 · ปิดที่แท่ง L+2"])

    if forming and forming['t'] == last['t'] + 300_000:
        preview = add_emas([dict(b) for b in bars] + [dict(forming)])
        # Trend is based on closed M5 bars; the forming close must not alter its direction.
        preview[-1]['e21'], preview[-1]['e55'] = last['e21'], last['e55']
        candidates = detect(preview, p, include_last=True, start=len(preview) - 1)
        if candidates and candidates[-1]['i'] == len(preview) - 1:
            candidate = candidates[-1]
            return dict(base, state='PREP', label='กำลังก่อตัว · ยังไม่ยืนยัน', kind=candidate['kind'],
                        k_tag=candidate['k_tag'], dir=candidate['dir'],
                        reasons=[f"แท่งยังไม่ปิด — รอยืนยันที่ {to_ict(forming['t'] + 300_000):%H:%M} ไทย"])
    return dict(base, state='WAIT', label='รอ', reasons=_why_wait(bars, p))
