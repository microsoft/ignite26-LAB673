"""Generate the lab's architecture diagrams as SVG files.

Run from the repository root:
    python img/diagrams/build_diagrams.py
"""

from html import escape
from pathlib import Path

OUT = Path(__file__).parent

# Border and fill colors per resource type
COLORS = {
    "kb": ("#1864ab", "#d0ebff"),
    "ks": ("#d9480f", "#fff4e6"),
    "index": ("#2b8a3e", "#ebfbee"),
    "owl": ("#862e9c", "#f8f0fc"),
}
KIND_LABELS = {"kb": "Knowledge base", "ks": "Knowledge source", "index": "Search index", "owl": "Ontology file"}
FONT = "Segoe UI, Helvetica, Arial, sans-serif"
TITLE_SIZE, BODY_SIZE, TAG_SIZE, LINE = 19, 15, 12, 1.3
TAG_HEIGHT = TAG_SIZE + 8
TAG_ROOM = 18  # extra height at the top of each box so the text clears the type tag
MODELS = "MR1 + gpt-6-luna\nanswer synthesis"
CHUNKS_BODY = "106 PDF chunks\nwith text vectors"


class Diagram:
    def __init__(self, width, height, title):
        self.width, self.height, self.title = width, height, title
        self.parts = []
        self.boxes = {}
        self.tags = {}

    def text(self, x, y, text, size=BODY_SIZE, anchor="start", weight="normal", color="#212529"):
        lines = text.split("\n")
        spans = "".join(
            f'<tspan x="{x}" dy="{0 if i == 0 else size * LINE}">{escape(line)}</tspan>' for i, line in enumerate(lines)
        )
        self.parts.append(
            f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" '
            f'text-anchor="{anchor}" dominant-baseline="hanging">{spans}</text>'
        )

    def box(self, box_id, x, y, width, height, title, body="", kind="index"):
        stroke, fill = COLORS[kind]
        title_height = (title.count("\n") + 1) * TITLE_SIZE * LINE
        body_height = (body.count("\n") + 1) * BODY_SIZE * LINE + 4 if body else 0
        height = max(height, title_height + body_height + 36) + TAG_ROOM
        self.boxes[box_id] = (x, y, width, height)
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
        top = y + TAG_ROOM + (height - TAG_ROOM - title_height - body_height) / 2
        self.text(x + width / 2, top, title, size=TITLE_SIZE, anchor="middle", weight="600")
        if body:
            self.text(x + width / 2, top + title_height + 4, body, anchor="middle", color="#495057")
        self.tags[box_id] = self.tag(x + width / 2, y, KIND_LABELS[kind], stroke)

    def group(self, group_id, x, y, width, height):
        """A dashed, unfilled outline around boxes that share the same incoming arrows."""
        self.boxes[group_id] = (x, y, width, height)
        self.tags[group_id] = (1, 0)  # No tag, so arrows always end at the outline
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="14" fill="none" '
            f'stroke="#868e96" stroke-width="2" stroke-dasharray="8 6"/>'
        )

    def tag(self, center_x, y, label, color):
        """A pill centered on a box's top border that names the resource type."""
        width = len(label) * TAG_SIZE * 0.62 + 16
        height = TAG_HEIGHT
        x = center_x - width / 2
        self.parts.append(
            f'<rect x="{x:.0f}" y="{y - height / 2}" width="{width:.0f}" height="{height}" rx="{height / 2}" fill="{color}"/>'
        )
        self.parts.append(
            f'<text x="{x + width / 2:.0f}" y="{y}" font-size="{TAG_SIZE}" font-weight="600" fill="#ffffff" '
            f'text-anchor="middle" dominant-baseline="central">{escape(label)}</text>'
        )
        return x, x + width

    def arrow(self, points, label=None, label_at=None, dashed=False, label_anchor="middle"):
        path = " ".join(f"{'M' if i == 0 else 'L'} {px} {py}" for i, (px, py) in enumerate(points))
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        self.parts.append(
            f'<path d="{path}" fill="none" stroke="#495057" stroke-width="2"{dash} marker-end="url(#arrow)"/>'
        )
        if label:
            self.text(*label_at, label, anchor=label_anchor, color="#495057")

    def down(self, from_box, to_box, from_x=None, to_x=None, label=None, dashed=False):
        """Arrow from the bottom edge of one box to the type tag on top of another (centered by default)."""
        ax, ay, aw, ah = self.boxes[from_box]
        bx, by, bw, bh = self.boxes[to_box]
        x0 = from_x if from_x is not None else ax + aw / 2
        x1 = to_x if to_x is not None else bx + bw / 2
        tag_left, tag_right = self.tags[to_box]
        y0, y1 = ay + ah, by - (TAG_HEIGHT / 2 if tag_left <= x1 <= tag_right else 0) - 2
        label_lines = label.count("\n") + 1 if label else 0
        self.arrow([(x0, y0), (x1, y1)], label=label, dashed=dashed, label_anchor="start",
                   label_at=(max(x0, x1) + 14, (y0 + y1) / 2 - label_lines * BODY_SIZE * LINE / 2))

    def left(self, from_box, to_box, label=None):
        """Arrow from the left edge of one box to the right edge of another, at the second box's middle."""
        ax, ay, aw, ah = self.boxes[from_box]
        bx, by, bw, bh = self.boxes[to_box]
        y = by + bh / 2
        x0, x1 = ax, bx + bw + 2
        label_lines = label.count("\n") + 1 if label else 0
        self.arrow([(x0, y), (x1, y)], label=label, label_at=((x0 + x1) / 2, y - 8 - label_lines * BODY_SIZE * LINE))

    def right(self, from_box, to_box, label=None, dashed=False):
        """Arrow from the right edge of one box to the left edge of another, at the second box's middle."""
        ax, ay, aw, ah = self.boxes[from_box]
        bx, by, bw, bh = self.boxes[to_box]
        y = by + bh / 2
        x0, x1 = ax + aw, bx - 2
        label_lines = label.count("\n") + 1 if label else 0
        self.arrow(
            [(x0, y), (x1, y)], label=label, label_at=((x0 + x1) / 2, y - 8 - label_lines * BODY_SIZE * LINE), dashed=dashed
        )

    def save(self, name):
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" '
            f'width="{self.width}" height="{self.height}" font-family="{FONT}" role="img">\n'
            f"<title>{escape(self.title)}</title>\n"
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
            'orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#495057"/></marker></defs>\n'
            f'<rect width="{self.width}" height="{self.height}" fill="#ffffff"/>\n'
            + "\n".join(self.parts)
            + "\n</svg>\n"
        )
        path = OUT / f"{name}.svg"
        path.write_text(svg)
        print(f"Wrote {path}")


def knowledge_base_diagram(name, title, kb, kb_body, arrow_label):
    """One Part 1 knowledge base over the four document knowledge sources and their indexes."""
    d = Diagram(1380, 640, title)
    d.box("kb", 330, 30, 720, 90, kb, kb_body, kind="kb")
    d.group("sources", 20, 255, 1340, 165)
    counts = {"production": 64, "sales": 32, "policies": 10}
    for i, (domain, count) in enumerate(counts.items()):
        x = 40 + i * 440
        d.box(f"ks-{domain}", x, 290, 420, 80, f"cocoarynth-{domain}-knowledge-source", kind="ks")
        d.box(f"index-{domain}", x, 490, 420, 80, f"cocoarynth-{domain}", f"{count} PDF chunks\nwith text vectors", kind="index")
        d.down(f"ks-{domain}", f"index-{domain}")
    d.down("kb", "sources", label=arrow_label)
    d.save(name)


def graph_notebook(name, title, kb, ks, owl, owl_body, index, index_body, link_label):
    d = Diagram(880, 590, title)
    d.box("kb", 40, 30, 400, 90, kb, MODELS, kind="kb")
    d.box("ks", 40, 240, 400, 90, ks, "graphOntology: inline", kind="ks")
    d.box("owl", 580, 245, 260, 80, owl, owl_body, kind="owl")
    d.box("index", 40, 430, 400, 120, index, index_body, kind="index")
    d.box("chunks", 580, 450, 260, 80, "cocoarynth-chunks", CHUNKS_BODY, kind="index")
    d.down("kb", "ks")
    d.left("owl", "ks", label="converted to\nJSON-LD")
    d.down("ks", "index")
    d.right("index", "chunks", label=link_label, dashed=True)
    d.save(name)


if __name__ == "__main__":
    knowledge_base_diagram(
        "notebook-01-standard", "Notebook 01: the standard knowledge base chooses which sources to search",
        "cocoarynth-standard-knowledge-base", "MR1 + gpt-6-luna\nplans queries and writes a cited answer",
        "chooses which sources to search",
    )
    knowledge_base_diagram(
        "notebook-01-mr1", "Notebook 01: the MR1 knowledge base searches every source",
        "cocoarynth-mr1-knowledge-base", "MR1 only\nreturns chunks, not an answer",
        "searches all three sources",
    )
    graph_notebook(
        "notebook-02", "Notebook 02: the graph knowledge source and its ontology",
        "cocoarynth-graph-knowledge-base", "cocoarynth-graph-knowledge-source", "cocoarynth.owl", "13 classes\n13 relationships",
        "cocoarynth-graph", "120 assertions: subject,\npredicate, object\n64 entities, 91 facts",
        "chunk_id\n(provenance)",
    )
    graph_notebook(
        "notebook-03", "Notebook 03: the topics knowledge source and the sitemap ontology",
        "cocoarynth-topics-knowledge-base", "cocoarynth-topics-knowledge-source", "cocoarynth-sitemap.owl", "Topic, Document,\nTextChunk",
        "cocoarynth-topics", "8 topics with labels and vectors\nsitemap links: hasSubtopic,\nhasMember, hasTextChunk",
        "hasMember and\nhasTextChunk\n(provenance)",
    )
