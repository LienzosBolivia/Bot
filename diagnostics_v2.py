"""Comparación experimental predefinida; no selecciona ganadores ni usa holdout."""
import numpy as np
import pandas as pd
import research as r


def simulate(weights, returns, funding, previous, fee, max_dd=-0.04):
    previous = np.array(previous, dtype=float)
    equity = peak = 1.0
    stopped = False
    rows = []
    for t in weights.index:
        target = weights.loc[t].to_numpy() if not stopped else np.zeros(4)
        price = float(target @ returns.loc[t].to_numpy())
        fund = -float(previous @ funding.loc[t].to_numpy())
        turnover = float(np.abs(target-previous).sum())
        cost = fee*turnover
        net = price+fund-cost
        if net <= -1: raise ValueError('Pérdida >= capital')
        estimated = equity*(1+net)
        trigger = not stopped and estimated/max(peak, estimated)-1 <= max_dd
        exit_cost = (1+net)*fee*np.abs(target).sum() if trigger else 0.0
        net -= exit_cost
        rows.append(dict(timestamp=t, price=price, funding=fund, fees=cost,
                         exit_fees=exit_cost, turnover=turnover, net=net, kill_switch=trigger))
        equity *= 1+net
        peak = max(peak, equity)
        previous = np.zeros(4) if trigger else target.copy()
        stopped = stopped or trigger
    return pd.DataFrame(rows).set_index('timestamp'), previous


def run(data, output):
    features = r.compute_regime_features(data)
    positions, metadata = r.generate_research_candidates(data)
    historical = r.compute_historical_net_returns(data, positions).loc[features.index]
    positions = positions.loc[features.index]
    returns, funding = r._retornos_y_funding(data)
    returns, funding = returns.loc[features.index], funding.loc[features.index]
    names = list(metadata)
    # Dos hipótesis nuevas, fijadas antes de observar sus resultados.
    variants = ['C_original', 'V2_regime_score', 'V2_alpha_carry']
    states = {(v, extra): np.zeros(4) for v in variants for extra in [0., 0.0002, 0.0005]}
    history, allocations, contributions, validations = [], [], [], []
    for i in range(2160, len(features)-72+1, 72):
        sl = slice(i, i+72)
        win = historical[names].iloc[i-2160:i]
        val = r.calibrated_dsr_and_validation(win)
        mask = features.regime_id.shift(1).iloc[i-2160:i] == features.regime_id.iloc[i-1]
        live = [s for s in names if val.loc[s,'roi'] > 0 and val.loc[s,'dsr'] > .60
                and bool(val.loc[s,'subperiod_ok']) and abs(positions[s].iloc[i]) > 1e-9]
        scores = {s: float(val.loc[s,'dsr']*val.loc[s,'roi']) for s in live}
        filtered = {s: score for s, score in scores.items() if mask.sum() >= 24 and win.loc[mask,s].mean() > 0}
        alpha = {s: score for s, score in filtered.items() if s != 'Carry_BTC_SpotPerp'}
        for s in names:
            validations.append(dict(cycle=features.index[i], strategy=s, **val.loc[s].to_dict(), eligible=s in live))
        for variant in variants:
            selected = scores if variant == 'C_original' else filtered if variant == 'V2_regime_score' else alpha
            total = sum(selected.values())
            mix = {s: score/total for s, score in selected.items()} if total else {}
            # Carry fallback conserva su señal original; efectivo sigue disponible.
            if variant == 'V2_alpha_carry' and not mix and 'Carry_BTC_SpotPerp' in live:
                mix = {'Carry_BTC_SpotPerp': 1.0}
            weights = pd.DataFrame(0., index=features.index[sl], columns=r.COLS_ACT)
            for s, share in mix.items():
                part = share*r.estrategia_a_pesos(s, positions, sl)
                weights += part
                allocations.append(dict(cycle=features.index[i], variant=variant, strategy=s, allocation=share))
                # Atribución bruta de precio planificada. Costes/funding reales se registran a nivel cartera.
                contributions.append(dict(cycle=features.index[i], variant=variant, strategy=s,
                    planned_price_sum=float((part*returns.iloc[sl]).sum().sum())))
            for extra in [0., .0002, .0005]:
                key = variant, extra
                detail, states[key] = simulate(weights, returns.iloc[sl], funding.iloc[sl], states[key], r.FEE_RATE+extra)
                detail['variant'], detail['extra_cost_bps'], detail['cycle'] = variant, extra*10000, features.index[i]
                history.append(detail.reset_index())
    hourly = pd.concat(history, ignore_index=True)
    hourly.to_csv(output/'v2_hourly.csv', index=False)
    pd.DataFrame(allocations).to_csv(output/'v2_allocations.csv', index=False)
    pd.DataFrame(contributions).to_csv(output/'v2_planned_price_attribution.csv', index=False)
    pd.DataFrame(validations).to_csv(output/'v2_validation.csv', index=False)
    metrics = []
    for (variant, extra), group in hourly.groupby(['variant','extra_cost_bps']):
        group = group.sort_values('timestamp')
        net = group.net
        eq = (1+net).cumprod()
        cycles = group.groupby('cycle').net.apply(lambda x: (1+x).prod()-1)
        trimmed = cycles.copy()
        trimmed.loc[trimmed.nlargest(3).index] = 0
        metrics.append(dict(variant=variant, extra_cost_bps=extra, roi_pct=(eq.iloc[-1]-1)*100,
            cagr_pct=(eq.iloc[-1]**(8760/len(net))-1)*100,
            hourly_mdd_pct=(eq/eq.cummax().clip(lower=1)-1).min()*100,
            roi_without_best3_pct=((1+trimmed).prod()-1)*100,
            kill_switches=int(group.kill_switch.sum()), price_sum=group.price.sum(),
            funding_sum=group.funding.sum(), fees_sum=(group.fees+group.exit_fees).sum()))
    table = pd.DataFrame(metrics)
    table.to_csv(output/'v2_comparison.csv', index=False)
    print('\n=== V2 EXPERIMENTAL: COMPARACIÓN Y ESTRÉS DE COSTES ===')
    print(table.to_string(index=False))
    print('Atribución planificada no incluye efecto del kill-switch. Contabilidad real agregada en v2_hourly.csv.')
    print('Modelo de pesos original: no certifica ejecución a apertura, deriva de pesos, margen ni liquidaciones.')
    print('Dos variantes nuevas examinadas en desarrollo; DSR no corrige toda la búsqueda histórica del proyecto.')
    return hourly
