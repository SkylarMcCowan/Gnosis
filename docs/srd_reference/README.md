# D&D 3.5 SRD — Local Reference Corpus

Local, offline copy of the D&D 3.5 System Reference Document (Open Game
Content under the Open Game License v1.0a — see [LICENSE.md](LICENSE.md)).
Imported so Gnosis Crawler tickets that need exact rules text (data files
under a future `data/` directory, the alignment/deity compliance engine,
etc.) can grep a local file instead of doing a web request per lookup —
several live SRD mirrors (d20srd.org, Fandom) block automated fetches
outright, which is what prompted pulling this in as a static copy.

## Provenance

Sourced from the [katekorsaro/dnd3.5e-srd](https://github.com/katekorsaro/dnd3.5e-srd)
GitHub repo, which itself converts the original SRD RTF files distributed
by Wizards of the Coast (mirrored at
[archive.org/details/dnd35srd](https://archive.org/details/dnd35srd)) to
Markdown via Pandoc. Not modified further here beyond the copy itself.

See [SOURCED.md](SOURCED.md) for a full inventory of what's here (short
version: essentially the whole core SRD — PHB, DMG, and MM content —
plus Epic Level Handbook and Expanded Psionics Handbook material) and
[SOURCING_GUIDE.md](SOURCING_GUIDE.md) for how to pull in more if a
future ticket needs something not covered yet.

## Structure

- **`core/`** — the finished, hand-cleaned chapters (source repo's
  `04.done/`): Abilities & Conditions, Basics, Classes I/II, Combat I/II,
  Description, Equipment, Feats, Magic Items I–VI, Magic Overview, Races,
  Skills I/II. Highest confidence — use these first.
- **`extra/`** — raw Pandoc conversions, work-in-progress formatting
  (source repo's `02.conversion/` + `03.formatting/`): monsters, spells,
  spell lists, epic content, prestige-class-adjacent material, divine
  ranks/domains, carrying/exploration. Usable but not hand-verified —
  cross-check anything pulled from here against a second source before
  encoding it into a data file, the way `core/` material doesn't
  strictly need.
- **`LICENSE.md`** — full verbatim Open Game License v1.0a text,
  required to accompany any distribution of this content per the
  license's own Section 10 ("You MUST include a copy of this License
  with every copy of the Open Game Content You Distribute").

## Where this feeds into the project

[gnosis_crawler_alignment.md](../gnosis_crawler_alignment.md) already
quotes the exact `core/ClassesI.md` / `ClassesII.md` text for the
Paladin/Cleric/Druid/Monk/Barbarian alignment rules — that's ticket
GC-041 in [the backlog](../gnosis_crawler_backlog.md), done. Later
tickets pulling class tables, feats, spells, equipment, or monster stat
blocks into `data/*.json` should cite the specific `core/` or `extra/`
file and section they came from, the same way.

## License notice (OGL Section 15, reproduced as required)

> Open Game License v 1.0a Copyright 2000, Wizards of the Coast, Inc.
>
> System Reference Document Copyright 2000-2003, Wizards of the Coast,
> Inc.; Authors Jonathan Tweet, Monte Cook, Skip Williams, Rich Baker,
> Andy Collins, David Noonan, Rich Redman, Bruce R. Cordell, John D.
> Rateliff, Thomas Reid, James Wyatt, based on original material by E.
> Gary Gygax and Dave Arneson.

Everything in `core/` and `extra/` is Open Game Content under that
license, with the Product Identity exclusions listed in `extra/Legal.md`
(proper nouns like specific deity/plane names, "Dungeons & Dragons," the
Underdark, etc.) — those excluded names are not to be used verbatim in
Gnosis Crawler's own content (Section 4 of the main design doc already
calls this out).
