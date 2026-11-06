import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, '..', 'engine'))
from siw import (P, add_emas, classify, dedupe_signals, detect, fresh_tag,
                 is_engulf, is_pin, message, outcome_v7, to_ict, to_srv, us_dst)
from fetch import parse
import fetch as fetch_module
from datetime import datetime


def rising_bars(n=100):
    bars = []
    for i in range(n):
        close = 100 + i * 0.1
        bars.append(dict(t=i * 300_000, o=close - 0.04, h=close + 0.12,
                         l=close - 0.12, c=close))
    return add_emas(bars)


def buy_pin_bars(n=100, i=80):
    bars = rising_bars(n)
    previous = bars[i - 1]
    previous.update(o=108.1, h=108.2, l=106.5, c=107.4)  # red pullback
    signal = bars[i]
    signal.update(o=107.2, h=107.6, l=104.9, c=107.3)    # red PIN is permitted
    return add_emas(bars)


def raw_bars(rows):
    return [dict(t=i * 300_000, o=o, h=h, l=l, c=c)
            for i, (o, h, l, c) in enumerate(rows)]


class V6Rules(unittest.TestCase):
    def test_pin_body_cap_is_40_percent_and_any_colour(self):
        red_pin = dict(o=11.0, h=11.2, l=9.2, c=10.2)
        self.assertTrue(is_pin(red_pin, 'B'))
        self.assertTrue(is_pin(red_pin, 'S') is False)
        body, _, _ = (abs(red_pin['c'] - red_pin['o']) / (red_pin['h'] - red_pin['l']), 0, 0)
        self.assertAlmostEqual(body, 0.4, places=5)

    def test_engulf_has_zero_tolerance(self):
        previous = dict(o=110.0, h=110.2, l=108.8, c=109.0)
        exact = dict(o=109.0, h=110.1, l=108.8, c=110.0)
        off_by_four_cents = dict(o=109.04, h=110.1, l=108.8, c=110.0)
        self.assertTrue(is_engulf(exact, previous, 'B'))
        self.assertFalse(is_engulf(off_by_four_cents, previous, 'B'))
        self.assertIsNone(classify([previous, off_by_four_cents], 1, 'B'))

    def test_previous_bar_must_be_opposite_colour_pullback(self):
        bars = [dict(o=100, h=101, l=99, c=100),
                dict(o=100, h=101, l=99, c=100)]
        self.assertIsNone(classify(bars, 1, 'B'))  # doji is not a red pullback

    def test_fresh_extreme_tags_k10_then_k5(self):
        bars = rising_bars(30)
        i = 20
        for b in bars:
            b['l'] = 110.0
        bars[i - 1]['l'] = 105.0
        bars[i]['l'] = 104.0
        self.assertEqual(fresh_tag(bars, i, 'B'), 'K10')

        bars[i - 11]['l'] = 103.0  # outside the preceding five, inside the ten
        self.assertEqual(fresh_tag(bars, i, 'B'), 'K5')

    def test_fails_k5_means_no_signal_tag(self):
        bars = rising_bars(30)
        i = 20
        for b in bars:
            b['l'] = 110.0
        bars[i - 1]['l'] = 105.0
        bars[i]['l'] = 104.0
        bars[i - 6]['l'] = 103.0  # part of the preceding five bars
        self.assertIsNone(fresh_tag(bars, i, 'B'))

    def test_sell_fresh_extreme_mirrors_buy(self):
        bars = rising_bars(30)
        i = 20
        for b in bars:
            b['h'] = 110.0
        bars[i - 1]['h'] = 115.0
        bars[i]['h'] = 116.0
        self.assertEqual(fresh_tag(bars, i, 'S'), 'K10')

    def test_detect_uses_pin_k10_structural_sl_and_real_next_open(self):
        bars = buy_pin_bars()
        signals = detect(bars, start=60)
        signal = next(s for s in signals if s['i'] == 80)
        self.assertEqual((signal['dir'], signal['kind'], signal['k_tag']), ('B', 'PIN', 'K10'))
        self.assertEqual(signal['entry'], round(bars[81]['o'], 2))
        self.assertAlmostEqual(signal['sl'], min(bars[79]['l'], bars[80]['l']))
        self.assertFalse(signal['skip'])
        self.assertFalse(signal['entry_est'])

    def test_entry_estimate_can_use_open_of_forming_l_plus_1(self):
        bars = buy_pin_bars(n=81)
        estimate = detect(bars, start=60, include_last=True)[-1]
        exact = detect(bars, start=60, include_last=True, entry_open=107.55)[-1]
        self.assertTrue(estimate['entry_est'])
        self.assertEqual(estimate['entry'], round(bars[-1]['c'], 2))
        self.assertFalse(exact['entry_est'])
        self.assertEqual(exact['entry'], 107.55)

    def test_dedupe_keeps_later_same_side_signal_and_marks_update(self):
        signals = [dict(i=10, t=3_000_000, dir='B'),
                   dict(i=11, t=3_300_000, dir='B'),
                   dict(i=12, t=3_600_000, dir='S')]
        out = dedupe_signals(signals)
        self.assertEqual([(s['i'], s['dir']) for s in out], [(11, 'B'), (12, 'S')])
        self.assertEqual(out[0]['replaces_t'], 3_000_000)


class ExitV7(unittest.TestCase):
    def setUp(self):
        self.signal = dict(i=1, dir='B', skip=False)
        self.base = raw_bars([
            (100, 101, 98, 100),   # L-1
            (101, 103, 99, 102),   # L
            (100, 101, 99, 100),   # L+1, entry at 100
            (100, 102, 99, 101),   # L+2
        ])

    def test_uses_structure_and_tp20(self):
        bars = [dict(b) for b in self.base]
        bars[2].update(h=120.1, l=99.0)
        result = outcome_v7(bars, self.signal)
        self.assertEqual(result['how'], 'TP')
        self.assertAlmostEqual(result['pnl'], 19.72, places=2)

    def test_same_bar_stop_and_target_counts_as_stop(self):
        bars = [dict(b) for b in self.base]
        bars[2].update(h=121.0, l=97.0)
        result = outcome_v7(bars, self.signal)
        self.assertEqual(result['how'], 'SL')
        self.assertAlmostEqual(result['pnl'], -2.28, places=2)

    def test_time_exit_is_close_of_l_plus_2(self):
        bars = [dict(b) for b in self.base]
        bars[3].update(h=105, l=99, c=104)
        result = outcome_v7(bars, self.signal)
        self.assertEqual(result['how'], 'TIME')
        self.assertAlmostEqual(result['pnl'], 3.72, places=2)

    def test_gap_through_stop_fills_at_l_plus_2_open(self):
        bars = [dict(b) for b in self.base]
        bars[3].update(o=97.0, h=101.0, l=96.0, c=99.0)
        result = outcome_v7(bars, self.signal)
        self.assertEqual(result['how'], 'SL')
        self.assertAlmostEqual(result['pnl'], -3.28, places=2)

    def test_waits_until_l_plus_2_is_closed(self):
        self.assertIsNone(outcome_v7(self.base[:3], self.signal))

    def test_sl_over_eight_dollars_is_skipped(self):
        bars = [dict(b) for b in self.base]
        bars[0]['l'], bars[1]['l'], bars[2]['o'] = 91.0, 92.0, 100.0
        result = outcome_v7(bars, self.signal)
        self.assertTrue(result['skip'])
        self.assertIn('> $8', result['reason'])

    def test_skip_message_does_not_present_a_trade(self):
        text = message(dict(t=1793761200000, dir='B', kind='PIN', k_tag='K5',
                            skip=True, skip_reason='SL distance > $8', entry=100,
                            sl=90, tp=120))
        self.assertIn('ข้ามสัญญาณ', text)
        self.assertIn('SL distance > $8', text)
        self.assertIn('ไม่มีรายการเข้าเทรด', text)
        self.assertNotIn('เข้า:', text)
        self.assertNotIn('TP 120', text)

    def test_signal_message_names_v7_and_k_tag(self):
        text = message(dict(t=1793761200000, dir='S', kind='ENG', k_tag='K10',
                            entry=100, sl=102, tp=80, sl_dist=2, entry_est=False))
        self.assertIn('ขาย (SELL)', text)
        self.assertIn('ENG K10', text)
        self.assertIn('Exit v7', text)
        self.assertIn('แจ้งเตือนเท่านั้น', text)


class TimeAndFetch(unittest.TestCase):
    def test_dst_and_time_conversions(self):
        self.assertTrue(us_dst(datetime(2026, 10, 31, 12)))
        self.assertFalse(us_dst(datetime(2026, 11, 2, 12)))
        self.assertFalse(us_dst(datetime(2027, 3, 13, 12)))
        self.assertTrue(us_dst(datetime(2027, 3, 15, 12)))
        t = 1793761200000  # 2026-11-04 03:00 UTC
        self.assertEqual(f"{to_srv(t):%H:%M}", '05:00')
        self.assertEqual(f"{to_ict(t):%H:%M}", '10:00')

    def test_parse_jsonp_sorts_oldest_first(self):
        bars = parse('_cb([[2000,1,2,0.5,1.5,1],[1000,1,2,0.5,1.5,1]]);')
        self.assertEqual([b['t'] for b in bars], [1000, 2000])

    def test_fetch_retries_stale_data_once(self):
        now = 10_000_000
        stale = [dict(t=now - 40 * 60_000, o=1, h=2, l=0.5, c=1.5, v=1)]
        fresh = [dict(t=now - 6 * 60_000, o=1, h=2, l=0.5, c=1.5, v=1)]
        with patch.object(fetch_module, '_download', side_effect=[stale, fresh]) as download:
            with patch.object(fetch_module.time, 'sleep'):
                result = fetch_module.fetch(500, now)
        self.assertEqual(result, fresh)
        self.assertEqual(download.call_count, 2)

    def test_feed_returns_stale_bars_only_after_retry(self):
        now = 10_000_000
        stale = [dict(t=now - 40 * 60_000, o=1, h=2, l=0.5, c=1.5, v=1)]
        with patch.object(fetch_module, '_download', side_effect=[stale, stale]):
            with patch.object(fetch_module.time, 'sleep'):
                result = fetch_module.fetch(500, now)
        self.assertEqual(result, stale)


if __name__ == '__main__':
    unittest.main()
