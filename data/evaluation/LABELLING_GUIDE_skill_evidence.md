# Labelling guide: skill evidence in job postings

Each item is one phrase found in one job posting, with its sentence and some surrounding text, plus the job title
and company. Judge **this occurrence**, in this context. Do not judge the phrase in general.

For each item, write one JSON line with these fields:

```json
{"item_id": "...", "label": "...", "is_skill_sense": true, "evidence_role": "...", "strength": "...", "note": "..."}
```

## `label`

- `DEMAND_EVIDENCE`: this occurrence tells us that the job needs this skill or knowledge. That includes:
  - requirements, preferred qualifications and listed skills;
  - tools or technologies the job holder will work with;
  - tasks the job holder will perform that require the skill (for example, "you will lead a team of engineers"
    is evidence of a team-leadership competence);
  - education requirements naming a field.
- `NOT_DEMAND_EVIDENCE`: this occurrence does not tell us that the job needs it. That includes:
  - company descriptions and marketing text;
  - equal-opportunity or legal text;
  - benefits;
  - social-media links;
  - descriptions of what the company or its customers do, rather than what the job holder does;
  - the word used in a sense that is not a skill (for example "from scratch", "a sales lead", "it");
  - generic phrasing that names no real skill.

## `is_skill_sense`

`true` if the phrase is used here in a sense that denotes a skill, knowledge area, tool or competence; `false`
otherwise. This is independent of `label`: a skill named in a company description has `is_skill_sense: true` and
`label: NOT_DEMAND_EVIDENCE`.

## `evidence_role`

The role of the sentence or section in the posting. One of:

`REQUIRED`, `PREFERRED`, `SKILLS_LIST`, `RESPONSIBILITY`, `EDUCATION`, `COMPANY_DESCRIPTION`, `LEGAL_EEO`,
`BENEFITS`, `SOCIAL_LINKS`, `OTHER`.

## `strength`

How strongly this occurrence shows demand. One of:

| Value | Meaning | Examples |
|---|---|---|
| `STRONG` | an explicit requirement or listed required skill | "Required: X", "must have X", "X skills" in requirements |
| `MEDIUM` | experience asked for, or a task the job holder performs that needs the skill | |
| `WEAK` | optional or preferred | "X is a plus", "nice to have X" |
| `NONE` | not evidence | |

## `note`

A few words. Optional.

## Rules

- Judge only from the text given. Do not guess what the system does.
- When genuinely unsure, choose the label you find more likely and say so in `note`.
