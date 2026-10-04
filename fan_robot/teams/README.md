# Team packs

One folder per club. Copy `example_en/` (English) or `trabzonspor/` (Turkish), rename the folder,
edit the files, and choose the team on the app's settings page. Your own packs can also live in
`~/fan_robot/teams/<id>/` on the robot (they survive app updates and win over bundled ones).

| File | What |
|---|---|
| `team.yaml` | name, nicknames, colours, language, rivals, ids for the live score feed |
| `phrases.yaml` | short spoken lines for each fan moment, in the team's language (several per moment; one is picked at random) |
| `jokes.yaml` | friendly jokes. Rule: banter yes, insults no (no people, cities, ethnicity, religion, violence, betting) |

Facts in `team.yaml` must be checkable: add a source comment. Club history goes in `knowledge/`
later, with a `[src: ...]` tag on every fact.
