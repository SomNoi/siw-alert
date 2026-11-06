"""Dukascopy XAU/USD BID M5 fetcher. Stale data is returned only for display; run.py suppresses alerts."""
import json
import re
import time
import urllib.request

URL = ("https://freeserv.dukascopy.com/2.0/?path=chart/json3&instrument=XAU/USD&offer_side=B&interval=5MIN"
       "&splits=true&stocks=true&limit={limit}&time_direction=P&timestamp={ts}&jsonp=_cb")
BAR_MS = 300_000
STALE_AFTER_MS = 15 * 60_000


def parse(text):
    match = re.search(r'_cb\((.*)\)\s*;?\s*$', text.strip(), re.S)
    rows = json.loads(match.group(1) if match else text)
    bars = [dict(t=int(row[0]), o=float(row[1]), h=float(row[2]),
                 l=float(row[3]), c=float(row[4]), v=float(row[5])) for row in rows]
    bars.sort(key=lambda bar: bar['t'])
    return bars


def _download(limit, now_ms):
    req = urllib.request.Request(URL.format(limit=limit, ts=now_ms), headers={
        'Referer': 'https://freeserv.dukascopy.com/',
        'User-Agent': 'Mozilla/5.0',
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        return parse(response.read().decode())


def closed_only(bars, now_ms=None):
    now_ms = now_ms or int(time.time() * 1000)
    return [bar for bar in bars if bar['t'] + BAR_MS <= now_ms]


def _is_stale(bars, now_ms):
    closed = closed_only(bars, now_ms)
    return not closed or now_ms - (closed[-1]['t'] + BAR_MS) > STALE_AFTER_MS


def fetch(limit=500, now_ms=None):
    """Fetch twice if the feed errors or is stale. Return stale bars for display, never for alerts."""
    now_ms = now_ms or int(time.time() * 1000)
    last_bars, errors = None, []
    for attempt in range(2):
        try:
            bars = _download(limit, now_ms)
            if bars:
                last_bars = bars
                if not _is_stale(bars, now_ms):
                    return bars
                errors.append('Dukascopy newest closed bar is stale')
            else:
                errors.append('Dukascopy returned no bars')
        except Exception as error:
            errors.append(f'{type(error).__name__}: {error}')
        if attempt == 0:
            time.sleep(3)
    if last_bars:
        return last_bars
    raise RuntimeError('Dukascopy fetch failed after one retry: ' + '; '.join(errors))
