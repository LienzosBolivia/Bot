"""Comprobaciones sintéticas, sin descargar datos ni evaluar el holdout."""
import unittest
import numpy as np
import pandas as pd
import research as r

class ResearchTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(28)
        index = pd.date_range('2024-10-31', periods=3000, freq='h')
        self.data = pd.DataFrame(index=index)
        for asset, initial in [('btc', 70000), ('bnb', 600)]:
            px = initial*np.exp(np.cumsum(rng.normal(0, 0.004, len(index))))
            self.data[f'{asset}_close'] = px
            self.data[f'{asset}_spot_close'] = px*(1+rng.normal(0, 0.0002, len(index)))
            events = pd.Series(np.where(index.hour % 8 == 0, rng.normal(0.0001, 0.0002, len(index)), np.nan), index=index)
            self.data[f'{asset}_fund_last'] = events.ffill()
            self.data[f'{asset}_fund_event'] = events.fillna(0)

    def test_candidates_are_causal(self):
        full, metadata = r.generate_research_candidates(self.data)
        prefix, _ = r.generate_research_candidates(self.data.iloc[:1500])
        self.assertEqual(len(metadata), 18)
        pd.testing.assert_frame_equal(full.iloc[:1500], prefix)
        self.assertLessEqual(full[list(metadata)].abs().max().max(), 1)

    def test_historical_matches_simulator(self):
        pos, _ = r.generate_research_candidates(self.data)
        net = r.compute_historical_net_returns(self.data, pos)
        returns, funding = r._retornos_y_funding(self.data)
        for name in net.columns:
            for start in [0, 1200, 2200]:
                sl = slice(start, start+72)
                prior = np.zeros(4) if start == 0 else r.estrategia_a_pesos(name, pos, slice(start-1, start)).iloc[-1].to_numpy()
                actual, _ = r.simular_ciclo_portafolio(r.estrategia_a_pesos(name, pos, sl), returns.iloc[sl], funding.iloc[sl], prior, max_dd=-np.inf)
                np.testing.assert_allclose(actual, net[name].iloc[sl], atol=1e-12, rtol=0)

    def test_kill_switch_closes_and_stays_flat_for_cycle(self):
        idx = self.data.index[:3]
        weights = pd.DataFrame(0., index=idx, columns=r.COLS_ACT)
        weights['BTC'] = 1.
        returns = weights*0
        returns['BTC'] = [-0.05, 0.5, 0.5]
        out, last = r.simular_ciclo_portafolio(weights, returns, weights*0, np.zeros(4))
        self.assertLess(out.iloc[0], -0.05)
        self.assertTrue((out.iloc[1:] == 0).all())
        np.testing.assert_array_equal(last, np.zeros(4))

if __name__ == '__main__': unittest.main()
