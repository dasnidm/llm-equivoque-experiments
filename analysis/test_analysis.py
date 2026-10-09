"""Numerical unit tests only; synthetic values are never evaluation records."""
import unittest
import numpy as np
import pandas as pd

from analyze import CaseBootstrap, endpoints, estimates


class AnalysisTests(unittest.TestCase):
    def test_valid_pre_endpoint_survives_failed_post(self):
        state = {'status': 'failed', 'turns': [
            {'turn': 3, 'ok': True, 'parsed': {'freedom': 75, 'impact': 60, 'counterfactual': 'yes'}},
            {'turn': 4, 'ok': False, 'parsed': {'freedom': 1, 'impact': 1, 'counterfactual': 'no'}}]}
        result = endpoints(state)
        self.assertEqual(result['pre_impact'], 60)
        self.assertNotIn('post_impact', result)

    def test_cluster_draw_keeps_both_frames_together(self):
        df = pd.DataFrame([{'case_id': i, 'value': i * 10 + offset}
                           for i in range(5) for offset in (0, 2)])
        bootstrap = CaseBootstrap(df.case_id.unique(), 41)
        mean, samples, n, cases = bootstrap.means(df, 'value')
        expected = bootstrap.weights @ (np.arange(5) * 10 + 1) / 5
        np.testing.assert_allclose(samples, expected)
        self.assertEqual((mean, n, cases), (21, 10, 5))
        np.testing.assert_equal(bootstrap.weights.sum(axis=1), 5)

    def test_equal_route_weights_and_sparse_threshold(self):
        rows = []
        for i in range(50):
            for frame in ('cards', 'cats'):
                route = ('KK', 'DD', 'KD', 'DK')[i % 4]
                pre = {'KK': 90, 'DD': 70, 'KD': 40, 'DK': 20}[route]
                rows.append({'configuration_id': 'test', 'case_id': i, 'frame': frame,
                    'route': route, 'pre_impact': pre, 'post_impact': 1,
                    'pre_freedom': 85, 'post_freedom': 75})
        df = pd.DataFrame(rows)
        result = estimates(df, CaseBootstrap(df.case_id.unique(), 11))
        primary = result[result.metric == 'primary_route_association'].iloc[0]
        self.assertEqual(primary.estimate, 50)
        self.assertEqual(primary.status, 'estimable')
        sparse = df.copy()
        sparse.loc[(sparse.route == 'DK') & (sparse.case_id > 3), 'pre_impact'] = np.nan
        result = estimates(sparse, CaseBootstrap(sparse.case_id.unique(), 11))
        primary = result[result.metric == 'primary_route_association'].iloc[0]
        self.assertEqual(primary.status, 'insufficient')
        self.assertTrue(np.isnan(primary.estimate))
        frame = result[result.metric == 'cats_minus_cards_pre_freedom'].iloc[0]
        self.assertEqual((frame.estimate, frame.n_cases, frame.n_pairs), (0, 50, 50))


if __name__ == '__main__':
    unittest.main()
