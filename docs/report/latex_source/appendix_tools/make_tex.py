"""Writes code_attachments.tex (Appendix A) from the verbatim project lines in snippets.json."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import snippets
ROOT = Path(sys.argv[1]); OUT = Path(sys.argv[2])
snippets.ROOT = ROOT
def esc(t):
    for a, b in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"), ("#", r"\#"), ("$", r"\$")]:
        t = t.replace(a, b)
    return t.replace("'s", "'s")
out = [r"\chapter{CODE ATTACHMENTS}", r"\label{app:code}", "",
 "This appendix reproduces short excerpts of the project source that implement the parts of the module evaluated in this report. "
 "The lines are copied verbatim from the repository; the numbers in the margin are the line numbers in the original file. "
 "Excerpts are limited to the code discussed in the chapters, so the rest of each file is omitted.", ""]
for s in snippets.SNIPPETS:
    src = (ROOT / s["file"]).read_text(encoding="utf-8").splitlines()
    for ln in (l for a, b in s["ranges"] for l in src[a-1:b]):
        assert ln.isascii(), (s["id"], ln)
    out += [rf"\section{{{esc(s['title'])}}}", rf"\label{{app:{s['id'].replace('.', '')}}}",
            esc(s["text"]).replace("Section ", r"Section~").replace("Table ", r"Table~").replace("Equation ", r"Equation~")
            + rf" Source: \code{{{esc(s['file']).replace('/', '/' + chr(92) + 'allowbreak{}')}}}, lines " + ", ".join(f"{a}--{b}" for a, b in s["ranges"]) + ".", ""]
    for k, (a, b) in enumerate(s["ranges"]):
        if k:
            out += [rf"\noindent{{\small\itshape Lines {s['ranges'][k-1][1]+1}--{a-1} omitted.}}", ""]
        out += [rf"\begin{{lstlisting}}[style=repo, firstnumber={a}]"] + src[a-1:b] + [r"\end{lstlisting}", ""]
OUT.write_text("\n".join(out) + "\n")
print("written", OUT)
