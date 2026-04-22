# E1 sensitivity × E2 synthesis cost

For every W2 sensitivity cell this records the resulting EDC / TVC footprint. H_max is a runtime-only comparator threshold and therefore cost-invariant; LEHT / LLR / TVC cycle-table size all have directly computable area terms.

| 轴 | 值 | EDC 面积 (mm²) | TVC 面积 (mm²) | Ctrl-logic 合计 (EDC+TVC+Q+GTSU) | Total 面积 (mm²) | Total 功耗 (mW) |
|----|----|:--------------:|:--------------:|:--------------------------------:|:----------------:|:----------------:|
| edc_h_max | 10.0 | 0.0001 | 0.0002 | 0.0017 | 1.2517 | 25.118 |
| edc_h_max | 8.0 | 0.0001 | 0.0002 | 0.0017 | 1.2517 | 25.118 |
| edc_h_max | 7.0 | 0.0001 | 0.0002 | 0.0017 | 1.2517 | 25.118 |
| edc_h_max | 6.0 | 0.0001 | 0.0002 | 0.0017 | 1.2517 | 25.118 |
| edc_leht_size | 4 | 0.0001 | 0.0002 | 0.0017 | 1.2517 | 25.116 |
| edc_leht_size | 8 | 0.0001 | 0.0002 | 0.0017 | 1.2517 | 25.118 |
| edc_leht_size | 12 | 0.0001 | 0.0002 | 0.0017 | 1.2517 | 25.120 |
| edc_leht_size | 16 | 0.0001 | 0.0002 | 0.0017 | 1.2517 | 25.121 |
| edc_llr_bits | 2 | 0.0001 | 0.0002 | 0.0017 | 1.2517 | 25.061 |
| edc_llr_bits | 3 | 0.0001 | 0.0002 | 0.0017 | 1.2517 | 25.118 |
| edc_llr_bits | 4 | 0.0003 | 0.0002 | 0.0019 | 1.2519 | 25.229 |
| tvc_cycle_table_size | 1 | 0.0001 | 0.0001 | 0.0016 | 1.2516 | 25.056 |
| tvc_cycle_table_size | 2 | 0.0001 | 0.0002 | 0.0017 | 1.2517 | 25.077 |
| tvc_cycle_table_size | 4 | 0.0001 | 0.0002 | 0.0017 | 1.2517 | 25.118 |
| tvc_cycle_table_size | 8 | 0.0001 | 0.0004 | 0.0019 | 1.2519 | 25.200 |
