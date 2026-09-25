# Phase 2 input inspection


### demand_oper (mms.demandoperationalactual)

- columns and dtypes:

```
INTERVAL_DATETIME                 object
REGIONID                          object
OPERATIONAL_DEMAND                 int64
OPERATIONAL_DEMAND_ADJUSTMENT    float64
WDR_ESTIMATE                     float64
LASTCHANGED                       object
dtype: object
```

- date coverage: 2020-12-01 00:30:00 to 2026-09-01 00:00:00
- REGIONID present (5): ['NSW1', 'QLD1', 'SA1', 'TAS1', 'VIC1']
- interval resolution (mode of diffs per REGIONID, minutes): min 30.0, median 30.0, max 30.0
- missing-value counts:

```
OPERATIONAL_DEMAND_ADJUSTMENT    30337
WDR_ESTIMATE                     78085
dtype: int64
```

- units: MW

### totaldemand_daily (mms.dispatchregionsum, pre-aggregated)

- columns and dtypes:

```
REGIONID        object
MARKET_DATE     object
SUM_MW         float64
N_ROWS           int64
N_INTERVALS      int64
N_NULL           int64
dtype: object
```

- date coverage: 2010-01-01 00:00:00 to 2026-08-31 00:00:00
- REGIONID present (5): ['NSW1', 'QLD1', 'SA1', 'TAS1', 'VIC1']
- missing-value counts: none
- units: MW (summed to GWh in Phase 2)

### rooftop_pv (mms.rooftop_pv_actual, MEASUREMENT)

- columns and dtypes:

```
INTERVAL_DATETIME     object
REGIONID              object
POWER                float64
TYPE                  object
QI                   float64
dtype: object
```

- date coverage: 2018-03-08 15:00:00 to 2026-09-01 00:00:00
- REGIONID present (5): ['NSW1', 'QLD1', 'SA1', 'TAS1', 'VIC1']
- interval resolution (mode of diffs per REGIONID, minutes): min 30.0, median 30.0, max 30.0
- missing-value counts:

```
POWER    209
dtype: int64
```

- units: MW

### metar (bom.metar)

- columns and dtypes:

```
MET_DATETIME     object
ID_NUM            int64
T_DB            float64
dtype: object
```

- date coverage: 2000-12-31 00:00:00 to 2026-08-31 23:30:00
- WMO ID present (7): [94575, 94648, 94675, 94765, 94868, 94970, 95936]
- interval resolution (mode of diffs per ID_NUM, minutes): min 30.0, median 30.0, max 30.0
- missing-value counts: none
- units: degrees C

### daily_maxmin (bom.daily_max_min_temperature)

- columns and dtypes:

```
Met_Date                  object
ID_Num                     int64
Daily_Max_Temperature    float64
Daily_Min_Temperature    float64
Daily_Avg_Temperature    float64
dtype: object
```

- date coverage: 2000-12-31 00:00:00 to 2026-08-31 00:00:00
- WMO ID present (7): [94575, 94648, 94675, 94765, 94868, 94970, 95936]
- missing-value counts: none
- units: degrees C