"""Offline and Streamlit reports built from persisted accounting evidence."""
from __future__ import annotations
from dataclasses import asdict, is_dataclass
from pathlib import Path
from types import SimpleNamespace
import html
import json
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from aster.analytics import metrics, monthly_returns, rolling_statistics

COLORS = ['#62e6bb', '#77aaff', '#ffb968', '#ff6b85', '#c397ff']


def _figure(title):
    fig = go.Figure()
    fig.update_layout(template='plotly_dark', title={'text':title, 'font':{'size':18}},
                      paper_bgcolor='#101a2b', plot_bgcolor='#101a2b',
                      colorway=COLORS, height=350, margin=dict(l=55,r=25,t=58,b=45),
                      font=dict(family='Inter, Arial, sans-serif',color='#c7d3e5'),
                      legend=dict(orientation='h',y=1.12,x=0), hovermode='x unified')
    fig.update_xaxes(gridcolor='#223047')
    fig.update_yaxes(gridcolor='#223047')
    return fig


def align_benchmark(equity, benchmark):
    """Only past benchmark observations may be carried to a portfolio timestamp."""
    if benchmark is None or benchmark.empty or 'timestamp' not in benchmark:
        return pd.DataFrame()
    right = benchmark.copy()
    right['timestamp'] = pd.to_datetime(right.timestamp, utc=True)
    if right.timestamp.duplicated().any():
        raise ValueError('Benchmark timestamps must be unique')
    left = equity[['timestamp']].copy()
    left['timestamp'] = pd.to_datetime(left.timestamp, utc=True)
    return pd.merge_asof(left.sort_values('timestamp'), right.sort_values('timestamp'),
                         on='timestamp', direction='backward')


def charts(result):
    e, t, f = result.equity, result.trades, result.fills
    figures = {}
    if e.empty:
        return figures
    x = pd.to_datetime(e.timestamp, utc=True)
    fig = _figure('Portfolio equity · reporting currency')
    fig.add_trace(go.Scatter(x=x,y=e.equity,name='Portfolio',line=dict(width=2.5)))
    benchmark = align_benchmark(e, getattr(result,'benchmark',None))
    if not benchmark.empty:
        for col in benchmark.columns:
            if col == 'timestamp' or not pd.api.types.is_numeric_dtype(benchmark[col]):
                continue
            valid = benchmark[col].dropna()
            if len(valid) and valid.iloc[0] > 0:
                # Rebase to portfolio equity at first available benchmark time.
                first_idx = valid.index[0]
                scaled = benchmark[col]/valid.iloc[0]*float(e.equity.iloc[first_idx])
                fig.add_trace(go.Scatter(x=benchmark.timestamp,y=scaled,name=col,
                                         line=dict(width=1.5,dash='dot')))
    figures['equity'] = fig
    fig = _figure('Drawdown · underwater')
    dd = e.equity/e.equity.cummax()-1
    fig.add_trace(go.Scatter(x=x,y=dd,fill='tozeroy',name='Drawdown',line_color=COLORS[3]))
    fig.update_yaxes(tickformat='.1%')
    figures['drawdown'] = fig
    last = e.iloc[-1]
    get = lambda name:float(last.get(name,0))
    trading = get('realized_pnl')+get('unrealized_pnl')
    slipped = get('slippage_cost')
    fig = _figure('P&L bridge · reference prices to net equity change')
    fig.add_trace(go.Waterfall(x=['Reference trading P&L','Execution slippage','Trading fees','Funding','Liquidation fees','Net P&L'],
                              y=[trading+slipped,-slipped,-get('trading_fees'),get('funding_pnl'),-get('liquidation_fees'),0],
                              measure=['relative']*5+['total'],
                              increasing=dict(marker_color=COLORS[0]),decreasing=dict(marker_color=COLORS[3]),
                              totals=dict(marker_color=COLORS[1])))
    figures['attribution'] = fig
    for key,title,cols in [('leverage','Leverage · notional / equity',['gross_leverage']),
                            ('exposure','Long / short / net exposure',['long_exposure','short_exposure','net_exposure'])]:
        fig = _figure(title)
        for col in cols:
            if col in e:
                values = -e[col] if col == 'short_exposure' else e[col]
                fig.add_trace(go.Scatter(x=x,y=values,name=col.replace('_',' ').title()))
        figures[key] = fig
    for key,label in [('symbol','Symbol contribution · closed net P&L'),('exchange','Exchange contribution · closed net P&L')]:
        fig = _figure(label)
        if {key,'net_pnl'} <= set(t) and len(t):
            values = t.groupby(key).net_pnl.sum().sort_values()
            fig.add_trace(go.Bar(x=values.index,y=values.values,
                                marker_color=[COLORS[0] if v >= 0 else COLORS[3] for v in values]))
        figures[key] = fig
    fig = _figure('Monthly returns · UTC')
    month = monthly_returns(e)
    if len(month):
        table = month.pivot(index='year',columns='month',values='return').reindex(columns=range(1,13))
        fig.add_trace(go.Heatmap(z=table.to_numpy(),x=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],
                                y=[str(y) for y in table.index],colorscale=[[0,COLORS[3]],[.5,'#172238'],[1,COLORS[0]]],zmid=0,
                                text=table.map(lambda v:f'{v:.1%}' if pd.notna(v) else '').to_numpy(),texttemplate='%{text}',
                                hovertemplate='%{y} %{x}<br>%{z:.2%}<extra></extra>'))
    figures['monthly'] = fig
    rolling = rolling_statistics(e)
    for col,label in [('rolling_sharpe','Rolling Sharpe · 30 UTC days'),('rolling_volatility','Rolling volatility · 30 UTC days'),
                      ('rolling_return','Rolling return · 30 UTC days'),('rolling_drawdown','Rolling max drawdown · 30 UTC days')]:
        fig = _figure(label)
        fig.add_trace(go.Scatter(x=rolling.timestamp,y=rolling[col],name=label))
        if col != 'rolling_sharpe':fig.update_yaxes(tickformat='.1%')
        figures[col] = fig
    fig = _figure('Closed-trade P&L distribution')
    if 'net_pnl' in t:
        fig.add_trace(go.Histogram(x=t.net_pnl,name='Net P&L',marker_color=COLORS[1],nbinsx=40))
    figures['trade_distribution'] = fig
    fig = _figure('Holding duration · seconds')
    if 'holding_seconds' in t:
        fig.add_trace(go.Histogram(x=t.holding_seconds,name='Seconds',marker_color=COLORS[4],nbinsx=40))
    figures['holding_duration'] = fig
    fig = _figure('Execution costs and funding · separate ledger totals')
    maker = float(f.loc[f.liquidity_type.eq('maker'),'fee'].sum()) if {'fee','liquidity_type'} <= set(f) else 0
    taker = float(f.loc[f.liquidity_type.eq('taker'),'fee'].sum()) if {'fee','liquidity_type'} <= set(f) else 0
    fig.add_trace(go.Bar(x=['Maker fees','Taker fees','Funding paid (negative = received)','Diagnostic slippage'],
                        y=[maker,taker,-get('funding_pnl'),slipped],marker_color=COLORS[:4]))
    figures['costs'] = fig
    return figures


CARD_KEYS = [('total_return','Total return','pct'),('cagr','CAGR','pct'),('sharpe','Sharpe','num'),
             ('sortino','Sortino','num'),('max_drawdown','Max drawdown','pct'),('profit_factor','Profit factor','num'),
             ('trading_pnl','Trading P&L','money'),('funding_pnl','Funding P&L','money'),('trading_fees','Trading fees','money'),
             ('slippage_cost','Diagnostic slippage','money'),('liquidation_count','Liquidations','int'),('turnover','Turnover','money')]


def format_value(value, kind='num'):
    if value is None or pd.isna(value):return '—'
    if kind == 'pct':return f'{value:.2%}'
    if kind == 'int':return f'{value:,.0f}'
    return f'{value:,.2f}'


def _plain(value):
    if is_dataclass(value):return asdict(value)
    if isinstance(value,dict):return value
    if hasattr(value,'__dict__'):return vars(value)
    return value


def write_html(result, path, metrics_dict=None):
    m = metrics_dict if metrics_dict is not None else metrics(result.equity,result.trades,result.fills)
    cards = ''.join(f'<div class="card"><span>{label}</span><strong>{html.escape(format_value(m.get(key),kind))}</strong></div>' for key,label,kind in CARD_KEYS)
    parts = []
    for i,(name,fig) in enumerate(charts(result).items()):
        parts.append('<section class="chart">'+pio.to_html(fig,full_html=False,include_plotlyjs=True if i==0 else False,config={'displaylogo':False})+'</section>')
    provenance = {'strategy':getattr(result,'strategy','saved run'), 'configuration':_plain(getattr(result,'config',{})),
                  'data_quality':getattr(result,'quality',{}), 'metadata':getattr(result,'metadata',{})}
    evidence = html.escape(json.dumps(provenance,indent=2,default=str))
    source = str(getattr(result, 'metadata', {}).get('data_source', 'Data source: inspect run provenance'))
    counts = ' · '.join(f'{name}: {len(getattr(result,name,pd.DataFrame())):,}' for name in ['trades','fills','funding','events'])
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Aster · Crypto research</title><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#080f1c;color:#dbe5f5;font-family:Inter,Arial,sans-serif}}main{{max-width:1500px;margin:auto;padding:36px}}.eyebrow{{letter-spacing:3px;color:#62e6bb;font-size:12px}}h1{{font-size:34px;margin:12px 0}}.sub{{color:#8ea0ba;line-height:1.6}}.cards{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin:26px 0}}.card{{padding:20px 16px;border:1px solid #253249;border-radius:12px;background:#101a2b}}.card span{{display:block;color:#96a8c2;font-size:12px}}.card strong{{display:block;margin-top:14px;font-size:23px}}.charts{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.chart{{overflow:hidden;border:1px solid #253249;border-radius:12px;background:#101a2b}}.chart:first-child{{grid-column:1/-1}}details{{margin-top:24px;padding:20px;background:#101a2b;border:1px solid #253249;border-radius:12px}}pre{{white-space:pre-wrap;word-break:break-word;font-size:12px;color:#a9bad1}}@media(max-width:1000px){{.cards{{grid-template-columns:repeat(3,1fr)}}}}@media(max-width:650px){{main{{padding:16px}}.cards{{grid-template-columns:repeat(2,1fr)}}.charts{{display:block}}.chart{{margin-bottom:16px}}}}
    </style></head><body><main><div class="eyebrow">ASTER / CRYPTO RESEARCH</div><h1>{html.escape(str(getattr(result,'strategy','Backtest')))}</h1><div class="sub">{html.escape(source)} · execution costs visible · UTC timestamps<br>{counts}</div><div class="cards">{cards}</div><p class="sub">Executed-price trading P&L already includes slippage. The bridge adds back diagnostic slippage to reference prices before subtracting it once. Closed-trade attribution excludes open positions. Annualized ratios on short samples are unstable.</p><div class="charts">{''.join(parts)}</div><details open><summary>Execution assumptions, data quality and reproducibility</summary><pre>{evidence}</pre></details></main></body></html>'''
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(document)
    return target


def load_result(directory):
    directory=Path(directory)
    frames={}
    for name in ['equity','trades','fills','funding','events','positions']:
        file=directory/f'{name}.csv'
        try:frames[name]=pd.read_csv(file) if file.exists() else pd.DataFrame()
        except pd.errors.EmptyDataError:frames[name]=pd.DataFrame()
    if frames['equity'].empty:raise ValueError('Run has no equity.csv observations')
    metadata=json.loads((directory/'metadata.json').read_text()) if (directory/'metadata.json').exists() else {}
    saved=json.loads((directory/'metrics.json').read_text()) if (directory/'metrics.json').exists() else None
    benchmark=pd.read_csv(directory/'benchmark.csv') if (directory/'benchmark.csv').exists() else None
    return SimpleNamespace(**frames,metadata=metadata,quality=metadata.get('data_quality',metadata.get('quality',{})),
                           config=metadata.get('engine',metadata.get('config',metadata.get('configuration',{}))),strategy=metadata.get('strategy',directory.name),
                           benchmark=benchmark),saved


def app():
    import streamlit as st
    st.set_page_config(page_title='Aster · Crypto research',page_icon='✦',layout='wide')
    st.markdown('<style>.stApp{background:#080f1c} [data-testid="stMetric"]{background:#101a2b;padding:18px;border:1px solid #253249;border-radius:10px}</style>',unsafe_allow_html=True)
    st.sidebar.title('ASTER / RESEARCH')
    root=Path(st.sidebar.text_input('Results directory','results'))
    runs=sorted([p for p in root.iterdir() if p.is_dir() and (p/'equity.csv').exists()],reverse=True) if root.exists() else []
    if (root/'equity.csv').exists():runs=[root]+runs
    if not runs:
        st.title('Aster · Crypto research');st.info('Run a backtest first, then select its results directory.');return
    chosen=st.sidebar.selectbox('Saved run',runs,format_func=lambda p:p.name)
    try:result,saved=load_result(chosen)
    except (ValueError,OSError,json.JSONDecodeError) as error:st.error(str(error));return
    st.title(str(result.strategy))
    source = str(result.metadata.get('data_source', 'Data source: inspect run provenance'))
    if 'synthetic' in source.lower():st.warning(source)
    else:st.caption(source)
    st.caption(f'{chosen} · timestamps shown in UTC · reporting currency follows run metadata')
    uploaded=st.sidebar.file_uploader('Benchmark CSV (timestamp + equity or named price columns)',type='csv')
    if uploaded is not None:
        try:
            result.benchmark=pd.read_csv(uploaded)
            align_benchmark(result.equity,result.benchmark)
            st.sidebar.caption('Past observations only; no backward filling from future data. Benchmarks rebase at first overlap.')
        except (ValueError,KeyError) as error:st.error(f'Invalid benchmark: {error}');result.benchmark=None
    m=saved or metrics(result.equity,result.trades,result.fills)
    for start in [0,6]:
        columns=st.columns(6)
        for col,(key,label,kind) in zip(columns,CARD_KEYS[start:start+6]):col.metric(label,format_value(m.get(key),kind))
    st.caption('Slippage is diagnostic and already embedded in executed-price trading P&L. Cost bridge subtracts it once from reference prices. Short-run annualized ratios may be unstable.')
    analytics,ledgers,assumptions=st.tabs(['Performance & costs','Ledger explorer','Assumptions & evidence'])
    with analytics:
        figures=charts(result)
        if 'equity' in figures:st.plotly_chart(figures.pop('equity'),width='stretch')
        items=list(figures.items())
        for i in range(0,len(items),2):
            for col,(_,fig) in zip(st.columns(2),items[i:i+2]):col.plotly_chart(fig,width='stretch')
    with ledgers:
        name=st.selectbox('Ledger',['trades','fills','funding','events','positions','equity'])
        ledger=getattr(result,name).copy()
        filters=st.columns(2)
        for col,key in zip(filters,['exchange','symbol']):
            if key in ledger:
                selected=col.multiselect(key.title(),sorted(ledger[key].dropna().astype(str).unique()))
                if selected:ledger=ledger[ledger[key].astype(str).isin(selected)]
        st.caption(f'{len(ledger):,} rows · ledger filters do not recalculate portfolio-level metrics')
        st.dataframe(ledger,width='stretch')
        st.download_button('Download selected ledger CSV',ledger.to_csv(index=False),file_name=f'{name}.csv',mime='text/csv')
    with assumptions:
        st.subheader('Run provenance');st.json(result.metadata)
        st.subheader('Data quality');st.json(result.quality)
        st.subheader('Execution and risk configuration');st.json(result.config)
        st.info('OHLC candles cannot establish intrabar queue priority. Review configured fill, latency, funding and margin assumptions before interpreting returns. Historical universe and data gaps remain part of research validity.')
