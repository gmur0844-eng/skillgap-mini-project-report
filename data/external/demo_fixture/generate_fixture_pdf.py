"""
Generates data/external/demo_fixture/sample_curriculum.pdf — a small,
STRUCTURALLY REALISTIC but entirely made-up curriculum document, used only to
test the PDF extraction/structuring pipeline. This is NOT a real university
curriculum and must never be used as analytical input (see README.md in this
folder). Run once with `python generate_fixture_pdf.py`.

Dependency note: this script requires `reportlab` (pip install reportlab),
which is intentionally NOT in backend/requirements.txt -- it is a one-off
tooling dependency for regenerating this fixture, not something the actual
application/pipeline needs at runtime.
"""
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT_PATH = Path(__file__).parent / "sample_curriculum.pdf"

PAGE_1 = [
    "DEMO UNIVERSITY (FIXTURE DATA - NOT REAL)",
    "B.Tech Computer Science - Programme Handbook",
    "",
    "CS101 Introduction to Programming",
    "Unit 1: Programming Fundamentals",
    "Topics: variables, control flow, functions, recursion",
    "Course Outcomes",
    "- Write basic procedural programs",
    "- Debug simple logic errors",
]

PAGE_2 = [
    "CS301 Machine Learning",
    "Unit 1: Supervised Learning",
    "Topics: regression, classification, decision trees, neural networks",
    "Unit 2: Deep Learning",
    "Topics: backpropagation, CNNs, transformers",
    "Course Outcomes",
    "- Train and evaluate a supervised model",
    "- Explain the bias-variance tradeoff",
]

PAGE_3 = [
    "CS405 Cloud Computing",
    "Unit 1: Cloud Fundamentals",
    "Topics: virtualization, containers, AWS, GCP",
    "Unit 2: Orchestration",
    "Topics: Docker, Kubernetes, CI/CD pipelines",
]


def draw_page(c, lines):
    c.setFont("Helvetica", 11)
    y = 800
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
    c.showPage()


def main():
    c = canvas.Canvas(str(OUT_PATH), pagesize=A4)
    for page_lines in (PAGE_1, PAGE_2, PAGE_3):
        draw_page(c, page_lines)
    c.save()
    print(f"Wrote fixture PDF to {OUT_PATH}")


if __name__ == "__main__":
    main()
