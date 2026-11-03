"""
The assistant: a conversational agent over the analysis data, with syllabus drafting.

  llm.py       local chat model (Ollama): native tool calling, or a JSON protocol for models without it
  tools.py     what the agent may do: read the analysis (no confirmation), start analyses (confirmed by the user),
               draft syllabi
  syllabus.py  grounded drafting: an evidence pack from the run, the model writes, code checks every citation
  agent.py     the loop: model -> tool calls -> results -> answer; figures in an answer are checked against the
               tool results
  store.py     conversations and drafts on disk (data/assistant/, git-ignored)

Nothing the assistant writes is an analysis result. Drafts are labelled as model-written and must be reviewed by
faculty; the analysis pipeline never reads them.
"""
