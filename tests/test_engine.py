import csv, os, sys, unittest
from datetime import datetime
HERE = os.path.dirname(__file__); sys.path.insert(0, os.path.join(HERE, '..', 'engine'))
from siw import add_emas, detect, us_dst, to_srv, message, P
from fetch import parse
FIX = os.path.join(HERE, 'fixtures', 'duka_slice.csv')
FULL = '/workspace/fx-research/siw_v2_20261104/duka_xau_m5_bid.csv'
REF = '/workspace/fx-research/siw_v2_20261104'

def load(path):
    with open(path) as f:
        return add_emas([dict(t=int(r['t']), o=float(r['o']), h=float(r['h']), l=float(r['l']), c=float(r['c'])) for r in csv.DictReader(f)])

def ref_signals(path, dedupe):
    import importlib.util as u; sp = u.spec_from_file_location('siw_ref', os.path.join(REF, 'siw.py')); ref = u.module_from_spec(sp); sp.loader.exec_module(ref)
    df = ref.load(path); s = ref.detect(df, dict(dedupe=dedupe))
    return [(int(r.i), r.dir, r.kind, round(float(r.entry), 2)) for _, r in s.iterrows()]

class Parity(unittest.TestCase):
    def check(self, path):
        bars = load(path)
        for dd in (1, 3):
            mine = detect(bars, dict(dedupe=dd)); ref = ref_signals(path, dd)
            self.assertTrue(mine); self.assertEqual([(s['i'], s['dir'], s['kind']) for s in mine], [r[:3] for r in ref])
            for s, r in zip(mine, ref): self.assertLessEqual(abs(s['entry'] - r[3]), 0.0101)  # rounding mode only
    @unittest.skipUnless(os.path.exists(os.path.join(REF, 'siw.py')), 'reference siw.py not present')
    def test_parity_fixture(self): self.check(FIX)
    @unittest.skipUnless(os.path.exists(FULL), 'full csv not present')
    def test_parity_full(self): self.check(FULL)

    def test_parity_frozen(self):
        """CI-safe: compare against siw.py output frozen in fixtures/ref_siw_py_signals.json"""
        import json; ref = json.load(open(os.path.join(HERE, 'fixtures', 'ref_siw_py_signals.json'))); bars = load(FIX)
        for dd in (1, 3):
            mine = detect(bars, dict(dedupe=dd)); r = ref[str(dd)]
            self.assertEqual([[s['i'], s['dir'], s['kind']] for s in mine], [x[:3] for x in r])
            for s, x in zip(mine, r): self.assertLessEqual(abs(s['entry'] - x[3]), 0.0101)

class Units(unittest.TestCase):
    def test_golden_fixture(self):
        s = detect(load(FIX)); self.assertGreater(len(s), 5)
        for x in s:
            sg = 1 if x['dir'] == 'B' else -1
            self.assertAlmostEqual(x['tp'] - x['entry'], sg*20, 2); self.assertAlmostEqual(x['entry'] - x['sl'], sg*10, 2)
            self.assertLessEqual(x['leg_dist'], 10)
    def test_dedupe(self):
        s = detect(load(FIX), dict(dedupe=3)); last = {}
        for x in s:
            if x['dir'] in last: self.assertGreaterEqual(x['i'] - last[x['dir']], 3)
            last[x['dir']] = x['i']
    def test_dst(self):
        self.assertTrue(us_dst(datetime(2026, 10, 31, 12))); self.assertFalse(us_dst(datetime(2026, 11, 2, 12)))
        self.assertFalse(us_dst(datetime(2027, 3, 13, 12))); self.assertTrue(us_dst(datetime(2027, 3, 15, 12)))
        t = int(datetime(2026, 11, 4, 3, 0).timestamp()*1000) if False else 1793761200000  # 2026-11-04 03:00 UTC
        self.assertEqual(f"{to_srv(t):%H:%M}", '05:00')
    def test_parse_jsonp(self):
        b = parse('_cb([[2000,1,2,0.5,1.5,1],[1000,1,2,0.5,1.5,1]]);')
        self.assertEqual([x['t'] for x in b], [1000, 2000])
    def test_message(self):
        m = message(dict(t=1793761200000, dir='S', kind='B_ENGULF', entry=4000.0, sl=4005.0, tp=3980.0))
        self.assertIn('🔷 SIW ขาย', m); self.assertIn('10:00 ไทย', m); self.assertIn('05:00 MT5', m)


class Status(unittest.TestCase):
    def test_states(self):
        from siw import status
        bars = load(FIX); sigs = detect(bars, include_last=True)
        s = sigs[-1]; cut = bars[:s['i']+1]
        st = status(cut, detect(cut, include_last=True), None, cut[-1]['t'] + 400_000)
        self.assertEqual(st['state'], 'BUY' if s['dir'] == 'B' else 'SELL'); self.assertIn(st['label'], ('ซื้อได้', 'ขายได้'))
        st = status(bars, sigs, None, bars[-1]['t'] + 10**9); self.assertEqual(st['state'], 'CLOSED')
        w = status(bars, [], None, bars[-1]['t'] + 400_000); self.assertEqual(w['state'], 'WAIT'); self.assertTrue(w['reasons'])

class ExitV4(unittest.TestCase):
    def mk(self, rows):
        return [dict(t=i*300_000, o=o, h=h, l=l, c=c) for i, (o, h, l, c) in enumerate(rows)]
    def test_time_exit(self):
        from siw import outcome_v4
        b = self.mk([(100,101,99,100), (100,103,98,102), (102,104,101,103), (103,140,60,103)])
        o = outcome_v4(b, dict(i=0, dir='B')); self.assertEqual(o['how'], '10m'); self.assertAlmostEqual(o['pnl'], 3 - 0.28, 2)
    def test_sl_first(self):
        from siw import outcome_v4
        b = self.mk([(100,101,99,100), (100,121,89,100), (100,100,100,100)])
        o = outcome_v4(b, dict(i=0, dir='B')); self.assertEqual(o['how'], 'SL'); self.assertAlmostEqual(o['pnl'], -10.28, 2)
    def test_tp_sell(self):
        from siw import outcome_v4
        b = self.mk([(100,101,99,100), (100,101,95,96), (96,97,79,80)])
        o = outcome_v4(b, dict(i=0, dir='S')); self.assertEqual(o['how'], 'TP'); self.assertAlmostEqual(o['pnl'], 19.72, 2)
    def test_pending(self):
        from siw import outcome_v4
        self.assertIsNone(outcome_v4(self.mk([(1,1,1,1)]*2), dict(i=0, dir='B')))
    def test_parity_research(self):
        """matches research siw.outcome_v4 on fixture signals"""
        try: import pandas as pd
        except ImportError: self.skipTest('pandas')
        R = '/workspace/fx-research/siw_v2_20261104'
        if not os.path.exists(R): self.skipTest('no research dir')
        import importlib.util as U; sp = U.spec_from_file_location('siw_research', R + '/siw.py'); rs = U.module_from_spec(sp); sp.loader.exec_module(rs)
        from siw import outcome_v4
        bars = load(FIX); df = pd.DataFrame(bars)
        for s in detect(bars)[:60]:
            o = outcome_v4(bars, s)
            if o: self.assertAlmostEqual(o['pnl'], round(rs.outcome_v4(df, s['i']+1, s['dir'])[1], 2), 2)

if __name__ == '__main__': unittest.main()
