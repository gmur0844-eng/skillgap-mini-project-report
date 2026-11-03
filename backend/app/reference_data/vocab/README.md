Discipline-scoped vocabulary files. Each JSON file may contain
`"abbreviations": {...}`, `"synonym_groups": [[...]]` and
`"_applies_to_disciplines": [<discipline-slug>, ...]`. An empty or missing
`_applies_to_disciplines` means the file is discipline-neutral (applies
everywhere). Files here are data; adding one never requires a code change.
