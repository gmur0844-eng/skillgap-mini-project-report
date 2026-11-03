"""Write the LaTeX tables of Chapter 5 from analysis/results.json (no number is typed by hand)."""
import json, sys
from pathlib import Path
R = json.load(open(sys.argv[1])); OUT = Path(sys.argv[2]); s = R["systems"]
CLS = ["SAME_CONCEPT", "PARENT", "CHILD", "PARTIAL_OVERLAP", "RELATED", "UNRELATED", "AMBIGUOUS", "INSUFFICIENT_EVIDENCE"]
MAC = {"SAME_CONCEPT": r"\SC", "PARENT": r"\PA", "CHILD": r"\CH", "PARTIAL_OVERLAP": r"\PO", "RELATED": r"\RE",
       "UNRELATED": r"\UN", "AMBIGUOUS": r"\AM", "INSUFFICIENT_EVIDENCE": r"\IE"}
SHORT = {"SAME_CONCEPT": "SC", "PARENT": "PA", "CHILD": "CH", "PARTIAL_OVERLAP": "PO", "RELATED": "RE", "UNRELATED": "UN",
         "AMBIGUOUS": "AM", "INSUFFICIENT_EVIDENCE": "IE", None: "--"}
def esc(t): return (t or "").replace("&", r"\&").replace("_", r"\_").replace("%", r"\%").replace("#", r"\#")
# confusion matrix v3 raw
def confusion(key, name):
    rows = []
    for g in CLS:
        cnt = [sum(1 for x in s.values() if x["gold"] == g and x[key] == p) for p in CLS]
        if not sum(cnt): continue
        cells = []
        for p, n in zip(CLS, cnt):
            if n == 0: cells.append(r"\textcolor{gray!60}{0}")
            elif p == g: cells.append(r"\cellcolor{green!25}\textbf{%d}" % n)
            else: cells.append(r"\cellcolor{red!%d}%d" % (min(10 + 6 * n, 50), n))
        rows.append(f"{MAC[g]} & " + " & ".join(cells) + f" & {sum(cnt)}" + r" \\")
    tot = [sum(1 for x in s.values() if x[key] == p) for p in CLS]
    head = " & ".join(r"\rotatebox{70}{%s}" % MAC[p] for p in CLS)
    return (r"\begin{tabular}{@{}l" + "c" * 8 + r"c@{}}" "\n\\toprule\n" + r"\textbf{Reference} $\downarrow$ / \textbf{" + name + r"} $\rightarrow$ & " + head +
            r" & \textbf{Total} \\" "\n\\midrule\n" + "\n".join(rows) + "\n\\midrule\n" + r"\textbf{Predicted} & " + " & ".join(map(str, tot)) +
            f" & {sum(tot)}" + r" \\" "\n\\bottomrule\n\\end{tabular}\n")
(OUT / "confusion_v3_raw.tex").write_text(confusion("V3_RAW", "v3 raw"))
(OUT / "confusion_v3_val.tex").write_text(confusion("V3_VAL", "v3 validated"))
(OUT / "confusion_v4_raw.tex").write_text(confusion("V4_RAW", "v4 raw"))
# per-class P/R/F1
def f(v): return "--" if v is None else f"{v:.2f}"
rows = []
for c in CLS:
    a, b = R["prf"]["V3_RAW"][c], R["prf"]["V3_VAL"][c]
    if not (a["support"] or a["pred"] or b["pred"]): continue
    rows.append(f"{MAC[c]} & {a['support']} & {a['pred']} & {f(a['p'])} & {f(a['r'])} & {f(a['f1'])} & {b['pred']} & {f(b['p'])} & {f(b['r'])} & {f(b['f1'])}" + r" \\")
prf = (r"\begin{tabular}{@{}lr|rrrr|rrrr@{}}" "\n\\toprule\n" + r" & & \multicolumn{4}{c|}{\textbf{v3 raw}} & \multicolumn{4}{c}{\textbf{v3 validated}} \\" "\n"
       + r"\textbf{Class} & \textbf{Ref.} & \textbf{Pred.} & \textbf{P} & \textbf{R} & \textbf{F1} & \textbf{Pred.} & \textbf{P} & \textbf{R} & \textbf{F1} \\" "\n\\midrule\n"
       + "\n".join(rows) + "\n\\midrule\n" + r"Macro-F1 (reference classes) & \multicolumn{5}{r|}{%.2f} & \multicolumn{4}{r}{%.2f} \\" % (R["prf"]["V3_RAW"]["_macro_f1_over_reference_classes"], R["prf"]["V3_VAL"]["_macro_f1_over_reference_classes"])
       + "\n\\bottomrule\n\\end{tabular}\n")
(OUT / "prf_v3.tex").write_text(prf)
# error categories with cases
cat_names = {"narrower_as_same": (r"Narrower concept called same (\CH~$\rightarrow$~\SC)"), "overlap_as_same": (r"Partial overlap called same (\PO~$\rightarrow$~\SC)"),
             "broader_as_related": (r"Broader concept called related (\PA~$\rightarrow$~\RE)")}
lines = []
for k, title in cat_names.items():
    cases = R["error_cases"][k]
    lines.append(r"\multicolumn{3}{@{}l}{\textbf{" + title + f": {len(cases)} cases" + r"}} \\")
    for q, left, right in cases:
        lines.append(f"{q} & {esc(left)} & {esc(right)}" + r" \\")
    lines.append(r"\addlinespace")
(OUT / "error_cases.tex").write_text(r"\begin{tabularx}{\textwidth}{@{}p{1.5cm}X X@{}}" "\n\\toprule\n" + r"\textbf{Case} & \textbf{Concept A (source)} & \textbf{Concept B (ESCO concept or topic)} \\" "\n\\midrule\n" + "\n".join(lines) + "\n\\bottomrule\n\\end{tabularx}\n")
# pairwise agreement
ids = ["R01", "R02", "R03", "R04", "R05"]
rows = []
for a in ids:
    cells = []
    for b in ids:
        if a == b: cells.append("--")
        else:
            k = R["pairwise"].get(f"{a}-{b}") or R["pairwise"].get(f"{b}-{a}")
            cells.append(f"{k['kappa']:.2f} ({k['agree']})")
    rows.append(f"{a} & " + " & ".join(cells) + r" \\")
(OUT / "pairwise.tex").write_text(r"\begin{tabular}{@{}l" + "c" * 5 + r"@{}}" "\n\\toprule\n & " + " & ".join(r"\textbf{%s}" % i for i in ids) + r" \\" "\n\\midrule\n" + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n")
# per-case longtable
rows = []
for q, x in sorted(s.items()):
    def mark(v): return (r"\textbf{%s}" % SHORT[v]) if v == x["gold"] else SHORT[v]
    rows.append(f"{q} & {esc(x['left'][:34])}{'\\ldots' if len(x['left'])>34 else ''} & {esc(x['right'][:30])}{'\\ldots' if len(x['right'])>30 else ''} & {SHORT[x['gold']]} & {mark(x['V3_RAW'])} & {mark(x['V3_VAL'])} & {mark(x['V4_RAW'])}" + r" \\")
(OUT / "per_case.tex").write_text("\n".join(rows) + "\n")
# kind table
rows = [f"\\code{{{esc(k)}}} & {v['n']} & {v['raw']} & {v['val']} & {sum(1 for x in s.values() if x['kind']==k and x['V4_RAW']==x['gold'])}" + r" \\" for k, v in R["kind_v3"].items()]
(OUT / "by_kind.tex").write_text("\n".join(rows) + "\n")
print("ok", sorted(p.name for p in OUT.iterdir()))
