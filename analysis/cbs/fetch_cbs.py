#!/usr/bin/env python3
"""
fetch_cbs.py - CBS socio-demographics of Bloemhof against Rotterdam, for the app.

Component 4.6. Owner: Atanas Malinkov. Built 2026-11-03.

People, age, households and origin come from the newest CBS "Kerncijfers wijken
en buurten" table that has them, income from the newest that has income (CBS
publishes income about two years late). Read from CBS OData in Python, since it
does not send CORS headers reliably. Shares are computed from the counts, so
Bloemhof and Rotterdam are measured the same way. Low and high income are the
households in the national lowest 40 % and highest 20 % of disposable income.

    python analysis/cbs/fetch_cbs.py

Writes data/processed/cbs_indicators.json. The same in every scenario, it
describes today's residents.
"""

import json
import pathlib
import re
import sys

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import PROCESSED, STUDY_AREA  #noqa: E402

ODATA = "https://opendata.cbs.nl/ODataApi/odata/{table}/TypedDataSet"

PARAMS = {
    "buurt": STUDY_AREA.buurten[0][0],  #Bloemhof
    "gemeente": STUDY_AREA.cbs_gemeente,  #Rotterdam
}

#one CBS table per topic: the newest with data for the buurt (checked 2026-11-03)
CASES = [
    {"topic": "people", "table": "86358NED", "year": 2026},
    {"topic": "income", "table": "85618NED", "year": 2023},  #2024 and later have no buurt income yet
]


def fetch_rows(table, codes):
    #{code: row} from a CBS OData table; CBS pads region codes with spaces to 10 characters
    flt = " or ".join(f"WijkenEnBuurten eq '{c.ljust(10)}'" for c in codes)
    r = requests.get(ODATA.format(table=table), params={"$filter": flt, "$format": "json"}, timeout=180)
    r.raise_for_status()
    rows = {row["WijkenEnBuurten"].strip(): row for row in r.json()["value"]}
    missing = [c for c in codes if c not in rows]
    assert not missing, f"{table}: no row for {missing}"
    return rows


def pick(row, name):
    #the value of column `name`, whatever number CBS appends; the lowest number is the total
    keys = sorted((int(m.group(1)), k) for k in row if (m := re.fullmatch(rf"{name}_(\d+)", k)))
    if not keys:
        return None
    v = row[keys[0][1]]
    return None if v is None or (isinstance(v, (int, float)) and v < -99990) else v  #CBS codes for "not available"


def shares(row, parts):
    #percentages of the parts, from the counts, so the two areas are measured alike
    counts = [sum(pick(row, n) or 0 for n in names) for _, names in parts]
    tot = sum(counts)
    return [round(100 * c / tot, 1) for c in counts]


def people(rows, p, year, table):
    #inhabitants, density, households, and the age, household and origin shares
    b, g = rows[p["buurt"]], rows[p["gemeente"]]
    age = [("0–15", ["k_0Tot15Jaar"]), ("15–25", ["k_15Tot25Jaar"]), ("25–45", ["k_25Tot45Jaar"]),
           ("45–65", ["k_45Tot65Jaar"]), ("65+", ["k_65JaarOfOuder", "k_65JaarTot80Jaar", "k_80JaarOfOuder"])]  #65+ is one column or two, by edition
    hh = [("single person", ["Eenpersoonshuishoudens"]), ("couple, no children", ["HuishoudensZonderKinderen"]),
          ("with children", ["HuishoudensMetKinderen"])]
    origin = [("Netherlands", ["Nederland"]), ("Europe, not NL", ["EuropaExclusiefNederland"]),
              ("outside Europe", ["BuitenEuropa"])]  #origin of the person or their parents
    group = lambda key, title, parts, note: {
        "key": key, "title": title, "year": year, "note": note,
        "categories": [{"label": lab, "bloemhof": vb, "rotterdam": vg}
                       for (lab, _), vb, vg in zip(parts, shares(b, parts), shares(g, parts))]}
    return {
        "people": {"year": year, "table": table, "rows": [
            {"label": "Inhabitants", "unit": "", "bloemhof": pick(b, "AantalInwoners"), "rotterdam": pick(g, "AantalInwoners")},
            {"label": "Density", "unit": "per km²", "bloemhof": pick(b, "Bevolkingsdichtheid"), "rotterdam": pick(g, "Bevolkingsdichtheid")},
            {"label": "Households", "unit": "", "bloemhof": pick(b, "HuishoudensTotaal"), "rotterdam": pick(g, "HuishoudensTotaal")},
            {"label": "Mean household size", "unit": "people", "bloemhof": pick(b, "GemiddeldeHuishoudensgrootte"),
             "rotterdam": pick(g, "GemiddeldeHuishoudensgrootte")},
        ]},
        "groups": [
            group("age", "Age", age, "share of inhabitants"),
            group("households", "Households", hh, "share of households"),
            group("origin", "Origin", origin, "country of origin of the person or their parents"),
        ],
    }


def income(rows, p, year, table):
    #households in the national lowest 40 % and highest 20 %, and the standardised household income
    b, g = rows[p["buurt"]], rows[p["gemeente"]]
    row = lambda label, unit, name: {"label": label, "unit": unit, "bloemhof": pick(b, name), "rotterdam": pick(g, name)}
    return {"income": {"year": year, "table": table, "rows": [
        row("Households in the lowest 40 % nationally", "%", "k_40HuishoudensMetLaagsteInkomen"),
        row("Households in the highest 20 % nationally", "%", "k_20HuishoudensMetHoogsteInkomen"),
        row("Mean standardised household income", "€1,000", "GemGestandaardiseerdInkomenVanHuish"),
    ]}}


def main():
    p = PARAMS
    out = {
        "_written_by": "analysis/cbs/fetch_cbs.py",
        "_source": "CBS StatLine OData, Kerncijfers wijken en buurten",
        "_note": "Bloemhof against the municipality of Rotterdam. Shares computed from CBS counts. "
                 "The same in every scenario: it describes today's residents.",
        "buurt": STUDY_AREA.buurten[0][1], "code": p["buurt"], "gemeente": "Rotterdam",
    }
    for c in CASES:  #one table per topic
        rows = fetch_rows(c["table"], [p["buurt"], p["gemeente"]])
        out.update((people if c["topic"] == "people" else income)(rows, p, c["year"], c["table"]))
        print(f"  {c['topic']}: table {c['table']} ({c['year']})")
    for g in out["groups"]:  #a quick look at what was written
        print(f"  {g['title']:10} " + "  ".join(f"{x['label']} {x['bloemhof']}/{x['rotterdam']}" for x in g["categories"]))
    for r in out["people"]["rows"] + out["income"]["rows"]:
        print(f"  {r['label']}: {r['bloemhof']} / {r['rotterdam']}")
    (PROCESSED / "cbs_indicators.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("  wrote data/processed/cbs_indicators.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
