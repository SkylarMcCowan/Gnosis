# Golden Dawn / Thoth Tarot Study — milestone 1

Launch `./run_gui.sh` and select **Tarot Study** in the main navigation.
The panel works offline without Ollama. External source links open only when clicked.

Start on Dashboard, then select Tree of Life. Click a sphere or connecting line;
the selector provides the same access by keyboard. Selecting a Path highlights its
two endpoints. Polarity View emphasizes Severity on the left, Mercy on the right
and equilibrium in the Middle Pillar. The diagram is a conventional Golden Dawn
Tree; it does not silently substitute Crowley's later correspondences.

The Card Explorer contains 22 Majors and 40 numbered Minors (including Aces).
Search names, Thoth titles, Hebrew letters, Sephiroth or astrological attributions.
Follow links between cards, Paths, Sephiroth and suits. Each card has a stepwise
“Derive this card” lesson. Suggested syntheses are original teaching interpretations,
not historical quotations or scientifically established explanations. Turn off basic
explanations or change disclosure depth for more traditional study.

Study / Quizzes includes correspondence, Path, element, Tree-placement and basic
derivation questions. Answer before opening the reference. Progress includes accuracy,
per-question mistakes, consecutive correct answers and due dates. A correct answer is
scheduled in 1, 2, 4, 8, 16, then 30 days; a mistake resets the streak and schedules a
10-minute review. Three consecutive correct answers count as provisional mastery,
not proof of interpretive skill. Due items precede unseen items; otherwise the user
can practice early. Progress is saved atomically to `hermetic_study/progress.json`
under `core.config.project_root()`. A malformed file is preserved and the panel
explicitly offers unsaved practice. Failed saves are reported without replacing
previous progress.

## Source distinctions

- Golden Dawn-derived baseline: *Book T* material as published in
  [Liber LXXVIII, The Equinox I:8 (1912)](https://sacred-texts.com/oto/lib78.htm).
- Hermetic correspondence tables: [Liber 777](https://www.tarrdaniel.com/documents/Thelemagick/publication/english/Liber_DCCLXXVII.html),
  a Crowley compilation containing inherited and expanded material.
- Crowley/Harris's *The Book of Thoth* (1944): separately labeled titles, imagery
  descriptions and interpretive changes. No deck images are bundled.
- Modern teaching synthesis: explicitly labeled prompts and explanatory prose.
- Torrens: a reserved source category, with no unsupported claims assigned to it.

The Emperor/Star comparison records Crowley's changed letters while retaining
Aries/Aquarius from the individual card essays. Reconciling the essays, appendix
tables and Tree placement is disputed; no automatic “Thoth Tree” is inferred.
Strength/Justice numerals vary between published witnesses: the letter, sign and
Path identify the baseline reliably. Celestial spheres are symbolic categories:
Kether is not Neptune, Chokmah is not Uranus, and Malkuth is not a classical planet.
Divine/angelic names use normalized transliterations; editions and world conventions
vary. Hermetic Qabalah is not presented as the whole of Jewish Kabbalah.

## Architecture and correction workflow

- `hermetic_study/data/*.json`: linked records with stable IDs, sources and versions.
  All ten Sephiroth, twenty-two Paths, twenty-two Majors, forty numbered Minors and
  four suits are separate collections. Path IDs are 11–32, never trump numerals.
- `model.py`: catalog validation, correspondence links, derivation and HTML views;
  independent of Qt and the chat runtime.
- `study.py`: question generation and versioned local progress; independent of Qt.
- `widget.py`: navigation, graph interaction, explorer and quiz controls.
- `tests/test_hermetic_study.py`: reference anchors, mapping integrity, mouse and
  navigation behavior, search, disclosure, persistence and failure handling.

To correct a correspondence, edit the appropriate JSON record and its source/version
metadata, add a regression assertion for the historical distinction, and run:

```sh
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m pytest tests/test_hermetic_study.py tests/test_tarot.py -q
```

Preserve IDs when wording changes so review history remains connected. New source
records should include tradition, edition, locator and uncertainty notes; never
silently merge competing versions. A future schema migration must explicitly handle
stored progress when identifiers change.

## Deliberately deferred

The navigation labels Court Cards, Astrology & Decans, Elemental Dignities,
Spreads & Divination and Opening of the Key as **Planned**. These are curriculum
previews, not working modules. Future iterations also include Tree reading mode,
manual daily derivation sessions, personal notes and a reading journal. Opening of
the Key must become a guided multi-operation procedure, not a generic 15-card layout.
Later entities can use additional JSON collections linked by stable card/source IDs;
readings and notes should be separate user stores, not edits to the reference catalog.

The existing `/tarot` command remains the existing reading feature; this panel does
not change its behavior or claim it is an Opening of the Key implementation.
