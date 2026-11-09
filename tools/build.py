#!/usr/bin/env python3
"""Plaud 公司健康度看板 —— 生成脚本（目前全部是【模拟数据】）

用法：
  python3 tools/build.py --preview /tmp/preview.html   # 只生成不加密的预览页（本地看效果，不要提交）
  HEALTH_PAGE_PASSWORD=*** python3 tools/build.py       # 生成加密后的 index.html（网页上线用）

参数：
  --asof YYYY-MM-DD   数据截至日（默认：北京时间昨天）

产出：
  data/health_data.json  看板用的全部数字（模拟），方便核对
  index.html             口令页 + 加密后的看板（口令来自环境变量 HEALTH_PAGE_PASSWORD）

模拟数据说明：每个「出货月 × 区域」用固定种子生成，同一个月重跑数字不变；
日期往后推，只会多出新的月份、或让没满 30/60/90 天的批次变成可算。
以后接真实数据：只要把 make_data() 换成读真实来源，输出同样结构的 dict 即可，页面部分不用改。
"""
import argparse, base64, math, calendar, datetime as dt, hashlib, html, json, os, random, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGIONS = ['美洲', '欧洲中东非', '亚太', '中国']
REGION_BASE = {'美洲': 14000, '欧洲中东非': 9000, '亚太': 6000, '中国': 4000}
FIRST_MONTH = (2025, 11)

# 指标定义：range = 归一化区间（行业可接受下限 → 优秀线），warn/good = 预警线 / 健康线
METRICS = [
    dict(key='act', name='出货激活率 (T+90)', tag='真需求', unit='%', weight=30, range=(40, 90), warn=60, good=75),
    dict(key='sub', name='订阅转化率 (T+90)', tag='真价值', unit='%', weight=25, range=(5, 30), warn=12, good=20),
    dict(key='dau', name='DAU / MAU', tag='真习惯', unit='%', weight=25, range=(10, 35), warn=15, good=25),
    dict(key='nps', name='NPS', tag='真口碑', unit='', weight=20, range=(-20, 80), warn=30, good=50),
]


# ---------------- 模拟数据 ----------------
def months_between(a, b):
    y, m = a
    out = []
    while (y, m) <= b:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def month_end(y, m):
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def rng_for(*parts):
    seed = int(hashlib.md5('|'.join(map(str, parts)).encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def make_data(asof):
    months = months_between(FIRST_MONTH, (asof.year, asof.month))
    cohorts = []
    for i, (y, m) in enumerate(months):
        end = min(month_end(y, m), asof)
        rows = []
        for r in REGIONS:
            g = rng_for('cohort', y, m, r)
            season = 1.35 if m in (11, 12) else (0.85 if m in (1, 2) else 1.0)
            full = REGION_BASE[r] * season * (1 + 0.012 * i) * g.uniform(0.9, 1.1)
            days = (end - dt.date(y, m, 1)).days + 1
            shipped = int(full * days / calendar.monthrange(y, m)[1])
            reg_adj = {'美洲': 0.02, '欧洲中东非': 0.0, '亚太': -0.015, '中国': -0.03}[r]
            a90 = 0.735 + reg_adj + 0.025 * math.sin(i / 2.2) + g.uniform(-0.012, 0.012)
            row = dict(region=r, shipped=shipped,
                       act30=a90 - g.uniform(0.07, 0.09), act60=a90 - g.uniform(0.02, 0.035), act90=a90,
                       sub90=0.165 + 0.002 * i + reg_adj * 0.4 + g.uniform(-0.01, 0.01))
            rows.append(row)
        # 没满 N 天的批次不算（按出货月最后一天 + N 天）
        me = month_end(y, m)
        mature = {n: me + dt.timedelta(days=n) <= asof for n in (30, 60, 90)}
        for row in rows:
            for n in (30, 60, 90):
                if not mature[n]:
                    row[f'act{n}'] = None
            if not mature[90]:
                row['sub90'] = None
        cohorts.append(dict(month=f'{y}-{m:02d}', partial=end < month_end(y, m), mature=mature, regions=rows))

    usage = []  # 按自然月：DAU/MAU、NPS（只放已经过完的月）
    for i, (y, m) in enumerate(months):
        if month_end(y, m) >= asof:
            continue
        g = rng_for('usage', y, m)
        usage.append(dict(month=f'{y}-{m:02d}',
                          dau=0.205 - 0.004 * math.cos(i / 1.7) - 0.0006 * i + g.uniform(-0.006, 0.006),
                          mau=int(sum(REGION_BASE.values()) * (6 + 0.9 * i) * g.uniform(0.97, 1.03)),
                          nps=round(38 + 4 * math.sin(i / 2.5) + g.uniform(-2.5, 2.5)),
                          nps_n=int(g.uniform(700, 1300))))
    return dict(asof=asof.isoformat(), simulated=True, cohorts=cohorts, usage=usage)


# ---------------- 汇总 ----------------
def agg(cohort, key):
    rows = [r for r in cohort['regions'] if r[key] is not None]
    w = sum(r['shipped'] for r in rows)
    return sum(r[key] * r['shipped'] for r in rows) / w if rows and w else None


def series(data):
    """每个指标的时间序列：[(期, 值%)]，只取已经能算的期。"""
    s = {'act': [], 'sub': [], 'dau': [], 'nps': []}
    for c in data['cohorts']:
        a, b = agg(c, 'act90'), agg(c, 'sub90')
        if a is not None:
            s['act'].append((c['month'] + ' 出货', a * 100))
        if b is not None:
            s['sub'].append((c['month'] + ' 出货', b * 100))
    for u in data['usage']:
        s['dau'].append((u['month'], u['dau'] * 100))
        s['nps'].append((u['month'], float(u['nps'])))
    return s


def norm(v, lo, hi):
    return max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))


def status(v, warn, good):
    if v >= good:
        return 'good', '●', '健康'
    if v >= warn:
        return 'warn', '▲', '需关注'
    return 'bad', '■', '预警'


# ---------------- 页面 ----------------
def esc(x):
    return html.escape(str(x))


def fmt(v, unit):
    return '—' if v is None else (f'{v:.1f}%' if unit == '%' else f'{v:.0f}')


def pct(v):
    return '—' if v is None else f'{v * 100:.1f}%'


def sparkline(points, unit):
    pts = points[-8:]
    W, H, P = 300, 56, 8
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        hi = lo + 1
    xs = [P + i * (W - 2 * P) / max(1, len(pts) - 1) for i in range(len(pts))]
    ys = [H - P - (v - lo) / (hi - lo) * (H - 2 * P) for v in vals]
    path = ' '.join(f'{"M" if i == 0 else "L"}{x:.1f},{y:.1f}' for i, (x, y) in enumerate(zip(xs, ys)))
    hits = ''.join(
        f'<circle class="hit" cx="{x:.1f}" cy="{y:.1f}" r="12" data-tip="{esc(p)}：{esc(fmt(v, unit))}"></circle>'
        for (p, v), x, y in zip(pts, xs, ys))
    return (f'<svg class="spark" viewBox="0 0 {W} {H}" preserveAspectRatio="none" role="img" '
            f'aria-label="近 {len(pts)} 期走势">'
            f'<path d="{path}" fill="none" stroke="var(--line)" stroke-width="2" vector-effect="non-scaling-stroke"/>'
            f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="4" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/>'
            f'{hits}</svg>')


def render(data):
    s = series(data)
    cards, bars, score = [], [], 0.0
    for md in METRICS:
        pts = s[md['key']]
        cur = pts[-1][1]
        prev = pts[-2][1] if len(pts) > 1 else None
        n = norm(cur, *md['range'])
        score += n * md['weight'] / 100
        st, icon, label = status(cur, md['warn'], md['good'])
        lo, hi = md['range']
        pos = (cur - lo) / (hi - lo) * 100
        if prev is None:
            delta = ''
        else:
            d = cur - prev
            arrow = '↑' if d > 0 else ('↓' if d < 0 else '→')
            du = 'pp' if md['unit'] == '%' else ''
            delta = f'<div class="delta {"up" if d > 0 else "down" if d < 0 else ""}">{arrow} {abs(d):.1f}{du} <span>较上一完整期（{esc(pts[-2][0])}）</span></div>'
        u = md['unit']
        cards.append(f'''
<article class="kpi">
  <header><h3>{esc(md["name"])}</h3><span class="chip">{esc(md["tag"])}</span></header>
  <div class="period">当期：{esc(pts[-1][0])}</div>
  <div class="big {st}">{fmt(cur, u)}</div>
  {delta}
  {sparkline(pts, u)}
  <div class="gauge"><div class="fill" style="width:{max(0, min(100, pos)):.1f}%"></div></div>
  <div class="gauge-lbl"><span>{lo}{u}</span><span class="st {st}">{icon} {label}（阈值 {md["warn"]} / {md["good"]}）</span><span>{hi}{u}</span></div>
</article>''')
        bars.append(f'''<div class="brow"><span class="bname">{esc(md["name"].split(" (")[0])}</span>
<span class="btrack" title="归一化得分 {n:.0f} / 100"><span class="bfill" style="width:{n:.1f}%"></span></span>
<span class="bval">{fmt(cur, u)}</span><span class="bscore">{n:.0f} 分</span></div>''')
    total = round(score)
    tst, ticon, tlabel = status(total, 50, 75)

    # 出货 cohort 表
    crow = []
    for c in reversed(data['cohorts']):
        shipped = sum(r['shipped'] for r in c['regions'])
        note = '（本月进行中）' if c['partial'] else ''
        crow.append(f'<tr><td>{c["month"]}{note}</td><td class="n">{shipped:,}</td>'
                    f'<td class="n">{pct(agg(c, "act30"))}</td><td class="n">{pct(agg(c, "act60"))}</td>'
                    f'<td class="n">{pct(agg(c, "act90"))}</td><td class="n">{pct(agg(c, "sub90"))}</td></tr>')
    latest = [c for c in data['cohorts'] if c['mature'][90]][-1]
    rrow = ''.join(f'<tr><td>{r["region"]}</td><td class="n">{r["shipped"]:,}</td><td class="n">{pct(r["act90"])}</td>'
                   f'<td class="n">{pct(r["sub90"])}</td></tr>' for r in latest['regions'])
    urow = ''.join(f'<tr><td>{u["month"]}</td><td class="n">{u["mau"]:,}</td><td class="n">{u["dau"] * 100:.1f}%</td>'
                   f'<td class="n">{u["nps"]}</td><td class="n">{u["nps_n"]:,}</td></tr>' for u in reversed(data['usage']))

    # 出货量柱状图（按出货月）
    cs = data['cohorts']
    vals = [sum(r['shipped'] for r in c['regions']) for c in cs]
    vmax = max(vals) * 1.1
    W, H, PL, PB = 720, 200, 44, 24
    bw = (W - PL) / len(cs)
    ticks = ''.join(
        f'<line x1="{PL}" x2="{W}" y1="{H - PB - t / vmax * (H - PB - 8):.1f}" y2="{H - PB - t / vmax * (H - PB - 8):.1f}" class="grid"/>'
        f'<text x="{PL - 6}" y="{H - PB - t / vmax * (H - PB - 8) + 4:.1f}" class="ax" text-anchor="end">{t // 1000}k</text>'
        for t in range(0, int(vmax), 10000))
    bars_svg = ''
    for i, (c, v) in enumerate(zip(cs, vals)):
        h = v / vmax * (H - PB - 8)
        x = PL + i * bw + 3
        cls = 'bar partial' if c['partial'] else 'bar'
        bars_svg += (f'<path class="{cls}" d="M{x:.1f},{H - PB} V{H - PB - h + 4:.1f} q0,-4 4,-4 H{x + bw - 10:.1f} q4,0 4,4 V{H - PB} Z"/>'
                     f'<rect class="hit" x="{x - 3:.1f}" y="0" width="{bw:.1f}" height="{H - PB}" '
                     f'data-tip="{c["month"]} 出货：{v:,} 台{"（本月进行中）" if c["partial"] else ""}"/>'
                     f'<text x="{x + (bw - 6) / 2:.1f}" y="{H - 6}" class="ax" text-anchor="middle">{c["month"][2:].replace("-", "/")}</text>')
    ship_chart = f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="每月出货量">{ticks}{bars_svg}</svg>'

    weights = ' · '.join(f'{m["name"].split(" (")[0]} {m["weight"]}%' for m in METRICS)
    defs = ''.join(
        f'<tr><td>{esc(m["name"])}</td><td class="n">{m["weight"]}%</td><td class="n">{m["range"][0]} → {m["range"][1]}</td>'
        f'<td class="n">{m["warn"]} / {m["good"]}</td></tr>' for m in METRICS)
    gen = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=8)

    return TEMPLATE.format(
        asof=esc(data['asof']), gen=gen.strftime('%Y-%m-%d %H:%M'), total=total, tst=tst, ticon=ticon, tlabel=tlabel,
        bars=''.join(bars), weights=esc(weights), cards=''.join(cards), crow=''.join(crow), rrow=rrow, urow=urow,
        latest=latest['month'], ship_chart=ship_chart, defs=defs)


TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow, noarchive">
<title>Plaud 公司健康度看板</title>
<style>
:root {{
  color-scheme: light;
  --bg:#f9f9f7; --surface:#fcfcfb; --t1:#0b0b0b; --t2:#52514e; --t3:#898781; --bd:rgba(11,11,11,.10);
  --accent:#2a78d6; --line:#86b6ef; --track:#ecebe7; --gridc:rgba(11,11,11,.08);
  --good:#0ca30c; --warn:#b97a00; --bad:#d03b3b; --banner:#fff7e6; --bannerbd:#fab219;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    color-scheme: dark;
    --bg:#0d0d0d; --surface:#1a1a19; --t1:#f0efec; --t2:#c3c2b7; --t3:#8d8c85; --bd:rgba(255,255,255,.10);
    --accent:#3987e5; --line:#5598e7; --track:#2c2c2a; --gridc:rgba(255,255,255,.08);
    --good:#3fbf3f; --warn:#fab219; --bad:#e66767; --banner:#2a2414; --bannerbd:#c98500;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --bg:#0d0d0d; --surface:#1a1a19; --t1:#f0efec; --t2:#c3c2b7; --t3:#8d8c85; --bd:rgba(255,255,255,.10);
  --accent:#3987e5; --line:#5598e7; --track:#2c2c2a; --gridc:rgba(255,255,255,.08);
  --good:#3fbf3f; --warn:#fab219; --bad:#e66767; --banner:#2a2414; --bannerbd:#c98500;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--t1); font:14px/1.6 system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }}
.wrap {{ max-width:1180px; margin:0 auto; padding:28px 16px 48px; }}
.top {{ display:flex; gap:16px; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; }}
h1 {{ font-size:26px; margin:0 0 4px; letter-spacing:-.01em; }}
.sub {{ color:var(--t2); margin:0; }}
.btns {{ display:flex; gap:8px; flex-wrap:wrap; }}
.btn {{ font:inherit; padding:7px 14px; border-radius:9px; border:1px solid var(--bd); background:var(--surface); color:var(--t1); cursor:pointer; }}
.btn:hover {{ border-color:var(--accent); }}
.banner {{ margin:20px 0; padding:14px 18px; border-radius:12px; background:var(--banner); border:1px solid var(--bannerbd); border-left-width:5px; }}
.banner b {{ font-size:15px; }}
.card {{ background:var(--surface); border:1px solid var(--bd); border-radius:14px; padding:20px 22px; }}
.score {{ display:grid; grid-template-columns:200px 1fr; gap:24px; align-items:center; margin-bottom:16px; }}
.score .lbl {{ color:var(--t2); }}
.score .num {{ font-size:64px; font-weight:700; line-height:1; letter-spacing:-.03em; }}
.score .num small {{ font-size:18px; color:var(--t3); font-weight:400; }}
.pill {{ display:inline-block; margin-top:12px; padding:3px 12px; border-radius:999px; border:1px solid var(--bd); font-weight:600; }}
.brow {{ display:grid; grid-template-columns:96px 1fr 64px 52px; gap:12px; align-items:center; margin:6px 0; }}
.bname {{ color:var(--t2); }}
.btrack {{ height:14px; background:var(--track); border-radius:4px; overflow:hidden; }}
.bfill {{ display:block; height:100%; background:var(--accent); border-radius:0 4px 4px 0; }}
.bval {{ font-weight:600; font-variant-numeric:tabular-nums; }}
.bscore {{ color:var(--t3); font-size:12.5px; font-variant-numeric:tabular-nums; }}
.wtxt {{ color:var(--t3); font-size:12.5px; margin:10px 0 0; }}
.kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:16px; }}
.kpi {{ background:var(--surface); border:1px solid var(--bd); border-radius:14px; padding:16px 18px; min-width:0; }}
.kpi header {{ display:flex; gap:8px; align-items:center; }}
.kpi h3 {{ font-size:14px; font-weight:500; margin:0; color:var(--t2); }}
.chip {{ font-size:11.5px; padding:1px 7px; border:1px solid var(--bd); border-radius:6px; color:var(--t3); white-space:nowrap; }}
.period {{ font-size:12px; color:var(--t3); margin-top:2px; }}
.big {{ font-size:36px; font-weight:700; letter-spacing:-.02em; margin:2px 0; font-variant-numeric:tabular-nums; }}
.delta {{ font-weight:600; font-size:13px; color:var(--t2); }}
.delta span {{ font-weight:400; color:var(--t3); }}
.spark {{ width:100%; height:56px; margin:8px 0 6px; overflow:visible; }}
.gauge {{ height:6px; background:var(--track); border-radius:3px; overflow:hidden; }}
.gauge .fill {{ height:100%; background:var(--accent); }}
.gauge-lbl {{ display:flex; justify-content:space-between; font-size:11.5px; color:var(--t3); margin-top:5px; gap:4px; }}
.st {{ font-weight:600; color:var(--t1); }}
.st.good::first-letter {{ color:var(--good); }} .st.warn::first-letter {{ color:var(--warn); }} .st.bad::first-letter {{ color:var(--bad); }}
h2 {{ font-size:17px; margin:28px 0 10px; }}
.chart {{ width:100%; height:auto; display:block; }}
.chart .bar {{ fill:var(--accent); }} .chart .bar.partial {{ fill:var(--line); }}
.grid {{ stroke:var(--gridc); stroke-width:1; }} .ax {{ fill:var(--t3); font-size:11px; }}
.hit {{ fill:transparent; cursor:default; }}
details {{ margin-top:12px; }}
summary {{ cursor:pointer; color:var(--t2); font-weight:600; }}
.tbl {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; margin-top:8px; font-size:13px; }}
th,td {{ padding:7px 10px; border-bottom:1px solid var(--bd); text-align:left; white-space:nowrap; }}
th {{ color:var(--t3); font-weight:500; }}
td.n,th.n {{ text-align:right; font-variant-numeric:tabular-nums; }}
.foot {{ color:var(--t3); font-size:12px; margin-top:28px; }}
ul.def {{ margin:6px 0 0; padding-left:20px; color:var(--t2); }}
#tip {{ position:fixed; pointer-events:none; background:var(--t1); color:var(--bg); padding:5px 9px; border-radius:7px; font-size:12px; display:none; z-index:9; white-space:nowrap; }}
@media (max-width:980px) {{ .kpis {{ grid-template-columns:repeat(2,1fr); }} }}
@media (max-width:620px) {{
  .kpis {{ grid-template-columns:1fr; }} .score {{ grid-template-columns:1fr; gap:12px; }}
  .brow {{ grid-template-columns:72px 1fr 52px; }} .bscore {{ display:none; }} h1 {{ font-size:22px; }}
}}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div>
      <h1>Plaud 公司健康度看板</h1>
      <p class="sub">四个「真」指标 · 出货 cohort 视角 · 数据截至 {asof}</p>
    </div>
    <div class="btns">
      <button class="btn" id="theme" type="button">深色 / 浅色</button>
      <button class="btn" id="expand" type="button">展开所有数据表</button>
    </div>
  </div>

  <div class="banner"><b>⚠ 当前全部为模拟数据（虚拟数值，仅用于展示看板结构，不代表真实经营情况，请勿引用）。</b>
  出货量计划接易仓订单接口；激活 / 订阅 / DAU / NPS 四路数据源尚未接入（见文末「口径与数据源」）。</div>

  <section class="card score">
    <div>
      <div class="lbl">综合健康度</div>
      <div class="num">{total}<small> / 100</small></div>
      <span class="pill st {tst}">{ticon} {tlabel}</span>
    </div>
    <div>
      {bars}
      <p class="wtxt">加权：{weights}。每项按「行业可接受下限 → 优秀线」线性归一到 0–100（右侧为归一化得分）。综合 ≥75 健康、50–75 需关注、&lt;50 预警。</p>
    </div>
  </section>

  <section class="kpis">{cards}</section>

  <h2>每月出货量（出货 cohort 的分母）</h2>
  <div class="card">
    {ship_chart}
    <details class="dt"><summary>出货 cohort 明细表</summary>
      <div class="tbl"><table>
        <tr><th>出货月</th><th class="n">出货量（台）</th><th class="n">T+30 激活率</th><th class="n">T+60 激活率</th><th class="n">T+90 激活率</th><th class="n">T+90 订阅转化率</th></tr>
        {crow}
      </table></div>
      <p class="foot">「—」= 这批货出货月最后一天起还没满 30 / 60 / 90 天，暂不计算。</p>
    </details>
  </div>

  <h2>分区域（最近一个满 90 天的出货月：{latest}）</h2>
  <div class="card">
    <details class="dt"><summary>分区域明细表</summary>
      <div class="tbl"><table>
        <tr><th>区域</th><th class="n">出货量（台）</th><th class="n">T+90 激活率</th><th class="n">T+90 订阅转化率</th></tr>
        {rrow}
      </table></div>
    </details>
  </div>

  <h2>活跃与口碑（按自然月）</h2>
  <div class="card">
    <details class="dt"><summary>DAU/MAU 与 NPS 明细表</summary>
      <div class="tbl"><table>
        <tr><th>月份</th><th class="n">MAU</th><th class="n">DAU/MAU</th><th class="n">NPS</th><th class="n">NPS 样本数</th></tr>
        {urow}
      </table></div>
    </details>
  </div>

  <h2>口径与数据源</h2>
  <div class="card">
    <ul class="def">
      <li><b>出货 cohort</b>：按设备出货月份（易仓「仓库发货时间」）分批，每批单独看它出货后 30 / 60 / 90 天的表现。</li>
      <li><b>出货激活率 (T+90)</b> = 该批出货设备中，出货后 90 天内完成激活的台数 ÷ 该批出货台数。数据源：出货 ← 易仓；激活 ← 待接入（软件 / 数据团队）。</li>
      <li><b>订阅转化率 (T+90)</b> = 该批设备对应用户中，90 天内开通付费订阅的人数 ÷ 该批出货台数。数据源：待接入。</li>
      <li><b>DAU / MAU</b> = 当月日活跃用户的日均值 ÷ 当月月活跃用户数。数据源：待接入。</li>
      <li><b>NPS</b> = 推荐者（9–10 分）占比 − 贬损者（0–6 分）占比，×100。数据源：待接入（用户调研）。</li>
      <li><b>较上一完整期</b>：激活 / 订阅与上一个出货月比；DAU/MAU、NPS 与上一个自然月比。</li>
    </ul>
    <div class="tbl"><table>
      <tr><th>指标</th><th class="n">权重</th><th class="n">归一化区间</th><th class="n">预警线 / 健康线</th></tr>
      {defs}
    </table></div>
  </div>

  <p class="foot">生成时间：{gen}（北京时间）· 生成脚本：plaud-health 仓库 tools/build.py · 当前为模拟数据</p>
</div>
<div id="tip"></div>
<script>
(function () {{
  var root = document.documentElement;
  try {{ var t = localStorage.getItem('ph-theme'); if (t) root.setAttribute('data-theme', t); }} catch (e) {{}}
  document.getElementById('theme').onclick = function () {{
    var cur = root.getAttribute('data-theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    var nx = cur === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', nx);
    try {{ localStorage.setItem('ph-theme', nx); }} catch (e) {{}}
  }};
  var open = false;
  document.getElementById('expand').onclick = function () {{
    open = !open;
    document.querySelectorAll('details.dt').forEach(function (d) {{ d.open = open; }});
    this.textContent = open ? '收起所有数据表' : '展开所有数据表';
  }};
  var tip = document.getElementById('tip');
  document.querySelectorAll('.hit').forEach(function (el) {{
    el.addEventListener('mousemove', function (e) {{
      tip.textContent = el.getAttribute('data-tip'); tip.style.display = 'block';
      tip.style.left = Math.min(e.clientX + 12, innerWidth - tip.offsetWidth - 8) + 'px';
      tip.style.top = (e.clientY - 34) + 'px';
    }});
    el.addEventListener('mouseleave', function () {{ tip.style.display = 'none'; }});
  }});
}})();
</script>
</body>
</html>
'''


# ---------------- 加密（和网页口令页的解密方式对应） ----------------
def encrypt(plain, password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    salt, iv, it = os.urandom(16), os.urandom(12), 250000
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=it).derive(password.encode())
    ct = AESGCM(key).encrypt(iv, plain.encode(), None)
    b = lambda x: base64.b64encode(x).decode()
    return json.dumps({'v': 1, 'iter': it, 'salt': b(salt), 'iv': b(iv), 'ct': b(ct)}, separators=(',', ':'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--asof', help='数据截至日 YYYY-MM-DD（默认北京时间昨天）')
    ap.add_argument('--preview', help='只写不加密的预览页到这个路径（不要提交）')
    a = ap.parse_args()
    today_bj = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=8)).date()
    asof = dt.date.fromisoformat(a.asof) if a.asof else today_bj - dt.timedelta(days=1)

    data = make_data(asof)
    page = render(data)
    os.makedirs(os.path.join(ROOT, 'data'), exist_ok=True)
    with open(os.path.join(ROOT, 'data', 'health_data.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    if a.preview:
        with open(a.preview, 'w', encoding='utf-8') as f:
            f.write(page)
        print('预览页已写到', a.preview)
        return
    pw = os.environ.get('HEALTH_PAGE_PASSWORD', '')
    if not pw:
        sys.exit('缺少环境变量 HEALTH_PAGE_PASSWORD（网页口令）。只想看效果请用 --preview <路径>')
    shell = open(os.path.join(ROOT, 'tools', 'login_shell.html'), encoding='utf-8').read()
    out = shell.replace('__PAYLOAD__', encrypt(page, pw))
    with open(os.path.join(ROOT, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(out)
    print(f'index.html 已生成（数据截至 {asof}，模拟数据，已加密）')


if __name__ == '__main__':
    main()
