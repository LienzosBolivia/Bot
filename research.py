"""Laboratorio BTC/BNB. Integración del ensayo proporcionado; solo desarrollo."""
import io
import zipfile
import requests
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import norm, skew, kurtosis
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

FEE_RATE = 0.0008
DATA_START = pd.Timestamp('2024-10-31 00:00:00')
DATA_END = pd.Timestamp('2026-09-30 15:00:00')
TIMEFRAME = '1h'
BASE_URL = 'https://data.binance.vision/data'
COLS_ACT = ['BTC', 'BNB', 'BTC_SPOT', 'BNB_SPOT']


def _session():
    s = requests.Session()
    retry = Retry(total=3, connect=3, read=3, backoff_factor=0.75,
                  status_forcelist=[429, 500, 502, 503, 504])
    s.mount('https://', HTTPAdapter(max_retries=retry))
    return s


def _monthly_csv(session, market, kind, symbol, year_month):
    if kind == 'klines':
        prefix = 'spot' if market == 'spot' else 'futures/um'
        rel = f'{prefix}/monthly/klines/{symbol}/{TIMEFRAME}/{symbol}-{TIMEFRAME}-{year_month}.zip'
    elif kind == 'fundingRate' and market == 'futures':
        rel = f'futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{year_month}.zip'
    else:
        raise ValueError((market, kind))
    url = f'{BASE_URL}/{rel}'
    response = session.get(url, timeout=(10, 45))
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith('.csv')]
        if len(names) != 1:
            raise RuntimeError(f'Archivo CSV ambiguo: {url}: {names}')
        with archive.open(names[0]) as csv_data:
            if kind == 'klines':
                raw = pd.read_csv(csv_data, header=None, low_memory=False)
                if raw.shape[1] < 5:
                    raise RuntimeError(f'Klines sin suficientes columnas: {url}')
                out = raw.iloc[:, [0, 4]].copy()
            else:
                raw = pd.read_csv(csv_data)
                raw.columns = [str(c).strip() for c in raw.columns]
                if not {'calc_time', 'last_funding_rate'}.issubset(raw.columns):
                    raise RuntimeError(f'Columnas funding inesperadas: {url}, {raw.columns.tolist()}')
                out = raw[['calc_time', 'last_funding_rate']].copy()
            out.columns = ['timestamp', 'value']
    out['timestamp'] = pd.to_numeric(out['timestamp'], errors='coerce')
    out['value'] = pd.to_numeric(out['value'], errors='coerce')
    out = out.dropna(subset=['timestamp', 'value'])
    if out.empty:
        raise RuntimeError(f'No hay observaciones validas: {url}')
    timestamps = out['timestamp'].astype('int64').to_numpy()
    ts_ms = np.where(np.abs(timestamps) >= 100_000_000_000_000, timestamps // 1000, timestamps)
    out['timestamp'] = pd.to_datetime(ts_ms, unit='ms', utc=True).tz_localize(None)
    if kind == 'fundingRate':
        nearest = out['timestamp'].dt.round('h')
        offset = (out['timestamp'] - nearest).abs().max()
        if offset > pd.Timedelta(seconds=1):
            raise RuntimeError(f'Evento funding lejos de hora exacta ({offset}): {url}')
        out['timestamp'] = nearest
    out = out.set_index('timestamp')['value'].sort_index()
    if out.index.has_duplicates:
        raise RuntimeError(f'Fechas duplicadas en archivo: {url}')
    return out


def _load_series(session, market, kind, symbol):
    months = pd.period_range(DATA_START, DATA_END, freq='M')
    chunks = [_monthly_csv(session, market, kind, symbol, str(m)) for m in months]
    out = pd.concat(chunks).sort_index()
    if out.index.has_duplicates:
        raise RuntimeError(f'Timestamps duplicados entre meses: {market} {kind} {symbol}')
    if out.isna().any() or not np.isfinite(out.to_numpy()).all():
        raise RuntimeError(f'Datos no finitos: {market} {kind} {symbol}')
    if kind == 'klines' and (out <= 0).any():
        raise RuntimeError(f'Precios invalidos: {market} {symbol}')
    print(f'  {market:7s} {kind:11s} {symbol}: {len(chunks)}/{len(months)} meses; {len(out)} filas', flush=True)
    return out


def _verify_funding_calendar(funding, symbol):
    window = funding.loc[DATA_START:DATA_END]
    if window.empty:
        raise RuntimeError(f'Sin funding para {symbol}')
    expected = pd.date_range(DATA_START, DATA_END, freq='8h')
    missing, extra = expected.difference(window.index), window.index.difference(expected)
    if len(missing) or len(extra):
        raise RuntimeError(f'Calendario funding {symbol} inesperado: {len(missing)} eventos ausentes, '
                           f'{len(extra)} fuera de patron. Revisar cambios reales de intervalo antes de simular.')
    if not window.index.isin(pd.date_range(DATA_START, DATA_END, freq='h')).all():
        raise RuntimeError(f'Eventos funding sin alineacion horaria: {symbol}')
    return window


def construir_datos_limpios():
    expected_hours = pd.date_range(DATA_START, DATA_END, freq='h')
    if len(expected_hours) < 100:
        raise ValueError('Rango temporal demasiado corto')
    with _session() as session:
        sources = {}
        for asset, symbol in [('btc', 'BTCUSDT'), ('bnb', 'BNBUSDT')]:
            sources[f'{asset}_spot_close'] = _load_series(session, 'spot', 'klines', symbol)
            sources[f'{asset}_close'] = _load_series(session, 'futures', 'klines', symbol)
            sources[f'{asset}_funding'] = _load_series(session, 'futures', 'fundingRate', symbol)
    market = pd.DataFrame(index=expected_hours)
    for col in ['btc_spot_close', 'bnb_spot_close', 'btc_close', 'bnb_close']:
        market[col] = sources[col].reindex(expected_hours)
    nulls = market.isna().sum()
    if nulls.any():
        raise RuntimeError(f'Faltan velas de mercado (no se rellenan):\n{nulls[nulls > 0]}')
    for asset in ['btc', 'bnb']:
        funding = _verify_funding_calendar(sources[f'{asset}_funding'], asset)
        market[f'{asset}_fund_event'] = funding.reindex(expected_hours).fillna(0.0)
        market[f'{asset}_fund_last'] = funding.reindex(expected_hours).ffill()
        if market[f'{asset}_fund_last'].isna().any():
            raise RuntimeError(f'Falta funding inicial de {asset}; ajustar rango')
    if not market.index.equals(expected_hours):
        raise RuntimeError('El indice horario se ha modificado')
    for asset in ['btc', 'bnb']:
        eq_ratio = (market[f'{asset}_spot_close'] == market[f'{asset}_close']).mean()
        base_bps = (market[f'{asset}_close'] / market[f'{asset}_spot_close'] - 1.0) * 1e4
        print(f'{asset.upper()}: spot=futuros {eq_ratio:.4%} de velas; base media={base_bps.mean():.3f} bps; '
              f'min={base_bps.min():.3f}; max={base_bps.max():.3f}')
        if eq_ratio > 0.9999:
            raise RuntimeError(f'SPOT/PERP IDENTICOS para {asset}: detener backtest')
    return market, sources


def auditar_spot_vs_futuros(data):
    for asset in ['btc', 'bnb']:
        igual = (data[f'{asset}_spot_close'] == data[f'{asset}_close']).mean()
        base = (data[f'{asset}_close'] / data[f'{asset}_spot_close'] - 1.0) * 1e4
        corr = data[f'{asset}_spot_close'].pct_change().corr(data[f'{asset}_close'].pct_change())
        print(f'{asset.upper()}: velas idénticas={igual:.4%} | base bps media={base.mean():.2f} '
              f'std={base.std():.2f} min={base.min():.2f} max={base.max():.2f} | corr retornos={corr:.4f}')
        assert igual < 0.9999, f'Spot y perpetuo idénticos en {asset}'


def compute_regime_features(data):
    feat = pd.DataFrame(index=data.index)
    ret_btc, ret_bnb = data.btc_close.pct_change(), data.bnb_close.pct_change()
    feat['vol_72h'] = ret_btc.rolling(72).std() * np.sqrt(24 * 365)
    feat['vol_ratio'] = feat.vol_72h / (ret_btc.rolling(336).std() * np.sqrt(24 * 365) + 1e-8)
    direction = (data.btc_close - data.btc_close.shift(72)).abs()
    volatility = data.btc_close.diff().abs().rolling(72).sum()
    feat['er_72h'] = direction / (volatility + 1e-8)
    feat['mom_72h'] = data.btc_close.pct_change(72)
    feat['spread_bnb_btc'] = ret_bnb.rolling(72).sum() - ret_btc.rolling(72).sum()
    feat['funding_ann_72h'] = data.btc_fund_last.rolling(72).mean() * 3 * 365
    f_z = (feat.funding_ann_72h - feat.funding_ann_72h.rolling(336).mean()) / (feat.funding_ann_72h.rolling(336).std() + 1e-8)
    conditions = [f_z.abs() > 1.75, (feat.er_72h > 0.22) & (feat.mom_72h > 0),
                  (feat.er_72h > 0.22) & (feat.mom_72h <= 0)]
    feat['regime_id'] = np.select(conditions, [3, 1, 2], default=0)
    return feat.dropna()


def _maquina_estados(long_in, short_in, long_out, short_out, update_mask=None):
    li, si, lo, so = [np.asarray(x, dtype=bool) for x in [long_in, short_in, long_out, short_out]]
    upd = np.ones(len(li), dtype=bool) if update_mask is None else np.asarray(update_mask, dtype=bool)
    pos, p = np.zeros(len(li)), 0.0
    for i in range(len(li)):
        if upd[i]:
            if p == 0.0:
                if li[i] and not si[i]: p = 1.0
                elif si[i] and not li[i]: p = -1.0
            elif p == 1.0:
                if si[i]: p = -1.0
                elif lo[i]: p = 0.0
            else:
                if li[i]: p = 1.0
                elif so[i]: p = 0.0
        pos[i] = p
    return pos


def _buffer_rebalanceo(objetivo, ancho=0.5):
    obj = np.nan_to_num(np.asarray(objetivo, dtype=float))
    out, w = np.zeros(len(obj)), 0.0
    for i in range(len(obj)):
        if abs(obj[i] - w) >= ancho: w = obj[i]
        out[i] = w
    return out


def _a_posicion(arr, index):
    return pd.Series(arr, index=index).shift(1).fillna(0.0)


def generate_research_candidates(data):
    """18 candidatas originales; posiciones desplazadas una fila."""
    index = data.index
    close_btc, close_bnb = data.btc_close, data.bnb_close
    ret_btc, ret_bnb = close_btc.pct_change().fillna(0.0), close_bnb.pct_change().fillna(0.0)
    f_btc, f_bnb = data.btc_fund_last, data.bnb_fund_last
    fund_upd = index.hour % 8 == 0
    positions, metadata = {}, {}
    def add(name, pos, family):
        positions[name] = _a_posicion(pos, index)
        metadata[name] = {'family': family}
    band = 4.0 * FEE_RATE
    for fast, slow in [(12, 48), (24, 96), (36, 144)]:
        ema_f, ema_s = close_btc.ewm(span=fast, adjust=False).mean(), close_btc.ewm(span=slow, adjust=False).mean()
        d = (ema_f - ema_s) / (ema_s + 1e-8)
        add(f'Trend_EMA_{fast}_{slow}', _maquina_estados(d > band, d < -band, d <= 0, d >= 0), 'Trend')
    for window in [24, 48, 72]:
        upper, lower = close_btc.rolling(window).max().shift(1), close_btc.rolling(window).min().shift(1)
        raw = pd.Series(np.where(close_btc > upper, 1.0, np.where(close_btc < lower, -1.0, np.nan)), index=index).ffill().fillna(0.0)
        add(f'Breakout_{window}h', raw, 'Breakout')
    for window, z_thresh in [(24, 2.0), (48, 2.2), (72, 2.5)]:
        z = (close_btc - close_btc.rolling(window).mean()) / (close_btc.rolling(window).std() + 1e-8)
        add(f'MeanRev_{window}h_Z{z_thresh}', _maquina_estados(z < -z_thresh, z > z_thresh, z >= -0.4, z <= 0.4), 'MeanRev')
    spread = np.log(close_btc / close_bnb)
    for window, z_t in [(48, 1.8), (96, 2.0)]:
        z = (spread - spread.rolling(window).mean()) / (spread.rolling(window).std() + 1e-8)
        add(f'RelVal_BTC_BNB_{window}h', _maquina_estados(z < -z_t, z > z_t, z >= -0.25, z <= 0.25), 'RelativeValue')
    for window in [48, 96]:
        mom = close_btc.pct_change(window)
        vol = ret_btc.rolling(window).std() * np.sqrt(24 * 365) + 1e-8
        scaled = np.clip((mom / (vol / np.sqrt(365 * 24 / window))) * 0.5, -1.0, 1.0)
        objetivo = np.round(scaled.to_numpy() * 4.0) / 4.0
        add(f'VolTarget_Mom_{window}h', _buffer_rebalanceo(objetivo, ancho=0.5), 'VolMomentum')
    for f_win, z_thresh in [(72, 1.6), (144, 1.9)]:
        z = (f_btc - f_btc.rolling(f_win).mean()) / (f_btc.rolling(f_win).std() + 1e-8)
        mom = close_btc.pct_change(12)
        pos = _maquina_estados((z < -z_thresh) & (mom >= -0.002), (z > z_thresh) & (mom <= 0.002), z >= -0.3, z <= 0.3, fund_upd)
        add(f'Funding_Exhaustion_{f_win}h_Z{z_thresh}', pos, 'FundingExhaustion')
    f_diff = f_btc - f_bnb
    for f_win in [72, 168]:
        z = f_diff.rolling(f_win).mean() / (f_diff.rolling(f_win).std() + 1e-8)
        sp_mom = spread.diff(24)
        pos = _maquina_estados((z < -0.75) & (sp_mom > -0.025), (z > 0.75) & (sp_mom < 0.025), z >= -0.2, z <= 0.2, fund_upd)
        add(f'RelVal_FundingCarry_{f_win}h', pos, 'FundingCarry')
    if 'btc_spot_close' in data.columns:
        f_med, nada = f_btc.rolling(168).mean(), np.zeros(len(index), dtype=bool)
        add('Carry_BTC_SpotPerp', _maquina_estados(f_med > 0.00005, nada, f_med < -0.00005, nada, fund_upd), 'SpotPerpCarry')
    vol_b, vol_n = ret_btc.rolling(72).std().shift(1), ret_bnb.rolling(72).std().shift(1)
    inv_b, inv_n = 1.0 / (vol_b + 1e-8), 1.0 / (vol_n + 1e-8)
    wb = (inv_b / (inv_b + inv_n)).where(index.hour == 0).ffill()
    wb = ((wb * 20).round() / 20).fillna(0.5).clip(0.2, 0.8)
    positions['_w_btc_rv'], positions['_w_bnb_rv'] = wb, 1.0 - wb
    positions['CASH_NO_TRADE'] = pd.Series(0.0, index=index)
    return pd.DataFrame(positions), metadata


def estrategia_a_pesos(nombre, posiciones, tramo):
    p = posiciones[nombre].iloc[tramo].astype(float)
    w = pd.DataFrame(0.0, index=p.index, columns=COLS_ACT)
    if nombre.startswith('RelVal_'):
        wb = posiciones['_w_btc_rv'].iloc[tramo].astype(float) if '_w_btc_rv' in posiciones.columns else pd.Series(0.5, index=p.index)
        w['BTC'], w['BNB'] = wb * p, -(1.0 - wb) * p
    elif nombre.startswith('Carry_BTC_SpotPerp'):
        w['BTC_SPOT'], w['BTC'] = 0.5 * p, -0.5 * p
    elif nombre != 'CASH_NO_TRADE':
        w['BTC'] = p
    return w


def _retornos_y_funding(data):
    px = pd.DataFrame(index=data.index)
    px['BTC'], px['BNB'] = data.btc_close, data.bnb_close
    px['BTC_SPOT'] = data.btc_spot_close if 'btc_spot_close' in data.columns else data.btc_close
    px['BNB_SPOT'] = data.bnb_spot_close if 'bnb_spot_close' in data.columns else data.bnb_close
    f = pd.DataFrame(0.0, index=data.index, columns=COLS_ACT)
    f['BTC'], f['BNB'] = data.btc_fund_event.fillna(0.0), data.bnb_fund_event.fillna(0.0)
    return px.pct_change().fillna(0.0), f


def compute_historical_net_returns(data, pos_df, fee=FEE_RATE):
    r, f = _retornos_y_funding(data)
    net = {}
    for col in pos_df.columns:
        if col.startswith('_'): continue
        if col == 'CASH_NO_TRADE':
            net[col] = pd.Series(0.0, index=pos_df.index)
            continue
        w = estrategia_a_pesos(col, pos_df, slice(0, len(pos_df)))
        giro = w.diff().abs().sum(axis=1).fillna(0.0)
        net[col] = (w * r).sum(axis=1) - (w.shift(1).fillna(0.0) * f).sum(axis=1) - fee * giro
    return pd.DataFrame(net, index=pos_df.index)


def simular_ciclo_portafolio(pesos, retornos_activos, funding_eventos, pesos_anteriores, fee=FEE_RATE, max_dd=-0.04):
    anterior = np.asarray(pesos_anteriores, dtype=float).copy()
    equity, pico = 1.0, 1.0
    resultados = pd.Series(0.0, index=pesos.index)
    for t in pesos.index:
        objetivo = pesos.loc[t, COLS_ACT].to_numpy(dtype=float)
        retorno = retornos_activos.loc[t, COLS_ACT].to_numpy(dtype=float)
        f_ev = funding_eventos.loc[t, COLS_ACT].to_numpy(dtype=float)
        coste = fee * np.abs(objetivo - anterior).sum()
        neto = float(objetivo @ retorno - anterior @ f_ev - coste)
        if neto <= -1.0: raise ValueError('Posible liquidación detectada.')
        equity_estimada = equity * (1.0 + neto)
        dd = equity_estimada / max(pico, equity_estimada) - 1.0
        if dd <= max_dd:
            neto = (1.0 + neto) * (1.0 - fee * np.abs(objetivo).sum()) - 1.0
            resultados.loc[t] = neto
            anterior = np.zeros(len(COLS_ACT))
            break
        resultados.loc[t] = neto
        equity, pico, anterior = equity_estimada, max(pico, equity_estimada), objetivo
    return resultados, anterior


def calibrated_dsr_and_validation(window_returns_df):
    n_days = len(window_returns_df) // 24
    daily = {c: np.prod(1.0 + window_returns_df[c].iloc[:n_days * 24].to_numpy().reshape(n_days, 24), axis=1) - 1.0 for c in window_returns_df.columns}
    df_daily = pd.DataFrame(daily)
    T_d, M = len(df_daily), len(df_daily.columns)
    corr_m = df_daily.corr().fillna(0.0)
    avg_corr = np.clip((corr_m.values.sum() - M) / max(1, M * (M - 1)), 0.0, 0.95)
    n_eff = max(2.0, 1.0 + (M - 1) * (1.0 - avg_corr))
    euler = 0.5772156649
    z_max = (1.0 - euler) * norm.ppf(1.0 - 1.0 / n_eff) + euler * norm.ppf(1.0 - 1.0 / (n_eff * np.e))
    sr_benchmark = z_max / np.sqrt(T_d)
    metrics, half = {}, T_d // 2
    for col in df_daily.columns:
        s = df_daily[col]
        std_s = s.std(ddof=1)
        if std_s < 1e-9:
            metrics[col] = dict(dsr=0.0, roi=0.0, mdd=0.0, subperiod_ok=False, sr_ann=0.0)
            continue
        sr_d = float(s.mean() / std_s)
        rho1 = float(np.clip(s.autocorr(lag=1) if len(s) > 5 else 0.0, -0.5, 0.5))
        if np.isnan(rho1): rho1 = 0.0
        ac_factor = np.clip(1.0 + 2.0 * rho1 / (1.0 - rho1 + 1e-8), 0.5, 3.0)
        sk, ku = float(skew(s)), float(kurtosis(s, fisher=False))
        num = (sr_d - sr_benchmark) * np.sqrt(T_d - 1)
        den = np.sqrt(max(1e-9, ac_factor * (1.0 - sk * sr_d + ((ku - 1.0) / 4.0) * sr_d ** 2)))
        eq = (1.0 + window_returns_df[col]).cumprod()
        roi, mdd = float(eq.iloc[-1] - 1.0), float((eq / eq.cummax().clip(lower=1.0) - 1.0).min())
        h1, h2 = float(np.prod(1.0 + s.iloc[:half]) - 1.0), float(np.prod(1.0 + s.iloc[half:]) - 1.0)
        metrics[col] = dict(dsr=float(norm.cdf(num / den)), roi=roi, mdd=mdd,
                            subperiod_ok=(roi > 0 and h1 > -0.05 and h2 > -0.04 and mdd > -0.12), sr_ann=sr_d * np.sqrt(365))
    return pd.DataFrame(metrics).T


def auditar_validador_independiente(data, lookback=2160, ciclo=72, dsr_thresh=0.60):
    feat = compute_regime_features(data)
    pos, _ = generate_research_candidates(data)
    net = compute_historical_net_returns(data, pos).loc[feat.index]
    nombres = [c for c in net.columns if c != 'CASH_NO_TRADE']
    registros = []
    for idx in range(lookback, len(feat) - ciclo + 1, ciclo):
        val = calibrated_dsr_and_validation(net[nombres].iloc[idx - lookback:idx])
        roi, dsr, estab = val.roi > 0, val.dsr > dsr_thresh, val.subperiod_ok.astype(bool)
        registros.append(dict(positivas_netas=int(roi.sum()), pasan_dsr=int(dsr.sum()), pasan_estabilidad=int(estab.sum()),
                              aprobadas_finales=int((roi & dsr & estab).sum()), max_dsr=float(val.dsr.max()), max_sr_anual=float(val.sr_ann.max())))
    audit = pd.DataFrame(registros)
    print(f'\n=== AUDITORÍA DEL VALIDADOR INDEPENDIENTE ({len(audit)} ciclos, desarrollo, 8 familias) ===')
    for col in ['positivas_netas', 'pasan_dsr', 'aprobadas_finales']:
        print(f'Ciclos con >=1 {col}: {(audit[col] > 0).sum()} ({(audit[col] > 0).mean()*100:.1f}%)')
    print(audit.describe().round(4))
    return audit


def run_three_stage_lab_with_funding(data, lookback_hours=2160, cycle_hours=72, dsr_thresh=0.60, max_cycle_dd=-0.04):
    features = compute_regime_features(data)
    pos, _ = generate_research_candidates(data)
    net = compute_historical_net_returns(data, pos).loc[features.index]
    pos = pos.loc[features.index]
    r, f = _retornos_y_funding(data)
    r, f = r.loc[features.index], f.loc[features.index]
    active = [c for c in net.columns if c != 'CASH_NO_TRADE']
    prev = [np.zeros(len(COLS_ACT)) for _ in range(4)]
    current_strat, last_regime = 'CASH_NO_TRADE', -1
    results = []
    log = dict(Rechazo_Validador_DSR=0, Rechazo_Sin_Senal_Activa=0, Rechazo_Selector_Regimen=0, Ejecucion_Activa=0)
    for idx in range(lookback_hours, len(features) - cycle_hours + 1, cycle_hours):
        hist, oos = slice(idx - lookback_hours, idx), slice(idx, idx + cycle_hours)
        win = net[active].iloc[hist]
        val = calibrated_dsr_and_validation(win)
        approved = list(val[(val.roi > 0) & (val.dsr > dsr_thresh) & val.subperiod_ok.astype(bool)].index)
        live = [s for s in approved if abs(float(pos[s].iloc[idx])) > 1e-9]
        scores = {s: float(val.loc[s, 'dsr'] * val.loc[s, 'roi']) for s in live}
        regime = int(features.iloc[idx - 1].regime_id)
        mask = features.regime_id.shift(1).iloc[hist] == regime
        chosen = 'CASH_NO_TRADE'
        if not approved: log['Rechazo_Validador_DSR'] += 1
        elif not live: log['Rechazo_Sin_Senal_Activa'] += 1
        else:
            best = 0.0
            for s in live:
                cond_ret = win[s][mask]
                if len(cond_ret) >= 24:
                    expectancy = cond_ret.mean() / (cond_ret.std() + 1e-8)
                    if expectancy > best: best, chosen = expectancy, s
            log['Rechazo_Selector_Regimen' if chosen == 'CASH_NO_TRADE' else 'Ejecucion_Activa'] += 1
        if regime != last_regime or current_strat not in approved:
            current_strat, last_regime = chosen, regime
        weights = [estrategia_a_pesos(s, pos, oos) for s in [chosen, current_strat, 'CASH_NO_TRADE']]
        total = sum(scores.values())
        if total > 0:
            for s in live: weights[2] += scores[s] / total * estrategia_a_pesos(s, pos, oos)
        wd = pd.DataFrame(0.0, index=weights[0].index, columns=COLS_ACT)
        wd['BTC_SPOT'], wd['BTC'] = 0.5, -0.5
        weights.append(wd)
        outputs = []
        for j, w in enumerate(weights):
            out, prev[j] = simular_ciclo_portafolio(w, r.iloc[oos], f.iloc[oos], prev[j], fee=FEE_RATE, max_dd=max_cycle_dd)
            outputs.append((1.0 + out).prod() - 1.0)
        results.append(dict(timestamp=features.index[idx], Config_A_72h_Selector=outputs[0], Config_B_Regime_Switch=outputs[1],
                            Config_C_Dynamic_Weights=outputs[2], Benchmark_Carry_Pasivo=outputs[3],
                            Benchmark_BTC_Hold=(1.0 + r['BTC'].iloc[oos]).prod() - 1.0, Selected_Strategy=chosen, Regime=regime))
    res = pd.DataFrame(results).set_index('timestamp')
    print('\n=== DECISIONES DEL SISTEMA CON FUNDING RATES (MUESTRA DESARROLLO) ===')
    for k, v in log.items(): print(f'  - {k:26s}: {v:3d} ciclos ({v/len(res)*100:5.1f}%)')
    print('\nFrecuencia de estrategias seleccionadas (Config A):')
    print(res.Selected_Strategy.value_counts())
    return res


def diagnostico_consistencia(data):
    feat = compute_regime_features(data)
    pos, _ = generate_research_candidates(data)
    net = compute_historical_net_returns(data, pos).loc[feat.index]
    pos = pos.loc[feat.index]
    r, f = _retornos_y_funding(data)
    r, f = r.loc[feat.index], f.loc[feat.index]
    errores = {}
    for idx in range(2160, len(feat) - 72, 72 * 7):
        tramo = slice(idx, idx + 72)
        for s in net.columns:
            w = estrategia_a_pesos(s, pos, tramo)
            previo = estrategia_a_pesos(s, pos, slice(idx - 1, idx)).iloc[-1].to_numpy()
            sim, _ = simular_ciclo_portafolio(w, r.iloc[tramo], f.iloc[tramo], previo, fee=FEE_RATE, max_dd=-np.inf)
            err = float(np.max(np.abs(sim.to_numpy() - net[s].iloc[tramo].to_numpy())))
            errores[s] = max(errores.get(s, 0.0), err)
    resultado = pd.Series(errores).sort_values(ascending=False)
    print('\n=== TEST DE CONSISTENCIA: error máximo por estrategia ===')
    print(resultado.to_string())
    assert resultado.max() < 1e-10, 'ERROR: backtest histórico y simulador no producen los mismos retornos.'
    print('OK: contabilidad consistente en las ventanas probadas.')
    return resultado


def diagnostico_cash_and_carry(data, fee=FEE_RATE, umbral_funding=0.0, ventana=72):
    if 'btc_spot_close' not in data.columns:
        print('Cash&Carry omitido: faltan las columnas *_spot_close.')
        return None
    filas = []
    for nombre, c in [('BTC', 'btc'), ('BNB', 'bnb')]:
        rs, rp = data[f'{c}_spot_close'].pct_change().fillna(0.0), data[f'{c}_close'].pct_change().fillna(0.0)
        fe = data[f'{c}_fund_event'].fillna(0.0)
        fm = data[f'{c}_fund_last'].rolling(ventana).mean()
        variantes = {'siempre_activo': pd.Series(1.0, index=data.index),
                     f'solo_si_funding_medio_{ventana}h>{umbral_funding}': (fm > umbral_funding).astype(float)}
        for var, sig in variantes.items():
            pos = sig.shift(1).fillna(0.0)
            base, funding = pos * (rs - rp), pos.shift(1).fillna(0.0) * fe
            costes = -2.0 * fee * pos.diff().abs().fillna(0.0)
            total = base + funding + costes
            anios, eq = len(data) / (24 * 365), (1.0 + total).cumprod()
            filas.append({'activo': nombre, 'variante': var, 'base_%': base.sum()*100, 'funding_%': funding.sum()*100,
                          'costes_%': costes.sum()*100, 'total_%': total.sum()*100,
                          'anualizado_%': (eq.iloc[-1] ** (1.0/anios) - 1.0)*100,
                          'maxDD_%': (eq/eq.cummax()-1.0).min()*100, 'tiempo_activo_%': (pos>0).mean()*100})
    tabla = pd.DataFrame(filas).set_index(['activo', 'variante']).round(2)
    print('\n=== CASH & CARRY PURO (desarrollo, sobre nominal de una pata) ===')
    print(tabla.to_string())
    return tabla


def auditar_penalizacion_dsr(data, lookback=2160, ciclo=72):
    feat = compute_regime_features(data)
    pos, _ = generate_research_candidates(data)
    net = compute_historical_net_returns(data, pos).loc[feat.index]
    nombres = [c for c in net.columns if c != 'CASH_NO_TRADE']
    reg = {c: [] for c in nombres}
    for idx in range(lookback, len(feat) - ciclo + 1, ciclo):
        win = net[nombres].iloc[idx-lookback:idx]
        n = len(win)//24
        for col in nombres:
            vals = win[col].iloc[:n*24].to_numpy().reshape(n, 24)
            s = pd.Series(np.prod(1.0+vals, axis=1)-1.0)
            fila = dict(activos=(s != 0).mean()*100, sr=np.nan, ku=np.nan, t_ku=np.nan, t_sk=np.nan, fac=np.nan)
            if s.std(ddof=1) > 1e-9:
                sr = float(s.mean()/s.std(ddof=1))
                sk, ku = float(skew(s)), float(kurtosis(s, fisher=False))
                t_ku, t_sk = ((ku-1)/4)*sr**2, -sk*sr
                fila.update(sr=sr*np.sqrt(365), ku=ku, t_ku=t_ku, t_sk=t_sk, fac=np.sqrt(max(1e-9, 1+t_sk+t_ku)))
            reg[col].append(fila)
    filas = []
    for col, lista in reg.items():
        d = pd.DataFrame(lista)
        filas.append(dict(Estrategia=col, Dias_Activos_porcentaje=d.activos.mean(), Ventanas_sin_actividad_porcentaje=d.sr.isna().mean()*100,
                          SR_Anual_Medio=d.sr.mean(), SR_Anual_Max=d.sr.max(), Kurtosis_Media=d.ku.mean(),
                          Termino_Curtosis=d.t_ku.mean(), Termino_Asimetria=d.t_sk.mean(), Factor_Den_Medio=d.fac.mean()))
    tabla = pd.DataFrame(filas).set_index('Estrategia').round(3)
    print('\n=== DIAGNÓSTICO 5: INACTIVIDAD, CURTOSIS Y DENOMINADOR DEL DSR ===')
    print(tabla.to_string())
    return tabla


def main(output_dir):
    from pathlib import Path
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    df_clean, fuentes_independientes = construir_datos_limpios()
    split_idx = int(len(df_clean)*0.75)
    df_dev, df_holdout = df_clean.iloc[:split_idx].copy(deep=True), df_clean.iloc[split_idx:].copy(deep=True)
    print(f'\nDatos reconstruidos: {len(df_clean)} velas cerradas')
    print(f'Desarrollo: {len(df_dev)} velas: {df_dev.index.min()} a {df_dev.index.max()}')
    print(f'HOLDOUT SIN EVALUAR: {len(df_holdout)} velas: {df_holdout.index.min()} a {df_holdout.index.max()}')
    assert len(df_clean) == 16792, 'Cambio de cobertura respecto a la ultima ejecucion; revisar periodos'
    assert len(df_dev) == 12594 and len(df_holdout) == 4198
    print('LISTO: fuentes independientes, velas completas, calendario funding y particion verificados')
    auditar_spot_vs_futuros(df_dev)
    audit = auditar_validador_independiente(df_dev)
    audit.to_csv(output_dir/'audit_dev.csv', index=False)
    sim = run_three_stage_lab_with_funding(df_dev)
    sim.to_csv(output_dir/'sim_dev_fund.csv')
    cols = ['Config_A_72h_Selector', 'Config_B_Regime_Switch', 'Config_C_Dynamic_Weights', 'Benchmark_Carry_Pasivo', 'Benchmark_BTC_Hold']
    equity = (1.0+sim[cols]).cumprod()
    equity.to_csv(output_dir/'equity_dev.csv')
    plt.figure(figsize=(12, 6))
    for col in cols: plt.plot(equity.index, equity[col], label=col, linewidth=2.0 if 'Config_A' in col else 1.3)
    plt.title('Muestra de Desarrollo (75%): 18 candidatas (Precio, Valor Relativo, Funding, Carry Spot-Perp)')
    plt.ylabel('Capital Acumulado (Base 1.0)')
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir/'equity_dev.png', dpi=160)
    plt.close()
    print('\n=== MÉTRICAS EN MUESTRA DE DESARROLLO (CON CONTABILIDAD DE FUNDING) ===')
    metrics = []
    for col in cols:
        r = sim[col]
        cagr = ((1.0+r).prod() ** (365.0/(len(r)*3.0))-1.0)*100
        cum = (1.0+r).cumprod()
        mdd = (cum/cum.cummax().clip(lower=1.0)-1.0).min()*100
        sharpe = r.mean()/(r.std()+1e-8)*np.sqrt(365.0/3.0)
        print(f'{col:26s} | CAGR: {cagr:6.2f}% | Max DD: {mdd:6.2f}% | Sharpe: {sharpe:5.2f}')
        metrics.append(dict(config=col, cagr_pct=cagr, max_dd_pct=mdd, sharpe=sharpe))
    pd.DataFrame(metrics).to_csv(output_dir/'metrics_dev.csv', index=False)
    diagnostico_consistencia(df_dev).to_csv(output_dir/'consistencia.csv', header=['error_maximo'])
    cfg = cols[:3]
    activos = sim.loc[sim.Selected_Strategy != 'CASH_NO_TRADE']
    print('\n=== CICLOS ACTIVADOS ===')
    print(activos[['Selected_Strategy', 'Regime']+cfg].to_string())
    print('\n=== DIFERENCIA MÁXIMA ABSOLUTA VS CONFIG A ===')
    print(sim[cfg].sub(sim[cfg[0]], axis=0).abs().max())
    diagnostico_cash_and_carry(df_dev).to_csv(output_dir/'carry_dev.csv')
    auditar_penalizacion_dsr(df_dev).to_csv(output_dir/'diag_dsr.csv')

    from diagnostics_v2 import run as run_v2
    run_v2(df_dev, output_dir)

    from diagnostics_v3 import run as run_v3
    run_v3(df_dev, output_dir)
