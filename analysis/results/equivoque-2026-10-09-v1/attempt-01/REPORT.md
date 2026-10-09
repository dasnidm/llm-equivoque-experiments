# Equivoque evaluation report

Run: `equivoque-2026-10-09-v1`. Integration revision: `4266e7a93d6f931d2f1b60688ad312df0184ed9f`.
Protocol SHA-256: `a3aca2247341955f28abeee8fd3dd0ebab6f5bfdb33726853525106c74a178e9`.

**Collection finished; raw-data integrity checks passed.**

2100 assigned trials; 2096 valid pre-disclosure endpoints and 2093 valid post-disclosure endpoints.
21 of 21 primary route associations were estimable under the prespecified thresholds.

## Primary route associations

The primary estimate equally weights KK and DD versus KD and DK. Routes arise from model choices; contrasts are associations. Cases are shared across frames and configurations. The 2,000 bootstrap replicates resample all 50 paired starting cases together using the frozen seed. Intervals are nominal pointwise percentile 95% intervals, with no confirmatory significance claims.

| configuration_id | estimate | ci_low | ci_high | n_KK | n_DD | n_KD | n_DK | n_cases | valid_bootstrap_replicates | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-5.6-luna-high | 0.00 | 0.00 | 0.00 | 26.00 | 26.00 | 24.00 | 24.00 | 50 | 2000 | estimable |
| gpt-5.6-luna-low | 0.22 | 0.00 | 0.71 | 26.00 | 25.00 | 23.00 | 25.00 | 50 | 2000 | estimable |
| gpt-5.6-luna-medium | 0.00 | 0.00 | 0.00 | 30.00 | 25.00 | 24.00 | 21.00 | 50 | 2000 | estimable |
| gpt-5.6-sol-high | 0.00 | 0.00 | 0.00 | 22.00 | 22.00 | 26.00 | 30.00 | 50 | 2000 | estimable |
| gpt-5.6-sol-low | 0.00 | 0.00 | 0.00 | 25.00 | 22.00 | 27.00 | 25.00 | 50 | 2000 | estimable |
| gpt-5.6-sol-medium | 0.00 | 0.00 | 0.00 | 28.00 | 22.00 | 23.00 | 27.00 | 50 | 2000 | estimable |
| gpt-5.6-terra-high | 0.00 | 0.00 | 0.00 | 24.00 | 29.00 | 25.00 | 22.00 | 50 | 2000 | estimable |
| gpt-5.6-terra-low | 0.00 | 0.00 | 0.00 | 21.00 | 28.00 | 27.00 | 24.00 | 50 | 2000 | estimable |
| gpt-5.6-terra-medium | 0.00 | 0.00 | 0.00 | 30.00 | 28.00 | 18.00 | 24.00 | 50 | 2000 | estimable |
| gpt-6-astra-high | 0.00 | 0.00 | 0.00 | 24.00 | 24.00 | 28.00 | 23.00 | 50 | 2000 | estimable |
| gpt-6-astra-low | 0.00 | 0.00 | 0.00 | 26.00 | 24.00 | 27.00 | 23.00 | 50 | 2000 | estimable |
| gpt-6-astra-medium | 0.00 | 0.00 | 0.00 | 24.00 | 25.00 | 25.00 | 25.00 | 50 | 2000 | estimable |
| gpt-6-luna-high | 0.00 | 0.00 | 0.00 | 24.00 | 26.00 | 25.00 | 25.00 | 50 | 2000 | estimable |
| gpt-6-luna-low | 0.00 | 0.00 | 0.00 | 27.00 | 25.00 | 23.00 | 25.00 | 50 | 2000 | estimable |
| gpt-6-luna-medium | -1.88 | -6.50 | 0.43 | 23.00 | 25.00 | 25.00 | 27.00 | 50 | 2000 | estimable |
| gpt-6-sol-high | 0.00 | 0.00 | 0.00 | 26.00 | 26.00 | 24.00 | 24.00 | 50 | 2000 | estimable |
| gpt-6-sol-low | 0.00 | 0.00 | 0.00 | 28.00 | 25.00 | 22.00 | 25.00 | 50 | 2000 | estimable |
| gpt-6-sol-medium | 0.00 | 0.00 | 0.00 | 26.00 | 26.00 | 23.00 | 25.00 | 50 | 2000 | estimable |
| gpt-6.1-sol-high | 0.00 | 0.00 | 0.00 | 26.00 | 26.00 | 25.00 | 23.00 | 50 | 2000 | estimable |
| gpt-6.1-sol-low | 0.00 | 0.00 | 0.00 | 27.00 | 25.00 | 25.00 | 23.00 | 50 | 2000 | estimable |
| gpt-6.1-sol-medium | 0.00 | 0.00 | 0.00 | 27.00 | 25.00 | 26.00 | 22.00 | 50 | 2000 | estimable |

## Within-trial disclosure changes

| configuration_id | metric | estimate | ci_low | ci_high | n_trials | n_cases | status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-5.6-luna-high | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 100 | 50 | estimable |
| gpt-5.6-luna-high | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 100 | 50 | estimable |
| gpt-5.6-luna-low | disclosure_change_impact | -98.90 | -99.00 | -98.69 | 99 | 50 | estimable |
| gpt-5.6-luna-low | disclosure_change_freedom | 0.20 | 0.00 | 0.61 | 99 | 50 | estimable |
| gpt-5.6-luna-medium | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 100 | 50 | estimable |
| gpt-5.6-luna-medium | disclosure_change_freedom | 0.10 | 0.00 | 0.30 | 100 | 50 | estimable |
| gpt-5.6-sol-high | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 100 | 50 | estimable |
| gpt-5.6-sol-high | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 100 | 50 | estimable |
| gpt-5.6-sol-low | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 99 | 50 | estimable |
| gpt-5.6-sol-low | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 99 | 50 | estimable |
| gpt-5.6-sol-medium | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 99 | 50 | estimable |
| gpt-5.6-sol-medium | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 99 | 50 | estimable |
| gpt-5.6-terra-high | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 100 | 50 | estimable |
| gpt-5.6-terra-high | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 100 | 50 | estimable |
| gpt-5.6-terra-low | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 100 | 50 | estimable |
| gpt-5.6-terra-low | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 100 | 50 | estimable |
| gpt-5.6-terra-medium | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 100 | 50 | estimable |
| gpt-5.6-terra-medium | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 100 | 50 | estimable |
| gpt-6-astra-high | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 99 | 50 | estimable |
| gpt-6-astra-high | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 99 | 50 | estimable |
| gpt-6-astra-low | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 100 | 50 | estimable |
| gpt-6-astra-low | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 100 | 50 | estimable |
| gpt-6-astra-medium | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 98 | 50 | estimable |
| gpt-6-astra-medium | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 98 | 50 | estimable |
| gpt-6-luna-high | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 100 | 50 | estimable |
| gpt-6-luna-high | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 100 | 50 | estimable |
| gpt-6-luna-low | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 100 | 50 | estimable |
| gpt-6-luna-low | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 100 | 50 | estimable |
| gpt-6-luna-medium | disclosure_change_impact | -97.86 | -99.00 | -95.78 | 100 | 50 | estimable |
| gpt-6-luna-medium | disclosure_change_freedom | 0.55 | 0.00 | 1.25 | 100 | 50 | estimable |
| gpt-6-sol-high | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 100 | 50 | estimable |
| gpt-6-sol-high | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 100 | 50 | estimable |
| gpt-6-sol-low | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 100 | 50 | estimable |
| gpt-6-sol-low | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 100 | 50 | estimable |
| gpt-6-sol-medium | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 100 | 50 | estimable |
| gpt-6-sol-medium | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 100 | 50 | estimable |
| gpt-6.1-sol-high | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 99 | 50 | estimable |
| gpt-6.1-sol-high | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 99 | 50 | estimable |
| gpt-6.1-sol-low | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 100 | 50 | estimable |
| gpt-6.1-sol-low | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 100 | 50 | estimable |
| gpt-6.1-sol-medium | disclosure_change_impact | -99.00 | -99.00 | -99.00 | 100 | 50 | estimable |
| gpt-6.1-sol-medium | disclosure_change_freedom | 0.00 | 0.00 | 0.00 | 100 | 50 | estimable |

## Paired cats-minus-cards differences

| configuration_id | metric | estimate | ci_low | ci_high | n_pairs | n_cases | status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-5.6-luna-high | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-luna-high | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-luna-high | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-luna-high | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-luna-low | cats_minus_cards_pre_impact | -0.20 | -0.62 | 0.00 | 49.00 | 49 | estimable |
| gpt-5.6-luna-low | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 49.00 | 49 | estimable |
| gpt-5.6-luna-low | cats_minus_cards_pre_freedom | -0.41 | -1.25 | 0.00 | 49.00 | 49 | estimable |
| gpt-5.6-luna-low | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 49.00 | 49 | estimable |
| gpt-5.6-luna-medium | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-luna-medium | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-luna-medium | cats_minus_cards_pre_freedom | 0.20 | 0.00 | 0.60 | 50.00 | 50 | estimable |
| gpt-5.6-luna-medium | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-sol-high | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-sol-high | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-sol-high | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-sol-high | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-sol-low | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 49.00 | 49 | estimable |
| gpt-5.6-sol-low | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 49.00 | 49 | estimable |
| gpt-5.6-sol-low | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 49.00 | 49 | estimable |
| gpt-5.6-sol-low | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 49.00 | 49 | estimable |
| gpt-5.6-sol-medium | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-sol-medium | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 49.00 | 49 | estimable |
| gpt-5.6-sol-medium | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-sol-medium | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 49.00 | 49 | estimable |
| gpt-5.6-terra-high | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-terra-high | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-terra-high | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-terra-high | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-terra-low | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-terra-low | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-terra-low | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-terra-low | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-terra-medium | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-terra-medium | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-terra-medium | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-5.6-terra-medium | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-astra-high | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 49.00 | 49 | estimable |
| gpt-6-astra-high | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 49.00 | 49 | estimable |
| gpt-6-astra-high | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 49.00 | 49 | estimable |
| gpt-6-astra-high | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 49.00 | 49 | estimable |
| gpt-6-astra-low | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-astra-low | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-astra-low | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-astra-low | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-astra-medium | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 49.00 | 49 | estimable |
| gpt-6-astra-medium | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 48.00 | 48 | estimable |
| gpt-6-astra-medium | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 49.00 | 49 | estimable |
| gpt-6-astra-medium | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 48.00 | 48 | estimable |
| gpt-6-luna-high | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-luna-high | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-luna-high | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-luna-high | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-luna-low | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-luna-low | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-luna-low | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-luna-low | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-luna-medium | cats_minus_cards_pre_impact | 1.88 | -0.40 | 6.14 | 50.00 | 50 | estimable |
| gpt-6-luna-medium | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-luna-medium | cats_minus_cards_pre_freedom | -0.60 | -2.00 | 0.60 | 50.00 | 50 | estimable |
| gpt-6-luna-medium | cats_minus_cards_post_freedom | 0.10 | 0.00 | 0.30 | 50.00 | 50 | estimable |
| gpt-6-sol-high | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-sol-high | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-sol-high | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-sol-high | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-sol-low | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-sol-low | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-sol-low | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-sol-low | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-sol-medium | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-sol-medium | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-sol-medium | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6-sol-medium | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6.1-sol-high | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6.1-sol-high | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 49.00 | 49 | estimable |
| gpt-6.1-sol-high | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6.1-sol-high | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 49.00 | 49 | estimable |
| gpt-6.1-sol-low | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6.1-sol-low | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6.1-sol-low | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6.1-sol-low | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6.1-sol-medium | cats_minus_cards_pre_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6.1-sol-medium | cats_minus_cards_post_impact | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6.1-sol-medium | cats_minus_cards_pre_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |
| gpt-6.1-sol-medium | cats_minus_cards_post_freedom | 0.00 | 0.00 | 0.00 | 50.00 | 50 | estimable |

## Post-disclosure evidence consistency and missingness

| configuration_id | frame | assigned | valid_post | counterfactual_no_count | counterfactual_no_rate | minimum_impact_count | minimum_impact_rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-5.6-luna-high | cards | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-5.6-luna-high | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-5.6-luna-low | cards | 50 | 49 | 49 | 1.00 | 49 | 1.00 |
| gpt-5.6-luna-low | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-5.6-luna-medium | cards | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-5.6-luna-medium | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-5.6-sol-high | cards | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-5.6-sol-high | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-5.6-sol-low | cards | 50 | 49 | 49 | 1.00 | 49 | 1.00 |
| gpt-5.6-sol-low | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-5.6-sol-medium | cards | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-5.6-sol-medium | cats | 50 | 49 | 49 | 1.00 | 49 | 1.00 |
| gpt-5.6-terra-high | cards | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-5.6-terra-high | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-5.6-terra-low | cards | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-5.6-terra-low | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-5.6-terra-medium | cards | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-5.6-terra-medium | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6-astra-high | cards | 50 | 49 | 49 | 1.00 | 49 | 1.00 |
| gpt-6-astra-high | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6-astra-low | cards | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6-astra-low | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6-astra-medium | cards | 50 | 49 | 49 | 1.00 | 49 | 1.00 |
| gpt-6-astra-medium | cats | 50 | 49 | 49 | 1.00 | 49 | 1.00 |
| gpt-6-luna-high | cards | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6-luna-high | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6-luna-low | cards | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6-luna-low | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6-luna-medium | cards | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6-luna-medium | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6-sol-high | cards | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6-sol-high | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6-sol-low | cards | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6-sol-low | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6-sol-medium | cards | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6-sol-medium | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6.1-sol-high | cards | 50 | 49 | 49 | 1.00 | 49 | 1.00 |
| gpt-6.1-sol-high | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6.1-sol-low | cards | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6.1-sol-low | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6.1-sol-medium | cards | 50 | 50 | 50 | 1.00 | 50 | 1.00 |
| gpt-6.1-sol-medium | cats | 50 | 50 | 50 | 1.00 | 50 | 1.00 |

| configuration_id | frame | assigned | valid_pre | valid_post | valid_pre_post_pairs | failed | interrupted | unattempted |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-5.6-luna-high | cards | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-5.6-luna-high | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-5.6-luna-low | cards | 50 | 49 | 49 | 49 | 1 | 0 | 0 |
| gpt-5.6-luna-low | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-5.6-luna-medium | cards | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-5.6-luna-medium | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-5.6-sol-high | cards | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-5.6-sol-high | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-5.6-sol-low | cards | 50 | 49 | 49 | 49 | 1 | 0 | 0 |
| gpt-5.6-sol-low | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-5.6-sol-medium | cards | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-5.6-sol-medium | cats | 50 | 50 | 49 | 49 | 1 | 0 | 0 |
| gpt-5.6-terra-high | cards | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-5.6-terra-high | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-5.6-terra-low | cards | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-5.6-terra-low | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-5.6-terra-medium | cards | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-5.6-terra-medium | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6-astra-high | cards | 50 | 49 | 49 | 49 | 1 | 0 | 0 |
| gpt-6-astra-high | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6-astra-low | cards | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6-astra-low | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6-astra-medium | cards | 50 | 49 | 49 | 49 | 1 | 0 | 0 |
| gpt-6-astra-medium | cats | 50 | 50 | 49 | 49 | 1 | 0 | 0 |
| gpt-6-luna-high | cards | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6-luna-high | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6-luna-low | cards | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6-luna-low | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6-luna-medium | cards | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6-luna-medium | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6-sol-high | cards | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6-sol-high | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6-sol-low | cards | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6-sol-low | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6-sol-medium | cards | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6-sol-medium | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6.1-sol-high | cards | 50 | 50 | 49 | 49 | 1 | 0 | 0 |
| gpt-6.1-sol-high | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6.1-sol-low | cards | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6.1-sol-low | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6.1-sol-medium | cards | 50 | 50 | 50 | 50 | 0 | 0 | 0 |
| gpt-6.1-sol-medium | cats | 50 | 50 | 50 | 50 | 0 | 0 | 0 |

## Interpretation and technical limits

Native CLI subjects also receive the documented empty-directory environment context. Its working-directory paths contain the repository/run name, including the word equivoque. This is a possible topic cue before disclosure, even though no repository files, worker instructions, assigned target, or invariant rule are supplied. The context is part of the frozen harness and common across conditions; results describe judgments under that context, not the canonical message text in isolation. The protocol was not changed and trials were not replaced after collection began.

A runtime reattachment stopped the coordinator and worker parents during collection. Seven already-requested native turns finished in their CLI children and left final durable event streams. Each had one schema-valid response, one final turn.completed event, matching session/system/prompt/schema, and no tools or metadata fallback. The coordinator recovered those responses without a new model invocation. Their original process exit codes and monotonic latencies are unavailable and remain missing; endpoint responses and available usage are retained. Fresh live readiness checks preceded resumption, with no replacement trials.

The user subsequently requested ten additional executor processes and immediate concurrency 17. Original A–G manifests, the 2,100-trial roster, canonical stimuli, models, efforts, targets, cases and subject paths remained unchanged. Only unstarted evaluation IDs were exclusively subdivided; existing partial trials stayed with their original executors. Ten helper native-session checks added 40 separately retained calibration invocations. Seven existing native requests drained before subdivision and were reconciled without replay. Their exit status 0 was observed from /proc, but original monotonic latencies remain missing. Changing concurrency and manifest subsequences is an operational scheduling amendment, not a randomized scaling experiment.

Seven evaluation turns subsequently exceeded the frozen 300-second native deadline. These trials remain failed, with their timeout records and any valid earlier endpoints retained; no failed or uncertain request was replayed. New trial intake was paused. Ten other already-requested native responses finished within the deadline and were reconciled from their final streams with observed exit status 0; their monotonic durations remain missing. Eight safe partial sessions resumed only their next unrequested turn. Twenty-one shared live service checks passed before another launch gate. The same 17 executors resumed with fair whole-trial permits and measured concurrency increases from 2 to 4, 7, 10 and 17; longer pending responses reduce subsequent intake. This scheduling history is preserved as technical evidence, without causal claims about scaling or the cause of the slowdown.

A second runtime reattachment stopped the collection parents with 17 turns pending in durable state. Each already-requested turn left one schema-valid final native response inside its unchanged deadline, with matching session/system/prompt/schema and no tools or model-metadata fallback. Their native event logs retain WebSocket 403 reconnect errors and the CLI transport switch to HTTPS before successful completion. All 17 responses were reconciled without new invocations. Original per-turn process exit codes and monotonic durations could not be uniquely recovered and remain missing. Four trials ended at Turn 4; thirteen continued only their next unrequested turn. Another shared 21-configuration live check passed before a separately numbered gate and measured concurrency ramp. No failed trial was repeated or replaced.

Disclosure combines an explanation, exhaustive evidence, and a later measurement. Its change cannot isolate the effect of any one component. Card and cat wording also differs in names, action verbs, and removal terms. Frame differences do not isolate only object category. These are model-generated judgments in one task family, not human agency measures.

Valid Turn 3 endpoints contribute even when Turn 4 fails. Within-trial changes and frame differences use endpoint-valid pairs. All assigned failures and unattempted trials remain in denominators; missing ratings are not imputed. Sparse route contrasts remain insufficient, without replacement trials.

See tables/estimates.csv for point estimates, contributing cases/trials, valid bootstrap counts, intervals, and insufficient cells. tables/missingness.csv contains endpoint denominators. Other CSVs retain route counts, counterfactual transitions, evidence consistency, target/position, choices, worker/time descriptions, and technical summaries. Static SVG and PNG figures have captions in figure_captions.json.

Worker calibration requested 383 subject invocations across preserved attempts; development requested 5 and shared service checks requested 42 additional invocations, for 430 non-evaluation invocations in total. These, loopback request inspections, simulations, and the previous pilot are excluded from evaluation. Shared service calls are counted once; inherited per-executor readiness adds no calls. CLI HTTP retries are not observable as a reliable total; no cost is inferred without billing evidence. Backend model versions are not independently exposed by the CLI event stream. Exact requested models, effort settings, commands, usage, raw responses, and failures are preserved in the raw records.
