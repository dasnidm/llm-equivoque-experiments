# CLI version technical comparison

All observations are technical and excluded from the scientific sample.

| Stage | CLI | Pool | Models | Completed conversations | Successful turns/min | Native 429 retry logs | p95 adapter seconds | Result |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| old-a1-rpm80-p4 | 0.159.0-alpha.3 | 4 | 2 | 4/4 | not estimable | unknown | 6.32 | native telemetry unavailable |
| stable-b1-rpm80-p4 | 0.167.0 | 4 | 2 | 0/4 | not estimable | unknown | 3.85 | Incomplete technical session; no replacement |
| old-i-a1-rpm80-p4 | 0.159.0-alpha.3 | 4 | 2 | 4/4 | 64.5 | 0 | 4.68 | pass |
| stable-i-b1-rpm80-p4 | 0.167.0 | 4 | 2 | 4/4 | 66.9 | 0 | 4.92 | pass |
| alpha-i-c1-rpm80-p4 | 0.169.0-alpha.3 | 4 | 2 | 4/4 | 65.9 | 0 | 5.21 | pass |
| stable-i-b2-rpm80-p4 | 0.167.0 | 4 | 2 | 4/4 | 50.4 | 0 | 5.26 | pass |
| old-i-a2-rpm80-p4 | 0.159.0-alpha.3 | 4 | 2 | 4/4 | 56.3 | 0 | 7.20 | integrity pass; operator pause, excluded from speed comparison |
| old-i-a3-rpm80-p4 | 0.159.0-alpha.3 | 4 | 2 | 4/4 | 68.1 | 0 | 4.97 | pass |
| stable-i-rpm100-p6 | 0.167.0 | 6 | 2 | 6/6 | 83.7 | 0 | 5.03 | pass |
| stable-i-models8-rpm160-p8 | 0.167.0 | 8 | 8 | 8/8 | not estimable | 16 | 21.74 | native response 429; rejected as a zero-429 load |
| stable-i-models2-rpm110-p8 | 0.167.0 | 8 | 2 | 8/8 | not estimable | 10 | 6.37 | native response 429; rejected as a zero-429 load |
| stable-i-models8-rpm200-p10 | 0.167.0 | 10 | 8 | 10/16 | not estimable | 30 | 30.84 | native response 429; rejected as a zero-429 load |
