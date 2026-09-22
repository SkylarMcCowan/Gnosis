"""PyQt study panel. UI consumes the catalog; no occult records live here."""

from datetime import datetime, timezone
from html import escape
import random

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QBrush,
    QPen,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QDesktopServices,
)
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QSplitter,
    QTextBrowser,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QPushButton,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsLineItem,
    QGraphicsEllipseItem,
    QGraphicsItem,
)

from .model import Catalog, paragraph, link
from .study import Progress, question_bank


INTRO = """
<h1>Golden Dawn / Thoth Tarot Study</h1>

<p>Learn the structure before memorizing meanings.</p>

<pre>
                        TAROT
               ┌───────────┴───────────┐
          MAJOR ARCANA           NUMBERED MINORS
            22 PATHS              10 SEPHIROTH
         Hebrew letters           Numbers 1–10
      Elements / astrology        × four suits
</pre>

<p>
<b>Court Cards</b> form their own elemental and zodiacal
structure and are the next major catalog expansion.
</p>

<h3>Your learning sequence</h3>

<p>
Tree of Life → Sephiroth → Paths → Elements → Astrology
→ Tarot → Opening of the Key
</p>

<p>
Start with a Sephirah. Compare its four numbered cards,
then follow a connecting Path. Use <b>Derive this card</b>
to build an interpretation one layer at a time.
</p>

<p>
The Opening of the Key section now teaches the complete
five-operation structure, physical dealing procedure,
card counting and pairing method.
</p>

<p>
This is an introduction to Hermetic Qabalah as used in
Golden Dawn-derived Tarot, not a comprehensive account of
Jewish Kabbalah. The correspondences belong to a historical
esoteric system; they are not scientifically established
causal relationships.
</p>

<h3>Two traditions, explicitly distinguished</h3>

<p>
The Tree uses the conventional Golden Dawn letter-path
arrangement. Card pages show Crowley/Thoth titles, imagery
and changes in a separate comparison. A trump number is
not a Path number. Strength/Justice numbering also varies
among published witnesses.
</p>

<h3>Available in this milestone</h3>

<p>
10 Sephiroth · 22 Paths · 22 Majors · 40 numbered Minors ·
interactive pillars · card derivation · Opening of the Key
curriculum · local quizzes and review progress.
</p>

<p>
Court Cards, a full elemental-dignity laboratory and
virtual 78-card OOTK simulation remain later modules.
</p>
"""


PILLARS = """
<h3>Three Pillars · modern explanation of traditional symbolism</h3>

<p>
<b>Mercy — right:</b> expansion and outgoing activity.
<b>Severity — left:</b> contraction, definition and
receptive form.
<b>Middle — center:</b> equilibrium and reconciliation.
</p>

<p>
These complementary polarities are not good versus evil.
Historical masculine/feminine language is symbolic and
relational, not a division into literal biological genders.
</p>

<p>
Tiphareth mediates as the solar center: equilibrium
coordinates the opposing tendencies rather than erasing
either. The Middle Pillar links source, reconciliation,
foundation and manifestation.
</p>
"""


PLANNED = {
    "Court Cards": (
        "Study Knight, Queen, Prince and Princess as elemental "
        "combinations, with versioned zodiacal regions. Court "
        "cards are not simply numbered Sephiroth or personality "
        "labels."
    ),
    "Astrology & Decans": (
        "An interactive zodiac wheel and 36-decan table will "
        "connect signs to numbered Minors 2–10. Basic decan "
        "attributions are already visible on card pages. "
        "Aces have no individual decan."
    ),
    "Elemental Dignities": (
        "Compare pairs and small groups of elements, then ask "
        "how their interaction modifies the reading. Historical "
        "rules will be sourced and distinguished from modern "
        "variations. OOTK lessons already explain where "
        "elemental qualification enters the procedure."
    ),
    "Spreads & Divination": (
        "Additional source-labeled layouts and interpretation "
        "methods will distinguish documented Golden Dawn "
        "material, later occult practice and Thoth adaptations. "
        "Opening of the Key is now implemented separately."
    ),
}


class PathItem(QGraphicsLineItem):
    def __init__(
        self,
        path_id,
        a,
        b,
        callback,
    ):
        super().__init__(
            *a,
            *b,
        )

        self.path_id = path_id
        self.callback = callback

        self.setPen(
            QPen(
                QColor("#68738c"),
                4,
            )
        )

        self.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )

        self.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

    def shape(self):
        line = self.line()

        path = QPainterPath(
            line.p1()
        )

        path.lineTo(
            line.p2()
        )

        stroker = QPainterPathStroker()
        stroker.setWidth(16)

        return stroker.createStroke(
            path
        )

    def mousePressEvent(
        self,
        event,
    ):
        self.callback(
            "path",
            str(self.path_id),
        )

        event.accept()

    def keyPressEvent(
        self,
        event,
    ):
        if event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Space,
        ):
            self.callback(
                "path",
                str(self.path_id),
            )
        else:
            super().keyPressEvent(
                event
            )


class SephirahItem(QGraphicsEllipseItem):
    def __init__(
        self,
        record,
        callback,
    ):
        x, y = record["position"]

        super().__init__(
            x - 52,
            y - 36,
            104,
            72,
        )

        self.record = record
        self.callback = callback

        self.setZValue(2)

        self.setPen(
            QPen(
                QColor("#c7b582"),
                2,
            )
        )

        self.setBrush(
            QBrush(
                QColor("#242a40")
            )
        )

        self.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )

        self.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        self.setToolTip(
            (
                f"{record['id']}. "
                f"{record['name']} — "
                f"{record['translation']}"
            )
        )

    def mousePressEvent(
        self,
        event,
    ):
        self.callback(
            "sephirah",
            str(self.record["id"]),
        )

        event.accept()

    def keyPressEvent(
        self,
        event,
    ):
        if event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Space,
        ):
            self.callback(
                "sephirah",
                str(self.record["id"]),
            )
        else:
            super().keyPressEvent(
                event
            )


class TreeView(QGraphicsView):
    activated = pyqtSignal(
        str,
        str,
    )

    def __init__(
        self,
        catalog,
    ):
        super().__init__()

        self.catalog = catalog

        scene = QGraphicsScene(
            self
        )

        self.setScene(
            scene
        )

        scene.setSceneRect(
            35,
            0,
            530,
            865,
        )

        self.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )

        self.setBackgroundBrush(
            QColor("#121624")
        )

        self.setAccessibleName(
            (
                "Golden Dawn Tree of Life; "
                "equivalent keyboard selectors "
                "are beside the diagram"
            )
        )

        self.pillars = []

        pillar_specs = [
            (
                120,
                "SEVERITY",
                "#8265ae",
            ),
            (
                300,
                "MIDDLE",
                "#bba45b",
            ),
            (
                480,
                "MERCY",
                "#488eb4",
            ),
        ]

        for x, name, color in pillar_specs:
            item = scene.addRect(
                x - 56,
                36,
                112,
                810,
                QPen(
                    Qt.PenStyle.NoPen
                ),
                QBrush(
                    QColor(color)
                ),
            )

            item.setOpacity(
                0.16
            )

            item.setZValue(
                -2
            )

            item.setVisible(
                False
            )

            self.pillars.append(
                item
            )

            label = scene.addSimpleText(
                name
            )

            label.setBrush(
                QColor("#d3c7a6")
            )

            label.setPos(
                (
                    x
                    - label.boundingRect().width()
                    / 2
                ),
                8,
            )

        self.paths = {}
        self.nodes = {}

        for p in catalog.paths.values():
            a, b = [
                catalog.sephiroth[n][
                    "position"
                ]
                for n in p["endpoints"]
            ]

            item = PathItem(
                p["id"],
                a,
                b,
                self.activated.emit,
            )

            item.setToolTip(
                (
                    f"Path {p['id']} · "
                    f"{p['letter']} · "
                    f"{catalog.majors[p['major_id']]['name']}"
                )
            )

            scene.addItem(
                item
            )

            self.paths[
                p["id"]
            ] = item

            if p["id"] == 13:
                t = 0.5
            elif p["id"] == 25:
                t = 0.35
            else:
                t = 0.5

            label = scene.addSimpleText(
                (
                    f"{p['id']} "
                    f"{p['hebrew']}"
                )
            )

            label.setBrush(
                QColor("#e1d4a5")
            )

            label.setPos(
                (
                    a[0]
                    + (
                        b[0] - a[0]
                    )
                    * t
                    + 5
                ),
                (
                    a[1]
                    + (
                        b[1] - a[1]
                    )
                    * t
                    - 20
                ),
            )

            label.setAcceptedMouseButtons(
                Qt.MouseButton.NoButton
            )

            label.setZValue(1)

        for s in catalog.sephiroth.values():
            item = SephirahItem(
                s,
                self.activated.emit,
            )

            scene.addItem(
                item
            )

            self.nodes[
                s["id"]
            ] = item

            label = scene.addSimpleText(
                (
                    f"{s['id']}\n"
                    f"{s['name']}"
                )
            )

            label.setBrush(
                QColor("#f1edf6")
            )

            x, y = s["position"]

            label.setPos(
                (
                    x
                    - label.boundingRect().width()
                    / 2
                ),
                (
                    y
                    - label.boundingRect().height()
                    / 2
                ),
            )

            label.setAcceptedMouseButtons(
                Qt.MouseButton.NoButton
            )

            label.setZValue(3)

    def set_polarity(
        self,
        enabled,
    ):
        for item in self.pillars:
            item.setVisible(
                enabled
            )

    def highlight(
        self,
        kind,
        key,
    ):
        path_id = (
            int(key)
            if kind == "path"
            else None
        )

        if path_id:
            endpoints = self.catalog.paths[
                path_id
            ]["endpoints"]
        else:
            endpoints = [
                int(key)
            ]

        for n, item in self.paths.items():
            selected = (
                n == path_id
            )

            item.setPen(
                QPen(
                    QColor(
                        "#f7cf75"
                        if selected
                        else "#68738c"
                    ),
                    7
                    if selected
                    else 4,
                )
            )

        for n, item in self.nodes.items():
            item.setBrush(
                QBrush(
                    QColor(
                        "#605132"
                        if n in endpoints
                        else "#242a40"
                    )
                )
            )

    def resizeEvent(
        self,
        event,
    ):
        super().resizeEvent(
            event
        )

        self.fitInView(
            self.sceneRect(),
            Qt.AspectRatioMode.KeepAspectRatio,
        )

    def showEvent(
        self,
        event,
    ):
        super().showEvent(
            event
        )

        self.fitInView(
            self.sceneRect(),
            Qt.AspectRatioMode.KeepAspectRatio,
        )


class HermeticStudyWidget(QWidget):
    def __init__(
        self,
        parent=None,
        *,
        progress_path=None,
    ):
        super().__init__(
            parent
        )

        self.catalog = Catalog()

        self.current_topic = (
            "card",
            "major-11",
        )

        self.setObjectName(
            "hermeticStudy"
        )

        self.setStyleSheet(
            """
            QWidget#hermeticStudy {
                background: #121624;
                color: #eee9dd;
            }

            QTextBrowser,
            QListWidget,
            QLineEdit,
            QComboBox {
                background: #1c2233;
                color: #eee9dd;
                border: 1px solid #444760;
                border-radius: 5px;
                padding: 6px;
            }

            QListWidget::item:selected {
                background: #514667;
            }

            QLabel,
            QCheckBox {
                color: #eee9dd;
            }

            QPushButton {
                padding: 7px 12px;
                color: #eee9dd;
                background: #39334e;
            }

            QPushButton:disabled {
                color: #9993a5;
            }
            """
        )

        root = QVBoxLayout(
            self
        )

        heading = QLabel(
            (
                "GOLDEN DAWN / THOTH  ·  "
                "Learn the system"
            )
        )

        heading.setStyleSheet(
            (
                "font-size: 20px; "
                "color: #e1cd91; "
                "padding: 6px;"
            )
        )

        root.addWidget(
            heading
        )

        controls = QHBoxLayout()

        self.basic = QCheckBox(
            "Show basic explanations"
        )

        self.basic.setChecked(
            True
        )

        self.depth = QComboBox()

        self.depth.addItems(
            [
                "Core lesson",
                "Deeper correspondences",
                "Sources / history",
            ]
        )

        self.depth.setCurrentIndex(
            2
        )

        controls.addWidget(
            self.basic
        )

        controls.addWidget(
            self.depth
        )

        controls.addStretch()

        root.addLayout(
            controls
        )

        split = QSplitter()

        root.addWidget(
            split,
            1,
        )

        self.navigation = QListWidget()

        self.navigation.setMaximumWidth(
            235
        )

        self.navigation.setMinimumWidth(
            160
        )

        self.navigation.setAccessibleName(
            "Hermetic study sections"
        )

        self.pages = QStackedWidget()

        split.addWidget(
            self.navigation
        )

        split.addWidget(
            self.pages
        )

        split.setStretchFactor(
            1,
            1,
        )

        self.section_indices = {}

        self.add_section(
            "Dashboard",
            self.browser(
                INTRO
            ),
        )

        self.add_section(
            "Tree of Life",
            self.build_tree(),
        )

        self.add_section(
            "22 Paths / Major Arcana",
            self.build_index(
                "major"
            ),
        )

        self.add_section(
            "Minor Arcana",
            self.build_index(
                "minor"
            ),
        )

        for name in (
            "Court Cards",
            "Astrology & Decans",
            "Elemental Dignities",
        ):
            self.add_section(
                name,
                self.browser(
                    (
                        "<h2>"
                        + name
                        + " · Planned</h2>"
                        + paragraph(
                            PLANNED[name]
                        )
                    )
                ),
                planned=True,
            )

        self.add_section(
            "Golden Dawn Correspondences",
            self.build_correspondences(),
        )

        self.add_section(
            "Spreads & Divination",
            self.browser(
                (
                    "<h2>"
                    "Spreads & Divination · Planned"
                    "</h2>"
                    + paragraph(
                        PLANNED[
                            "Spreads & Divination"
                        ]
                    )
                )
            ),
            planned=True,
        )

        self.add_section(
            "Opening of the Key",
            self.build_ootk(),
        )

        self.add_section(
            "Study / Quizzes",
            self.build_study(
                progress_path
            ),
        )

        self.add_section(
            "Card Explorer",
            self.build_explorer(),
        )

        self.navigation.currentRowChanged.connect(
            self.pages.setCurrentIndex
        )

        self.basic.toggled.connect(
            self.refresh_details
        )

        self.depth.currentIndexChanged.connect(
            self.refresh_details
        )

        self.navigation.setCurrentRow(
            0
        )

        self.refresh_details()

    # ------------------------------------------------------------------
    # Generic browser / navigation
    # ------------------------------------------------------------------

    def browser(
        self,
        html="",
    ):
        b = QTextBrowser()

        b.setOpenLinks(
            False
        )

        b.setOpenExternalLinks(
            False
        )

        b.document().setDefaultStyleSheet(
            """
            body {
                color: #eee9dd;
            }

            a {
                color: #abcefa;
            }

            h2,
            h3 {
                color: #e1cd91;
            }

            li {
                margin-bottom: 10px;
            }

            table {
                border-collapse: collapse;
                width: 100%;
            }

            th {
                color: #e1cd91;
                padding: 6px;
                border-bottom: 1px solid #555a70;
            }

            td {
                padding: 6px;
                border-bottom: 1px solid #33384c;
                vertical-align: top;
            }
            """
        )

        b.setHtml(
            html
        )

        b.anchorClicked.connect(
            self.follow_link
        )

        return b

    def add_section(
        self,
        name,
        widget,
        planned=False,
    ):
        self.section_indices[
            name
        ] = self.pages.count()

        label = name

        if planned:
            label += " · Planned"

        self.navigation.addItem(
            label
        )

        self.pages.addWidget(
            widget
        )

    def go(
        self,
        name,
    ):
        self.navigation.setCurrentRow(
            self.section_indices[
                name
            ]
        )

    # ------------------------------------------------------------------
    # Tree
    # ------------------------------------------------------------------

    def build_tree(self):
        page = QWidget()
        layout = QVBoxLayout(
            page
        )

        title = QLabel(
            (
                "Golden Dawn Tree · "
                "Majors on Paths · "
                "numbered Minors on Sephiroth"
            )
        )

        title.setWordWrap(
            True
        )

        layout.addWidget(
            title
        )

        self.polarity = QCheckBox(
            (
                "Polarity View — "
                "emphasize all three pillars"
            )
        )

        layout.addWidget(
            self.polarity
        )

        splitter = QSplitter()

        layout.addWidget(
            splitter,
            1,
        )

        self.tree = TreeView(
            self.catalog
        )

        splitter.addWidget(
            self.tree
        )

        right = QWidget()
        rl = QVBoxLayout(
            right
        )

        self.tree_selector = QComboBox()

        for s in self.catalog.sephiroth.values():
            self.tree_selector.addItem(
                (
                    f"Sephirah {s['id']} · "
                    f"{s['name']}"
                ),
                (
                    "sephirah",
                    str(s["id"]),
                ),
            )

        for p in self.catalog.paths.values():
            self.tree_selector.addItem(
                (
                    f"Path {p['id']} · "
                    f"{p['letter']} · "
                    f"{self.catalog.majors[p['major_id']]['name']}"
                ),
                (
                    "path",
                    str(p["id"]),
                ),
            )

        self.tree_selector.setAccessibleName(
            (
                "Select any Sephirah "
                "or Path"
            )
        )

        rl.addWidget(
            self.tree_selector
        )

        self.tree_detail = self.browser()

        rl.addWidget(
            self.tree_detail,
            1,
        )

        splitter.addWidget(
            right
        )

        splitter.setSizes(
            [
                440,
                470,
            ]
        )

        self.polarity.toggled.connect(
            self.tree.set_polarity
        )

        self.tree.activated.connect(
            self.select_tree
        )

        self.tree_selector.currentIndexChanged.connect(
            lambda: self.select_tree(
                *self.tree_selector.currentData()
            )
        )

        self.tree_topic = (
            "sephirah",
            "1",
        )

        self.select_tree(
            *self.tree_topic
        )

        return page

    def select_tree(
        self,
        kind,
        key,
    ):
        self.tree_topic = (
            kind,
            str(key),
        )

        self.tree.highlight(
            kind,
            key,
        )

        index = next(
            i
            for i in range(
                self.tree_selector.count()
            )
            if tuple(
                self.tree_selector.itemData(
                    i
                )
            )
            == self.tree_topic
        )

        self.tree_selector.blockSignals(
            True
        )

        self.tree_selector.setCurrentIndex(
            index
        )

        self.tree_selector.blockSignals(
            False
        )

        html = self.catalog.render(
            kind,
            key,
            self.basic.isChecked(),
            self.depth.currentIndex(),
        )

        self.tree_detail.setHtml(
            html + PILLARS
        )

    # ------------------------------------------------------------------
    # Indices / reference
    # ------------------------------------------------------------------

    def build_index(
        self,
        kind,
    ):
        if kind == "major":
            heading = (
                "Major Arcana → 22 Paths"
            )
            records = (
                self.catalog.majors
            )
        else:
            heading = (
                "Numbered Minors → "
                "10 Sephiroth"
            )
            records = (
                self.catalog.minors
            )

        body = (
            "<h2>"
            + heading
            + "</h2>"
            "<ul>"
        )

        for c in records.values():
            if kind == "major":
                extra = (
                    f"Path {c['path']} · "
                    f"{self.catalog.paths[c['path']]['letter']}"
                )
            else:
                extra = (
                    f"{self.catalog.sephiroth[c['sephirah']]['name']} · "
                    f"{c['thoth_title']}"
                )

            body += (
                "<li>"
                + link(
                    "card",
                    c["id"],
                    c["name"],
                )
                + " — "
                + escape(extra)
                + "</li>"
            )

        body += "</ul>"

        return self.browser(
            body
        )

    def build_correspondences(self):
        body = (
            "<h2>Golden Dawn correspondences</h2>"
            "<p>"
            "Choose a topic; source editions "
            "are listed separately below."
            "</p>"
            "<h3>Sephiroth</h3>"
        )

        body += "<p>"

        body += " · ".join(
            link(
                "sephirah",
                s["id"],
                s["name"],
            )
            for s
            in self.catalog.sephiroth.values()
        )

        body += (
            "</p>"
            "<h3>Suits / elements / worlds</h3>"
            "<p>"
        )

        body += " · ".join(
            link(
                "suit",
                s["id"],
                (
                    f"{s['name']} / "
                    f"{s['element']} / "
                    f"{s['world']}"
                ),
            )
            for s
            in self.catalog.suits.values()
        )

        body += (
            "</p>"
            "<h3>Sources and versions</h3>"
            "<ul>"
        )

        body += "".join(
            (
                "<li>"
                + link(
                    "source",
                    s["id"],
                    s["title"],
                )
                + " — "
                + escape(
                    s["tradition"]
                )
                + "</li>"
            )
            for s
            in self.catalog.sources.values()
        )

        body += "</ul>"

        return self.browser(
            body
        )

    # ------------------------------------------------------------------
    # Opening of the Key
    # ------------------------------------------------------------------

    def build_ootk(self):
        page = QWidget()

        layout = QVBoxLayout(
            page
        )

        title = QLabel(
            (
                "Opening of the Key · "
                "Guided Golden Dawn Method"
            )
        )

        title.setStyleSheet(
            (
                "font-size: 18px; "
                "color: #e1cd91; "
                "padding: 6px;"
            )
        )

        title.setWordWrap(
            True
        )

        layout.addWidget(
            title
        )

        subtitle = QLabel(
            (
                "Use this beside a physical Tarot deck. "
                "The app teaches the procedure and "
                "correspondences; it does not draw "
                "the cards for you."
            )
        )

        subtitle.setWordWrap(
            True
        )

        layout.addWidget(
            subtitle
        )

        row = QHBoxLayout()

        row.addWidget(
            QLabel(
                "Lesson:"
            )
        )

        self.ootk_selector = QComboBox()

        self.ootk_selector.addItem(
            "Overview",
            "overview",
        )

        self.ootk_selector.addItem(
            "Card Counting & Pairing",
            "counting",
        )

        for operation in self.catalog.ootk[
            "operations"
        ]:
            self.ootk_selector.addItem(
                (
                    f"Sample Draw Demo · Operation "
                    f"{operation['id']}"
                ),
                f"demo-{operation['id']}",
            )

        for operation in self.catalog.ootk[
            "operations"
        ]:
            self.ootk_selector.addItem(
                (
                    f"Operation {operation['id']} · "
                    f"{operation['title']}"
                ),
                str(
                    operation["id"]
                ),
            )

        row.addWidget(
            self.ootk_selector,
            1,
        )

        layout.addLayout(
            row
        )

        quick = QHBoxLayout()

        overview_button = QPushButton(
            "Overview"
        )

        counting_button = QPushButton(
            "Counting"
        )

        first_button = QPushButton(
            "Start Operation I"
        )

        demo_button = QPushButton(
            "Sample Draw Demo"
        )

        overview_button.clicked.connect(
            lambda: self.select_ootk(
                "overview"
            )
        )

        counting_button.clicked.connect(
            lambda: self.select_ootk(
                "counting"
            )
        )

        first_button.clicked.connect(
            lambda: self.select_ootk(
                "1"
            )
        )

        demo_button.clicked.connect(
            lambda: self.select_ootk(
                "demo-1"
            )
        )

        quick.addWidget(
            overview_button
        )

        quick.addWidget(
            counting_button
        )

        quick.addWidget(
            first_button
        )

        quick.addWidget(
            demo_button
        )

        quick.addStretch()

        layout.addLayout(
            quick
        )

        # Guided sample-draw controls.
        self.ootk_demo_operation = 1
        self.ootk_demo_step = 0

        self.ootk_demo_controls = QWidget()
        demo_controls_layout = QHBoxLayout(
            self.ootk_demo_controls
        )
        demo_controls_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        self.ootk_demo_previous = QPushButton(
            "← Previous Step"
        )

        self.ootk_demo_step_label = QLabel(
            ""
        )

        self.ootk_demo_step_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.ootk_demo_next = QPushButton(
            "Next Step →"
        )

        self.ootk_demo_previous.clicked.connect(
            self.ootk_demo_previous_step
        )

        self.ootk_demo_next.clicked.connect(
            self.ootk_demo_next_step
        )

        demo_controls_layout.addWidget(
            self.ootk_demo_previous
        )

        demo_controls_layout.addWidget(
            self.ootk_demo_step_label,
            1,
        )

        demo_controls_layout.addWidget(
            self.ootk_demo_next
        )

        layout.addWidget(
            self.ootk_demo_controls
        )

        self.ootk_demo_controls.hide()

        self.ootk_detail = self.browser()

        layout.addWidget(
            self.ootk_detail,
            1,
        )

        self.ootk_selector.currentIndexChanged.connect(
            lambda _index: self._show_ootk_current()
        )

        self.select_ootk(
            "overview"
        )

        return page

    def _show_ootk_current(self):
        key = self.ootk_selector.currentData()

        if key is None:
            return

        key = str(key)

        if key.startswith("demo-"):
            self.ootk_demo_operation = int(
                key.split("-", 1)[1]
            )
            self.ootk_demo_controls.show()
            self._render_ootk_demo()
            return

        self.ootk_demo_controls.hide()

        self.ootk_detail.setHtml(
            self.catalog.render(
                "ootk",
                key,
                self.basic.isChecked(),
                self.depth.currentIndex(),
            )
        )

    def select_ootk(
        self,
        key,
    ):
        key = str(key)

        for i in range(
            self.ootk_selector.count()
        ):
            if str(
                self.ootk_selector.itemData(
                    i
                )
            ) == key:
                self.ootk_selector.blockSignals(
                    True
                )

                self.ootk_selector.setCurrentIndex(
                    i
                )

                self.ootk_selector.blockSignals(
                    False
                )

                break

        if key.startswith("demo-"):
            self.ootk_demo_operation = int(
                key.split("-", 1)[1]
            )
            self.ootk_demo_step = 0
            self.ootk_demo_controls.show()
            self._render_ootk_demo()
            return

        self.ootk_demo_controls.hide()

        self.ootk_detail.setHtml(
            self.catalog.render(
                "ootk",
                key,
                self.basic.isChecked(),
                self.depth.currentIndex(),
            )
        )

    def ootk_demo_previous_step(self):
        if self.ootk_demo_step > 0:
            self.ootk_demo_step -= 1
            self._render_ootk_demo()

    def ootk_demo_next_step(self):
        max_step = 5

        if self.ootk_demo_step < max_step:
            self.ootk_demo_step += 1
            self._render_ootk_demo()

    def _ootk_demo_card(
        self,
        name,
        subtitle="",
        *,
        highlight=False,
        muted=False,
    ):
        if highlight:
            border = "#e1cd91"
            background = "#514667"
        elif muted:
            border = "#34394e"
            background = "#181d2c"
        else:
            border = "#566078"
            background = "#242a40"

        subtitle_html = (
            f"<br><small>{escape(subtitle)}</small>"
            if subtitle
            else ""
        )

        return (
            "<div style='"
            "display:inline-block;"
            "vertical-align:top;"
            "text-align:center;"
            "margin:6px;"
            "padding:10px;"
            "min-width:105px;"
            "border-radius:8px;"
            f"border:2px solid {border};"
            f"background:{background};"
            "'>"
            f"<b>{escape(name)}</b>"
            f"{subtitle_html}"
            "</div>"
        )

    def _ootk_demo_packet(
        self,
        title,
        element,
        cards,
        *,
        highlight=False,
    ):
        border = (
            "#e1cd91"
            if highlight
            else "#444760"
        )

        body = (
            "<div style='"
            "margin:8px;"
            "padding:12px;"
            f"border:2px solid {border};"
            "border-radius:8px;"
            "background:#181d2c;"
            "'>"
            f"<h3>{escape(title)}</h3>"
            f"<p>{escape(element)}</p>"
        )

        for card in cards:
            body += self._ootk_demo_card(
                card,
                highlight=(
                    card == "Queen of Cups"
                ),
            )

        body += "</div>"

        return body

    def _ootk_demo_html_operation_1(self):
        step = self.ootk_demo_step

        water_cards = [
            "3 of Cups",
            "Queen of Cups",
            "5 of Cups",
            "The Lovers",
            "2 of Swords",
            "The Fool",
            "8 of Wands",
            "6 of Cups",
            "The Moon",
        ]

        if step == 0:
            return """
            <h2>Sample Draw · Operation I</h2>

            <h3>Step 1 · Prepare the question and Significator</h3>

            <p>
            This is a fixed teaching example. We are not asking the
            computer to perform a reading. We are using sample cards
            to learn the physical choreography of the First Operation.
            </p>

            <p>
            <b>Example question:</b><br>
            What forces are presently shaping a major personal
            transition?
            </p>

            <p>
            <b>Example Significator:</b><br>
            Queen of Cups
            </p>

            <p>
            The historical Golden Dawn procedure uses a Court card
            as the Significator. Court cards are not yet part of the
            app's catalog, so the Queen of Cups appears here only as
            a teaching placeholder.
            </p>

            <h3>What you would physically do</h3>

            <ol>
            <li>Select the Significator.</li>
            <li>Return it to the complete Tarot deck.</li>
            <li>Hold the question clearly in mind.</li>
            <li>Shuffle the full deck.</li>
            <li>Place the deck face down before beginning the cut.</li>
            </ol>

            <p>
            Press <b>Next Step</b> to perform the fourfold YHVH cut.
            </p>
            """

        if step == 1:
            html = """
            <h2>Sample Draw · Operation I</h2>

            <h3>Step 2 · Cut into four YHVH packets</h3>

            <p>
            After shuffling, cut the deck into four packets.
            In the finished arrangement the packets are read
            through the fourfold YHVH structure.
            </p>

            <p>
            For this sample, imagine the four packets now contain:
            </p>
            """

            html += self._ootk_demo_packet(
                "Yod",
                "Fire · Wands",
                [
                    "The Sun",
                    "3 of Wands",
                    "6 of Swords",
                ],
            )

            html += self._ootk_demo_packet(
                "Heh",
                "Water · Cups",
                [
                    "3 of Cups",
                    "Queen of Cups",
                    "5 of Cups",
                    "The Lovers",
                    "2 of Swords",
                    "The Fool",
                    "8 of Wands",
                    "6 of Cups",
                    "The Moon",
                ],
                highlight=True,
            )

            html += self._ootk_demo_packet(
                "Vau",
                "Air · Swords",
                [
                    "2 of Swords",
                    "9 of Disks",
                    "The Hermit",
                ],
            )

            html += self._ootk_demo_packet(
                "Heh Final",
                "Earth · Disks",
                [
                    "Ace of Disks",
                    "7 of Wands",
                    "10 of Disks",
                ],
            )

            html += """
            <h3>Locate the Significator</h3>

            <p>
            Our Queen of Cups appears in the <b>Heh / Water</b>
            packet.
            </p>

            <p>
            That does not mean "the answer is Cups."
            It tells us that the detailed First Operation will
            proceed through the Water packet.
            </p>

            <p>
            <b>Physical action:</b> retain the Water packet and
            set the other three aside without disturbing their
            internal order.
            </p>
            """

            return html

        if step == 2:
            cards = ""

            for index, card in enumerate(
                water_cards,
                start=1,
            ):
                subtitle = f"Position {index}"

                if card == "Queen of Cups":
                    subtitle += " · SIGNIFICATOR"

                cards += self._ootk_demo_card(
                    card,
                    subtitle,
                    highlight=(
                        card == "Queen of Cups"
                    ),
                )

            return (
                """
                <h2>Sample Draw · Operation I</h2>

                <h3>Step 3 · Spread the retained packet</h3>

                <p>
                Spread the retained packet face up as a horseshoe
                while preserving its order.
                </p>

                <p>
                For teaching purposes it is shown here as a row.
                The important thing is <b>order</b>, not the precise
                screen geometry.
                </p>
                """
                + cards
                + """
                <h3>Before counting</h3>

                <p>
                Take a moment to inspect the whole packet.
                Look for dominant suits, repeated numbers,
                clusters of Major Arcana, and elemental tensions.
                </p>

                <p>
                Our Significator is at position 2.
                Assume the Queen is facing toward the right,
                so counting proceeds to the right.
                </p>
                """
            )

        if step == 3:
            return """
            <h2>Sample Draw · Operation I</h2>

            <h3>Step 4 · Perform card counting</h3>

            <p>
            The starting card itself always counts as
            <b>1</b>.
            </p>

            <table cellpadding="7">
            <tr>
                <th>Selected card</th>
                <th>Count</th>
                <th>Lands on</th>
                <th>Why?</th>
            </tr>

            <tr>
                <td><b>Queen of Cups</b></td>
                <td>4</td>
                <td><b>2 of Swords</b></td>
                <td>
                Queen is a Court card; the non-Princess
                Courts count 4.
                </td>
            </tr>

            <tr>
                <td><b>2 of Swords</b></td>
                <td>2</td>
                <td><b>The Fool</b></td>
                <td>
                A numbered Minor counts by its own number.
                </td>
            </tr>

            <tr>
                <td><b>The Fool</b></td>
                <td>3</td>
                <td><b>6 of Cups</b></td>
                <td>
                The Fool is Aleph, one of the Three
                Mother-letter cards.
                </td>
            </tr>

            <tr>
                <td><b>6 of Cups</b></td>
                <td>6</td>
                <td><b>The Lovers</b></td>
                <td>
                A numbered Minor counts by its own number.
                </td>
            </tr>

            <tr>
                <td><b>The Lovers</b></td>
                <td>12</td>
                <td><b>The Fool</b></td>
                <td>
                Zayin is one of the twelve Simple /
                Zodiacal letters.
                </td>
            </tr>
            </table>

            <h3>The chain closes</h3>

            <p>
            We have landed on <b>The Fool</b> again.
            The Fool was already selected earlier in the chain,
            so counting stops.
            </p>

            <p>
            <b>Counting narrative:</b><br>
            Queen of Cups
            → 2 of Swords
            → The Fool
            → 6 of Cups
            → The Lovers
            → The Fool
            </p>

            <p>
            The point is not merely to memorize this chain.
            You would now interpret the symbolic movement
            produced by these cards.
            </p>
            """

        if step == 4:
            return """
            <h2>Sample Draw · Operation I</h2>

            <h3>Step 5 · Pair opposite ends inward</h3>

            <p>
            Return your attention to the complete retained packet,
            not only the cards selected during counting.
            </p>

            <p>
            With nine cards, pairing works like this:
            </p>

            <table cellpadding="7">
            <tr>
                <th>Pair</th>
                <th>Left side</th>
                <th>Right side</th>
            </tr>

            <tr>
                <td>1 ↔ 9</td>
                <td>3 of Cups</td>
                <td>The Moon</td>
            </tr>

            <tr>
                <td>2 ↔ 8</td>
                <td><b>Queen of Cups</b></td>
                <td>6 of Cups</td>
            </tr>

            <tr>
                <td>3 ↔ 7</td>
                <td>5 of Cups</td>
                <td>8 of Wands</td>
            </tr>

            <tr>
                <td>4 ↔ 6</td>
                <td>The Lovers</td>
                <td>The Fool</td>
            </tr>

            <tr>
                <td>Center</td>
                <td colspan="2">2 of Swords</td>
            </tr>
            </table>

            <h3>Why pairing matters</h3>

            <p>
            Pairing asks you to read cards relationally rather
            than as isolated dictionary entries.
            </p>

            <p>
            For example:
            </p>

            <p>
            <b>5 of Cups ↔ 8 of Wands</b><br>
            Water meets Fire. Those elements are antagonistic,
            so the interaction may weaken, strain or complicate
            the expression of both cards.
            </p>

            <p>
            That does <b>not</b> mean either card simply becomes
            "reversed."
            </p>
            """

        return """
        <h2>Sample Draw · Operation I</h2>

        <h3>Step 6 · Build the interpretation</h3>

        <p>
        You now have several distinct layers of evidence.
        Keep them separate before synthesizing them.
        </p>

        <table cellpadding="7">
        <tr>
            <th>Layer</th>
            <th>Sample result</th>
        </tr>

        <tr>
            <td>Question</td>
            <td>
            What forces are presently shaping a major
            personal transition?
            </td>
        </tr>

        <tr>
            <td>Significator</td>
            <td>Queen of Cups</td>
        </tr>

        <tr>
            <td>Operation-I field</td>
            <td>Heh · Water · Cups</td>
        </tr>

        <tr>
            <td>Counting chain</td>
            <td>
            Queen of Cups → 2 of Swords → The Fool →
            6 of Cups → The Lovers → The Fool
            </td>
        </tr>

        <tr>
            <td>Pairing</td>
            <td>
            3 Cups ↔ Moon · Queen Cups ↔ 6 Cups ·
            5 Cups ↔ 8 Wands · Lovers ↔ Fool ·
            2 Swords at center
            </td>
        </tr>
        </table>

        <h3>Your interpretation order</h3>

        <ol>
        <li>
        Start with the Water field containing the Significator.
        </li>

        <li>
        Read the counting chain as a sequence of developments.
        </li>

        <li>
        Examine the opposite-end pairs.
        </li>

        <li>
        Apply elemental dignity where cards interact.
        </li>

        <li>
        Look at the center card and overall suit balance.
        </li>

        <li>
        Only then synthesize the whole operation.
        </li>
        </ol>

        <h3>What happens next?</h3>

        <p>
        In a full Opening of the Key you gather the complete
        deck again and proceed to <b>Operation II — the Twelve
        Astrological Houses</b>.
        </p>

        <p>
        You do not treat Operation I as the entire answer.
        It is the opening condition of the same question that
        will continue through all five operations.
        </p>
        """


    def _ootk_demo_html_operation_2(self):
        step = self.ootk_demo_step

        if step == 0:
            return """
            <h2>Sample Draw · Operation II</h2>
            <h3>Step 1 · Gather and reshuffle the full deck</h3>
            <p>Keep the same question. Gather all cards and shuffle again. Do <b>not</b> cut.</p>
            <p>Deal cyclically into <b>12 Astrological House packets</b>:</p>
            <pre>
            I   II   III   IV   V   VI
            VII VIII IX    X    XI  XII
            </pre>
            <p>Deal one card to each House in sequence, repeating until the full deck is distributed.</p>
            """

        if step == 1:
            return """
            <h2>Sample Draw · Operation II</h2>
            <h3>Step 2 · Locate the Significator</h3>
            <p>In this sample the Queen of Cups appears in <b>House VII</b>.</p>
            <div style="padding:14px;border:2px solid #e1cd91;border-radius:8px;background:#514667;">
                <h3>House VII</h3>
                <p>Partnerships · agreements · open opposition</p>
            </div>
            <p>Retain that packet and set the other eleven aside without disturbing order.</p>
            """

        if step == 2:
            return """
            <h2>Sample Draw · Operation II</h2>
            <h3>Step 3 · Horseshoe, count and pair</h3>
            <pre>
                       [The Chariot]
                [4 Cups]         [9 Swords]

             [Queen Cups]       [3 Disks]

                [The Star]       [6 Wands]
            </pre>
            <p>Count from the Significator in the direction it faces, stop when a selected card repeats, then pair opposite ends inward.</p>
            """

        return """
        <h2>Sample Draw · Operation II</h2>
        <h3>Step 4 · Synthesize the House context</h3>
        <ol>
        <li>House VII supplies the field of experience.</li>
        <li>The counting chain supplies the developing narrative.</li>
        <li>The pairs show relational tensions and supports.</li>
        <li>Elemental dignity qualifies how strongly cards express.</li>
        </ol>
        <p>Gather the full deck again for <b>Operation III</b>.</p>
        """

    def _ootk_demo_html_operation_3(self):
        step = self.ootk_demo_step

        if step == 0:
            return """
            <h2>Sample Draw · Operation III</h2>
            <h3>Step 1 · Deal into the Twelve Zodiac Signs</h3>
            <p>Gather and shuffle the entire deck again. Do not cut.</p>
            <pre>
            Aries      Taurus      Gemini
            Cancer     Leo         Virgo
            Libra      Scorpio     Sagittarius
            Capricorn  Aquarius    Pisces
            </pre>
            <p>Deal cyclically through all twelve signs until the deck is distributed.</p>
            """

        if step == 1:
            return """
            <h2>Sample Draw · Operation III</h2>
            <h3>Step 2 · Locate the Significator</h3>
            <p>In this sample the Queen of Cups falls in <b>Scorpio</b>.</p>
            <div style="padding:14px;border:2px solid #e1cd91;border-radius:8px;background:#514667;">
                <h3>Scorpio</h3>
                <p>Golden Dawn Major correspondence: Death</p>
            </div>
            <p>The sign supplies the Zodiacal field. The Major is a correspondence to that field, not an extra card drawn into the packet.</p>
            """

        if step == 2:
            return """
            <h2>Sample Draw · Operation III</h2>
            <h3>Step 3 · Horseshoe, count and pair</h3>
            <pre>
                      [5 of Cups]
               [Death]         [2 Disks]

           [Queen Cups]       [The Moon]

               [7 Cups]        [Ace Wands]
            </pre>
            <p>Use the same engine: <b>Significator → counting chain → repeat → pairing</b>.</p>
            """

        return """
        <h2>Sample Draw · Operation III</h2>
        <h3>Step 4 · Synthesize Zodiacal development</h3>
        <ol>
        <li>Keep the original question unchanged.</li>
        <li>Use Scorpio as the packet's Zodiacal context.</li>
        <li>Interpret the actual cards independently.</li>
        <li>Use counting for narrative movement.</li>
        <li>Use pairing and elemental dignity for relationships.</li>
        </ol>
        <p>Next comes <b>Operation IV — Thirty-Six Decanates</b>.</p>
        """

    def _ootk_demo_html_operation_4(self):
        step = self.ootk_demo_step

        if step == 0:
            return """
            <h2>Sample Draw · Operation IV</h2>
            <h3>Step 1 · Cut at the Significator</h3>
            <p>Shuffle the full deck, locate the Significator without disturbing relative order, and rotate/cut so it becomes the beginning point.</p>
            <p>Place the Significator face up in the center. It is <b>not</b> one of the 36 outer cards.</p>
            """

        if step == 1:
            return """
            <h2>Sample Draw · Operation IV</h2>
            <h3>Step 2 · Deal the Thirty-Six-card circle</h3>
            <pre>
                         [01] [02] [03]
                    [36]             [04]
                 [35]                   [05]

                         [QUEEN CUPS]

                 [19]                   [18]
                    [20]             [17]
                         [21] [22] [23]
            </pre>
            <p>Continue until all <b>36 outer positions</b> are filled in one continuous dealt order.</p>
            """

        if step == 2:
            return """
            <h2>Sample Draw · Operation IV</h2>
            <h3>Step 3 · Counting changes here</h3>
            <div style="padding:14px;border:2px solid #e1cd91;border-radius:8px;background:#514667;">
                <b>Do not begin from the Significator.</b><br>
                Begin with outer card <b>1</b>.
            </div>
            <p>Count in the same direction the circle was dealt. Stop when the chain lands on a card already selected.</p>
            """

        if step == 3:
            return """
            <h2>Sample Draw · Operation IV</h2>
            <h3>Step 4 · Pair the circular arrangement</h3>
            <pre>
            1  ↔ 36
            2  ↔ 35
            3  ↔ 34
            4  ↔ 33
               ...
            18 ↔ 19
            </pre>
            <p>Interpret each pair with card meaning and elemental dignity.</p>
            """

        return """
        <h2>Sample Draw · Operation IV</h2>
        <h3>Step 5 · Read the decanic development</h3>
        <ol>
        <li>Significator establishes the center.</li>
        <li>The 36 dealt positions form the development field.</li>
        <li>Counting begins from outer card 1.</li>
        <li>Pair 1↔36, 2↔35, and so on.</li>
        <li>Synthesize with Operations I–III.</li>
        </ol>
        <p>Gather the full deck again for the final operation.</p>
        """

    def _ootk_demo_html_operation_5(self):
        step = self.ootk_demo_step

        if step == 0:
            return """
            <h2>Sample Draw · Operation V</h2>
            <h3>Step 1 · Deal into the Ten Sephiroth</h3>
            <p>Gather and shuffle the full deck again. Do not cut.</p>
            <pre>
            1  Kether       6  Tiphareth
            2  Chokmah      7  Netzach
            3  Binah        8  Hod
            4  Chesed       9  Yesod
            5  Geburah     10  Malkuth
            </pre>
            <p>Deal cyclically through all ten packets until the deck is distributed.</p>
            """

        if step == 1:
            return """
            <h2>Sample Draw · Operation V</h2>
            <h3>Step 2 · Locate the Significator</h3>
            <p>In this sample the Queen of Cups appears under:</p>
            <div style="padding:14px;border:2px solid #e1cd91;border-radius:8px;background:#514667;">
                <h3>6 · Tiphareth</h3>
                <p>Beauty · Sun · Middle Pillar · mediation and equilibrium</p>
            </div>
            <p>Tiphareth is the symbolic context of the conclusion, not a simple positive verdict.</p>
            """

        if step == 2:
            return """
            <h2>Sample Draw · Operation V</h2>
            <h3>Step 3 · Read the retained Sephirah packet</h3>
            <pre>
                        [The Sun]
                 [6 Wands]     [2 Cups]

             [Queen Cups]     [Adjustment]

                 [9 Disks]     [The Fool]
            </pre>
            <p>Count from the Significator, stop on repetition, then pair opposite ends inward.</p>
            """

        if step == 3:
            return """
            <h2>Sample Draw · Operation V</h2>
            <h3>Step 4 · Build the Sephirothic conclusion</h3>
            <ol>
            <li>Start with Tiphareth as the concluding field.</li>
            <li>Read the counting chain as the final narrative.</li>
            <li>Read the pairs relationally.</li>
            <li>Apply elemental dignity.</li>
            <li>Keep Sephirah meaning, card meaning and pair meaning distinct before synthesis.</li>
            </ol>
            """

        return """
        <h2>Sample Draw · Operation V</h2>
        <h3>Step 5 · Synthesize the complete Opening of the Key</h3>
        <table cellpadding="7">
        <tr><th>Operation</th><th>Sample context</th><th>Role</th></tr>
        <tr><td>I</td><td>Heh / Water</td><td>Opening condition</td></tr>
        <tr><td>II</td><td>House VII</td><td>Field of lived development</td></tr>
        <tr><td>III</td><td>Scorpio</td><td>Zodiacal mode</td></tr>
        <tr><td>IV</td><td>36 Decanates</td><td>Detailed development</td></tr>
        <tr><td>V</td><td>Tiphareth</td><td>Qabalistic conclusion</td></tr>
        </table>
        <p>The final reading is one question viewed through five symbolic frameworks, not five unrelated predictions.</p>
        <p><b>Full five-operation sample walkthrough complete.</b></p>
        """

    def _ootk_demo_html(self):
        operation = getattr(
            self,
            "ootk_demo_operation",
            1,
        )

        renderer = getattr(
            self,
            f"_ootk_demo_html_operation_{operation}",
        )

        return renderer()

    def _render_ootk_demo(self):
        operation = getattr(
            self,
            "ootk_demo_operation",
            1,
        )

        max_steps = {
            1: 5,
            2: 3,
            3: 3,
            4: 4,
            5: 4,
        }

        max_step = max_steps[
            operation
        ]

        self.ootk_demo_step = max(
            0,
            min(
                self.ootk_demo_step,
                max_step,
            ),
        )

        self.ootk_demo_step_label.setText(
            (
                f"Operation {operation} · "
                f"Step {self.ootk_demo_step + 1} "
                f"of {max_step + 1}"
            )
        )

        self.ootk_demo_previous.setEnabled(
            self.ootk_demo_step > 0
        )

        self.ootk_demo_next.setEnabled(
            self.ootk_demo_step < max_step
        )

        if self.ootk_demo_step == max_step:
            if operation < 5:
                self.ootk_demo_next.setText(
                    f"Operation {operation} Complete"
                )
            else:
                self.ootk_demo_next.setText(
                    "Full Demo Complete"
                )
        else:
            self.ootk_demo_next.setText(
                "Next Step →"
            )

        self.ootk_detail.setHtml(
            self._ootk_demo_html()
        )

    # ------------------------------------------------------------------
    # Card explorer
    # ------------------------------------------------------------------

    def build_explorer(self):
        page = QWidget()

        layout = QVBoxLayout(
            page
        )

        filters = QHBoxLayout()

        self.search = QLineEdit()

        self.search.setPlaceholderText(
            (
                "Find a card, letter, "
                "Sephirah or title…"
            )
        )

        self.search.setAccessibleName(
            "Search the card catalog"
        )

        self.card_filter = QComboBox()

        self.card_filter.addItems(
            [
                "All 62 cards",
                "Major Arcana",
                "Numbered Minors",
            ]
        )

        filters.addWidget(
            self.search,
            1,
        )

        filters.addWidget(
            self.card_filter
        )

        layout.addLayout(
            filters
        )

        split = QSplitter()

        layout.addWidget(
            split,
            1,
        )

        self.card_list = QListWidget()

        self.card_list.setMaximumWidth(
            250
        )

        self.card_list.setAccessibleName(
            (
                "Cards matching "
                "your search"
            )
        )

        self.detail = self.browser()

        split.addWidget(
            self.card_list
        )

        split.addWidget(
            self.detail
        )

        split.setStretchFactor(
            1,
            1,
        )

        self.card_list.currentItemChanged.connect(
            self.card_selected
        )

        self.search.textChanged.connect(
            self.filter_cards
        )

        self.card_filter.currentIndexChanged.connect(
            self.filter_cards
        )

        self.filter_cards()

        return page

    def filter_cards(self):
        self.card_list.clear()

        needle = (
            self.search.text()
            .casefold()
            .strip()
        )

        for c in self.catalog.cards.values():
            if (
                self.card_filter.currentIndex()
                == 1
                and c["kind"] != "major"
            ):
                continue

            if (
                self.card_filter.currentIndex()
                == 2
                and c["kind"] != "minor"
            ):
                continue

            if c["kind"] == "major":
                p = self.catalog.paths[
                    c["path"]
                ]

                searchable = (
                    f"{c['name']} "
                    f"{c['thoth_name']} "
                    f"{p['letter']} "
                    f"{p['hebrew']} "
                    f"{p['id']} "
                    f"{p['astrology']}"
                )

            else:
                searchable = (
                    f"{c['name']} "
                    f"{c['thoth_title']} "
                    f"{c['gd_title']} "
                    f"{self.catalog.sephiroth[c['sephirah']]['name']} "
                    f"{c['planet']} "
                    f"{c['zodiac']} "
                    f"{self.catalog.suits[c['suit']]['element']}"
                )

            if needle not in searchable.casefold():
                continue

            item = QListWidgetItem(
                c["name"]
            )

            item.setData(
                Qt.ItemDataRole.UserRole,
                c["id"],
            )

            self.card_list.addItem(
                item
            )

        if self.card_list.count():
            self.card_list.setCurrentRow(
                0
            )
        else:
            self.detail.setHtml(
                (
                    "<p>"
                    "No matching cards. "
                    "Try another name or "
                    "clear the filters."
                    "</p>"
                )
            )

    def card_selected(
        self,
        item,
        previous=None,
    ):
        if not item:
            return

        self.current_topic = (
            "card",
            item.data(
                Qt.ItemDataRole.UserRole
            ),
        )

        self.detail.setHtml(
            self.catalog.render(
                *self.current_topic,
                self.basic.isChecked(),
                self.depth.currentIndex(),
            )
        )

    # ------------------------------------------------------------------
    # Refresh / links
    # ------------------------------------------------------------------

    def refresh_details(
        self,
        *args,
    ):
        if hasattr(
            self,
            "detail",
        ):
            self.detail.setHtml(
                self.catalog.render(
                    *self.current_topic,
                    self.basic.isChecked(),
                    self.depth.currentIndex(),
                )
            )

        if hasattr(
            self,
            "tree_topic",
        ):
            self.select_tree(
                *self.tree_topic
            )

        if hasattr(
            self,
            "ootk_selector",
        ):
            self._show_ootk_current()

    def follow_link(
        self,
        url,
    ):
        if url.scheme() in (
            "https",
            "http",
        ):
            QDesktopServices.openUrl(
                url
            )
            return

        if url.scheme() != "study":
            return

        try:
            kind, key = url.path().split(
                "/",
                1,
            )
        except ValueError:
            return

        if kind == "tree":
            if key.startswith("s"):
                self.select_tree(
                    "sephirah",
                    key[1:],
                )
            else:
                self.select_tree(
                    "path",
                    key,
                )

            self.go(
                "Tree of Life"
            )

        elif kind in (
            "sephirah",
            "path",
        ):
            self.select_tree(
                kind,
                key,
            )

            self.go(
                "Tree of Life"
            )

        elif kind == "ootk":
            self.select_ootk(
                key
            )

            self.go(
                "Opening of the Key"
            )

        elif kind == "card":
            self.search.clear()

            self.card_filter.setCurrentIndex(
                0
            )

            for i in range(
                self.card_list.count()
            ):
                if (
                    self.card_list.item(
                        i
                    ).data(
                        Qt.ItemDataRole.UserRole
                    )
                    == key
                ):
                    self.card_list.setCurrentRow(
                        i
                    )
                    break

            self.go(
                "Card Explorer"
            )

        else:
            self.current_topic = (
                kind,
                key,
            )

            self.detail.setHtml(
                self.catalog.render(
                    kind,
                    key,
                    self.basic.isChecked(),
                    self.depth.currentIndex(),
                )
            )

            self.go(
                "Card Explorer"
            )

    # ------------------------------------------------------------------
    # Study / quizzes
    # ------------------------------------------------------------------

    def build_study(
        self,
        progress_path,
    ):
        page = QWidget()

        layout = QVBoxLayout(
            page
        )

        self.progress_error = None

        try:
            self.progress = Progress(
                progress_path
            )

        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            self.progress = None

            self.progress_error = (
                "Progress could not be loaded: "
                f"{exc}. Existing data has not "
                "been replaced. Practice is "
                "available without saving."
            )

        self.questions = question_bank(
            self.catalog
        )

        self.quiz_category = QComboBox()

        self.quiz_category.addItems(
            [
                "All topics",
                "Correspondences",
                "Paths",
                "Elements",
                "Tree",
                "Derivation",
                "Opening of the Key",
            ]
        )

        layout.addWidget(
            self.quiz_category
        )

        self.stats = QLabel()

        self.stats.setWordWrap(
            True
        )

        layout.addWidget(
            self.stats
        )

        self.question_label = QLabel()

        self.question_label.setWordWrap(
            True
        )

        self.question_label.setStyleSheet(
            (
                "font-size: 18px; "
                "padding: 12px;"
            )
        )

        layout.addWidget(
            self.question_label
        )

        self.answers = QComboBox()

        layout.addWidget(
            self.answers
        )

        buttons = QHBoxLayout()

        self.check_button = QPushButton(
            "Check answer"
        )

        self.next_button = QPushButton(
            "Next question"
        )

        self.review_button = QPushButton(
            "Review reference"
        )

        for b in (
            self.check_button,
            self.next_button,
            self.review_button,
        ):
            buttons.addWidget(
                b
            )

        layout.addLayout(
            buttons
        )

        self.feedback = self.browser()

        layout.addWidget(
            self.feedback,
            1,
        )

        self.check_button.clicked.connect(
            self.check_answer
        )

        self.next_button.clicked.connect(
            self.next_question
        )

        self.quiz_category.currentIndexChanged.connect(
            self.next_question
        )

        self.review_button.clicked.connect(
            lambda: self.follow_link(
                QUrl(
                    (
                        "study:"
                        + self.question.target[0]
                        + "/"
                        + self.question.target[1]
                    )
                )
            )
        )

        self.next_question()

        return page

    def update_stats(self):
        if self.progress is None:
            self.stats.setText(
                self.progress_error
            )
            return

        (
            attempts,
            correct,
            mastered,
        ) = self.progress.summary()

        due = sum(
            (
                datetime.fromisoformat(
                    r["due"]
                )
                <= datetime.now(
                    timezone.utc
                )
            )
            for r
            in self.progress.records.values()
        )

        repeated = sum(
            (
                r["mistakes"] >= 2
            )
            for r
            in self.progress.records.values()
        )

        if attempts:
            self.stats.setText(
                (
                    f"{correct}/{attempts} correct · "
                    f"{correct / attempts:.0%} accuracy"
                )
            )
        else:
            self.stats.setText(
                "No attempts yet"
            )

        self.stats.setText(
            (
                self.stats.text()
                + (
                    f" · {mastered} provisionally "
                    "mastered "
                    "(3 consecutive correct)"
                    f" · {due} due"
                    f" · {repeated} "
                    "repeated-mistake topics"
                )
            )
        )

    def next_question(
        self,
        *args,
    ):
        previous = getattr(
            getattr(
                self,
                "question",
                None,
            ),
            "id",
            None,
        )

        if (
            self.quiz_category.currentIndex()
            == 0
        ):
            pool = list(
                self.questions
            )
        else:
            category = (
                self.quiz_category.currentText()
            )

            pool = [
                q
                for q in self.questions
                if q.category == category
            ]

        if self.progress:
            self.question = (
                self.progress.choose(
                    pool,
                    exclude=previous,
                )
            )
        else:
            choices = [
                q
                for q in pool
                if q.id != previous
            ] or pool

            self.question = random.choice(
                choices
            )

        self.question_label.setText(
            self.question.prompt
        )

        self.answers.clear()

        self.answers.addItem(
            "Choose an answer…",
            None,
        )

        choices = list(
            self.question.choices
        )

        random.shuffle(
            choices
        )

        for choice in choices:
            self.answers.addItem(
                choice,
                choice,
            )

        self.check_button.setEnabled(
            True
        )

        self.review_button.setEnabled(
            False
        )

        self.feedback.setHtml(
            (
                "<p>"
                "Recall the correspondence, "
                "then explain to yourself why "
                "it belongs at that layer."
                "</p>"
                "<p>"
                "Due reviews are prioritized, "
                "followed by unseen questions. "
                "Extra practice is available "
                "when no reviews are due."
                "</p>"
            )
        )

        self.update_stats()

    def check_answer(self):
        if not self.check_button.isEnabled():
            return

        answer = self.answers.currentData()

        if answer is None:
            self.feedback.setHtml(
                (
                    "<p>"
                    "Select an answer "
                    "before checking."
                    "</p>"
                )
            )
            return

        correct = (
            answer
            == self.question.answer
        )

        self.check_button.setEnabled(
            False
        )

        self.review_button.setEnabled(
            True
        )

        if correct:
            heading = "Correct"
        else:
            heading = (
                "Review this correspondence"
            )

        message = (
            "<h3>"
            + heading
            + "</h3>"
            + paragraph(
                (
                    "Reference: "
                    + self.question.answer
                )
            )
        )

        if self.progress:
            try:
                self.progress.record(
                    self.question.id,
                    correct,
                )

                record = self.progress.records[
                    self.question.id
                ]

                message += paragraph(
                    (
                        "Next review: "
                        + record["due"]
                    )
                )

            except OSError as exc:
                message += paragraph(
                    (
                        "Could not save this attempt: "
                        f"{exc}. Your previous "
                        "progress is preserved."
                    )
                )

        message += paragraph(
            (
                "Open the reference and "
                "reconstruct the relationship; "
                "recall alone is only a first "
                "step toward understanding."
            )
        )

        self.feedback.setHtml(
            message
        )

        self.update_stats()