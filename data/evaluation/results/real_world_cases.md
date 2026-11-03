# Ten real-world cases (run `438ec2c0d5182dd4`)

Each case is selected by the stated rule from GOLD outputs; nothing is hand-picked by name.

## 1. Same concept with different wording
*Selection:* no SAME_CONCEPT topic mapping differs in words; first established ESCO alias match in postings instead · *Evidence class:* **NORMALIZED (taxonomy alias, sense established)**

```json
{
 "text": "agile development environment",
 "esco_concept": "Agile development",
 "sense_state": "ESTABLISHED_BY_CONTEXT",
 "sense_evidence": {
  "other_labels_of_concept_in_text": [
   "agile development"
  ]
 },
 "note": "all 53 SAME_CONCEPT curriculum mappings have identical word sets (spacing/quote differences only)"
}
```

## 2. Parent / child
*Selection:* first explicit 'Head: items' subtopic group; first PARENT reference mapping · *Evidence class:* **EXTRACTED + MODEL_SUGGESTED**

```json
{
 "explicit_hierarchy": [
  {
   "parent": "Synthesis Routes",
   "child": "Bottom-up approaches – PVD",
   "page": 223,
   "source_line": "Synthesis Routes: Bottom-up approaches – PVD, CVD, sol-gel process, wet chemical synthesis and"
  },
  {
   "parent": "Synthesis Routes",
   "child": "wet chemical synthesis and",
   "page": 223,
   "source_line": "Synthesis Routes: Bottom-up approaches – PVD, CVD, sol-gel process, wet chemical synthesis and"
  },
  {
   "parent": "Synthesis Routes",
   "child": "sol-gel process",
   "page": 223,
   "source_line": "Synthesis Routes: Bottom-up approaches – PVD, CVD, sol-gel process, wet chemical synthesis and"
  },
  {
   "parent": "Synthesis Routes",
   "child": "CVD",
   "page": 223,
   "source_line": "Synthesis Routes: Bottom-up approaches – PVD, CVD, sol-gel process, wet chemical synthesis and"
  }
 ],
 "reference_mapping_parent": {
  "target_topic": "methods",
  "reference_topic": "methods and objects",
  "relationship": "PARENT (target broader than reference)"
 }
}
```

## 3. Context-dependent word
*Selection:* most frequent posting surface held back by the label evidence rule · *Evidence class:* **INSUFFICIENT_EVIDENCE**

```json
{
 "surface": "communication",
 "postings_with_text": 55,
 "status": "INSUFFICIENT_EVIDENCE",
 "reason": "LABEL_CONTEXT_DEPENDENT: single ordinary word: the text match does not establish the skill sense",
 "contexts": [
  ".\n\n**Required Skills:-**\n\n- Intermediate in MS Excel\n- Good Communication Skills\n\n**Experience:-**\n\n1 or more years of relevant exper",
  "ly, write sharp and engaging copy, and translate ideas into communication across different platforms.\n\nKey Responsibilities\n\n\\\\* Deve",
  "rong knowledge of lithium-ion battery products\n\n• Excellent communication and negotiation skills\n\n• Ability to build dealer and OEM r"
 ],
 "esco_candidates": [
  "communication"
 ]
}
```

## 4. ESCO alias ambiguity
*Selection:* surface with the most ALIAS_SENSE_REVIEW_REQUIRED posting mentions · *Evidence class:* **REVIEW_REQUIRED**

```json
{
 "surface": "IT",
 "mentions_under_review": 14,
 "taxonomy_fact": "'IT' is an English ESCO altLabel of 'computer technology' (full ESCO v1.2.1 classification)",
 "context": "ms including Sales, Product Development, Technical Support, IT, Global Headquarters, and Channel Partners.\n- Strong analyt",
 "question": "Does this occurrence of 'IT' refer to the ESCO concept 'computer technology'?",
 "adjudication": {
  "relationship": "AMBIGUOUS",
  "decision_state": "RULE_VERDICT_NO_MODEL",
  "provider": "deterministic_fallback",
  "uncertainty": "AI_PROVIDER_UNAVAILABLE: no language model was available; this is the rule verdict"
 }
}
```

## 5. Academic concept without ESCO match
*Selection:* highest-support concept none of whose topics has an ESCO-mapped mention · *Evidence class:* **DISCOVERED (concept) + ESCO_UNMAPPED**

```json
{
 "concept": "Linked List",
 "support": 11,
 "courses": [
  "22CSC05",
  "22ITC20N"
 ],
 "example_topics": [
  "Removal from a Doubly Linked List",
  "Linked lists",
  "Reversing a Linked List",
  "Insertion into a Doubly Linked List"
 ]
}
```

## 6. Industry skill with ESCO match
*Selection:* highest posting count among demand rows with that ESCO status · *Evidence class:* **FACT (counts) + REFERENCE_MAPPED / NORMALIZED**

```json
{
 "skill": "SQL",
 "esco_status": "EXACT",
 "esco_uri": "http://data.europa.eu/esco/skill/598de5b0-5b58-4ea7-8058-a4bc4d18c742",
 "posting_count": 5,
 "company_count": 5,
 "support_state": "SUPPORTED",
 "mapping_reason": "label match in the full ESCO v1.2.1 classification; prefLabel precedence over other concepts' alt/hidden labels",
 "closest_esco_candidates": [],
 "scope_warning": "These results describe the supplied job-posting dataset and are not necessarily representative of the entire labour market."
}
```

## 7. Industry skill without ESCO match
*Selection:* highest posting count among demand rows with that ESCO status · *Evidence class:* **FACT (counts) + REFERENCE_MAPPED / NORMALIZED**

```json
{
 "skill": "azure",
 "esco_status": "UNMAPPED",
 "esco_uri": null,
 "posting_count": 5,
 "company_count": 5,
 "support_state": "SUPPORTED",
 "mapping_reason": "the closest ESCO label contains the surface as a part of a longer name (RELATED, not the same concept); no label in the full ESCO v1.2.1 English classification matches this surface",
 "closest_esco_candidates": [
  [
   "Azure SQL Database",
   0.5036,
   "CONTAINED_IN_LONGER_LABEL"
  ],
  [
   "positioning of guardrails and toeboards",
   0.0,
   "OTHER"
  ],
  [
   "positioning guardrails and toeboards",
   0.0,
   "OTHER"
  ]
 ],
 "scope_warning": "These results describe the supplied job-posting dataset and are not necessarily representative of the entire labour market."
}
```

## 8. Curriculum topic with partial coverage
*Selection:* target coverage MENTION first, else INTRODUCTORY · *Evidence class:* **INFERRED_FROM_TEXT**

```json
{
 "skill": "ml",
 "coverage_level": "MENTION",
 "relation_counts": {
  "INCIDENTAL": 1,
  "RELATED": 1
 },
 "reason": "only RELATED/INCIDENTAL mentions (the skill qualifies another subject)",
 "evidence": [
  {
   "course_code": "22CSE26",
   "page": 183,
   "text": "Advanced Processing Feature Engineering Classical NLP/ML Pipeline",
   "relation": "RELATED"
  },
  {
   "course_code": "22ADO01",
   "page": 221,
   "text": "Influence of AI and ML in Clinical and Genomic Diagnostics",
   "relation": "INCIDENTAL"
  }
 ]
}
```

## 9. Concept across multiple courses
*Selection:* concept with the most distinct courses · *Evidence class:* **DISCOVERED (TF-IDF clustering)**

```json
{
 "concept": "Data types",
 "courses": [
  "22CSC03 Object Oriented Programming",
  "22CSC42 Web Programming",
  "22CSE28 Full Stack Development",
  "22CSO04N WEB PROGRAMMING WITH JAVASCRIPT",
  "22CSO05N FUNDAMENTALS OF JAVA PROGRAMMING",
  "22ITC02N Java Programming",
  "22ITC17 Web Technologies"
 ],
 "support": 8
}
```

## 10. Industry concept emerging over time
*Selection:* trend states of all demand skills · *Evidence class:* **INSUFFICIENT_EVIDENCE**

```json
{
 "trend_states": {
  "INSUFFICIENT_EVIDENCE": 115
 },
 "reason": "1 period(s) with {'2026-09': 100} postings; trends need >= 2 periods of >= 30 postings. No trend is produced and no recency weighting is applied.",
 "note": "no EMERGING claim is made: the supplied postings cover a single month"
}
```
