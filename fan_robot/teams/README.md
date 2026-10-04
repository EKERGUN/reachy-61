# Team packs

One folder per club. Copy `example_en/` (English) or `trabzonspor/` (Turkish), rename the folder,
edit the files, and choose the team on the app's settings page. Your own packs can also live in
`~/fan_robot/teams/<id>/` on the robot (they survive app updates and win over bundled ones).

| File | What |
|---|---|
| `team.yaml` | name, nicknames, colours, language, rivals, ids for the live score feed |
| `phrases.yaml` | short spoken lines for each fan moment, in the team's language (several per moment; one is picked at random) |
| `jokes.yaml` | friendly jokes. Rule: banter yes, insults no (no people, cities, ethnicity, religion, violence, betting). Plain text is split before the last line of dialogue for the pause; or give `setup` and `punchline` |
| `quiz.yaml` | quiz questions: `q`, 2-4 `options`, `answer` (index or a-d), `difficulty` 1-3, `explain`, **`source` (required)** |
| `knowledge.yaml` | club facts for the chat: `fact`, `topic`, **`source` (required)** |

Import facts and questions from a spreadsheet (CSV or Excel) instead of typing YAML:

    python scripts/import_dataset.py --team trabzonspor --facts facts.csv --quiz quiz.xlsx

Rows without a source URL are skipped and listed. Facts in `team.yaml` must be checkable too:
add a source comment.

Clips (music, match recordings, chants) are NOT part of a pack: each user uploads their own on
the remote's Settings tab (with an optional CSV: `file, type, mood, title, when`). They stay on
the robot in `~/fan_robot/media/<team>/` and are never published.
