import os, sys, time
os.environ["FACTORIO_CATALOG_DIR"] = r"x:\factorio_assistant\.tmp-catalog"
sys.path.insert(0, r"x:\factorio_assistant\app")
import sqlite3, json
import catalog_db

con = sqlite3.connect(r"x:\factorio_assistant\.tmp-catalog\catalog.sqlite")
con.row_factory = sqlite3.Row
print("--- description coverage ---")
for row in con.execute("SELECT kind, COUNT(*) n, SUM(localized_description IS NOT NULL AND localized_description!='') d FROM records GROUP BY kind ORDER BY n DESC"):
    print(f"  {row['kind']:12} {row['d'] or 0:5}/{row['n']:5}")
total, desc = con.execute("SELECT COUNT(*), SUM(localized_description IS NOT NULL AND localized_description!='') FROM records").fetchone()
print(f"  TOTAL        {desc}/{total}")
print("junk names remaining:", con.execute(
    "SELECT COUNT(*) FROM records WHERE localized_name LIKE 'Unknown key%' OR localized_name LIKE 'Something went wrong%'").fetchone()[0])
print("bob-solder recipe ->", con.execute("SELECT localized_name FROM records WHERE name='bob-solder' AND kind='recipe'").fetchone()[0])

cat = catalog_db.Catalog()
print("\n--- ranked search ---")
for q, kind in [("iron plate", ""), ("iron-plate", ""), ("saphirite", ""), ("assembling machine", ""),
                ("blue circuit", ""), ("solder", "recipe"), ("warehouse", ""), ("stiratite", "")]:
    t = time.perf_counter()
    total, results = cat.search(q, kind=kind, limit=5)
    ms = (time.perf_counter() - t) * 1000
    top = [f"{r['localized_name']}({r['kind']})" for r in results]
    print(f"  {q!r:22} kind={kind or '*':8} total={total:5} {ms:6.1f}ms  {top}")

print("\n--- facets (item) ---")
for facet in cat.facets("item")[:6]:
    print(f"  {facet['label']:26} {facet['count']:5}  subgroups={len(facet['subcategories'])}")

print("\n--- FNEI relations for iron-plate ---")
e = cat.entry("iron-plate", "item")
print("  made_in:", [x["localized_name"] for x in e.get("made_in", [])][:5])
print("  used_in:", [x["localized_name"] for x in e.get("used_in", [])][:5])
r = cat.entry("electronic-circuit", "recipe")
print("  recipe electronic-circuit crafted_in:", [x["localized_name"] for x in r.get("crafted_in", [])][:5])
print("  unlocked_by:", [x["localized_name"] for x in r.get("unlocked_by", [])])
print("\n  summary payload bytes:", len(json.dumps(catalog_db.summarize(e))), "vs full:", len(json.dumps(e)))
print("  suggestions for 'saphirit':", cat.suggestions("saphirit"))
