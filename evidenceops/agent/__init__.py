"""Tool-using incident investigator.

``loop.investigate`` drives any model that speaks the ``Model`` protocol:

- ``claude.ClaudeModel`` calls the Claude API (needs ``ANTHROPIC_API_KEY``).
- ``offline.OfflinePolicy`` is a deterministic stand-in that picks tools by
  rule, so the loop, citation checks and grading can run without a key. Its
  scores are not the model's scores.
"""
