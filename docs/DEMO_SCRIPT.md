# Hackathon demonstration script (8 minutes)

1. **Frame the problem (30 sec):** “The code tells us what changed. Watermelon tries to preserve why. A model interpretation is only useful when its source can be opened.”
2. **Show public source setup (45 sec):** Open Projects and Integrations. Connect a public repository with a small, selected issue/PR sample. Explain that a connected source does not imply a successful model extraction.
3. **Show ingestion (60 sec):** Open the job timeline. Point out real job status, processed counts, partial failures, and extraction blockers. State when a model result is illustrative or unavailable.
4. **Open a decision (60 sec):** Show status, version history, alternative, exact source excerpt, and the original GitHub/Discourse link. Click through to the source and explain that source provenance and claim support are separately checked.
5. **Explore code (45 sec):** Open a file/symbol relationship, label verified vs inferred/stale, then search for a historical issue/PR. Describe search score as a retrieval rank, not probability.
6. **Ask Watermelon (60 sec):** Ask a question with known evidence. Show answer and backend-resolved source links. Ask an unrelated question and show abstention if no evidence. If OpenRouter/Redis are not configured, show the explicit integration state instead of pretending it ran.
7. **PR Intelligence (60 sec):** Open a controlled public PR and analyze its current head. Show that weak evidence stays silent, findings cite a current decision/source, and publication is preview-only unless an authorized GitHub App is installed.
8. **Alternative Explorer (45 sec):** Enter the objective, compare approaches, identify any repeated rejected approach, and point out “unvalidated” labels. Do not imply patches or tests ran.
9. **Evaluation and trust (60 sec):** Show the blind PEP benchmark split, hashes, rubric, and status. Only show actual scores if a frozen model run and independent human adjudication exists. Explain pretraining exposure limits.
10. **Close (30 sec):** “The trust boundary is part of the product: original records are preserved, uncertainty is visible, and unsupported memory stays quiet.”

Use the current [verification matrix](VERIFICATION.md) to distinguish live capabilities from tested mocks and unavailable integrations during the demo.
