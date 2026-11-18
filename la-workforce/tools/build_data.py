"""Build data/workforce.json and data/workforce-summary.csv from the LA City Controller's payroll data.

Usage: python3 -I tools/build_data.py [cache folder]

Downloads each pay year from https://controllerdata.lacity.org/resource/g9h8-fvhu (City Employee Payroll)
into the cache folder (default: tools/.cache), skipping years already there. Delete a year's CSV to refresh it.
Standard library only. Names are never downloaded or written out.
"""
import csv, json, math, os, re, statistics, sys, urllib.parse, urllib.request
from collections import Counter, defaultdict
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, ".cache")
OUT = os.path.join(HERE, "..", "data")
API = "https://controllerdata.lacity.org/resource/g9h8-fvhu.csv"
FIELDS = ("record_nbr,pay_year,fms_department_title,job_class_pgrade,job_title,employment_type,"
          "regular_pay,overtime_pay,all_other_pay,total_pay,gender,ethnicity")

FIRST, LAST = 2018, 2025          # years shown; 2017 and 2026 (year to date) are only used to find full-year workers
DL_YEARS = range(FIRST - 1, LAST + 2)
DWP = "WATER AND POWER"
DWP_PARTIAL = {2025}              # LADWP payroll for these years is still incomplete: leave DWP out of pay measures
MIN_REG = 1000                    # ignore records with almost no regular pay when comparing pay

# 2024 the City recoded race/ethnicity (Caucasian -> White, most Filipino -> Native Hawaiian/Pacific Islander, ...).
ETH = {
    "HISPANIC": "hisp",
    "CAUCASIAN": "white", "WHITE": "white",
    "BLACK": "black", "BLACK OR AFRICAN AMERICAN": "black",
    "ASIAN": "api", "ASIAN AMERICAN": "api", "FILIPINO": "api", "PACIFIC ISLANDER": "api",
    "NATIVE HAWAIIAN OR OTHER PACIFIC ISLANDER": "api",
    "AMERICAN INDIAN": "aian", "AMERICAN INDIAN/ALASKAN NATIVE": "aian", "AMERICAN INDIAN OR ALASKA NATIVE": "aian",
    "OTHER": "other", "TWO OR MORE RACES": "other", "MULTIPLE": "other", "AMERICAN": "other", "NATIVE": "other",
}
EGROUPS = ["hisp", "white", "black", "api", "aian", "other"]
GENDER = {"MALE": "m", "FEMALE": "f"}

# LA City residents, ACS 2024 1-year, tables B03002 and B01001 (via Census Reporter).
POP = {"src": "U.S. Census Bureau, American Community Survey 2024 1-year estimates (tables B03002, B01001), City of Los Angeles",
       "total": 3878718, "e": {"hisp": 1831192, "white": 1078985, "black": 305964, "api": 471242 + 6457, "aian": 5041,
                               "other": 24463 + 155374}, "g": {"m": 1922307, "f": 1956411}}


# ---------------------------------------------------------------- download
def download(year):
    path = os.path.join(CACHE, f"payroll-{year}.csv")
    if os.path.exists(path):
        return path
    os.makedirs(CACHE, exist_ok=True)
    q = urllib.parse.urlencode({"$select": FIELDS, "$where": f"pay_year='{year}'", "$limit": 500000})
    print(f"downloading {year} ...", file=sys.stderr)
    with urllib.request.urlopen(f"{API}?{q}", timeout=600) as r, open(path + ".part", "wb") as f:
        f.write(r.read())
    os.replace(path + ".part", path)
    return path


# ---------------------------------------------------------------- person-years
def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def valid_code(r):
    """2024-25 rows moved into Workday without a classification carry the placeholder class XXXX."""
    code = (r["job_class_pgrade"] or "").split("-")[0].strip()
    return bool(code) and code not in ("NA", "XXXX")


def load_year(year):
    """One record per employee (record_nbr) per year. A transfer or second job adds rows; pay is summed and
    the job/department is the one with the most regular pay (full-time rows first)."""
    rows = defaultdict(list)
    with open(download(year), newline="") as f:
        for r in csv.DictReader(f):
            rows[r["record_nbr"]].append(r)
    people = {}
    for rid, rs in rows.items():
        main = max(rs, key=lambda r: (r["employment_type"] == "FULL_TIME", valid_code(r), num(r["regular_pay"])))
        types = {r["employment_type"] for r in rs}
        g = next((GENDER[r["gender"]] for r in rs if r["gender"] in GENDER), None)
        e = next((ETH[r["ethnicity"]] for r in rs if r["ethnicity"] in ETH), None)
        code = (main["job_class_pgrade"] or "").split("-")[0].strip()
        dept = main["fms_department_title"]
        people[rid] = dict(
            ft="FULL_TIME" in types, dept=dept, code=code, title=main["job_title"],
            job=(code + "|DWP" if dept == DWP else code) if valid_code(main) else None,
            reg=sum(num(r["regular_pay"]) for r in rs), ot=sum(num(r["overtime_pay"]) for r in rs),
            oth=sum(num(r["all_other_pay"]) for r in rs), tot=sum(num(r["total_pay"]) for r in rs), g=g, e=e)
    return people


# ---------------------------------------------------------------- stats helpers
def median(xs):
    return statistics.median(xs) if xs else None


def r0(x):
    return None if x is None else int(round(x))


def r3(x):
    return None if x is None else round(x, 3)


def solve(A, b):
    """Gaussian elimination with partial pivoting; returns None if singular."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-9:
            return None
        M[c], M[p] = M[p], M[c]
        for r in range(n):
            if r != c and M[r][c]:
                f = M[r][c] / M[c][c]
                M[r] = [a - f * bb for a, bb in zip(M[r], M[c])]
    return [M[i][n] / M[i][i] for i in range(n)]


REG_TERMS = ["f"] + [e for e in EGROUPS if e != "white"] + ["eunk"]


def same_job_gaps(workers, pay):
    """log(pay) on woman + race/ethnicity dummies (White is the reference) with job-classification fixed
    effects, i.e. comparing people in the same job. Returns % gaps and how many people in each group share a job
    with the comparison group (estimates resting on fewer than 30 are dropped)."""
    jobs = defaultdict(list)
    for w in workers:
        v = pay(w)
        if w["job"] and w["g"] and v > MIN_REG:
            x = [1.0 if w["g"] == "f" else 0.0] + [1.0 if w["e"] == k else 0.0 for k in REG_TERMS[1:-1]] + [1.0 if w["e"] is None else 0.0]
            jobs[w["job"]].append((x, math.log(v), w))
    k = len(REG_TERMS)
    XtX = [[0.0] * k for _ in range(k)]
    Xty = [0.0] * k
    support = Counter()
    for members in jobs.values():
        if len(members) < 2:
            continue
        n = len(members)
        mx = [sum(m[0][j] for m in members) / n for j in range(k)]
        my = sum(m[1] for m in members) / n
        has_m = any(m[2]["g"] == "m" for m in members)
        has_w = any(m[2]["e"] == "white" for m in members)
        for x, y, w in members:
            dx = [x[j] - mx[j] for j in range(k)]
            dy = y - my
            for a in range(k):
                Xty[a] += dx[a] * dy
                for c in range(a, k):
                    XtX[a][c] += dx[a] * dx[c]
            if w["g"] == "f" and has_m:
                support["f"] += 1
            if w["e"] and w["e"] != "white" and has_w:
                support[w["e"]] += 1
    for a in range(k):
        for c in range(a):
            XtX[a][c] = XtX[c][a]
    beta = solve(XtX, Xty)
    out = {}
    for j, t in enumerate(REG_TERMS[:-1]):
        out[t] = r3(math.exp(beta[j]) - 1) if beta and support[t] >= 30 else None
    return out


def gap(a, b):
    return r3(a / b - 1) if a and b else None


# ---------------------------------------------------------------- per scope-year summary
def summarize(year, ft, fy):
    """ft: everyone full-time in the year. fy: full-year full-time workers used for pay."""
    s = {"ft": len(ft),
         "ftG": dict(Counter(w["g"] or "u" for w in ft)),
         "ftE": dict(Counter(w["e"] or "u" for w in ft))}
    if len(fy) < 20:
        return s
    tot = lambda w: w["tot"]
    known_g = [w for w in fy if w["g"]]
    byg = {g: [w for w in fy if w["g"] == g] for g in "mf"}
    bye = {e: [w for w in fy if w["e"] == e] for e in EGROUPS}
    p = {"n": len(fy), "med": r0(median([w["tot"] for w in fy]))}
    p["medG"] = {g: r0(median([w["tot"] for w in ws])) if len(ws) >= 10 else None for g, ws in byg.items()}
    p["nG"] = {g: len(ws) for g, ws in byg.items()}
    p["medE"] = {e: r0(median([w["tot"] for w in ws])) if len(ws) >= 10 else None for e, ws in bye.items()}
    p["nE"] = {e: len(ws) for e, ws in bye.items()}
    sj = same_job_gaps(fy, tot)
    sjr = same_job_gaps(fy, lambda w: w["reg"])
    p["gapG"] = {"raw": gap(p["medG"]["f"], p["medG"]["m"]), "job": sj["f"], "jobReg": sjr["f"],
                 "rawReg": gap(median([w["reg"] for w in byg["f"]]), median([w["reg"] for w in byg["m"]]))}
    p["gapE"] = {e: {"raw": gap(p["medE"][e], p["medE"]["white"]), "job": sj.get(e), "jobReg": sjr.get(e)}
                 for e in EGROUPS if e != "white"}

    def comp(ws):
        if len(ws) < 10:
            return None
        n = len(ws)
        return [r0(sum(w["reg"] for w in ws) / n), r0(sum(w["ot"] for w in ws) / n), r0(sum(w["oth"] for w in ws) / n)]
    p["comp"] = {**{g: comp(ws) for g, ws in byg.items()}, **{e: comp(ws) for e, ws in bye.items()}, "all": comp(fy)}

    # pay ladder: deciles of total pay; women's share and race/ethnicity shares (among known) in each
    if len(fy) >= 200:
        srt = sorted(fy, key=tot)
        dec = []
        for d in range(10):
            ws = srt[len(srt) * d // 10: len(srt) * (d + 1) // 10]
            kg = [w for w in ws if w["g"]]
            ke = [w for w in ws if w["e"]]
            ce = Counter(w["e"] for w in ke)
            dec.append({"lo": r0(ws[0]["tot"]), "hi": r0(ws[-1]["tot"]),
                        "f": r3(sum(w["g"] == "f" for w in kg) / len(kg)) if kg else None,
                        "e": {e: r3(ce[e] / len(ke)) for e in EGROUPS} if ke else None})
        p["dec"] = dec
        top = srt[-max(1, len(srt) // 100):]
        p["top1"] = {"n": len(top), "lo": r0(top[0]["tot"]), "g": dict(Counter(w["g"] or "u" for w in top)),
                     "e": dict(Counter(w["e"] or "u" for w in top))}
    s["pay"] = p
    return s


def jobs_table(fy, titles):
    by = defaultdict(list)
    for w in fy:
        if w["job"]:
            by[w["job"]].append(w)
    out = []
    for job, ws in by.items():
        kg = [w for w in ws if w["g"]]
        if len(ws) < 15 or len(kg) < 10:
            continue
        code, dwp = job.split("|")[0], job.endswith("|DWP")
        title = titles.get(code, ws[0]["title"])
        out.append([title + (" (DWP)" if dwp else ""), len(ws), r3(sum(w["g"] == "f" for w in kg) / len(kg)),
                    r0(median([w["tot"] for w in ws])), r3(sum(w["ot"] for w in ws) / max(1, sum(w["tot"] for w in ws)))])
    out.sort(key=lambda r: -r[1])
    return out


LEVEL = re.compile(r"\s+(I|II|III|IV|V|VI)$")


def tidy_dept(d):
    small = {"and", "of", "for", "de", "los"}
    t = " ".join(w.capitalize() if i == 0 or w.lower() not in small else w.lower() for i, w in enumerate(d.lower().split()))
    return (t.replace("Los Angeles Housing", "Housing (LAHD)").replace("Public Works - ", "Public Works: ")
             .replace("City Employees Retirement System", "LACERS (Retirement System)").replace("Water and Power", "Water and Power (LADWP)")
             .replace("Information Technology Agency", "Information Technology Agency (ITA)"))


def slug(d):
    return re.sub(r"[^a-z0-9]+", "-", d.lower()).strip("-")


# ---------------------------------------------------------------- main
def main():
    P = {y: load_year(y) for y in DL_YEARS}

    # Fill missing gender / race-ethnicity from the same person's nearest other year.
    for y in DL_YEARS:
        for rid, w in P[y].items():
            for k in ("g", "e"):
                if w[k] is None:
                    for d in sorted((yy for yy in DL_YEARS if yy != y), key=lambda yy: (abs(yy - y), -yy)):
                        o = P[d].get(rid)
                        if o and o[k]:
                            w[k] = o[k]
                            break

    # Readable job titles: most common City title for each class code, without the level numeral.
    tc = defaultdict(Counter)
    for y in range(FIRST, LAST + 1):
        for w in P[y].values():
            if w["job"] and w["dept"] != DWP and w["title"] not in ("", "NA"):
                tc[w["code"]][LEVEL.sub("", w["title"].strip())] += 1
    titles = {c: v.most_common(1)[0][0].title().replace("'S", "'s") for c, v in tc.items()}

    depts = Counter()
    for w in P[LAST].values():
        if w["ft"]:
            depts[w["dept"]] += 1
    dept_list = [{"k": "all", "name": "All departments"}] + [
        {"k": slug(d), "name": tidy_dept(d), "raw": d} for d, n in sorted(depts.items(), key=lambda kv: -kv[1]) if n >= 25]
    raw_to_k = {d["raw"]: d["k"] for d in dept_list[1:]}

    S, J, csv_rows = {}, {}, []
    for y in range(FIRST, LAST + 1):
        ft = [w for w in P[y].values() if w["ft"]]
        fy_all = [w for rid, w in P[y].items() if w["ft"] and rid in P[y - 1] and rid in P[y + 1] and w["reg"] > MIN_REG]
        fy = [w for w in fy_all if not (y in DWP_PARTIAL and w["dept"] == DWP)]
        groups = {"all": (ft, fy)}
        for d in dept_list[1:]:
            groups[d["k"]] = ([w for w in ft if w["dept"] == d["raw"]],
                              [] if (y in DWP_PARTIAL and d["raw"] == DWP) else [w for w in fy_all if w["dept"] == d["raw"]])
        for k, (a, b) in groups.items():
            if not a:
                continue
            s = summarize(y, a, b)
            S[f"{k}|{y}"] = s
            J[f"{k}|{y}"] = jobs_table(b, titles)[: (250 if k == "all" else 40)]
            p = s.get("pay", {})
            csv_rows.append({
                "year": y, "department": "All departments" if k == "all" else next(d["name"] for d in dept_list if d["k"] == k),
                "full_time_employees": s["ft"], "women": s["ftG"].get("f", 0), "men": s["ftG"].get("m", 0), "gender_unknown": s["ftG"].get("u", 0),
                **{f"ft_{e}": s["ftE"].get(e, 0) for e in EGROUPS + ["u"]},
                "full_year_workers": p.get("n"), "median_total_pay": p.get("med"),
                "median_pay_women": (p.get("medG") or {}).get("f"), "median_pay_men": (p.get("medG") or {}).get("m"),
                "gender_gap_raw": (p.get("gapG") or {}).get("raw"), "gender_gap_same_job": (p.get("gapG") or {}).get("job"),
                **{f"median_pay_{e}": (p.get("medE") or {}).get(e) for e in EGROUPS},
                **{f"gap_vs_white_same_job_{e}": ((p.get("gapE") or {}).get(e) or {}).get("job") for e in EGROUPS if e != "white"},
            })

    # sensitivity check reported on the page: how much leaving DWP out moves the citywide gender gap
    sens = []
    for y in range(FIRST, LAST + 1):
        if y in DWP_PARTIAL:
            continue
        fy = [w for rid, w in P[y].items() if w["ft"] and rid in P[y - 1] and rid in P[y + 1] and w["reg"] > MIN_REG]
        a = summarize(y, fy, fy)["pay"]["gapG"]["raw"]
        b = summarize(y, fy, [w for w in fy if w["dept"] != DWP])["pay"]["gapG"]["raw"]
        sens.append(abs(a - b))

    for d in dept_list:
        d.pop("raw", None)
    meta = {"years": list(range(FIRST, LAST + 1)), "built": date.today().isoformat(), "dwpPartial": sorted(DWP_PARTIAL),
            "dwpSens": r3(max(sens)), "pop": POP, "source": API.replace(".csv", "")}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "workforce.json"), "w") as f:
        json.dump({"meta": meta, "depts": dept_list, "S": S, "J": J}, f, separators=(",", ":"))
    with open(os.path.join(OUT, "workforce-summary.csv"), "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(csv_rows[0]))
        wr.writeheader()
        wr.writerows(csv_rows)

    a = S[f"all|{LAST}"]["pay"]
    print(f"{len(dept_list) - 1} departments, {len(S)} scope-years. {LAST}: {S[f'all|{LAST}']['ft']:,} full-time, "
          f"{a['n']:,} full-year; gender gap raw {a['gapG']['raw']:+.1%}, same job {a['gapG']['job']:+.1%}; DWP sensitivity {meta['dwpSens']:.1%}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
