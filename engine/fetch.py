import json, re, time, urllib.request
URL = ("https://freeserv.dukascopy.com/2.0/?path=chart/json3&instrument=XAU/USD&offer_side=B&interval=5MIN"
       "&splits=true&stocks=true&limit={limit}&time_direction=P&timestamp={ts}&jsonp=_cb")
def parse(text):
    m = re.search(r'_cb\((.*)\)\s*;?\s*$', text.strip(), re.S)
    rows = json.loads(m.group(1) if m else text)
    bars = [dict(t=int(r[0]), o=float(r[1]), h=float(r[2]), l=float(r[3]), c=float(r[4]), v=float(r[5])) for r in rows]
    bars.sort(key=lambda b: b['t'])
    return bars
def fetch(limit=500, now_ms=None):
    now_ms = now_ms or int(time.time()*1000)
    req = urllib.request.Request(URL.format(limit=limit, ts=now_ms), headers={
        'Referer': 'https://freeserv.dukascopy.com/', 'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return parse(r.read().decode())
def closed_only(bars, now_ms=None):
    now_ms = now_ms or int(time.time()*1000)
    return [b for b in bars if b['t'] + 300_000 <= now_ms]
