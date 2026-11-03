"""Replace the Appendix A placeholder of the team's Word report with the code excerpts (nothing else changes)."""
import copy, json, sys
import docx
from docx.enum.text import WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Cm

SRC, SNIP, OUT = sys.argv[1:4]
d = docx.Document(SRC)
snips = json.load(open(SNIP))
P = d.paragraphs
head = next(i for i, p in enumerate(P) if p.text.strip() == "CODE ATTACHMENTS" and p.style.name == "Chapter Heading")
placeholder = [p for p in P[head + 1:head + 4] if p.style.name == "Body Text No Indent"]
assert len(placeholder) == 3 and placeholder[0].text.startswith("PLACEHOLDER"), [p.text[:40] for p in placeholder]
anchor = placeholder[-1]._p          # new content goes after the placeholder, which is then removed

def new_par(style, text="", after=None):
    p = d.add_paragraph(text, style=style)
    after.addnext(p._p)
    return p

def code_table(lines, after):
    t = d.add_table(rows=1, cols=1)
    tbl = t._tbl
    after.addnext(tbl)
    tblPr = tbl.tblPr
    w = OxmlElement("w:tblW"); w.set(qn("w:w"), "5000"); w.set(qn("w:type"), "pct"); tblPr.append(w)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right"):
        e = OxmlElement(f"w:{edge}"); e.set(qn("w:val"), "single"); e.set(qn("w:sz"), "4"); e.set(qn("w:color"), "A6A6A6")
        borders.append(e)
    tblPr.append(borders)
    cell = t.rows[0].cells[0]
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd"); shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), "F4F4F4")
    tcPr.append(shd)
    first = cell.paragraphs[0]
    for k, line in enumerate(lines):
        p = first if k == 0 else cell.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(0); pf.space_after = Pt(0)
        pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
        pf.left_indent = Cm(0.6); pf.first_line_indent = Cm(-0.6)   # wrapped continuation lines are indented
        r = p.add_run(line if line else " ")
        r.font.name = "Courier New"; r.font.size = Pt(7.5)
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "Courier New")
    return tbl

cur = anchor
intro = ("This appendix reproduces the parts of the project's source code that implement what this report describes. "
         "Each excerpt is copied verbatim from the repository; its file and line numbers are given with it, and lines "
         "left out are marked. Long lines wrap in print.")
cur = new_par("Body Text Report", intro, cur)._p
for s in snips:
    cur = new_par("Heading 2", f"{s['id']} {s['title']}", cur)._p
    cur = new_par("Body Text Report", s["text"], cur)._p
    note = new_par("Caption Note", "", cur)
    note.add_run("Source: ")
    r = note.add_run(s["file"]); r.font.name = "Courier New"
    note.add_run(f", lines {s['range_text'].replace('-', '–')}.")
    cur = note._p
    cur = code_table(s["lines"], cur)
for p in placeholder:
    p._p.getparent().remove(p._p)
# ask Word to refresh the table of contents and lists (page numbers move after the appendix grows)
st = d.settings.element
for old_uf in st.findall(qn("w:updateFields")):
    st.remove(old_uf)
uf = OxmlElement("w:updateFields"); uf.set(qn("w:val"), "true"); st.append(uf)
d.save(OUT)
print("saved", OUT)
