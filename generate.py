#!/usr/bin/env python3
"""
Factor Donchian Dashboard — GitHub Actions generator
Outputs: index.html (7-ETF) and 5etf.html (5-ETF)
Run daily at 22:00 UTC Mon-Fri via GitHub Actions.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from itertools import combinations
import json
from datetime import datetime
import warnings; warnings.filterwarnings('ignore')

N, SHIFT  = 30, 1
BENCHMARK = 'SPY'

UNIVERSES = [
    dict(tickers=['SPMO','DGRO','SPYG','SPHQ','IVE'],
         start='2016-01-01', label='5-ETF Pure Factors',
         fname='5etf.html'),
    dict(tickers=['SPMO','DGRO','SPYG','SPHQ','IVE','GLD','DBMF'],
         start='2019-07-01', label='7-ETF Factors + Alternatives',
         fname='index.html'),        # main page = 7-ETF
]

META = {
    'SPMO': {'name':'Momentum',      'color':'#E63946'},
    'DGRO': {'name':'Div. Growth',   'color':'#2A9D8F'},
    'SPYG': {'name':'Growth',        'color':'#F4A261'},
    'SPHQ': {'name':'Quality',       'color':'#2E86AB'},
    'IVE':  {'name':'Value',         'color':'#6A4C93'},
    'GLD':  {'name':'Gold',          'color':'#D4A017'},
    'DBMF': {'name':'Mgd Futures',   'color':'#27AE60'},
    'SPY':  {'name':'S&P 500',       'color':'#7F8C8D'},
}

BADGE = {
    'SPMO': ('rgba(230,57,70,.15)',  '#E63946'),
    'DGRO': ('rgba(42,157,143,.15)', '#2A9D8F'),
    'SPYG': ('rgba(244,162,97,.15)', '#C77C2A'),
    'SPHQ': ('rgba(46,134,171,.15)', '#2E86AB'),
    'IVE':  ('rgba(106,76,147,.15)', '#6A4C93'),
    'GLD':  ('rgba(212,160,23,.15)', '#9A7D0A'),
    'DBMF': ('rgba(39,174,96,.15)',  '#1D6A39'),
    'SPY':  ('rgba(27,42,74,.15)',   '#1B2A4A'),
}


def run(univ):
    TICKERS = univ['tickers']
    PAIRS   = list(combinations(TICKERS, 2))
    print(f"\n[{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}]  {univ['label']}")

    all_t = TICKERS + ([BENCHMARK] if BENCHMARK not in TICKERS else [])
    raw   = yf.download(all_t, start=univ['start'], auto_adjust=True, progress=False)
    prices= raw['Close'].dropna()
    fp    = prices[TICKERS]
    spy   = prices[BENCHMARK]
    latest= fp.index[-1]
    print(f"  Data through: {latest.date()}")

    curr_prices = {t: round(float(fp[t].iloc[-1]), 2) for t in TICKERS}
    curr_prices[BENCHMARK] = round(float(spy.iloc[-1]), 2)

    # Pairwise Donchian ratios with latching signal
    ratio_data = {}
    for A, B in PAIRS:
        key = f"{A}/{B}"
        r   = fp[A] / fp[B]
        dh  = r.rolling(N).max().shift(SHIFT)
        dl  = r.rolling(N).min().shift(SHIFT)
        latch = pd.Series(0, index=r.index, dtype=int)
        cur = 0
        for i in range(len(r)):
            if i < N + SHIFT or pd.isna(r.iloc[i]) or pd.isna(dh.iloc[i]):
                latch.iloc[i] = cur; continue
            if   r.iloc[i] > dh.iloc[i]: cur =  1
            elif r.iloc[i] < dl.iloc[i]: cur = -1
            latch.iloc[i] = cur
        ratio_data[key] = dict(A=A, B=B, ratio=r, dh=dh, dl=dl, latch=latch)

    # Daily vote counts
    votes_df = pd.DataFrame(0, index=fp.index, columns=TICKERS, dtype=int)
    for key, d in ratio_data.items():
        votes_df[d['A']] += (d['latch'] ==  1).astype(int)
        votes_df[d['B']] += (d['latch'] == -1).astype(int)

    def pick_winner(date):
        v  = votes_df.loc[date]; mx = v.max()
        if mx == 0: return None
        ties = v[v == mx].index.tolist()
        return ties[0] if len(ties) == 1 else fp.loc[date, ties].idxmax()

    winner_s = pd.Series({d: pick_winner(d) for d in fp.index}, dtype=object)

    # Backtest
    dr = fp.pct_change(); bench_dr = spy.pct_change()
    pos_lag  = winner_s.shift(1)
    strat_dr = pd.Series(0.0, index=fp.index)
    for date in fp.index:
        h = pos_lag[date]
        if h and h in dr.columns: strat_dr[date] = dr.loc[date, h]

    TRIM = N + 3
    sc   = strat_dr.iloc[TRIM:]
    bc   = bench_dr.iloc[TRIM:].fillna(0)

    def metrics(rets, label):
        rets = rets.fillna(0); cum = (1 + rets).cumprod()
        tot  = cum.iloc[-1] - 1
        ann  = (1 + tot) ** (252 / max(len(rets), 1)) - 1
        vol  = rets.std() * np.sqrt(252); sh = ann / vol if vol else 0
        dd   = (cum / cum.cummax()) - 1; mdd = dd.min()
        cal  = ann / abs(mdd) if mdd else 0
        return dict(label=label, ann=ann, vol=vol, sharpe=sh,
                    mdd=mdd, calmar=cal, cum=cum, total=tot)

    sm = metrics(sc, f'Factor Rotation ({len(TICKERS)}-ETF)')
    bm = metrics(bc, 'SPY B&H')
    fm = {t: metrics(dr[t].iloc[TRIM:], t) for t in TICKERS}

    # Switch log
    switches, prev = [], None
    for date in winner_s.index:
        curr = winner_s[date]
        if curr and curr != prev and prev is not None:
            switches.append(dict(date_obj=date,
                date=date.strftime('%d %b %Y'), from_=prev, to=curr))
        if curr: prev = curr

    curr_winner = winner_s[latest]
    n_switches  = len(switches)
    if switches and switches[-1]['to'] == curr_winner:
        last_sw   = switches[-1]
        since_str = last_sw['date']
        prev_hold = last_sw['from_']
        days_in   = (latest - last_sw['date_obj']).days + 1
    else:
        since_str = prev_hold = '—'; days_in = '—'

    print(f"  Winner: {curr_winner}  Days In: {days_in}  Since: {since_str}  Prev: {prev_hold}  Switches: {n_switches}")
    print(f"  Strategy: {sm['ann']:+.1%} ann  Sharpe {sm['sharpe']:.2f}  MaxDD {sm['mdd']:.1%}")

    # Annual returns
    annual_s, annual_b = {}, {}
    for yr in range(int(univ['start'][:4]), latest.year + 1):
        ms = sc[sc.index.year == yr]; mb = bc[bc.index.year == yr]
        if len(ms): annual_s[str(yr)] = round(((1+ms.fillna(0)).prod()-1)*100, 1)
        if len(mb): annual_b[str(yr)] = round(((1+mb.fillna(0)).prod()-1)*100, 1)

    # Current pair states
    pair_states = {}
    for key, d in ratio_data.items():
        r  = d['ratio'].iloc[-1]; dh = d['dh'].iloc[-1]; dl = d['dl'].iloc[-1]
        lt = d['latch'].iloc[-1]
        pct= round((r-dl)/(dh-dl)*100) if not pd.isna(dh) and dh != dl else 0
        if r > dh:   status = 'ABOVE'
        elif r < dl: status = 'BELOW'
        else:        status = 'IN BAND'
        pair_states[key] = dict(
            A=d['A'], B=d['B'], val=round(r,4), up=round(dh,4), lo=round(dl,4),
            pct=int(pct), status=status, lat=lt,
            last_dir='▲ last up' if lt==1 else ('▼ last down' if lt==-1 else '—'),
            vote_for=d['A'] if lt==1 else (d['B'] if lt==-1 else None))

    alloc_p = {t: round((winner_s.iloc[TRIM:]==t).sum()/len(winner_s.iloc[TRIM:])*100,1) for t in TICKERS}
    none_p  = round(winner_s.iloc[TRIM:].isna().sum()/len(winner_s.iloc[TRIM:])*100,1)

    # Chart data (thin down to every 3rd point)
    full_lbl = [d.strftime('%Y-%m-%d') for d in sc.index[::3]]
    full_s   = ((1+sc.fillna(0)).cumprod()*100).round(3).tolist()[::3]
    full_b   = ((1+bc.fillna(0)).cumprod()*100).round(3).tolist()[::3]
    full_f   = {t: ((1+dr[t].iloc[TRIM:].fillna(0)).cumprod()*100).round(3).tolist()[::3] for t in TICKERS}

    cut18 = latest - pd.Timedelta(days=548)
    ratio_charts = {}
    for key, d in ratio_data.items():
        r18=d['ratio'][d['ratio'].index>=cut18]; dh18=d['dh'][d['dh'].index>=cut18]; dl18=d['dl'][d['dl'].index>=cut18]
        ratio_charts[key] = dict(
            labels=[x.strftime('%Y-%m-%d') for x in r18.index],
            ratio=[round(float(v),5) if not pd.isna(v) else None for v in r18],
            up   =[round(float(v),5) if not pd.isna(v) else None for v in dh18],
            lo   =[round(float(v),5) if not pd.isna(v) else None for v in dl18])

    curr_votes = {t: int(votes_df.loc[latest, t]) for t in TICKERS}

    P = dict(
        label=univ['label'], tickers=TICKERS, n_pairs=len(PAIRS),
        pairs=[f"{A}/{B}" for A,B in PAIRS],
        curr_date=latest.strftime('%d %b %Y'),
        start_str=latest.strftime('%b %Y'),
        generated_utc=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
        curr_winner=curr_winner, curr_votes=curr_votes, max_votes=len(TICKERS)-1,
        days_in=days_in, since_str=since_str, prev_hold=prev_hold, n_switches=n_switches,
        curr_prices=curr_prices, pair_states=pair_states, alloc_pct=alloc_p, none_pct=none_p,
        perf_s=dict(ann=round(sm['ann']*100,2), vol=round(sm['vol']*100,2),
                    sharpe=round(sm['sharpe'],2), mdd=round(sm['mdd']*100,2),
                    calmar=round(sm['calmar'],2), total=round(sm['total']*100,1)),
        perf_b=dict(ann=round(bm['ann']*100,2), sharpe=round(bm['sharpe'],2),
                    mdd=round(bm['mdd']*100,2), total=round(bm['total']*100,1)),
        perf_f={t: dict(ann=round(fm[t]['ann']*100,2), mdd=round(fm[t]['mdd']*100,2),
                        sharpe=round(fm[t]['sharpe'],2), total=round(fm[t]['total']*100,1)) for t in TICKERS},
        annual_s=annual_s, annual_b=annual_b,
        switches=[dict(date=s['date'],from_=s['from_'],to=s['to']) for s in switches[-20:]],
        full_lbl=full_lbl, full_s=full_s, full_b=full_b, full_f=full_f,
        ratio_charts=ratio_charts)

    html = build_html(P)
    with open(univ['fname'], 'w') as f: f.write(html)
    print(f"  Written → {univ['fname']}")


def sc(s):
    return {'ABOVE':'status-above','BELOW':'status-below'}.get(s,'status-within')

def build_html(P):
    T=P['tickers']; PAIRS=P['pairs']; W=P['curr_winner']
    W_COL=META.get(W,{}).get('color','#C0392B') if W else '#C0392B'
    W_NAM=META.get(W,{}).get('name','—') if W else '—'
    sp=P['perf_s']; bp=P['perf_b']

    pair_rows=''
    for key in PAIRS:
        d=P['pair_states'][key]; vf=d['vote_for']
        vc=META.get(vf,{}).get('color','#7F8C8D') if vf else '#7F8C8D'
        vt=f"+1 {vf}<br><span class='sm' style='color:{vc}'>vote</span>" if vf else "—"
        txt=f"{d['status']}<br><span style='font-size:7px;opacity:.85'>{d['last_dir']}</span>"
        pair_rows+=f"""<div class="sr"><div class="sl">{key}</div>
          <div class="sv">{d['val']:.4f}<br><span class="sm">{d['pct']}% of range</span></div>
          <div class="sb"><span class="bv g">{d['up']:.4f}</span><span class="bl">upper</span></div>
          <div class="sb"><span class="bv r">{d['lo']:.4f}</span><span class="bl">lower</span></div>
          <div class="ss {sc(d['status'])}">{txt}</div>
          <div class="sv" style="font-weight:700;color:{vc}">{vt}</div></div>"""

    vote_cards=''
    for t in sorted(T,key=lambda x:-P['curr_votes'][x]):
        v=P['curr_votes'][t]; col=META[t]['color']; is_w=(t==W)
        bg=f"rgba({int(col[1:3],16)},{int(col[3:5],16)},{int(col[5:7],16)},.12)" if is_w else '#F7F9FC'
        bdr=f"1.5px solid {col}" if is_w else '1.5px solid #DDE3EA'
        stars='★'*v+'·'*(P['max_votes']-v)
        vote_cards+=f"""<div style="flex:1;text-align:center;padding:6px 3px;border-radius:4px;background:{bg};border:{bdr};min-width:55px">
          <div style="font-size:7px;color:#7F8C8D;text-transform:uppercase;letter-spacing:.8px;margin-bottom:1px">{t}</div>
          <div style="font-size:9px;color:#475569;margin-bottom:2px">{META[t]['name']}</div>
          <div style="font-size:17px;font-weight:700;font-family:'Courier New',monospace;color:{col if is_w else '#94a3b8'}">{v}</div>
          <div style="font-size:8px;color:{col if is_w else '#94a3b8'};margin-top:1px">{stars}</div></div>"""

    price_badges=''
    for t in T+([BENCHMARK] if BENCHMARK not in T else []):
        bg_c,txt_c=BADGE.get(t,('rgba(100,100,100,.1)','#475569'))
        price=P['curr_prices'].get(t,'—')
        ps=f"${price:.2f}" if isinstance(price,float) else '—'
        price_badges+=f"""<div class="pc" style="background:{bg_c};border-color:{txt_c}33">
          <div class="pt" style="color:{txt_c}">{t}</div>
          <div class="pv" style="color:{txt_c}">{ps}</div></div>"""

    rbar=rl=''
    for t in T:
        p=P['alloc_pct'][t]
        if p<2: continue
        c=META[t]['color']
        rbar+=f"<div class='rs' style='width:{p}%;background:{c}'>{''+t if p>8 else ''}</div>"
        rl  +=f"<div class='ri'><div class='rd' style='background:{c}'></div>{t} {p:.0f}%</div>"
    if P.get('none_pct',0)>2:
        rbar+=f"<div class='rs' style='width:{P['none_pct']}%;background:#BDC3C7'></div>"

    sw_rows=''
    for sw in reversed(P['switches']):
        fc=META.get(sw['from_'],{}).get('color','#666'); tc=META.get(sw['to'],{}).get('color','#666')
        sw_rows+=f"""<tr><td>{sw['date']}</td><td>
          <span class="badge" style="background:{fc}22;color:{fc}">{sw['from_']}</span>
          <span class="arr">→</span>
          <span class="badge" style="background:{tc}22;color:{tc}">{sw['to']}</span></td></tr>"""

    years=sorted(set(list(P['annual_s'].keys())+list(P['annual_b'].keys())))
    ann_lab=json.dumps(years)
    ann_str=json.dumps([P['annual_s'].get(y) for y in years])
    ann_spy=json.dumps([P['annual_b'].get(y) for y in years])

    perf_rows=''
    for t in T:
        p=P['perf_f'][t]; col=META[t]['color']; is_w=(t==W)
        bg=f"background:rgba({int(col[1:3],16)},{int(col[3:5],16)},{int(col[5:7],16)},.07);" if is_w else ''
        perf_rows+=f"""<tr style="{bg}"><td><span class="badge" style="background:{col}22;color:{col}">{t}</span>&nbsp;{META[t]['name']}</td>
          <td style="font-family:'Courier New',monospace;color:{'#1E8449' if p['ann']>=0 else '#922B21'}">{p['ann']:+.1f}%</td>
          <td style="font-family:'Courier New',monospace">{p['sharpe']:.2f}</td>
          <td style="font-family:'Courier New',monospace;color:#922B21">{p['mdd']:.1f}%</td>
          <td style="font-family:'Courier New',monospace">{p['total']:+.1f}%</td></tr>"""

    full_ds=f"""{{label:'Factor Rotation',data:{json.dumps(P['full_s'])},
      borderColor:'#C0392B',borderWidth:2.5,pointRadius:0,tension:.1,fill:false}},
    {{label:'SPY B&H',data:{json.dumps(P['full_b'])},
      borderColor:'#1C2B3A',borderWidth:1.8,borderDash:[5,3],pointRadius:0,tension:.1,fill:false}},"""
    for t in T:
        col=META[t]['color']
        full_ds+=f"""{{label:'{t} ({META[t]['name']})',data:{json.dumps(P['full_f'][t])},
      borderColor:'{col}',borderWidth:1,pointRadius:0,tension:.1,fill:false,borderDash:[2,2]}},"""

    ratio_divs=ratio_js=''
    for i,key in enumerate(PAIRS):
        d=P['pair_states'][key]; vf=d['vote_for']
        col=META.get(vf,{}).get('color','#7F8C8D') if vf else '#7F8C8D'
        vt=f"+1 {vf}" if vf else "—"
        rc=P['ratio_charts'][key]
        ratio_divs+=f"""<div class="card"><div class="ch"><span>{key}</span>
          <span class="ss {sc(d['status'])}" style="margin:0">{d['status']}</span></div>
          <div class="cb" style="padding:10px">
            <div style="font-size:9px;color:{col};font-weight:700;margin-bottom:4px;font-family:'Courier New',monospace">{vt}</div>
            <div style="height:110px;position:relative"><canvas id="rc{i}"></canvas></div>
          </div></div>"""
        ratio_js+=f"""makeRC('rc{i}',{json.dumps(rc['labels'])},{json.dumps(rc['ratio'])},{json.dumps(rc['up'])},{json.dumps(rc['lo'])},'{META[d["A"]]["color"]}');\n"""

    sig_logic=(f"Winner: <strong style='color:{W_COL}'>{W} — {W_NAM} "
               f"({P['curr_votes'].get(W,0)}/{P['max_votes']} votes)</strong> &nbsp;·&nbsp; "
               f"Each ratio votes for the ETF breaking above its 30-day Donchian high (latches until broken down).")

    # Nav link (cross-link between the two dashboards)
    other_link = '5etf.html' if P['n_pairs'] > 10 else 'index.html'
    other_label = '5-ETF View' if P['n_pairs'] > 10 else '7-ETF View'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LC · Factor Donchian · {P['label']}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{{--nv:#1C2B3A;--nv2:#243446;--rd:#C0392B;--bg:#F0F4F8;--bd:#DDE3EA;}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--nv);font-size:13px;}}
.hdr{{background:var(--nv);height:54px;display:flex;align-items:center;justify-content:space-between;padding:0 24px;border-bottom:3px solid var(--rd);}}
.hl{{display:flex;align-items:center;gap:14px;}}
.lc{{font-family:'Courier New',monospace;font-size:11px;font-weight:700;color:var(--rd);border:1px solid var(--rd);padding:3px 8px;border-radius:2px;letter-spacing:2px;}}
.ht{{color:#fff;font-size:14px;font-weight:600;}}.hs{{color:#94a3b8;font-size:10px;font-family:'Courier New',monospace;margin-top:2px;}}
.hr{{text-align:right;color:#94a3b8;font-size:11px;font-family:'Courier New',monospace;}}
.nav-link{{color:#94a3b8;font-size:11px;text-decoration:none;padding:4px 10px;border:1px solid #375068;border-radius:4px;margin-right:8px;}}
.nav-link:hover{{background:#375068;color:#fff;}}
.page{{max-width:1440px;margin:0 auto;padding:16px 22px;}}
.card{{background:#fff;border:1px solid var(--bd);border-radius:6px;overflow:hidden;}}
.ch{{background:var(--nv2);padding:7px 13px;font-size:10px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#94a3b8;display:flex;align-items:center;justify-content:space-between;}}
.cb{{padding:13px;}}
.g1{{display:grid;grid-template-columns:300px 1fr 220px;gap:13px;margin-bottom:13px;}}
.g3{{display:grid;grid-template-columns:1fr 390px;gap:13px;margin-bottom:13px;}}
.sig-card{{border-top:4px solid {W_COL};}}
.sa{{font-size:36px;font-weight:700;font-family:'Courier New',monospace;line-height:1.1;letter-spacing:-1px;}}
.sn{{font-size:12px;color:#64748b;margin:4px 0 13px;}}
.mg{{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:10px;}}
.mi{{background:var(--bg);border-radius:4px;padding:6px 8px;}}
.ml{{font-size:8px;color:#7F8C8D;text-transform:uppercase;letter-spacing:.8px;margin-bottom:2px;}}
.mv{{font-size:13px;font-weight:700;font-family:'Courier New',monospace;}}
.pr{{display:flex;gap:5px;flex-wrap:wrap;}}
.pc{{flex:1;border-radius:4px;padding:5px 4px;text-align:center;border:1px solid var(--bd);min-width:48px;}}
.pt{{font-size:8px;font-weight:700;letter-spacing:.8px;}}.pv{{font-size:11px;font-weight:600;font-family:'Courier New',monospace;}}
.shdr{{display:grid;grid-template-columns:90px 1fr 1fr 1fr 100px 80px;gap:5px;padding:0 0 5px;border-bottom:2px solid var(--nv);margin-bottom:3px;}}
.sr{{display:grid;grid-template-columns:90px 1fr 1fr 1fr 100px 80px;gap:5px;align-items:center;padding:5px 0;border-bottom:1px solid var(--bd);}}
.sr:last-child{{border-bottom:none;}}
.sl{{font-size:10px;font-weight:700;font-family:'Courier New',monospace;color:#475569;}}
.sv{{font-family:'Courier New',monospace;font-size:11px;font-weight:600;text-align:center;line-height:1.3;}}
.sm{{font-size:8px;color:#7F8C8D;}}
.sb{{display:flex;flex-direction:column;align-items:center;gap:1px;}}
.bv{{font-family:'Courier New',monospace;font-size:11px;font-weight:600;}}
.bv.g{{color:#1E8449;}}.bv.r{{color:#922B21;}}
.bl{{font-size:8px;color:#7F8C8D;text-transform:uppercase;}}
.ss{{font-size:9px;font-weight:700;padding:3px 5px;border-radius:3px;text-align:center;}}
.status-above{{background:#D5F5E3;color:#1E8449;}}.status-below{{background:#FADBD8;color:#922B21;}}.status-within{{background:#EBF5FB;color:#1A5276;}}
.col-h{{font-size:8px;font-weight:700;color:#7F8C8D;text-transform:uppercase;letter-spacing:.8px;text-align:center;}}
.pg{{display:grid;grid-template-columns:1fr 1fr;gap:6px;}}
.pi{{border-radius:4px;padding:7px 8px;background:var(--bg);}}
.pl{{font-size:9px;color:#7F8C8D;text-transform:uppercase;letter-spacing:.8px;margin-bottom:2px;}}
.pv2{{font-size:15px;font-weight:700;font-family:'Courier New',monospace;}}
.ps{{font-size:9px;color:#7F8C8D;margin-top:1px;}}
.rbar{{height:22px;border-radius:3px;overflow:hidden;display:flex;margin:6px 0;}}
.rs{{height:100%;display:flex;align-items:center;justify-content:center;font-size:8px;font-weight:700;color:rgba(255,255,255,.9);white-space:nowrap;overflow:hidden;}}
.rleg{{display:flex;gap:9px;flex-wrap:wrap;}}.ri{{display:flex;align-items:center;gap:4px;font-size:10px;color:#475569;}}.rd{{width:10px;height:10px;border-radius:2px;}}
.ytd-grid{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:7px;}}
.ytd-c{{border-radius:4px;padding:8px 9px;border:1px solid var(--bd);}}
.ytd-l{{font-size:8px;text-transform:uppercase;letter-spacing:.8px;margin-bottom:3px;}}
.ytd-v{{font-size:17px;font-weight:700;font-family:'Courier New',monospace;}}
.ytd-s{{font-size:9px;margin-top:2px;color:#7F8C8D;}}
.sw-wrap{{max-height:280px;overflow-y:auto;}}
.sw-t{{width:100%;border-collapse:collapse;font-size:11px;}}
.sw-t th{{background:var(--nv2);color:#94a3b8;padding:6px 7px;text-align:left;font-size:9px;letter-spacing:.8px;text-transform:uppercase;font-weight:600;position:sticky;top:0;z-index:1;}}
.sw-t td{{padding:5px 7px;border-bottom:1px solid var(--bd);vertical-align:middle;}}
.sw-t tr:last-child td{{border-bottom:none;}}.sw-t tr:hover td{{background:var(--bg);}}
.badge{{display:inline-block;padding:2px 6px;border-radius:3px;font-family:'Courier New',monospace;font-size:10px;font-weight:700;}}
.arr{{color:#7F8C8D;margin:0 3px;font-size:10px;}}
.perf-t{{width:100%;border-collapse:collapse;font-size:11px;}}
.perf-t th{{background:var(--nv2);color:#94a3b8;padding:5px 8px;text-align:center;font-size:9px;text-transform:uppercase;font-weight:600;letter-spacing:.8px;}}
.perf-t td{{padding:5px 8px;border-bottom:1px solid var(--bd);text-align:center;}}
.perf-t tr:last-child td{{border-bottom:none;}}.perf-t tr:hover td{{background:var(--bg);}}
canvas{{max-width:100%;}}
.footer{{text-align:center;padding:10px;font-size:10px;color:#7F8C8D;border-top:1px solid var(--bd);font-family:'Courier New',monospace;margin-top:13px;}}
</style>
</head>
<body>
<div class="hdr">
  <div class="hl"><span class="lc">LC</span>
    <div><div class="ht">Factor Donchian Rotation &nbsp;·&nbsp; {P['label']}</div>
      <div class="hs">N={N} · shift({SHIFT}) · pairwise ratio Donchian · latching signal · internal use only</div>
    </div></div>
  <div class="hr" style="display:flex;align-items:center;gap:8px">
    <a href="{other_link}" class="nav-link">{other_label}</a>
    <div>As of <strong style="color:#fff">{P['curr_date']}</strong><br>Updated {P['generated_utc']}</div>
  </div>
</div>
<div class="page">
<div class="g1">
  <!-- Signal card -->
  <div class="card sig-card">
    <div class="ch"><span>Active Holding</span><span style="font-size:11px">▶ LIVE</span></div>
    <div class="cb">
      <div class="sa" style="color:{W_COL}">{W or '—'}</div>
      <div class="sn">{W_NAM}</div>
      <div class="mg">
        <div class="mi"><div class="ml">Days In</div><div class="mv" style="color:{W_COL}">{P['days_in']}</div></div>
        <div class="mi"><div class="ml">Since</div><div class="mv" style="font-size:11px">{P['since_str']}</div></div>
        <div class="mi"><div class="ml">Previous</div><div class="mv">{P['prev_hold']}</div></div>
        <div class="mi"><div class="ml">Switches</div><div class="mv">{P['n_switches']}</div></div>
      </div>
      <div class="pr">{price_badges}</div>
    </div>
  </div>
  <!-- Pairwise table -->
  <div class="card">
    <div class="ch"><span>Pairwise Donchian Signal State</span><span>N={N} · shift({SHIFT}) · ratio breakout / latch</span></div>
    <div class="cb" style="padding:10px 13px">
      <div class="shdr"><div class="col-h">Pair</div><div class="col-h">Current</div><div class="col-h">Upper</div><div class="col-h">Lower</div><div class="col-h">Status / Direction</div><div class="col-h">Vote</div></div>
      {pair_rows}
      <div style="margin-top:10px;border-top:1px solid var(--bd);padding-top:9px">
        <div style="font-size:9px;color:#7F8C8D;text-transform:uppercase;letter-spacing:.8px;margin-bottom:6px">Vote Tally &nbsp;·&nbsp; <span style="color:var(--nv);text-transform:none">max {P['max_votes']} per factor · latching signal</span></div>
        <div style="display:flex;gap:5px;flex-wrap:wrap">{vote_cards}</div>
        <div style="margin-top:7px;font-size:9px;color:#475569;padding:5px 7px;background:var(--bg);border-radius:4px">{sig_logic}</div>
      </div>
    </div>
  </div>
  <!-- Perf card -->
  <div class="card">
    <div class="ch"><span>Performance</span><span>vs SPY B&amp;H</span></div>
    <div class="cb">
      <div style="font-size:9px;color:#7F8C8D;text-transform:uppercase;letter-spacing:.8px;margin-bottom:7px">Since Inception</div>
      <div class="pg">
        <div class="pi"><div class="pl">Ann. Return</div><div class="pv2" style="color:{'#1E8449' if sp['ann']>=0 else '#922B21'}">{sp['ann']:+.1f}%</div><div class="ps">SPY: {bp['ann']:+.1f}%</div></div>
        <div class="pi"><div class="pl">Sharpe Ratio</div><div class="pv2">{sp['sharpe']:.2f}</div><div class="ps">SPY: {bp['sharpe']:.2f}</div></div>
        <div class="pi"><div class="pl">Max Drawdown</div><div class="pv2" style="color:#922B21">{sp['mdd']:.1f}%</div><div class="ps">SPY: {bp['mdd']:.1f}%</div></div>
        <div class="pi"><div class="pl">Calmar</div><div class="pv2">{sp['calmar']:.2f}</div><div class="ps">SPY: {bp.get('calmar',0):.2f}</div></div>
      </div>
      <div style="margin-top:9px;border-top:1px solid var(--bd);padding-top:9px">
        <div style="font-size:9px;color:#7F8C8D;text-transform:uppercase;letter-spacing:.8px;margin-bottom:7px">Total Returns</div>
        <div class="ytd-grid">
          <div class="ytd-c"><div class="ytd-l">Strategy</div><div class="ytd-v" style="color:{'#1E8449' if sp['total']>=0 else '#922B21'}">{sp['total']:+.1f}%</div><div class="ytd-s">since inception</div></div>
          <div class="ytd-c"><div class="ytd-l">SPY B&H</div><div class="ytd-v">{bp['total']:+.1f}%</div><div class="ytd-s">since inception</div></div>
          <div class="ytd-c"><div class="ytd-l">Volatility</div><div class="ytd-v">{sp['vol']:.1f}%</div><div class="ytd-s">annualised</div></div>
        </div>
      </div>
      <div style="margin-top:9px;border-top:1px solid var(--bd);padding-top:7px">
        <div style="font-size:9px;color:#7F8C8D;text-transform:uppercase;letter-spacing:.8px;margin-bottom:4px">Regime Allocation</div>
        <div class="rbar">{rbar}</div><div class="rleg">{rl}</div>
      </div>
    </div>
  </div>
</div>
<div class="card" style="margin-bottom:13px">
  <div class="ch"><span>Cumulative Returns — Full Period (rebased 100)</span><span>Rotation vs Individual Factors vs SPY B&amp;H</span></div>
  <div class="cb"><div style="height:220px;position:relative"><canvas id="fullChart"></canvas></div></div>
</div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:13px;margin-bottom:13px">{ratio_divs}</div>
<div class="g3">
  <div>
    <div class="card" style="margin-bottom:13px">
      <div class="ch"><span>Annual Returns</span><span>Strategy vs SPY</span></div>
      <div class="cb" style="padding:10px"><div style="height:180px;position:relative"><canvas id="annChart"></canvas></div></div>
    </div>
    <div class="card">
      <div class="ch"><span>Individual Factor Performance (Buy &amp; Hold)</span></div>
      <div class="cb" style="padding:0">
        <table class="perf-t"><thead><tr><th style="text-align:left">Factor</th><th>Ann Ret</th><th>Sharpe</th><th>Max DD</th><th>Total Ret</th></tr></thead>
        <tbody>{perf_rows}</tbody></table></div></div>
  </div>
  <div class="card">
    <div class="ch"><span>Switch Log (last 20)</span><span style="font-size:10px;color:#64748b">Total: {P['n_switches']} switches</span></div>
    <div class="cb" style="padding:0"><div class="sw-wrap">
      <table class="sw-t"><thead><tr><th>Date</th><th>From → To</th></tr></thead>
      <tbody>{sw_rows}</tbody></table></div></div>
</div></div>
</div>
<div class="footer">
  {P['label']} &nbsp;·&nbsp; {', '.join(T)} &nbsp;·&nbsp;
  N={N} · shift({SHIFT}) · Pairwise ratio Donchian · Latching signal &nbsp;·&nbsp;
  Lighthouse Canton Pte. Ltd. &nbsp;·&nbsp; {P['generated_utc']}
</div>
<script>
new Chart(document.getElementById('fullChart'),{{type:'line',
  data:{{labels:{json.dumps(P['full_lbl'])},datasets:[{full_ds}]}},
  options:{{responsive:true,maintainAspectRatio:false,animation:false,
    plugins:{{legend:{{position:'top',labels:{{font:{{size:10}},boxWidth:18}}}},tooltip:{{mode:'index',intersect:false}}}},
    scales:{{x:{{ticks:{{maxTicksLimit:8,font:{{size:9}}}},grid:{{display:false}}}},
             y:{{ticks:{{font:{{size:9}},callback:v=>v.toFixed(0)}},grid:{{color:'#EBEBEB'}}}}}}}}
}});
new Chart(document.getElementById('annChart'),{{type:'bar',
  data:{{labels:{ann_lab},datasets:[
    {{label:'Strategy',data:{ann_str},backgroundColor:'rgba(192,57,43,.7)',borderColor:'#C0392B',borderWidth:1}},
    {{label:'SPY',data:{ann_spy},backgroundColor:'rgba(28,43,58,.4)',borderColor:'#1C2B3A',borderWidth:1}}
  ]}},
  options:{{responsive:true,maintainAspectRatio:false,animation:false,
    plugins:{{legend:{{position:'top',labels:{{font:{{size:10}},boxWidth:14}}}},
              tooltip:{{callbacks:{{label:c=>`${{c.dataset.label}}: ${{c.raw?.toFixed(1)??'–'}}%`}}}}}},
    scales:{{x:{{ticks:{{font:{{size:9}}}},grid:{{display:false}}}},y:{{ticks:{{font:{{size:9}},callback:v=>v+'%'}},grid:{{color:'#EBEBEB'}}}}}}}}
}});
function makeRC(id,labels,ratio,up,lo,col){{
  const el=document.getElementById(id); if(!el) return;
  new Chart(el,{{type:'line',data:{{labels,datasets:[
    {{label:'Ratio',data:ratio,borderColor:col,borderWidth:1.5,pointRadius:0,tension:.1,fill:false}},
    {{label:'Upper',data:up,borderColor:'#1E8449',borderWidth:1,borderDash:[3,2],pointRadius:0,tension:0}},
    {{label:'Lower',data:lo,borderColor:'#922B21',borderWidth:1,borderDash:[3,2],pointRadius:0,tension:0}}
  ]}},options:{{responsive:true,maintainAspectRatio:false,animation:false,
    plugins:{{legend:{{display:false}},tooltip:{{mode:'index',intersect:false,
      callbacks:{{label:c=>`${{c.dataset.label}}: ${{c.raw?.toFixed(4)??'–'}}`}}}}}},
    scales:{{x:{{ticks:{{maxTicksLimit:4,font:{{size:8}}}},grid:{{display:false}}}},y:{{ticks:{{maxTicksLimit:4,font:{{size:8}}}},grid:{{color:'#F0F0F0'}}}}}}}}
  }});
}}
{ratio_js}
</script>
</body></html>"""


for u in UNIVERSES:
    run(u)
print(f"\n[{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}]  All dashboards updated.")
