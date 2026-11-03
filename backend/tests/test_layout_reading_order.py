"""
Reading order and page-break continuation for table-aware extraction.
Minimal pdfplumber-like fakes reproduce the SHAPE of real reference pages:
(1) a course header ABOVE its Topics table must precede the table text;
(2) a Topics table that continues across a page break has no header row on
the next page; its rows are still topics of the same column;
(3) a long data cell containing the word "content" is not a header;
(4) a first row carrying a course header starts a new course, not a continuation.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipelines.preprocessing.layout_aware_extraction import (
    extract_page_blocks, page_topic_table_layout, reconstruct_page_text,
)


class FakeTable:
    def __init__(self, rows, bbox):
        self._rows, self.bbox = rows, bbox

    def extract(self):
        return self._rows


class FakePage:
    def __init__(self, tables, words):
        self._tables, self._words = tables, words

    def find_tables(self):
        return self._tables

    def extract_words(self):
        return self._words


def _words(line, top, x0=10):
    out, x = [], x0
    for w in line.split():
        out.append({"text": w, "x0": x, "x1": x + 5 * len(w), "top": top, "bottom": top + 8})
        x += 5 * len(w) + 4
    return out


def test_course_header_above_table_precedes_topics():
    table = FakeTable([["Unit #", "Topics"], ["1.", "Soldering and PCB design"]], (0, 200, 600, 400))
    words = _words("AB-101 Workshop Lab 2L:0T:4P", 100) + _words("Course Contents:", 150) + _words("47", 700)
    text = reconstruct_page_text(extract_page_blocks(FakePage([table], words)))
    assert text.index("AB-101") < text.index("Topics: Soldering")
    assert text.index("Topics: Soldering") < text.index("47")


def test_topics_table_continues_across_page_break():
    first = FakeTable([["Module", "Topics", "Pedagogy"], ["Unit 1", "Hashing", "Explain with examples"]], (0, 300, 600, 700))
    page1 = FakePage([first], _words("119", 750))
    blocks1 = extract_page_blocks(page1)
    layout = page_topic_table_layout(blocks1)
    assert layout == {"ncols": 3, "topic_col_idx": 1, "module_col_idx": 0}

    cont = FakeTable([["Unit 2", "Binary search trees", "Motivate students with the content of real data"]], (0, 50, 600, 300))
    blocks2 = extract_page_blocks(FakePage([cont], []), layout)
    topics = [b["text"] for b in blocks2 if b["block_type"] == "table_topic_column"]
    assert topics == ["Binary search trees"]
    assert blocks2[0]["table_layout"]["continued"] is True


def test_prose_after_table_ends_continuation():
    table = FakeTable([["Module", "Topics"], ["1", "Hashing"]], (0, 100, 600, 300))
    words = _words("Course Outcomes: students will be able to design hash tables", 400)
    assert page_topic_table_layout(extract_page_blocks(FakePage([table], words))) is None


def test_long_cell_mentioning_content_is_not_a_header():
    table = FakeTable([["Trees", "Heaps", "Focus on mathematical and algorithmic precise description of the content"]],
                      (0, 50, 600, 300))
    blocks = extract_page_blocks(FakePage([table], []))
    assert not any(b["block_type"] == "table_topic_column" for b in blocks)


def test_new_course_header_row_is_not_a_continuation():
    layout = {"ncols": 4, "topic_col_idx": 1, "module_col_idx": 0}
    header_table = FakeTable([["PCC CS-603", "Machine Learning", "3L:1T:0P", "4 Credits"]], (0, 50, 600, 80))
    blocks = extract_page_blocks(FakePage([header_table], []), layout)
    assert not any(b["block_type"] == "table_topic_column" for b in blocks)
