# analysis/cbs - CBS socio-demographics

Component 6 · owner: Atanas Malinkov · feeds `app/modules/cbs.js`

```bash
python analysis/cbs/fetch_cbs.py     # ~20 s, CBS OData
```

Writes `data/processed/cbs_indicators.json`: Bloemhof against the municipality of
Rotterdam. People, age, households and origin from Kerncijfers wijken en buurten
2026 (`86358NED`), income from 2023 (`85618NED`), the newest edition with income
per buurt. The app shows them as one dashboard card. It describes today's
residents, so it is the same in every scenario.

| | Bloemhof | Rotterdam |
|---|---|---|
| inhabitants (2026) | 13,760 | 673,804 |
| aged 65+ | 11.5 % | 16.2 % |
| single-person households | 46.9 % | 49.2 % |
| households with children | 34.4 % | 28.5 % |
| origin outside Europe | 64.4 % | 44.9 % |
| households in the national lowest 40 % of income (2023) | 62.4 % | 51.5 % |
| mean standardised household income (2023) | €27,100 | €35,800 |

Shares are computed from CBS counts, so both areas are measured the same way.

Traps, each checked on 2026-11-03:

- CBS pads region codes with spaces to 10 characters: `GM0599` is `'GM0599    '`.
- `-99997` means "not available". The 2024 and later tables have no income per
  buurt yet, and the PDOK wijkenbuurten WFS returns `-99997` for every Rotterdam
  field in its municipality layer, so the OData tables are used instead.
- Column names carry a number that changes per edition (`AantalInwoners_5`);
  `pick()` matches on the name. 65+ is one column in some editions and two
  (65–80, 80+) in others.
- Low and high income are the national lowest 40 % and highest 20 % of
  households by disposable income, not CBS's fixed low-income threshold
  (`HuishoudensMetEenLaagInkomen`, 9.8 % in Bloemhof).
