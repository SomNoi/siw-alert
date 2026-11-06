"""Fetch -> compute -> write dashboard/state -> notify new SIW v6 signals. Watch-only."""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from siw import add_emas, detect, message, status, to_ict, to_srv
from fetch import fetch, closed_only

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, 'state', 'state.json')
OUT = os.path.join(ROOT, 'docs', 'data', 'signals.json')
BAR_MS = 5 * 60_000
MAX_ALERT_AGE_MS = 15 * 60_000


def load_state():
    try:
        state = json.load(open(STATE))
    except (OSError, ValueError):
        state = {}
    alerted = state.get('alerted', [])
    try:
        alerted = [int(t) for t in alerted]
    except (TypeError, ValueError):
        alerted = []
    return {'alerted': alerted[-200:]}


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, 'w') as f:
        json.dump(state, f, indent=1)


def notify(topic, text, signal):
    skipped = bool(signal.get('skip'))
    title = ('SIW SKIP' if skipped else 'SIW UPDATE' if signal.get('replaces_t') else
             'SIW SELL' if signal['dir'] == 'S' else 'SIW BUY') + ' XAUUSD M5'
    req = urllib.request.Request(
        f'https://ntfy.sh/{topic}',
        data=text.encode(),
        headers={
            'Title': title,
            'Tags': 'warning' if skipped else 'large_blue_diamond',
            'Priority': 'high',
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        response.read()


def main():
    now = int(time.time() * 1000)
    all_bars = fetch(500, now)
    bars = add_emas(closed_only(all_bars, now))
    forming = None
    if all_bars and all_bars[-1]['t'] + BAR_MS > now:
        candidate = all_bars[-1]
        if bars and candidate['t'] == bars[-1]['t'] + BAR_MS:
            forming = candidate
    if len(bars) < 80:
        raise RuntimeError(f'not enough closed bars for EMA warm-up: {len(bars)}')

    entry_open = forming['o'] if forming else None
    signals = detect(bars, include_last=True, entry_open=entry_open)
    state = load_state()
    topic = os.environ.get('NTFY_TOPIC', '').strip()
    first_run = not os.path.exists(STATE)
    newest = bars[-1]['t']
    feed_fresh = now - (newest + BAR_MS) <= MAX_ALERT_AGE_MS

    for signal in signals:
        signal['ict'] = f"{to_ict(signal['t']):%Y-%m-%d %H:%M}"
        signal['srv'] = f"{to_srv(signal['t']):%Y-%m-%d %H:%M}"
        fresh = (newest - signal['t'] <= 2 * BAR_MS
                 and now - (signal['t'] + BAR_MS) <= MAX_ALERT_AGE_MS)
        if not feed_fresh or not fresh or signal['t'] in state['alerted']:
            continue
        text = message(signal)
        print(text)
        if first_run:
            # Seed without delivering a burst of historical alerts on first setup.
            state['alerted'].append(signal['t'])
        elif not topic:
            print('ntfy not sent: NTFY_TOPIC is not configured')
        else:
            try:
                notify(topic, text, signal)
            except Exception as error:
                # Do not mark failed deliveries as sent; a later run may retry while still fresh.
                print('ntfy error', error)
            else:
                state['alerted'].append(signal['t'])

    tail = bars[-150:]
    data = dict(
        rules_version='SIW v6 / Exit v7',
        generated_at=now,
        status=status(bars, signals, forming, now),
        source='Dukascopy XAU/USD BID M5 (about +$1.5 vs IC Markets)',
        newest_bar_t=newest,
        newest_ict=f"{to_ict(newest):%Y-%m-%d %H:%M}",
        price=bars[-1]['c'],
        e21=round(bars[-1]['e21'], 3),
        e55=round(bars[-1]['e55'], 3),
        trend=('BUY' if bars[-1]['e21'] > bars[-1]['e55'] else
               'SELL' if bars[-1]['e21'] < bars[-1]['e55'] else 'NEUTRAL'),
        bars=[[b['t'] // 1000, round(b['o'], 3), round(b['h'], 3), round(b['l'], 3),
               round(b['c'], 3), round(b['e21'], 3), round(b['e55'], 3)] for b in tail],
        signals=[{key: value for key, value in signal.items() if key != 'i'}
                 for signal in signals][-40:],
        params={key: list(value) if isinstance(value, tuple) else value
                for key, value in __import__('siw').P.items()},
    )
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    state['alerted'] = state['alerted'][-200:]
    save_state(state)


if __name__ == '__main__':
    main()
