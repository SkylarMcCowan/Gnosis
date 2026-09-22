"""Data loading and educational views. No Qt or model/network dependency."""

from html import escape
import json
from pathlib import Path


DATA_DIR = Path(__file__).with_name("data")

ZODIAC_ORDER = (
    "Aries",
    "Taurus",
    "Gemini",
    "Cancer",
    "Leo",
    "Virgo",
    "Libra",
    "Scorpio",
    "Sagittarius",
    "Capricorn",
    "Aquarius",
    "Pisces",
)


def link(kind, key, label):
    return f'<a href="study:{kind}/{key}">{escape(str(label))}</a>'


def paragraph(text):
    return f"<p>{escape(str(text))}</p>"


class Catalog:
    def __init__(self, data_dir=DATA_DIR):
        data_dir = Path(data_dir)

        for name in (
            "sephiroth",
            "paths",
            "majors",
            "minors",
            "suits",
            "sources",
        ):
            rows = json.loads(
                (data_dir / f"{name}.json").read_text(encoding="utf-8")
            )

            index = {r["id"]: r for r in rows}

            if len(index) != len(rows):
                raise ValueError(f"Duplicate IDs in {name}")

            setattr(self, name, index)

        self.cards = {
            **self.majors,
            **self.minors,
        }

        # Opening of the Key curriculum
        self.ootk = json.loads(
            (data_dir / "ootk.json").read_text(encoding="utf-8")
        )

        self.validate()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self):
        if set(self.sephiroth) != set(range(1, 11)):
            raise ValueError("Expected 10 Sephiroth")

        if set(self.paths) != set(range(11, 33)):
            raise ValueError("Expected 22 Paths")

        if len(self.majors) != 22:
            raise ValueError("Expected 22 Majors")

        if len(self.minors) != 40:
            raise ValueError("Expected 40 numbered Minors")

        for p in self.paths.values():
            if len(p["endpoints"]) != 2:
                raise ValueError("A Path must have two endpoints")

            if len(set(p["endpoints"])) != 2:
                raise ValueError("A Path must join two different Sephiroth")

            for endpoint in p["endpoints"]:
                if endpoint not in self.sephiroth:
                    raise ValueError("Unknown Path endpoint")

            if p["major_id"] not in self.majors:
                raise ValueError("Unknown Major assigned to Path")

            if self.majors[p["major_id"]]["path"] != p["id"]:
                raise ValueError("Inconsistent Major/Path relationship")

        for c in self.minors.values():
            if c["number"] != c["sephirah"]:
                raise ValueError("Minor number must match Sephirah")

            if c["sephirah"] not in self.sephiroth:
                raise ValueError("Unknown Sephirah")

            if c["suit"] not in self.suits:
                raise ValueError("Unknown suit")

            if c["number"] == 1:
                if any(
                    c[k] is not None
                    for k in ("planet", "zodiac", "decan")
                ):
                    raise ValueError(
                        "Aces do not have individual decans"
                    )

        for records in (
            self.sephiroth,
            self.paths,
            self.cards,
            self.suits,
        ):
            for record in records.values():
                if any(
                    source not in self.sources
                    for source in record["sources"]
                ):
                    raise ValueError("Unknown source")

        self._validate_ootk()

    def _validate_ootk(self):
        operations = self.ootk.get("operations", [])

        if [op["id"] for op in operations] != [1, 2, 3, 4, 5]:
            raise ValueError(
                "OOTK must contain five ordered operations"
            )

        source = self.ootk.get("source")
        if source not in self.sources:
            raise ValueError("Unknown OOTK source")

        first = operations[0]
        if first.get("layout") != "four-packets":
            raise ValueError(
                "OOTK First Operation must use four packets"
            )

        if len(first.get("packets", [])) != 4:
            raise ValueError(
                "OOTK First Operation requires four YHVH packets"
            )

        second = operations[1]
        if second.get("layout") != "twelve-packets":
            raise ValueError(
                "OOTK Second Operation must use twelve Houses"
            )

        third = operations[2]
        if third.get("layout") != "twelve-packets":
            raise ValueError(
                "OOTK Third Operation must use twelve Signs"
            )

        fourth = operations[3]
        if fourth.get("layout") != "thirty-six-circle":
            raise ValueError(
                "OOTK Fourth Operation must use 36 Decanates"
            )

        fifth = operations[4]
        if fifth.get("layout") != "ten-packets":
            raise ValueError(
                "OOTK Fifth Operation must use the ten Sephiroth"
            )

        if len(self.ootk.get("houses", [])) != 12:
            raise ValueError("OOTK must define twelve Houses")

    # ------------------------------------------------------------------
    # Shared rendering helpers
    # ------------------------------------------------------------------

    def source_html(self, ids):
        return (
            "<h3>Source / history</h3>"
            + "".join(
                paragraph(self.sources[s]["tradition"])
                + link(
                    "source",
                    s,
                    self.sources[s]["title"],
                )
                for s in dict.fromkeys(ids)
            )
            + paragraph(
                "Explanations and derivation questions are modern "
                "teaching synthesis, not quotations. These are "
                "historical esoteric correspondences, not "
                "scientifically established mechanisms."
            )
        )

    # ------------------------------------------------------------------
    # Tarot derivation
    # ------------------------------------------------------------------

    def derivation(self, card_id):
        c = self.cards[card_id]

        if c["kind"] == "major":
            p = self.paths[c["path"]]

            a, b = (
                self.sephiroth[i]
                for i in p["endpoints"]
            )

            return [
                (
                    "Class",
                    "Major Arcana → a connecting Path, "
                    "not a Sephirah",
                ),
                (
                    "Path",
                    f"{p['id']}: "
                    f"{a['name']} ↔ {b['name']} "
                    "(Golden Dawn Tree)",
                ),
                (
                    "Hebrew letter",
                    f"{p['hebrew']} {p['letter']} "
                    "(Golden Dawn)",
                ),
                (
                    "Attribution",
                    p["astrology"],
                ),
                (
                    "First endpoint",
                    a["traditional"],
                ),
                (
                    "Second endpoint",
                    b["traditional"],
                ),
                (
                    "Synthesis exercise",
                    c["prompt"],
                ),
                (
                    "Traditional theme",
                    c["theme"],
                ),
            ]

        s = self.sephiroth[c["sephirah"]]
        suit = self.suits[c["suit"]]

        if c["number"] == 1:
            astrology = (
                "Elemental root; no individual decan"
            )
        else:
            astrology = (
                f"{c['planet']} in {c['zodiac']}, "
                f"decan {c['decan']} "
                f"({c['degrees'][0]}°–"
                f"{c['degrees'][1]}°)"
            )

        return [
            (
                "Number",
                str(c["number"]),
            ),
            (
                "Sephirah",
                s["name"] + ": " + s["traditional"],
            ),
            (
                "Suit",
                c["suit"],
            ),
            (
                "Element / world",
                f"{suit['element']} / "
                f"{suit['world']}: "
                f"{suit['description']}",
            ),
            (
                "Astrology",
                astrology,
            ),
            (
                "Golden Dawn title",
                c["gd_title"],
            ),
            (
                "Thoth title",
                c["thoth_title"],
            ),
            (
                "Suggested synthesis "
                "(modern teaching interpretation)",
                c["synthesis"],
            ),
            (
                "Synthesis exercise",
                (
                    f"Apply {s['name']} to the activity "
                    f"of {suit['element']}. "
                    f"{s['basic']} "
                    "How does the astrological condition "
                    "qualify this? Compare your reasoning "
                    "with the two titles; a title is a "
                    "traditional synthesis, not the "
                    "inevitable result of an equation."
                ),
            ),
        ]

    # ------------------------------------------------------------------
    # OOTK helpers
    # ------------------------------------------------------------------

    def ootk_operation(self, operation_id):
        operation_id = int(operation_id)

        for operation in self.ootk["operations"]:
            if operation["id"] == operation_id:
                return operation

        raise KeyError(operation_id)

    def ootk_count_value(self, card_id):
        """
        Return the historical OOTK counting value for a card
        represented by the current 62-card catalog.

        Court-card counting will be added when courts.json is added.
        """
        card = self.cards[card_id]

        if card["kind"] == "minor":
            if card["number"] == 1:
                return (
                    5,
                    "Ace → Spirit and the four elements",
                )

            return (
                card["number"],
                (
                    f"{card['number']} → "
                    "its own pip / Sephirah number"
                ),
            )

        path = self.paths[card["path"]]
        letter = path["letter"]

        mothers = {
            "Aleph",
            "Mem",
            "Shin",
        }

        doubles = {
            "Beth",
            "Gimel",
            "Daleth",
            "Kaph",
            "Peh",
            "Resh",
            "Tav",
        }

        if letter in mothers:
            return (
                3,
                f"{letter} → Mother Letter",
            )

        if letter in doubles:
            return (
                9,
                (
                    f"{letter} → Double Letter "
                    "counting class"
                ),
            )

        return (
            12,
            (
                f"{letter} → Simple Letter / "
                "Zodiacal class"
            ),
        )

    def zodiac_major_map(self):
        result = {}

        for path in self.paths.values():
            sign = path["astrology"]

            if sign in ZODIAC_ORDER:
                result[sign] = self.majors[
                    path["major_id"]
                ]

        return result

    def decan_cards(self):
        zodiac_index = {
            sign: i
            for i, sign in enumerate(ZODIAC_ORDER)
        }

        cards = [
            c
            for c in self.minors.values()
            if c["decan"] is not None
        ]

        return sorted(
            cards,
            key=lambda c: (
                zodiac_index[c["zodiac"]],
                c["decan"],
            ),
        )

    # ------------------------------------------------------------------
    # OOTK rendering
    # ------------------------------------------------------------------

    def render_ootk_overview(self):
        overview = self.ootk["overview"]

        body = "<h2>Opening of the Key</h2>"

        body += paragraph(
            overview["summary"]
        )

        body += (
            "<h3>What the five operations do</h3>"
            "<ol>"
        )

        for operation in self.ootk["operations"]:
            body += (
                "<li>"
                f"<b>Operation {operation['id']} — "
                f"{escape(operation['title'])}</b>"
                "<br>"
                f"{escape(operation['system'])}"
                "<br>"
                f"{escape(operation['purpose'])}"
                "</li>"
            )

        body += "</ol>"

        body += "<h3>The recurring reading engine</h3>"

        body += (
            "<p><b>Question → Significator → "
            "symbolic field → counting → pairing → "
            "elemental qualification → synthesis</b></p>"
        )

        body += (
            "<h3>Core method</h3>"
            "<ol>"
        )

        for item in overview["core_method"]:
            body += (
                f"<li>{escape(item)}</li>"
            )

        body += "</ol>"

        body += (
            "<h3>Important: Court cards</h3>"
            + paragraph(overview["court_note"])
        )

        body += (
            "<h3>Inversions / reversals</h3>"
            + paragraph(overview["reversal_note"])
        )

        body += (
            "<h3>Learning sequence</h3>"
            "<p>"
            "<b>I.</b> Fourfold elemental opening "
            "→ "
            "<b>II.</b> House field "
            "→ "
            "<b>III.</b> Zodiacal mode "
            "→ "
            "<b>IV.</b> decanic development "
            "→ "
            "<b>V.</b> Sephirothic conclusion"
            "</p>"
        )

        body += self.source_html(
            [self.ootk["source"]]
        )

        return body

    def render_ootk_counting(self):
        counting = self.ootk["counting"]

        body = "<h2>OOTK Card Counting</h2>"

        body += paragraph(
            counting["introduction"]
        )

        body += (
            "<table cellpadding='6'>"
            "<tr>"
            "<th align='left'>Card class</th>"
            "<th align='left'>Count</th>"
            "<th align='left'>Reason</th>"
            "</tr>"
        )

        for rule in counting["rules"]:
            body += (
                "<tr>"
                f"<td>{escape(rule['label'])}</td>"
                f"<td>{escape(str(rule['count']))}</td>"
                f"<td>{escape(rule['reason'])}</td>"
                "</tr>"
            )

        body += "</table>"

        body += (
            "<h3>Example</h3>"
            + paragraph(
                "If the selected card is the 5 of Cups, "
                "that card is count 1. Continue 2, 3, 4, 5 "
                "in the established direction and interpret "
                "the card on which 5 lands. That new card "
                "supplies the next counting value."
            )
        )

        body += (
            "<h3>When does counting stop?</h3>"
            + paragraph(
                "When counting lands on a card that has "
                "already appeared in the counting chain, "
                "the sequence closes."
            )
        )

        body += (
            "<h3>Why physical orientation matters</h3>"
            + paragraph(
                "The historical procedure does not assign "
                "a separate reversed meaning merely because "
                "a card is inverted. Orientation is preserved "
                "because the direction in which the "
                "Significator faces determines the direction "
                "of counting in the horseshoe operations."
            )
        )

        body += (
            "<h3>Current application limitation</h3>"
            + paragraph(
                "The present catalog contains Majors and "
                "numbered Minors. Court-card values are shown "
                "here for learning, but Court cards will not "
                "be available in the Card Explorer until a "
                "future courts.json module is added."
            )
        )

        body += self.source_html(
            [self.ootk["source"]]
        )

        return body

    def render_ootk_operation(self, operation_id):
        op = self.ootk_operation(operation_id)

        body = (
            f"<h2>Operation {op['id']} · "
            f"{escape(op['title'])}</h2>"
        )

        body += (
            "<h3>"
            f"{escape(op['system'])}"
            "</h3>"
        )

        body += paragraph(
            op["purpose"]
        )

        body += "<h3>Physical procedure</h3><ol>"

        for step in op["steps"]:
            body += (
                f"<li>{escape(step)}</li>"
            )

        body += "</ol>"

        # --------------------------------------------------------------
        # Operation I — four YHVH packets
        # --------------------------------------------------------------

        if op["id"] == 1:
            body += (
                "<h3>The Four Packets</h3>"
                "<table cellpadding='6'>"
                "<tr>"
                "<th align='left'>Letter</th>"
                "<th align='left'>Element</th>"
                "<th align='left'>Suit</th>"
                "<th align='left'>Traditional field</th>"
                "</tr>"
            )

            for packet in op["packets"]:
                body += (
                    "<tr>"
                    f"<td>{escape(packet['key'])}</td>"
                    f"<td>{escape(packet['element'])}</td>"
                    f"<td>{escape(packet['suit'])}</td>"
                    f"<td>"
                    f"{escape(packet['traditional_field'])}"
                    "</td>"
                    "</tr>"
                )

            body += "</table>"

            body += (
                "<h3>What to record</h3>"
                + paragraph(
                    "Record the four exposed preliminary "
                    "cards, which YHVH packet contains the "
                    "Significator, the predominant suit in "
                    "the retained packet, the counting chain "
                    "and the final sequence of pairs."
                )
            )

        # --------------------------------------------------------------
        # Operation II — Houses
        # --------------------------------------------------------------

        elif op["id"] == 2:
            body += (
                "<h3>Twelve Houses · teaching reference</h3>"
                + paragraph(
                    "The House keywords below are modern "
                    "study shorthand. The historical OOTK "
                    "procedure supplies the twelve-House "
                    "structure; these brief explanations are "
                    "included to help you learn that structure."
                )
                + "<table cellpadding='5'>"
                "<tr>"
                "<th align='left'>House</th>"
                "<th align='left'>Study field</th>"
                "</tr>"
            )

            for house in self.ootk["houses"]:
                body += (
                    "<tr>"
                    f"<td><b>{house['number']}</b></td>"
                    f"<td>{escape(house['teaching'])}</td>"
                    "</tr>"
                )

            body += "</table>"

            body += (
                "<h3>Question to ask yourself</h3>"
                + paragraph(
                    "Why would this question be developing "
                    "through this particular House? Treat the "
                    "House as context, not as a standalone "
                    "prediction."
                )
            )

        # --------------------------------------------------------------
        # Operation III — Zodiac / Majors
        # --------------------------------------------------------------

        elif op["id"] == 3:
            mapping = self.zodiac_major_map()

            body += (
                "<h3>Zodiacal packets and their Majors</h3>"
                "<table cellpadding='5'>"
                "<tr>"
                "<th align='left'>Sign</th>"
                "<th align='left'>Major Arcana</th>"
                "<th align='left'>Path</th>"
                "</tr>"
            )

            for sign in ZODIAC_ORDER:
                card = mapping.get(sign)

                if card is None:
                    continue

                path = self.paths[
                    card["path"]
                ]

                body += (
                    "<tr>"
                    f"<td>{escape(sign)}</td>"
                    "<td>"
                    + link(
                        "card",
                        card["id"],
                        card["name"],
                    )
                    + "</td>"
                    "<td>"
                    + link(
                        "path",
                        path["id"],
                        (
                            f"{path['id']} "
                            f"{path['letter']}"
                        ),
                    )
                    + "</td>"
                    "</tr>"
                )

            body += "</table>"

            body += (
                "<h3>Interpretive distinction</h3>"
                + paragraph(
                    "The Sign identifies the packet's "
                    "Zodiacal quality. The associated Major "
                    "Arcana supplies the Golden Dawn symbolic "
                    "Path correspondence. The cards inside "
                    "the packet remain their own cards and "
                    "retain their own correspondences."
                )
            )

        # --------------------------------------------------------------
        # Operation IV — decans
        # --------------------------------------------------------------

        elif op["id"] == 4:
            body += (
                "<h3>Thirty-Six Decan Cards</h3>"
                + paragraph(
                    "The numbered Minors Two through Ten "
                    "already encode the thirty-six decanic "
                    "attributions. This reference table is "
                    "sorted by Zodiacal sign for study; it "
                    "does not replace the physical circular "
                    "dealing procedure."
                )
                + "<table cellpadding='5'>"
                "<tr>"
                "<th align='left'>Sign</th>"
                "<th align='left'>Degrees</th>"
                "<th align='left'>Planet</th>"
                "<th align='left'>Card</th>"
                "</tr>"
            )

            for card in self.decan_cards():
                body += (
                    "<tr>"
                    f"<td>{escape(card['zodiac'])}</td>"
                    f"<td>"
                    f"{card['degrees'][0]}°–"
                    f"{card['degrees'][1]}°"
                    "</td>"
                    f"<td>{escape(card['planet'])}</td>"
                    "<td>"
                    + link(
                        "card",
                        card["id"],
                        card["name"],
                    )
                    + "</td>"
                    "</tr>"
                )

            body += "</table>"

            body += (
                "<h3>Critical difference from the other operations</h3>"
                + paragraph(
                    "The Significator sits in the center. "
                    "Counting starts from card 1 of the "
                    "thirty-six-card circle, not from the "
                    "Significator, and proceeds in the "
                    "direction in which the cards were dealt."
                )
            )

        # --------------------------------------------------------------
        # Operation V — Tree
        # --------------------------------------------------------------

        elif op["id"] == 5:
            body += (
                "<h3>The Ten Packets</h3>"
                "<table cellpadding='5'>"
                "<tr>"
                "<th align='left'>#</th>"
                "<th align='left'>Sephirah</th>"
                "<th align='left'>Pillar</th>"
                "<th align='left'>Teaching focus</th>"
                "</tr>"
            )

            for s in self.sephiroth.values():
                body += (
                    "<tr>"
                    f"<td>{s['id']}</td>"
                    "<td>"
                    + link(
                        "sephirah",
                        s["id"],
                        s["name"],
                    )
                    + "</td>"
                    f"<td>{escape(s['pillar'])}</td>"
                    f"<td>{escape(s['traditional'])}</td>"
                    "</tr>"
                )

            body += "</table>"

            body += (
                "<h3>Do not turn the Sephirah into a verdict</h3>"
                + paragraph(
                    "If the Significator falls under "
                    "Tiphareth, for example, the reading "
                    "is being concluded through the symbolic "
                    "field of Tiphareth. It does not mean "
                    "that the answer is automatically good, "
                    "successful or harmonious."
                )
            )

            body += (
                "<p>"
                + link(
                    "tree",
                    "s1",
                    "Open the Tree of Life",
                )
                + "</p>"
            )

        body += (
            "<h3>After the operation</h3>"
            + paragraph(
                "Write your interpretation before checking "
                "card reference pages. The goal of this "
                "curriculum is to learn how the symbolic "
                "layers interact rather than substitute "
                "keywords for interpretation."
            )
        )

        body += self.source_html(
            [self.ootk["source"]]
        )

        return body

    # ------------------------------------------------------------------
    # Main renderer
    # ------------------------------------------------------------------

    def render(
        self,
        kind,
        key,
        basic=True,
        depth=2,
    ):
        if kind == "ootk":
            key = str(key)

            if key in ("0", "overview"):
                return self.render_ootk_overview()

            if key == "counting":
                return self.render_ootk_counting()

            return self.render_ootk_operation(
                int(key)
            )

        if kind == "card":
            c = self.cards[key]

            body = (
                f"<h2>{escape(c['name'])}</h2>"
            )

            if c["kind"] == "major":
                p = self.paths[c["path"]]

                body += (
                    "<h3>"
                    "Golden Dawn baseline · "
                    "Major Arcana → Path"
                    "</h3>"
                )

                body += link(
                    "path",
                    p["id"],
                    (
                        f"Path {p['id']} · "
                        f"{p['hebrew']} "
                        f"{p['letter']}"
                    ),
                )

                body += paragraph(
                    (
                        f"Astrology: {p['astrology']} · "
                        "Element: "
                        f"{p['element'] or 'No separate direct element in this table'}"
                    )
                )

                body += "<p>Endpoints: "

                body += " ↔ ".join(
                    link(
                        "sephirah",
                        n,
                        self.sephiroth[n]["name"],
                    )
                    for n in p["endpoints"]
                )

                body += "</p>"

                body += paragraph(
                    "Traditional theme: "
                    + c["theme"]
                )

                body += (
                    "<h3>Crowley / Thoth comparison</h3>"
                    + paragraph(
                        (
                            f"{c['thoth_number']} "
                            f"{c['thoth_name']} · "
                            "Hebrew letter: "
                            f"{c['thoth_letter']}"
                        )
                    )
                )

                body += paragraph(
                    c["difference"]
                )

                if depth >= 1:
                    body += (
                        "<h3>"
                        "Thoth imagery · study description"
                        "</h3>"
                        + paragraph(c["imagery"])
                    )

                body += (
                    "<p>"
                    + link(
                        "tree",
                        p["id"],
                        (
                            "Locate this Path on the "
                            "Golden Dawn Tree"
                        ),
                    )
                    + "</p>"
                )

            else:
                suit = self.suits[c["suit"]]

                body += (
                    "<h3>"
                    "Numbered Minor Arcana → Sephirah"
                    "</h3>"
                )

                body += link(
                    "sephirah",
                    c["sephirah"],
                    (
                        f"{c['number']} · "
                        f"{self.sephiroth[c['sephirah']]['name']}"
                    ),
                )

                body += " × "

                body += link(
                    "suit",
                    c["suit"],
                    (
                        f"{c['suit']} · "
                        f"{suit['element']}"
                    ),
                )

                body += paragraph(
                    (
                        f"Golden Dawn: "
                        f"{c['gd_title']} "
                        f"({suit['gd_name']})"
                    )
                )

                body += paragraph(
                    f"Thoth: {c['thoth_title']}"
                )

                if c["number"] == 1:
                    body += paragraph(
                        "An Ace is the root of its "
                        "element, not one of the "
                        "36 decan cards."
                    )
                else:
                    body += paragraph(
                        (
                            f"{c['planet']} in "
                            f"{c['zodiac']} · "
                            f"decan {c['decan']} · "
                            f"{c['degrees'][0]}°–"
                            f"{c['degrees'][1]}° "
                            "of the sign. The decan "
                            "ruler differs from the "
                            "Sephirah’s planetary sphere."
                        )
                    )

                body += (
                    "<p>"
                    + link(
                        "tree",
                        f"s{c['sephirah']}",
                        (
                            "Locate this Sephirah "
                            "on the Tree"
                        ),
                    )
                    + "</p>"
                )

            body += (
                "<h3>"
                "Derive this card · "
                "modern teaching synthesis"
                "</h3>"
            )

            if basic:
                body += paragraph(
                    "Read each layer in order. "
                    "Try your own synthesis before "
                    "treating the traditional theme "
                    "or title as an answer."
                )

            body += "<ol>"

            body += "".join(
                (
                    f"<li><b>{escape(label)}</b>: "
                    f"{escape(value)}</li>"
                )
                for label, value
                in self.derivation(key)
            )

            body += "</ol>"

            count, reason = self.ootk_count_value(
                key
            )

            body += (
                "<h3>Opening of the Key</h3>"
                + paragraph(
                    f"Card-count value: {count}. "
                    f"{reason}."
                )
                + "<p>"
                + link(
                    "ootk",
                    "counting",
                    "Learn OOTK card counting",
                )
                + "</p>"
            )

            sources = c["sources"]

        elif kind == "sephirah":
            s = self.sephiroth[int(key)]

            body = (
                f"<h2>{s['id']}. "
                f"{escape(s['name'])} · "
                f"{s['hebrew']}</h2>"
            )

            body += paragraph(
                (
                    s["translation"]
                    + " · "
                    + s["pillar"]
                    + " Pillar"
                )
            )

            if basic:
                body += (
                    "<h3>Basic explanation</h3>"
                    + paragraph(s["basic"])
                )

            body += (
                "<h3>Traditional terminology</h3>"
                + paragraph(s["traditional"])
            )

            body += paragraph(
                "Celestial sphere: "
                + s["planet"]
            )

            if depth >= 1:
                for label, field in (
                    ("Divine name", "divine_name"),
                    ("Archangel", "archangel"),
                    ("Angelic order", "angelic_order"),
                    ("Worlds", "worlds"),
                    ("Element", "element"),
                ):
                    body += paragraph(
                        f"{label}: {s[field]}"
                    )

                body += paragraph(
                    s["source_note"]
                )

            body += (
                "<h3>Numbered Minors here</h3>"
                "<p>"
            )

            body += " · ".join(
                link(
                    "card",
                    c["id"],
                    c["name"],
                )
                for c in self.minors.values()
                if c["sephirah"] == s["id"]
            )

            body += "</p>"

            body += (
                "<h3>Connecting Paths</h3>"
                "<p>"
            )

            body += " · ".join(
                link(
                    "path",
                    p["id"],
                    f"{p['id']} {p['letter']}",
                )
                for p in self.paths.values()
                if s["id"] in p["endpoints"]
            )

            body += "</p>"

            sources = s["sources"]

        elif kind == "path":
            p = self.paths[int(key)]

            return self.render(
                "card",
                p["major_id"],
                basic,
                depth,
            )

        elif kind == "suit":
            s = self.suits[key]

            body = (
                "<h2>"
                + escape(s["name"])
                + "</h2>"
            )

            body += paragraph(
                (
                    f"{s['element']} · "
                    f"{s['world']} · "
                    "Golden Dawn suit name: "
                    f"{s['gd_name']}"
                )
            )

            body += paragraph(
                s["description"]
            )

            body += paragraph(
                "The suit/world association is a "
                "symbolic scale. Each world can "
                "itself be studied as a complete Tree."
            )

            body += "<p>"

            body += " · ".join(
                link(
                    "card",
                    c["id"],
                    c["name"],
                )
                for c in self.minors.values()
                if c["suit"] == key
            )

            body += "</p>"

            sources = s["sources"]

        elif kind == "source":
            s = self.sources[key]

            return (
                "<h2>"
                + escape(s["title"])
                + "</h2>"
                + "".join(
                    paragraph(s[f])
                    for f in (
                        "tradition",
                        "edition",
                        "locator",
                        "note",
                    )
                )
                + (
                    (
                        '<p><a href="'
                        + escape(
                            s["url"],
                            quote=True,
                        )
                        + '">'
                        + "Open source in browser"
                        + "</a></p>"
                    )
                    if s["url"]
                    else ""
                )
            )

        else:
            raise KeyError(kind)

        if depth >= 2:
            version = (
                c["version"]
                if kind == "card"
                else s.get(
                    "version",
                    (
                        "Hermetic suit/world "
                        "convention"
                    ),
                )
            )

            body += paragraph(
                "Version: " + version
            )

            body += self.source_html(
                sources
            )

        return body