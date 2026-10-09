import unittest

import numpy as np
import pandas as pd

from equivoque.core import read_json
from equivoque2.protocol import CONFIG
from experiment2.analyze import case_bootstrap, estimates


def synthetic_frame(config):
    rows = []
    for c in config['configurations']:
        for k in range(10):
            for frame in ('cards', 'cats'):
                row = {'configuration_id': c['configuration_id'], 'case_id': f'case-{k:03d}', 'frame': frame}
                for m in range(1, 4):
                    row[f'm{m}_impact'] = 50.
                    row[f'm{m}_freedom'] = 100.
                    row[f'm{m}_counterfactual'] = 'yes' if m < 3 else 'no'
                rows.append(row)
    return pd.DataFrame(rows)


class AnalysisTests(unittest.TestCase):
    def test_case_rows_and_missingness_are_preserved(self):
        matrix = np.array([[1., 3.], [10., 10.], [np.nan, np.nan]])
        indices = np.tile(np.array([0, 1, 2]), (2000, 1))
        result, reps = case_bootstrap(matrix, indices)
        self.assertEqual(result['estimate'], 6.)
        self.assertEqual(result['n_cases'], 2)
        self.assertEqual(result['n_observations'], 4)
        self.assertEqual(result['status'], 'insufficient')
        np.testing.assert_array_equal(reps, np.full(2000, 6.))

    def test_overall_equally_weights_configurations_with_missing_endpoints(self):
        config = read_json(CONFIG)
        df = synthetic_frame(config)
        cid = config['configurations'][0]['configuration_id']
        df.loc[df.configuration_id == cid, 'm2_impact'] = 30.
        mask = (df.configuration_id == cid) & (df.frame == 'cards') & (df.case_id != 'case-000')
        df.loc[mask, 'm2_impact'] = np.nan
        result = estimates(config, df)
        overall = result[(result.configuration_id == 'ALL_EQUAL_CONFIGURATIONS') & (result.metric == 'm2_minus_m1_impact')].iloc[0]
        self.assertAlmostEqual(overall.estimate, -20 / 21)
        self.assertAlmostEqual(overall.ci_low, -20 / 21)
        self.assertAlmostEqual(overall.ci_high, -20 / 21)
        self.assertEqual(overall.n_observations, 411)

    def test_shared_bootstrap_preserves_cross_configuration_case_dependence(self):
        config = read_json(CONFIG)
        df = synthetic_frame(config)
        for i, sign in ((0, 1), (1, -1)):
            cid = config['configurations'][i]['configuration_id']
            mask = df.configuration_id == cid
            df.loc[mask, 'm2_impact'] = 50 + sign * df.loc[mask, 'case_id'].str[-3:].astype(int)
        result = estimates(config, df)
        overall = result[(result.configuration_id == 'ALL_EQUAL_CONFIGURATIONS') & (result.metric == 'm2_minus_m1_impact')].iloc[0]
        self.assertEqual(overall.estimate, 0.)
        self.assertEqual(overall.ci_low, 0.)
        self.assertEqual(overall.ci_high, 0.)


if __name__ == '__main__':
    unittest.main()
