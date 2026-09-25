#!/usr/bin/env python3
"""build.py — the task catalog, as one file: every benchmark we know of and whether it runs in Harbor form yet.

Research lands in raw/ as JSON lines, one benchmark per line, one file per sweep:

    raw/model-cards.jsonl     benchmarks named in frontier and open-weight model release tables
    raw/companies.jsonl       evals companies built for their own domain (public, partial, or private)
    raw/longtail.jsonl        the obscure ones — domain benchmarks from small groups, governments, individuals
    raw/hub-sources.jsonl     Hugging Face datasets and Spaces, Kaggle Benchmarks and competitions, with usage signals
    raw/harbor-coverage.jsonl what already exists as a Harbor dataset (upstream registry, the local corpus, or both)

The first four share one schema (see README.md); this merges them on a normalised id, unions `cited_by` and
`found_in`, keeps the first non-null value of every other field, and joins Harbor coverage on the same key.  The
local corpus's TASK-INDEX.json is a second, weaker join: a taskset folder of the same name counts as `local`.

    catalog/build.py            write index.jsonl and print the tally
"""
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
SWEEPS = ("model-cards", "companies", "longtail", "hub-sources")
HARBOR_TASKS = os.environ.get("HARBOR_TASKS", os.path.expanduser("~/Desktop/harbor-tasks"))


def key(s):
    """The join key: case, punctuation and a trailing -bench/-benchmark don't make two benchmarks different."""
    k = re.sub(r"[^a-z0-9]", "", (s or "").lower())
    return re.sub(r"bench(mark)?$", "", k) or k


# Five sweeps wrote ~300 free-text domains ("financial modelling in Excel", "legal (28 practice areas)").  Search needs
# a fixed facet, so each raw domain is filed under the first bucket one of its patterns matches; the text it came in
# with stays in `domain_raw`.  Order is load-bearing: the specific trades come before the generic ones, so "medical
# coding" is healthcare not swe, and "fintech backend engineering" is finance.
DOMAINS = [
    ("ai-safety", r"safety|alignment|scheming|sabotage|insider|proliferation"),
    ("security", r"secur|cyber|ctf|pentest|exploit|threat|smart-contract"),
    ("chip-hardware", r"chip|\beda\b|rtl|verilog|hardware|pcb|embedded|firmware"),
    ("healthcare", r"health|medical|clinic|\behr\b|\bemr\b|patient|physician|hospital|payer|pharmacy"),
    ("life-sciences", r"\bbio|drug|pharma|life.?science|genom|chem|materials"),
    ("tax-accounting", r"\btax|accounting|bookkeep|audit"),
    ("insurance", r"insurance|underwrit|mortgage"),
    ("legal", r"legal|\blaw\b|law-firm|compliance|governance"),
    ("finance", r"financ|banking|invest|credit|crypto|fintech|payment|trade|equit"),
    ("geospatial", r"\bgis\b|geospatial|earth"),
    ("customer-service", r"customer|support|voice|\bcall\b|phone|speech"),
    ("telecom", r"telecom|network|\b5g\b"),
    ("engineering-industrial", r"\bcad\b|cad-|\bbim\b|construction|\b3d\b|manufactur|plc|industr|robot|asset|energy|"
                               r"grid|power|aviation|field.?op|embodied|^engineering$"),
    ("games", r"\bgame"),
    ("data-sql", r"sql|data.?engineer|data.?scien|data.?analy|analytics|time-series|operations-research"),
    ("devops-sre", r"terminal|devops|\bsre\b|it-ops|it service|it automation|cloud|observab|incident"),
    ("ml-research", r"\bml\b|ml-|mlops|ai r&d|ai research|post-training|hpc|continual learning|rl environments"),
    ("swe", r"\bswe\b|software|coding|\bcode|program|refactor|migration|repo|full-stack|algorithm|java|agent-harness|"
            r"agent construction|devin|copilot"),
    ("office-docs", r"office|spreadsheet|excel|document|\bpdf"),
    ("web-research", r"\bweb|browser|search|deep research|retriev"),
    ("computer-use", r"computer.?use|\bgui\b|desktop|\bos\b|mobile|android|smartphone"),
    ("multilingual", r"multilingual|language"),
    ("enterprise-ops", r"enterprise|\bcrm\b|\berp\b|business|sales|\bhr\b|recruit|workflow|saas|logistic|supply|"
                       r"e-commerce|commerce|retail|real.?estate|government|civic|solar|professional|freelance|"
                       r"consumer|o\*net|sop"),
    ("tool-use", r"tool|\bmcp\b|function|assistant|personal"),
    ("science-math", r"scien|physics|math|lean|research|forecast|education"),
    ("reasoning-knowledge", r"reason|knowledge|long.?context|instruction|planning|memory|multi-turn|general|"
                            r"multi-domain|multi-agent|collaboration|agent|conversation|\bmulti\b"),
    ("multimodal", r"multimodal|audio|video|generation|accessib"),
]


def domain(raw):
    s = (raw or "").lower()
    return next((d for d, pat in DOMAINS if re.search(pat, s)), "other")


def canonical(k, h):
    """Sort order among a benchmark's Harbor datasets, best first.  The Hub carries forks, subsets and hardened
    variants under the same benchmark (Terminal-Bench 2.1 has seven), so a whole benchmark beats a subset, and a
    package named after the benchmark itself — `terminal-bench/terminal-bench-2-1` — beats someone's variant of it."""
    ds = h.get("harbor_dataset") or ""
    owner, _, name = ds.split("@")[0].rpartition("/")
    kind = {"benchmark": 0, "subset": 1}.get(h.get("kind"), 2)
    return (kind, key(name) != k, key(owner) not in k, -(h.get("n_tasks") or 0))


def lines(path):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"skip {os.path.basename(path)}:{n}: {e}", file=sys.stderr)


def merge(into, row, sweep):
    for k, v in row.items():
        if k == "cited_by":
            into["cited_by"] = sorted(set(into.get("cited_by") or []) | set(v or []))
        elif into.get(k) in (None, "", "unknown", []):
            into[k] = v
    into["found_in"] = sorted(set(into.get("found_in", [])) | {sweep})


def main():
    rows = {}
    for sweep in SWEEPS:
        for row in lines(os.path.join(RAW, f"{sweep}.jsonl")):
            k = key(row.get("id") or row.get("name"))
            if k:
                merge(rows.setdefault(k, {}), row, sweep)

    harbor = {}
    for h in lines(os.path.join(RAW, "harbor-coverage.jsonl")):
        for name in [h.get("id")] + (h.get("aliases") or []):
            harbor.setdefault(key(name), []).append(h)
    for k, hs in harbor.items():
        hs.sort(key=lambda h: canonical(k, h))
    try:
        with open(os.path.join(HARBOR_TASKS, "TASK-INDEX.json")) as f:
            local = {key(p.split("/", 1)[-1]) for p in json.load(f)}
    except (OSError, ValueError):
        local = set()

    for k, row in rows.items():
        row["domain_raw"], row["domain"] = row.get("domain"), domain(row.get("domain"))
        hs =harbor.get(k) or harbor.get(key(row.get("name")))
        if hs:
            row["harbor_status"] = "in-harbor"
            row["harbor"] = {x: hs[0].get(x) for x in ("harbor_dataset", "n_tasks", "source", "multi_container")}
            row["harbor"]["variants"] = [h["harbor_dataset"] for h in hs[1:]]
        elif k in local:
            row["harbor_status"] = "in-harbor"
            row["harbor"] = {"source": "local"}
        elif row.get("public") == "private":
            row["harbor_status"] = "private"
        elif row.get("harbor_status") in (None, "", "unknown"):
            row["harbor_status"] = "to-convert"

    out = sorted(rows.values(), key=lambda r: (r.get("domain") or "", r.get("id") or ""))
    with open(os.path.join(HERE, "index.jsonl"), "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"{len(out)} benchmarks -> catalog/index.jsonl")
    for name, c in (("harbor_status", Counter(r["harbor_status"] for r in out)),
                    ("public", Counter(r.get("public") for r in out)),
                    ("domain", Counter(r.get("domain") for r in out))):
        print(f"  {name}: " + ", ".join(f"{k}={v}" for k, v in c.most_common(20)))


if __name__ == "__main__":
    main()
