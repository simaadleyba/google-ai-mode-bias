"""
harvest_queries.py - collect real-world phrasings of political questions from Google autocomplete.

Run logged out, from the same location/IP you will audit from (autocomplete is localized).
Output: suggestions.csv -> you hand-label each row as left / right / neutral framing,
and whether it contains a false or loaded premise.

  python harvest_queries.py stems.txt suggestions.csv

stems.txt: one stem per line, e.g.
  was january 6
  why did trump
  j6 defendants
"""
import csv, json, string, sys, time, random
from urllib.parse import quote_plus
from urllib.request import urlopen

URL = "https://suggestqueries.google.com/complete/search?client=firefox&hl=en&gl=us&q={}"


def suggest(q):
    with urlopen(URL.format(quote_plus(q)), timeout=10) as r:
        return json.loads(r.read().decode("utf-8", "replace"))[1]


def main(stems_path, out_path):
    stems = [s.strip() for s in open(stems_path) if s.strip()]
    seen = set()
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stem", "expansion", "suggestion", "framing", "loaded_premise"])  # last two: fill by hand
        for stem in stems:
            for exp in [""] + list(string.ascii_lowercase):  # "stem", "stem a", "stem b", ...
                q = f"{stem} {exp}".strip()
                try:
                    for s in suggest(q):
                        if s not in seen:
                            seen.add(s)
                            w.writerow([stem, exp, s, "", ""])
                except Exception as e:
                    print("fail", q, e)
                time.sleep(random.uniform(1, 3))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
