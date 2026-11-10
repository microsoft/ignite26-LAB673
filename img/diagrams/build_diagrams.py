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
    "topicgraph": ("#5f3dc4", "#f3f0ff"),
    "topic": ("#0b7285", "#e3fafc"),
    "vector": ("#e67700", "#fff9db"),
}
KIND_LABELS = {
    "kb": "Knowledge base", "ks": "Knowledge source", "index": "Search index", "owl": "Ontology file",
    "topicgraph": "TopicGraph", "topic": "Topic", "vector": "Vector",
}
FONT = "Segoe UI, Helvetica, Arial, sans-serif"
TITLE_SIZE, BODY_SIZE, TAG_SIZE, LINE = 19, 15, 12, 1.3
TAG_HEIGHT = TAG_SIZE + 8
TAG_ROOM = 18  # extra height at the top of each box so the text clears the type tag
MODELS = "MR1 + gpt-6-luna\nanswer synthesis"
CHUNKS_BODY = "106 PDF chunks\nwith text vectors"


class Diagram:
    def __init__(self, width, height, title, description=None, title_size=TITLE_SIZE, body_size=BODY_SIZE,
                 tag_size=TAG_SIZE):
        self.width, self.height, self.title, self.description = width, height, title, description
        self.title_size, self.body_size, self.tag_size = title_size, body_size, tag_size
        self.tag_height = tag_size + 8
        self.tag_room = round(TAG_ROOM * tag_size / TAG_SIZE)  # extra height at the top of each box so the text clears the type tag
        self.parts = []
        self.boxes = {}
        self.tags = {}
        self.markers = {"arrow": "#495057"}

    def text(self, x, y, text, size=None, anchor="start", weight="normal", color="#212529", italic=False,
             baseline="hanging"):
        size = size or self.body_size
        lines = text.split("\n")
        spans = "".join(
            f'<tspan x="{x}" dy="{0 if i == 0 else size * LINE}">{escape(line)}</tspan>' for i, line in enumerate(lines)
        )
        style = ' font-style="italic"' if italic else ""
        self.parts.append(
            f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}"{style} '
            f'text-anchor="{anchor}" dominant-baseline="{baseline}">{spans}</text>'
        )

    def rect(self, x, y, width, height, fill="#ffffff", stroke="#adb5bd", stroke_width=2, rx=10, dashed=False):
        dash = ' stroke-dasharray="8 6"' if dashed else ""
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{rx}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{stroke_width}"{dash}/>'
        )

    def circle(self, cx, cy, r, fill="#ffffff", stroke="none", stroke_width=2):
        self.parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )

    def line(self, points, color="#495057", width=2, dash=None, arrow=False):
        """A polyline; with arrow=True it ends in an arrowhead of the same color."""
        path = " ".join(f"{'M' if i == 0 else 'L'} {px} {py}" for i, (px, py) in enumerate(points))
        dash = f' stroke-dasharray="{dash}"' if dash else ""
        marker = ""
        if arrow:
            marker_id = "arrow" if color == self.markers["arrow"] else f"arrow-{color.lstrip('#')}"
            self.markers[marker_id] = color
            marker = f' marker-end="url(#{marker_id})"'
        self.parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{width}"{dash}{marker}/>')

    def box_height(self, title, body="", height=0):
        title_height = (title.count("\n") + 1) * self.title_size * LINE
        body_height = (body.count("\n") + 1) * self.body_size * LINE + 4 if body else 0
        return max(height, title_height + body_height + 36) + self.tag_room

    def box(self, box_id, x, y, width, height, title, body="", kind="index", tag=None):
        stroke, fill = COLORS[kind]
        title_height = (title.count("\n") + 1) * self.title_size * LINE
        body_height = (body.count("\n") + 1) * self.body_size * LINE + 4 if body else 0
        height = self.box_height(title, body, height)
        self.boxes[box_id] = (x, y, width, height)
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
        top = y + self.tag_room + (height - self.tag_room - title_height - body_height) / 2
        self.text(x + width / 2, top, title, size=self.title_size, anchor="middle", weight="600")
        if body:
            self.text(x + width / 2, top + title_height + 4, body, anchor="middle", color="#495057")
        self.tags[box_id] = self.tag(x + width / 2, y, tag or KIND_LABELS[kind], stroke)

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
        width = len(label) * self.tag_size * 0.62 + 16
        height = self.tag_height
        x = center_x - width / 2
        self.parts.append(
            f'<rect x="{x:.0f}" y="{y - height / 2}" width="{width:.0f}" height="{height}" rx="{height / 2}" fill="{color}"/>'
        )
        self.parts.append(
            f'<text x="{x + width / 2:.0f}" y="{y}" font-size="{self.tag_size}" font-weight="600" fill="#ffffff" '
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
        y0, y1 = ay + ah, by - (self.tag_height / 2 if tag_left <= x1 <= tag_right else 0) - 2
        label_lines = label.count("\n") + 1 if label else 0
        self.arrow([(x0, y0), (x1, y1)], label=label, dashed=dashed, label_anchor="start",
                   label_at=(max(x0, x1) + 14, (y0 + y1) / 2 - label_lines * self.body_size * LINE / 2))

    def left(self, from_box, to_box, label=None):
        """Arrow from the left edge of one box to the right edge of another, at the second box's middle."""
        ax, ay, aw, ah = self.boxes[from_box]
        bx, by, bw, bh = self.boxes[to_box]
        y = by + bh / 2
        x0, x1 = ax, bx + bw + 2
        label_lines = label.count("\n") + 1 if label else 0
        self.arrow([(x0, y), (x1, y)], label=label, label_at=((x0 + x1) / 2, y - 8 - label_lines * self.body_size * LINE))

    def right(self, from_box, to_box, label=None, dashed=False):
        """Arrow from the right edge of one box to the left edge of another, at the second box's middle."""
        ax, ay, aw, ah = self.boxes[from_box]
        bx, by, bw, bh = self.boxes[to_box]
        y = by + bh / 2
        x0, x1 = ax + aw, bx - 2
        label_lines = label.count("\n") + 1 if label else 0
        self.arrow(
            [(x0, y), (x1, y)], label=label, label_at=((x0 + x1) / 2, y - 8 - label_lines * self.body_size * LINE), dashed=dashed
        )

    def save(self, name):
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" '
            f'width="{self.width}" height="{self.height}" font-family="{FONT}" role="img">\n'
            f"<title>{escape(self.title)}</title>\n"
            + (f"<desc>{escape(self.description)}</desc>\n" if self.description else "")
            + "<defs>"
            + "".join(
                f'<marker id="{marker_id}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
                f'orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>'
                for marker_id, color in self.markers.items()
            )
            + "</defs>\n"
            f'<rect width="{self.width}" height="{self.height}" fill="#ffffff"/>\n'
            + "\n".join(self.parts)
            + "\n</svg>\n"
        )
        path = OUT / f"{name}.svg"
        path.write_text(svg, encoding="utf-8")
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


# Larger type for the Part 3 topic graph diagrams, which the notebook shows one above the other
TOPIC_SIZES = {"title_size": 24, "body_size": 22, "tag_size": 18}
TOPIC_WIDTH = 960
CHUNK_STROKE, CHUNK_FILL = "#868e96", "#f8f9fa"
TOPIC_COLOR, CENTROID_COLOR = COLORS["topic"][0], COLORS["vector"][0]


def panel_heading(d, number, heading, subheading):
    """A numbered heading for one of the stacked topic graph panels."""
    d.circle(52, 46, 22, fill=TOPIC_COLOR)
    d.text(52, 47, str(number), size=24, anchor="middle", weight="700", color="#ffffff", baseline="central")
    d.text(90, 47, heading, size=28, weight="600", baseline="central")
    d.text(90, 82, subheading, color="#495057")


def note(d, x, y, width, height, text):
    d.rect(x, y, width, height, fill="#f8f9fa", stroke="#dee2e6")
    d.text(x + 20, y + 18, text, size=20, color="#343a40")


def chunk_card(d, x, y, dashed=False):
    d.rect(x, y, 130, 60, fill=CHUNK_FILL, stroke=CHUNK_STROKE, dashed=dashed)
    d.text(x + 65, y + 31, "chunk", size=20, anchor="middle", color="#495057", baseline="central")


def centroid(d, center_x, top):
    d.line([(center_x, top), (center_x, top + 22)], color=CENTROID_COLOR, width=2)
    d.circle(center_x, top + 34, 12, fill=CENTROID_COLOR)
    d.text(center_x + 22, top + 35, "centroid", size=20, color=CENTROID_COLOR, weight="600", baseline="central")


def topics_chunks_diagram():
    d = Diagram(
        TOPIC_WIDTH, 490, "Topic graph, step 1: compare chunk embeddings",
        "Seven chunk cards from the PDFs. Chunks with similar embeddings sit close together and are joined by dashed "
        "lines, forming two loose groups. One chunk has no close match and won't join a topic. Chunks are text from "
        "the original PDFs, not entities or extracted facts.",
        **TOPIC_SIZES,
    )
    panel_heading(d, 1, "Compare chunk embeddings", "Each card is one chunk of text from a PDF.")
    d.line([(640, 128), (700, 128)], color=TOPIC_COLOR, width=3, dash="7 6")
    d.text(712, 128, "similar embeddings", size=20, color=TOPIC_COLOR, baseline="central")
    groups = [[(70, 170), (250, 150), (160, 270)], [(570, 160), (760, 170), (660, 275)]]
    for cards in groups:
        for i, (x0, y0) in enumerate(cards):
            x1, y1 = cards[(i + 1) % len(cards)]
            d.line([(x0 + 65, y0 + 30), (x1 + 65, y1 + 30)], color=TOPIC_COLOR, width=3, dash="7 6")
    for cards in groups:
        for x, y in cards:
            chunk_card(d, x, y)
    chunk_card(d, 415, 300, dashed=True)
    d.text(480, 372, "no close match:\nnot in any topic", size=20, anchor="middle", color="#868e96")
    d.text(TOPIC_WIDTH / 2, 458, "Chunks are text from the original PDFs, not entities or extracted facts.",
           anchor="middle", weight="600", baseline="central")
    d.save("notebook-03-topics-1-chunks")


def topics_tree_diagram():
    d = Diagram(
        TOPIC_WIDTH, 600, "Topic graph, step 2: group similar chunks into topics",
        "A broad topic at level 0 has two subtopics, A and B, at level 1. A second broad topic at level 0 has no "
        "subtopics. Topics without subtopics are terminal topics, and each terminal topic stores a centroid vector. "
        "Similarity groups chunks; it doesn't assert facts. Titles describe a topic; they don't define it.",
        **TOPIC_SIZES,
    )
    panel_heading(d, 2, "Group similar chunks into topics", "Topics have two levels. Terminal topics have no subtopics.")
    d.box("broad", 40, 150, 440, 0, "Broad topic", "has subtopics", kind="topic", tag="Topic · level 0")
    d.box("solo", 560, 150, 360, 0, "Broad topic", "no subtopics: terminal", kind="topic", tag="Topic · level 0")
    d.box("a", 40, 340, 210, 0, "Subtopic A", "terminal", kind="topic", tag="Topic · level 1")
    d.box("b", 270, 340, 210, 0, "Subtopic B", "terminal", kind="topic", tag="Topic · level 1")
    d.down("broad", "a")
    d.down("broad", "b")
    for box_id in ("a", "b", "solo"):
        x, y, width, height = d.boxes[box_id]
        centroid(d, x + width / 2 - 40, y + height)
    d.text(TOPIC_WIDTH / 2, 538,
           "Similarity groups chunks; it doesn't assert facts.\nTitles describe a topic; they don't define it.",
           anchor="middle", weight="600")
    d.save("notebook-03-topics-2-topics")


def topic_graph_diagram():
    d = Diagram(
        TOPIC_WIDTH, 930, "Topic graph, step 3: navigate the topic graph, then read the evidence",
        "The topic index stores the topic graph as facts. The TopicGraph topicgraph-topic points to each level-0 "
        "topic through HasRootTopic. A broad topic points to each subtopic at level 1 through HasSubTopic. Each terminal "
        "topic points to its centroid Vector through HasCentroidVector. A vector search with a centroid over "
        "cocoarynth-chunks returns the nearest PDF chunks: examples for browsing, not stored membership. Topics guide "
        "where to look. Source chunks provide the evidence.",
        **TOPIC_SIZES,
    )
    panel_heading(d, 3, "Navigate the topic graph, then read the evidence",
                  "The topic index stores the graph as facts. Chunks stay in the source index.")
    d.box("graph", 60, 140, 400, 0, "topicgraph-topic", "the whole topic graph", kind="topicgraph")
    d.box("broad", 60, 330, 400, 0, "Broad topic", "level 0", kind="topic")
    d.box("narrow", 60, 520, 400, 0, "Subtopic", "level 1 · terminal", kind="topic")
    d.box("vector", 60, 710, 400, 0, "Centroid", "terminal topics only", kind="vector")
    d.box("chunks", 580, 710, 340, 0, "cocoarynth-chunks", "nearest PDF chunks:\nexamples, not membership",
          kind="index")
    d.down("graph", "broad", label="HasRootTopic")
    d.down("broad", "narrow", label="HasSubTopic")
    d.down("narrow", "vector", label="HasCentroidVector")
    d.right("vector", "chunks", label="vector\nsearch")
    note(d, 580, 140, 340, 150, "GQL follows HasRootTopic\nand HasSubTopic to walk\nfrom broad topics to\ntheir subtopics.")
    note(d, 580, 330, 340, 150, "A broad topic with no\nsubtopics is also terminal,\nso it has its own\ncentroid.")
    d.text(TOPIC_WIDTH / 2, 892, "Topics guide where to look. Source chunks provide the evidence.",
           anchor="middle", weight="600", baseline="central")
    d.save("notebook-03-topic-graph")


def topic_graph_notebook():
    """The Part 3 knowledge base, knowledge source, ontology, and indexes, in larger type than Parts 1 and 2."""
    d = Diagram(
        1100, 750, "Notebook 03: the topic graph knowledge source and its ontology",
        "cocoarynth-topics-knowledge-base uses cocoarynth-topics-knowledge-source, whose graphOntology is the "
        "cocoarynth-sitemap.owl ontology converted to inline JSON-LD. The knowledge source searches the "
        "cocoarynth-topics index: 54 facts about 8 topics, including 6 centroid vectors linked by HasRootTopic and "
        "HasSubTopic. A separate centroid search finds nearby chunks in cocoarynth-chunks.",
        title_size=26, body_size=22, tag_size=16,
    )
    d.box("kb", 40, 40, 540, 0, "cocoarynth-topics-knowledge-base", MODELS, kind="kb")
    d.box("ks", 40, 280, 540, 0, "cocoarynth-topics-knowledge-source", "graphOntology: inline", kind="ks")
    owl_title, owl_body = "cocoarynth-sitemap.owl", "TopicGraph, Topic,\nVector"
    ks_mid = 280 + d.boxes["ks"][3] / 2
    d.box("owl", 740, round(ks_mid - d.box_height(owl_title, owl_body) / 2), 340, 0, owl_title, owl_body, kind="owl")
    d.box("index", 40, 540, 540, 0, "cocoarynth-topics",
          "54 facts: 8 topics,\n6 centroid vectors\nHasRootTopic, HasSubTopic", kind="index")
    chunks_title = "cocoarynth-chunks"
    index_mid = 540 + d.boxes["index"][3] / 2
    d.box("chunks", 740, round(index_mid - d.box_height(chunks_title, CHUNKS_BODY) / 2), 340, 0, chunks_title,
          CHUNKS_BODY, kind="index")
    d.down("kb", "ks")
    d.left("owl", "ks", label="converted to\nJSON-LD")
    d.down("ks", "index")
    d.right("index", "chunks", label="centroid\nsearch", dashed=True)
    d.save("notebook-03")


if __name__ == "__main__":
    knowledge_base_diagram(
        "notebook-01-standard", "Notebook 01: the standard knowledge base chooses which sources to search",
        "cocoarynth-standard-knowledge-base", "MR1 + gpt-6-luna configured\nLow uses gpt-6-luna to plan and answer",
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
    topics_chunks_diagram()
    topics_tree_diagram()
    topic_graph_diagram()
    topic_graph_notebook()
