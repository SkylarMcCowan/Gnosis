"""Basic local quiz scheduling. Stable question IDs survive data corrections."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import random
import tempfile

from core import config


@dataclass(frozen=True)
class Question:
    id: str
    category: str
    prompt: str
    answer: str
    choices: tuple[str, ...]
    target: tuple[str, str]


def question_bank(catalog):
    result = []

    names = tuple(
        s["name"]
        for s in catalog.sephiroth.values()
    )

    def add(
        qid,
        category,
        prompt,
        answer,
        candidates,
        target,
    ):
        others = [
            v
            for v in dict.fromkeys(candidates)
            if v != answer
        ]

        # Stable distractors; UI shuffles display order
        # for each attempt.
        result.append(
            Question(
                qid,
                category,
                prompt,
                answer,
                tuple(
                    [answer]
                    + others[:3]
                ),
                target,
            )
        )

    # --------------------------------------------------------------
    # Sephiroth
    # --------------------------------------------------------------

    for s in catalog.sephiroth.values():
        add(
            f"number-{s['id']}",
            "Correspondences",
            (
                "Which Sephirah corresponds "
                f"to {s['id']}?"
            ),
            s["name"],
            names,
            (
                "sephirah",
                str(s["id"]),
            ),
        )

    # --------------------------------------------------------------
    # Paths / Major Arcana
    # --------------------------------------------------------------

    major_names = [
        c["name"]
        for c in catalog.majors.values()
    ]

    for p in catalog.paths.values():
        card = catalog.majors[
            p["major_id"]
        ]

        add(
            f"letter-{p['id']}",
            "Paths",
            (
                "In the Golden Dawn baseline, "
                "which Major corresponds to "
                f"{p['hebrew']} {p['letter']}?"
            ),
            card["name"],
            major_names,
            (
                "card",
                card["id"],
            ),
        )

    # --------------------------------------------------------------
    # Elements
    # --------------------------------------------------------------

    for s in catalog.suits.values():
        add(
            f"element-{s['id']}",
            "Elements",
            (
                "Which element corresponds "
                f"to {s['name']}?"
            ),
            s["element"],
            [
                "Fire",
                "Water",
                "Air",
                "Earth",
            ],
            (
                "suit",
                s["id"],
            ),
        )

    # --------------------------------------------------------------
    # Major vs Minor Tree placement
    # --------------------------------------------------------------

    for c in catalog.cards.values():
        answer = (
            "Path"
            if c["kind"] == "major"
            else "Sephirah"
        )

        add(
            f"placement-{c['id']}",
            "Tree",
            (
                f"Where does {c['name']} belong "
                "in the Golden Dawn "
                "correspondence structure?"
            ),
            answer,
            [
                "Path",
                "Sephirah",
                "Court elemental structure",
            ],
            (
                "card",
                c["id"],
            ),
        )

    # --------------------------------------------------------------
    # Minor derivation
    # --------------------------------------------------------------

    for c in catalog.minors.values():
        s = catalog.sephiroth[
            c["sephirah"]
        ]

        element = catalog.suits[
            c["suit"]
        ]["element"]

        answer = (
            f"{s['name']} + {element}"
        )

        candidates = [
            (
                f"{other['name']} + "
                f"{element}"
            )
            for other
            in catalog.sephiroth.values()
        ]

        add(
            f"derive-{c['id']}",
            "Derivation",
            (
                "Which Sephirah and element "
                "begin a derivation of "
                f"{c['name']}?"
            ),
            answer,
            candidates,
            (
                "card",
                c["id"],
            ),
        )

    # --------------------------------------------------------------
    # Opening of the Key — sequence
    # --------------------------------------------------------------

    ootk_structures = [
        (
            1,
            "Four YHVH packets",
        ),
        (
            2,
            "Twelve Astrological Houses",
        ),
        (
            3,
            "Twelve Zodiac Signs",
        ),
        (
            4,
            "Thirty-Six Decanates",
        ),
        (
            5,
            "Ten Sephiroth",
        ),
    ]

    structure_answers = [
        answer
        for _, answer
        in ootk_structures
    ]

    for number, answer in ootk_structures:
        add(
            f"ootk-operation-{number}",
            "Opening of the Key",
            (
                "What symbolic structure governs "
                f"Opening of the Key "
                f"Operation {number}?"
            ),
            answer,
            structure_answers,
            (
                "ootk",
                str(number),
            ),
        )

    # --------------------------------------------------------------
    # OOTK purpose
    # --------------------------------------------------------------

    add(
        "ootk-purpose-1",
        "Opening of the Key",
        (
            "What is the broad role of "
            "Operation I?"
        ),
        "Opening of the matter as it presently stands",
        [
            "Opening of the matter as it presently stands",
            "Final conclusion",
            "Only the querent's finances",
            "Selection of a new question",
        ],
        (
            "ootk",
            "1",
        ),
    )

    add(
        "ootk-purpose-5",
        "Opening of the Key",
        (
            "What is the broad role of "
            "Operation V?"
        ),
        "Conclusion or termination of the matter",
        [
            "Conclusion or termination of the matter",
            "Opening elemental condition",
            "Selection of the Significator",
            "Determining the Moon phase",
        ],
        (
            "ootk",
            "5",
        ),
    )

    # --------------------------------------------------------------
    # OOTK counting
    # --------------------------------------------------------------

    add(
        "ootk-count-ace",
        "Opening of the Key",
        (
            "How many cards are counted "
            "from an Ace in OOTK?"
        ),
        "5",
        [
            "3",
            "4",
            "5",
            "7",
        ],
        (
            "ootk",
            "counting",
        ),
    )

    add(
        "ootk-count-princess",
        "Opening of the Key",
        (
            "How many cards are counted from "
            "a Princess / Knave / Page?"
        ),
        "7",
        [
            "4",
            "5",
            "7",
            "12",
        ],
        (
            "ootk",
            "counting",
        ),
    )

    add(
        "ootk-count-court",
        "Opening of the Key",
        (
            "How many cards are counted from "
            "a King, Queen or Knight / Prince?"
        ),
        "4",
        [
            "3",
            "4",
            "7",
            "9",
        ],
        (
            "ootk",
            "counting",
        ),
    )

    add(
        "ootk-count-mother",
        "Opening of the Key",
        (
            "How many cards are counted from "
            "a Major attributed to Aleph, "
            "Mem or Shin?"
        ),
        "3",
        [
            "3",
            "5",
            "9",
            "12",
        ],
        (
            "ootk",
            "counting",
        ),
    )

    add(
        "ootk-count-double",
        "Opening of the Key",
        (
            "How many cards are counted from "
            "a Major attributed to one of the "
            "seven Double letters?"
        ),
        "9",
        [
            "3",
            "7",
            "9",
            "12",
        ],
        (
            "ootk",
            "counting",
        ),
    )

    add(
        "ootk-count-simple",
        "Opening of the Key",
        (
            "How many cards are counted from "
            "a Major attributed to a Simple "
            "Zodiacal letter?"
        ),
        "12",
        [
            "3",
            "5",
            "9",
            "12",
        ],
        (
            "ootk",
            "counting",
        ),
    )

    add(
        "ootk-count-pip",
        "Opening of the Key",
        (
            "What count is used from a "
            "numbered Minor in OOTK?"
        ),
        "Its own card number",
        [
            "Its own card number",
            "Always 4",
            "Always 10",
            "Its suit number",
        ],
        (
            "ootk",
            "counting",
        ),
    )

    add(
        "ootk-count-start",
        "Opening of the Key",
        (
            "When counting in OOTK, "
            "what number is assigned to "
            "the card from which you start?"
        ),
        "1",
        [
            "0",
            "1",
            "2",
            "The card's printed number",
        ],
        (
            "ootk",
            "counting",
        ),
    )

    add(
        "ootk-count-stop",
        "Opening of the Key",
        (
            "When does an OOTK counting "
            "sequence stop?"
        ),
        "When it lands on a card already read",
        [
            "When it lands on a card already read",
            "After exactly ten cards",
            "When a Major appears",
            "At the end of the row",
        ],
        (
            "ootk",
            "counting",
        ),
    )

    # --------------------------------------------------------------
    # OOTK physical technique
    # --------------------------------------------------------------

    add(
        "ootk-cut-first",
        "Opening of the Key",
        (
            "Which operation begins by cutting "
            "the pack into four YHVH packets?"
        ),
        "Operation I",
        [
            "Operation I",
            "Operation II",
            "Operation III",
            "Operation V",
        ],
        (
            "ootk",
            "1",
        ),
    )

    add(
        "ootk-no-cut-second",
        "Opening of the Key",
        (
            "After shuffling in Operation II, "
            "is the deck cut before dealing?"
        ),
        "No",
        [
            "Yes",
            "No",
            "Only if the Significator is reversed",
            "Only for a Major Arcana question",
        ],
        (
            "ootk",
            "2",
        ),
    )

    add(
        "ootk-op4-start",
        "Opening of the Key",
        (
            "In Operation IV, where does "
            "card counting begin?"
        ),
        "The first of the 36 dealt cards",
        [
            "The Significator",
            "The first of the 36 dealt cards",
            "The final card dealt",
            "The first Major Arcana",
        ],
        (
            "ootk",
            "4",
        ),
    )

    add(
        "ootk-op4-center",
        "Opening of the Key",
        (
            "Where is the Significator placed "
            "in Operation IV?"
        ),
        "Face up in the center",
        [
            "Face up in the center",
            "At the first decan position",
            "At the end of the circle",
            "Outside the layout",
        ],
        (
            "ootk",
            "4",
        ),
    )

    add(
        "ootk-op5-context",
        "Opening of the Key",
        (
            "What is noted before reading "
            "the retained packet in "
            "Operation V?"
        ),
        "Which Sephirah contains the Significator",
        [
            "Which Sephirah contains the Significator",
            "Only the Significator's suit",
            "Only the Moon phase",
            "The card at the bottom of the deck",
        ],
        (
            "ootk",
            "5",
        ),
    )

    add(
        "ootk-pairing",
        "Opening of the Key",
        (
            "After the counting sequence, "
            "how are horseshoe cards read?"
        ),
        "Pair opposite ends inward",
        [
            "Pair opposite ends inward",
            "Shuffle them again",
            "Read only Major Arcana",
            "Read every third card",
        ],
        (
            "ootk",
            "counting",
        ),
    )

    return result


class Progress:
    def __init__(self, path=None):
        self.path = (
            Path(path)
            if path
            else Path(
                config.path(
                    "hermetic_study",
                    "progress.json",
                )
            )
        )

        self.records = {}

        if self.path.exists():
            data = json.loads(
                self.path.read_text(
                    encoding="utf-8"
                )
            )

            if (
                not isinstance(data, dict)
                or data.get("version") != 1
                or not isinstance(
                    data.get("records"),
                    dict,
                )
            ):
                raise ValueError(
                    "Unrecognized study progress "
                    "format; existing file was preserved"
                )

            for row in data["records"].values():
                if (
                    not isinstance(row, dict)
                    or any(
                        type(row.get(k)) is not int
                        or row[k] < 0
                        for k in (
                            "attempts",
                            "correct",
                            "streak",
                            "mistakes",
                        )
                    )
                ):
                    raise ValueError(
                        "Invalid study progress record; "
                        "existing file was preserved"
                    )

                if (
                    row["correct"] > row["attempts"]
                    or row["mistakes"]
                    != row["attempts"]
                    - row["correct"]
                ):
                    raise ValueError(
                        "Inconsistent study progress record"
                    )

                if datetime.fromisoformat(
                    row["due"]
                ).tzinfo is None:
                    raise ValueError(
                        "Review date must include "
                        "a timezone"
                    )

            self.records = data["records"]

    def record(
        self,
        question_id,
        correct,
        now=None,
    ):
        now = (
            now
            or datetime.now(timezone.utc)
        )

        updated = deepcopy(
            self.records
        )

        r = updated.setdefault(
            question_id,
            dict(
                attempts=0,
                correct=0,
                streak=0,
                mistakes=0,
            ),
        )

        r["attempts"] += 1
        r["correct"] += int(correct)
        r["mistakes"] += int(not correct)

        r["streak"] = (
            r["streak"] + 1
            if correct
            else 0
        )

        if correct:
            delay = timedelta(
                days=min(
                    30,
                    2 ** min(
                        r["streak"] - 1,
                        5,
                    ),
                )
            )
        else:
            delay = timedelta(
                minutes=10
            )

        r["due"] = (
            now + delay
        ).isoformat()

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temp_name = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                delete=False,
            ) as f:
                temp_name = f.name

                json.dump(
                    dict(
                        version=1,
                        records=updated,
                    ),
                    f,
                    indent=2,
                )

                f.flush()
                os.fsync(
                    f.fileno()
                )

            os.replace(
                temp_name,
                self.path,
            )

        finally:
            if (
                temp_name
                and os.path.exists(
                    temp_name
                )
            ):
                os.unlink(
                    temp_name
                )

        self.records = updated

    def choose(
        self,
        questions,
        now=None,
        exclude=None,
    ):
        now = (
            now
            or datetime.now(timezone.utc)
        )

        pool = [
            q
            for q in questions
            if q.id != exclude
        ] or list(questions)

        due = [
            q
            for q in pool
            if (
                q.id in self.records
                and datetime.fromisoformat(
                    self.records[
                        q.id
                    ]["due"]
                )
                <= now
            )
        ]

        unseen = [
            q
            for q in pool
            if q.id not in self.records
        ]

        if due:
            return min(
                due,
                key=lambda q: self.records[
                    q.id
                ]["due"],
            )

        return random.choice(
            unseen or pool
        )

    def summary(self):
        rows = list(
            self.records.values()
        )

        attempts = sum(
            r["attempts"]
            for r in rows
        )

        correct = sum(
            r["correct"]
            for r in rows
        )

        mastered = sum(
            r["streak"] >= 3
            for r in rows
        )

        return (
            attempts,
            correct,
            mastered,
        )