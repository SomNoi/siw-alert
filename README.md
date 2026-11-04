# 🔷 SIW Alert — XAUUSD M5 (Star-in-Wick v2)

**ไทย:** แอปแจ้งเตือนสัญญาณ SIW ทองคำ (XAUUSD) กราฟ M5 แบบอัตโนมัติ — โค้ดล้วน ไม่มี AI ไม่มีเอเจนต์ตอนรัน. GitHub Actions ดึงแท่งเทียน Dukascopy ทุก ~5 นาที, คำนวณสัญญาณ, ส่ง push ผ่าน ntfy และอัปเดตหน้าเว็บ (PWA). **แจ้งเตือนเท่านั้น ไม่ส่งออเดอร์.**

**English:** Deterministic alert app for the SIW v2 XAUUSD M5 signal. A GitHub Actions cron fetches Dukascopy bars, runs the engine, pushes via ntfy.sh, and updates a GitHub Pages PWA. **Watch-only; never places orders.**

- Dashboard (PWA): https://somnoi.github.io/siw-alert/
- Push topic: https://ntfy.sh/siw-tqltiyequ0ci

## กฎ / Rules (port of `siw_v2_20261104/siw.py`)
1. EMA21/EMA55 on M5 closes: EMA21<EMA55 → sells only; > → buys only.
2. Confirm bar L: **A** pin bar / small body inside prior wick · **B** engulfing in trend direction · **C** prior pin/star + L closes in trend colour.
3. Leg filter: extreme of last 12 bars → close(L) ≤ $10.
4. Entry = open of L+1 (alert shows ≈close(L) because L+1 has just opened). SL $5, TP $20; after 15 min trail $3 + breakeven (manual).
5. Dedupe: skip same-direction signal within 3 bars of the last one.

Message: `🔷 SIW ขาย/ซื้อ <pattern>`, confirm-bar time in Thai time (ICT) and MT5 server time (ICT−4h during US DST, ICT−5h otherwise), entry, SL, TP.

## ติดตั้งบนมือถือ / Install on phone
1. ติดตั้งแอป **ntfy** (Play Store / App Store) → Subscribe topic `siw-tqltiyequ0ci` (server ntfy.sh) หรือเปิดลิงก์ https://ntfy.sh/siw-tqltiyequ0ci — Install the ntfy app and subscribe to that topic.
2. เปิด https://somnoi.github.io/siw-alert/ → iPhone Safari: แชร์ → "เพิ่มไปยังหน้าจอโฮม"; Android Chrome: เมนู → "ติดตั้งแอป". — Add the PWA to your home screen.

## โครงสร้าง / Layout
- `engine/siw.py` stdlib-only engine · `engine/fetch.py` Dukascopy fetch (server-side, needs Referer) · `engine/run.py` cron entry
- `tests/` unit + parity tests vs `siw.py` (frozen reference output on a 600-bar fixture slice; live parity vs full CSV when the research folder exists)
- `state/state.json` last alerted signals (prevents duplicates) · `docs/` PWA + `docs/data/signals.json`
- Topic is stored as repo secret `NTFY_TOPIC`. Change it: `gh secret set NTFY_TOPIC` and update docs/index.html + README.

## ข้อจำกัด / Limitations
- ผลทดสอบเป็น in-sample (ข้อมูลไม่กี่วัน) — rules were tuned in-sample; not proof of edge.
- ในการทดสอบ 1 สัปดาห์ ฝั่ง **Buy ขาดทุน** — buys lost in the 1-week test; treat buy alerts with caution.
- GitHub cron อาจช้า 5–20 นาที หรือข้ามรอบ — GitHub scheduled runs can lag or be skipped; alerts may arrive late. Only signals whose confirm bar is within the last 3 closed bars are pushed.
- ราคา Dukascopy BID สูงกว่า IC Markets ประมาณ +$1.5 — data offset vs IC; patterns can differ slightly between feeds.
- EMA warm-up uses only the last 500 bars (negligible vs full history but not bit-identical).
- The ntfy topic is public-by-obscurity (anyone who knows it can read/post). It contains no secrets.
- Not financial advice. ไม่ใช่คำแนะนำการลงทุน.
