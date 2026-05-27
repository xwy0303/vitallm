# Retrieval Window Latency - 2026-05-27

Environment: local Qdrant, semantic BGE collection, 3-run mean per query.

| Query bucket | top_k=5 mean ms | top_k=80 mean ms | Notes |
| --- | ---: | ---: | --- |
| B10 formulation | 1816.7 | 1970.0 | Global formulation query already expensive; widening adds modest local cost. |
| A11 document-scoped formulation | 223.1 | 238.9 | Hard document filter keeps cost low. |
| A12 document-scoped formulation | 271.7 | 262.5 | Hard document filter keeps cost low. |
| CRL PNIPAM mechanism | 183.8 | 1326.6 | Global broad query cost increases materially. |
| CuBTC reaction | 264.7 | 1895.1 | Global broad query cost increases materially. |

Conclusion: `formulation_candidate_min=80` is acceptable for local benchmark recovery, but should remain endpoint-internal config and needs API latency / stream first-token pressure testing before production default.
