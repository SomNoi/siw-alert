"""Fetch -> compute -> write docs/data + state -> push ntfy for new signals. Watch-only."""
import json, os, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from siw import add_emas, detect, message, to_ict, to_srv, P
from fetch import fetch, closed_only
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, 'state', 'state.json'); OUT = os.path.join(ROOT, 'docs', 'data', 'signals.json')

def load_state():
    try: return json.load(open(STATE))
    except Exception: return {'last': {'S': 0, 'B': 0}, 'alerted': []}

def notify(topic, text, s):
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=text.encode(), headers={
        'Title': ('SIW SELL' if s['dir'] == 'S' else 'SIW BUY') + ' XAUUSD M5',
        'Tags': 'large_blue_diamond', 'Priority': 'high'})
    urllib.request.urlopen(req, timeout=20).read()

def main():
    now = int(time.time()*1000)
    bars = add_emas(closed_only(fetch(500, now), now))
    if len(bars) < 80: print('not enough bars'); return
    sigs = detect(bars, include_last=True)
    st = load_state(); topic = os.environ.get('NTFY_TOPIC', '').strip()
    first_run = not os.path.exists(STATE)  # first run seeds state silently
    newest = bars[-1]['t']
    for s in sigs:
        s['ict'] = f"{to_ict(s['t']):%Y-%m-%d %H:%M}"; s['srv'] = f"{to_srv(s['t']):%Y-%m-%d %H:%M}"
        # alert only fresh signals (confirm bar within last 3 closed bars) not yet alerted, with 3-bar dedupe vs state
        fresh = newest - s['t'] <= 2 * 300_000
        if not fresh or s['t'] in st['alerted']: continue
        if (s['t'] - st['last'][s['dir']]) < P['dedupe'] * 300_000: continue
        st['last'][s['dir']] = s['t']; st['alerted'] = (st['alerted'] + [s['t']])[-50:]
        txt = message(s); print(txt)
        if topic and not first_run:
            try: notify(topic, txt, s)
            except Exception as e: print('ntfy error', e)
    tail = bars[-150:]
    data = dict(source='Dukascopy XAU/USD BID M5 (about +$1.5 vs IC Markets)', newest_bar_t=newest,
                newest_ict=f"{to_ict(newest):%Y-%m-%d %H:%M}", price=bars[-1]['c'], e21=round(bars[-1]['e21'], 3),
                e55=round(bars[-1]['e55'], 3), trend='BUY' if bars[-1]['e21'] > bars[-1]['e55'] else 'SELL',
                bars=[[b['t']//1000, round(b['o'],3), round(b['h'],3), round(b['l'],3), round(b['c'],3),
                       round(b['e21'],3), round(b['e55'],3)] for b in tail],
                signals=[{k: v for k, v in s.items() if k != 'i'} for s in sigs][-40:], params=P)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, 'w'), ensure_ascii=False, separators=(',', ':'))
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, 'w'), indent=1)

if __name__ == '__main__': main()
