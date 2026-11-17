"""V3: hipótesis fijas, sin optimización ni evaluación del holdout."""
from pathlib import Path
import numpy as np
import pandas as pd
import research as r
from diagnostics_v2 import simulate


def candidates(data):
    pos, meta = r.generate_research_candidates(data)
    close = data.btc_close
    efficiency = (close-close.shift(72)).abs()/(close.diff().abs().rolling(72).sum()+1e-8)
    # Interpretación explícita de asimetría: solo largos, salida por canal de media ventana.
    for window in [120, 240, 360]:
        entry = (close > close.rolling(window).max().shift(1)) & (efficiency > .25)
        leave = close < close.rolling(window//2).min().shift(1)
        zero = np.zeros(len(data), dtype=bool)
        name = f'V3_BreakoutLong_{window}h'
        pos[name] = r._a_posicion(r._maquina_estados(entry,zero,leave,zero),data.index)
        meta[name] = {'family':'V3_LongBreakout'}
    fm = data.btc_fund_last.rolling(168).mean()
    zero = np.zeros(len(data),dtype=bool)
    pos['Carry_BTC_SpotPerp_Wide'] = r._a_posicion(r._maquina_estados(fm>.00005,zero,fm<-.00015,zero,data.index.hour%8==0),data.index)
    meta['Carry_BTC_SpotPerp_Wide'] = {'family':'SpotPerpCarry'}
    return pos,meta


def run(data, output):
    output=Path(output)
    features=r.compute_regime_features(data)
    pos,meta=candidates(data)
    # Universo común de 22 candidatas: la penalización es comparable entre variantes.
    net=r.compute_historical_net_returns(data,pos).loc[features.index]
    pos=pos.loc[features.index]
    returns,funding=r._retornos_y_funding(data)
    returns,funding=returns.loc[features.index],funding.loc[features.index]
    original=[s for s in meta if not s.startswith('V3_') and not s.endswith('_Wide')]
    variants={'control_22':original,
              'wide_carry_22':[s for s in original if s!='Carry_BTC_SpotPerp']+['Carry_BTC_SpotPerp_Wide'],
              'long_breakouts_22':original+[s for s in meta if s.startswith('V3_')]}
    previous={(v,c):np.zeros(4) for v in variants for c in [0.,.0005]}
    records=[]; decisions=[]; validation=[]
    for i in range(2160,len(features)-72+1,72):
        val=r.calibrated_dsr_and_validation(net[list(meta)].iloc[i-2160:i])
        approved=[s for s in meta if val.loc[s,'roi']>0 and val.loc[s,'dsr']>.60 and bool(val.loc[s,'subperiod_ok'])]
        for s in meta:
            validation.append(dict(cycle=features.index[i],strategy=s,approved=s in approved,dsr=val.loc[s,'dsr']))
        sl=slice(i,i+72)
        for variant,universe in variants.items():
            live=[s for s in approved if s in universe and abs(pos[s].iloc[i])>1e-9]
            score={s:float(val.loc[s,'dsr']*val.loc[s,'roi']) for s in live}
            total=sum(score.values())
            weights=pd.DataFrame(0.,index=features.index[sl],columns=r.COLS_ACT)
            for s in live:
                allocation=score[s]/total
                weights+=allocation*r.estrategia_a_pesos(s,pos,sl)
                decisions.append(dict(cycle=features.index[i],variant=variant,strategy=s,allocation=allocation))
            for extra in [0.,.0005]:
                key=variant,extra
                detail,previous[key]=simulate(weights,returns.iloc[sl],funding.iloc[sl],previous[key],r.FEE_RATE+extra)
                detail['variant']=variant; detail['extra_bps']=extra*10000;detail['cycle']=features.index[i]
                records.append(detail.reset_index())
    hourly=pd.concat(records,ignore_index=True)
    hourly.to_csv(output/'v3_hourly.csv',index=False)
    pd.DataFrame(decisions).to_csv(output/'v3_allocations.csv',index=False)
    pd.DataFrame(validation).to_csv(output/'v3_validation.csv',index=False)
    summary=[]
    for (variant,cost),g in hourly.groupby(['variant','extra_bps']):
        eq=(1+g.net).cumprod()
        cycles=g.groupby('cycle').net.apply(lambda x:(1+x).prod()-1)
        trimmed=cycles.copy();trimmed.loc[trimmed.nlargest(3).index]=0
        # Bloques consecutivos de 24h, sin asignar ciclos enteros a meses.
        monthly=g.assign(month=pd.to_datetime(g.timestamp).dt.to_period('M')).groupby('month').net.apply(lambda x:(1+x).prod()-1)
        summary.append(dict(variant=variant,extra_bps=cost,roi_pct=(eq.iloc[-1]-1)*100,
            cagr_pct=(eq.iloc[-1]**(8760/len(g))-1)*100,mdd_pct=(eq/eq.cummax().clip(lower=1)-1).min()*100,
            without_best3_pct=((1+trimmed).prod()-1)*100,positive_months=int((monthly>0).sum()),months=len(monthly)))
    table=pd.DataFrame(summary);table.to_csv(output/'v3_comparison.csv',index=False)
    print('\nV3: UNIVERSO COMÚN DE 22 CANDIDATAS; HOLDOUT SIN EVALUAR')
    print(table.to_string(index=False))
    # Exposición y rotación son diagnósticos distintos.
    diagnostics=[]
    for s in meta:
        w=r.estrategia_a_pesos(s,pos,slice(0,len(pos)))
        diagnostics.append(dict(strategy=s,active_pct=(w.abs().sum(axis=1)>0).mean()*100,
                                turnover=w.diff().abs().sum().sum()))
    pd.DataFrame(diagnostics).to_csv(output/'v3_exposure_turnover.csv',index=False)
    return table
