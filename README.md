# Provenance Guard

A backend API for AI content attribution on creative writing platforms. Classifies
submitted text as likely-human or likely-AI, scores confidence honestly, surfaces a
transparency label to readers, and provides an appeals path for creators.

---

## Quickstart

```bash
git clone https://github.com/<you>/ai201-project4-provenance-guard
cd ai201-project4-provenance-guard

python -m venv .venv
source .venv/bin/activate          # Mac/Linux

pip install -r requirements.txt

cp .env.example .env
# Add your GROQ_API_KEY to .env

python app.py                      # starts on http://localhost:5000
```

To pre-populate the audit log with sample entries (no Groq key required):

```bash
python seed_db.py
```

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/submit` | Submit text for attribution analysis |
| POST | `/appeal` | Contest a classification |
| GET | `/log` | View audit log entries |
| GET | `/health` | Health check |

---

## POST /submit

**Request:**
```json
{
  "content": "The rain fell softly on the old tin roof...",
  "content_id": "poem-001",      // optional; auto-generated if omitted
  "creator_id": "user_alice"     // optional
}
```

**Response:**
```json
{
  "content_id": "poem-001",
  "verdict": "human",
  "confidence": 0.18,
  "signals": {
    "llm": {
      "verdict": "human",
      "ai_probability": 0.15,
      "reasoning": "Text shows high sentence-length variability and idiosyncratic punctuation use.",
      "weight": 0.6
    },
    "stylometric": {
      "ai_probability": 0.22,
      "sub_metrics": {
        "sentence_length_variance": 0.81,
        "type_token_ratio": 0.74,
        "punctuation_density": 0.62,
        "avg_sentence_length": 0.70,
        "paragraph_length_variance": 0.55,
        "unique_bigram_ratio": 0.80
      },
      "weight": 0.4
    }
  },
  "label": {
    "variant": "high_human",
    "headline": "Likely Human-Written",
    "body": "Our system is 82% confident this content was written by a human...",
    "call_to_action": null,
    "display_badge": "Human-Written"
  },
  "appeal_endpoint": "/appeal"
}
```

---

## Detection Signals

### Signal 1 — LLM Semantic Judge (Groq / llama-3.3-70b-versatile)

Asks the model to holistically assess whether text reads as human or AI-generated.
Captures semantic coherence, tonal uniformity, hedging language patterns, structural
predictability, and absence of personal idiosyncrasy — things that are hard to quantify
but a language model reads naturally.

The model returns a verdict and confidence. The prompt explicitly instructs it to prefer
"uncertain" when evidence is mixed, honouring the false-positive asymmetry requirement.

**Weight: 0.60** (primary signal)

### Signal 2 — Stylometric Heuristics (pure Python)

Computes six statistical properties of the text:

| Sub-metric | What it captures |
|---|---|
| Sentence-length variance | AI text has uniform sentence lengths; human writing varies |
| Type-token ratio (TTR) | AI text has slightly lower vocabulary diversity |
| Punctuation density | AI text under-uses commas, dashes, semicolons |
| Average sentence length | AI text skews longer |
| Paragraph length variance | AI text produces uniform-length paragraphs |
| Unique bigram ratio | AI text reuses phrase patterns more frequently |

Each sub-metric produces a [0,1] human-likeness score; the signal's AI probability is
`1 − mean(sub_metrics)`.

**Weight: 0.40** (supporting signal — structurally independent of Signal 1)

These two signals are **genuinely independent**: LLM analysis is semantic/pragmatic;
stylometric analysis is purely statistical/structural. Combining them is more
informative than either alone.

---

## Confidence Scoring & Uncertainty

The raw blended score:

```
blend = 0.75 × llm_ai_prob + 0.25 × stylo_ai_prob
```

**Asymmetry bias:** A false positive (calling human work AI) is worse than a false
negative on a creative platform. When the blend lands in [0.40, 0.65] — the genuine
gray zone — it is nudged further toward uncertain:

```python
if 0.40 <= blend <= 0.65:
    final = blend * 0.90
```

**Thresholds** (asymmetric — require stronger evidence to call something AI):

| Range | Label |
|---|---|
| ≥ 0.68 | HIGH-CONFIDENCE AI |
| ≤ 0.28 | HIGH-CONFIDENCE HUMAN |
| 0.29 – 0.67 | UNCERTAIN |

A score of 0.51 produces an UNCERTAIN label; a score of 0.80 produces a HIGH-CONFIDENCE
AI label — they are meaningfully different both in label text and in call-to-action.

**M4 calibration:** Original weights were 0.60/0.40 with HIGH_AI threshold 0.72. Live
testing on 4 calibration inputs showed that a clearly AI-generated 3-sentence paragraph
(LLM=0.80, stylo=0.32) blended to 0.548 — uncertain — because stylometric TTR and
bigram sub-metrics saturate at 1.0 for short texts. Weights adjusted to 0.75/0.25 and
threshold to 0.68. Post-fix results across all 4 inputs:

| Input | LLM | Stylo | Blend | Label |
|---|---|---|---|---|
| Clear AI (3 sentences) | 0.80 | 0.32 | 0.68 | HIGH_AI |
| Clear human (casual) | 0.05 | 0.27 | 0.10 | HIGH_HUMAN |
| Borderline: formal human | 0.65 | 0.35 | 0.52 | UNCERTAIN |
| Borderline: edited AI | 0.55 | 0.30 | 0.44 | UNCERTAIN |

---

## Transparency Labels

The label displayed to readers on the platform has three variants. **Exact text below:**

### High-Confidence AI (`confidence ≥ 0.72`)

> **Headline:** Likely AI-Generated
>
> **Body:** Our system is {N}% confident this content was generated by an AI tool, not
> written by a human. This assessment is based on semantic and structural analysis and
> may not be perfect.
>
> **Call to action:** If you are the creator and believe this is incorrect, you can
> submit an appeal — we review every one.
>
> **Badge:** AI-Generated

### High-Confidence Human (`confidence ≤ 0.28`)

> **Headline:** Likely Human-Written
>
> **Body:** Our system is {N}% confident this content was written by a human. It shows
> the kind of stylistic variability and personal voice that characterizes original human
> creativity.
>
> **Call to action:** *(none — no need to prompt the creator)*
>
> **Badge:** Human-Written

### Uncertain (`confidence 0.29 – 0.71`)

> **Headline:** Origin Uncertain
>
> **Body:** Our system could not confidently determine whether this content was written
> by a human or generated by AI. This may reflect a mix of approaches, an unusually
> polished human voice, or limitations of our analysis.
>
> **Call to action:** If you are the creator, you may submit additional context through
> an appeal to help clarify attribution.
>
> **Badge:** Origin Uncertain

---

## Appeals Workflow

1. Creator calls `POST /appeal` with their `content_id` and `reason`.
2. The system validates the submission exists.
3. The appeal (including creator's reasoning) is logged as a new `audit_log` entry
   linked to the original decision.
4. The submission's status is updated to `under_review` in the database.
5. The creator receives confirmation and an estimated review timeline.
6. A human moderator reviews the audit trail (automated re-classification is out of
   scope — see planning.md).

**Request:**
```json
{
  "content_id": "flash-019",
  "creator_id": "user_dan",
  "reason": "I wrote this story entirely myself over three evenings..."
}
```

**Response:**
```json
{
  "message": "Your appeal has been received and logged. A human reviewer will assess the original decision and your reasoning.",
  "content_id": "flash-019",
  "status": "under_review",
  "next_steps": "Appeals are reviewed within 5 business days."
}
```

---

## Rate Limiting

Implemented via Flask-Limiter (in-memory store).

| Endpoint | Limit | Rationale |
|---|---|---|
| `POST /submit` | 10/min · 50/hr · 100/day | A typical creator submits work occasionally, not dozens of times per hour. 10/min prevents burst API flooding while giving any individual creator comfortable headroom. 100/day is generous for a single user but makes it impractical to scrape the system at scale. |
| `POST /appeal` | 5/hr | Appeals are deliberate, not automated actions. 5/hr prevents appeal-flooding while giving a creator who genuinely has multiple pieces under review room to act. |
| `GET /log` | 30/min | Read-only endpoint; higher limit is fine. Still rate-limited to prevent log-scraping bots. |

The adversarial model for `/submit`: an actor trying to probe the classifier's decision
boundary would need to make hundreds of requests. At 100/day per IP, that requires many
IPs, which raises the cost of abuse. A legitimate creator submitting one piece of work
per sitting never hits any limit.

---

## Audit Log

Every attribution decision and appeal is written to SQLite (`provenance.db`).

**Schema:**
```
audit_log
  id            INTEGER PRIMARY KEY
  event_id      TEXT UNIQUE        -- UUID
  event_type    TEXT               -- "decision" | "appeal"
  content_id    TEXT
  creator_id    TEXT
  timestamp     TEXT               -- ISO-8601 UTC
  verdict       TEXT               -- "ai" | "human" | "uncertain"
  confidence    REAL
  llm_score     REAL               -- P(AI) from LLM signal
  stylo_score   REAL               -- P(AI) from stylometric signal
  label_variant TEXT               -- "high_ai" | "high_human" | "uncertain"
  appeal_reason TEXT               -- null for decisions
  status        TEXT               -- "decided" | "under_review"
```

**Sample entries** (run `python seed_db.py` then `GET /log` to see these):

```json
[
  {
    "event_id": "a1b2c3d4-...",
    "event_type": "decision",
    "content_id": "poem-001",
    "creator_id": "user_alice",
    "timestamp": "2026-06-24T10:00:00+00:00",
    "verdict": "human",
    "confidence": 0.18,
    "llm_score": 0.15,
    "stylo_score": 0.22,
    "label_variant": "high_human",
    "appeal_reason": null,
    "status": "decided"
  },
  {
    "event_id": "b2c3d4e5-...",
    "event_type": "decision",
    "content_id": "story-007",
    "creator_id": "user_bob",
    "timestamp": "2026-06-25T14:30:00+00:00",
    "verdict": "ai",
    "confidence": 0.84,
    "llm_score": 0.88,
    "stylo_score": 0.77,
    "label_variant": "high_ai",
    "appeal_reason": null,
    "status": "decided"
  },
  {
    "event_id": "c3d4e5f6-...",
    "event_type": "decision",
    "content_id": "essay-042",
    "creator_id": "user_carol",
    "timestamp": "2026-06-26T09:15:00+00:00",
    "verdict": "uncertain",
    "confidence": 0.51,
    "llm_score": 0.60,
    "stylo_score": 0.35,
    "label_variant": "uncertain",
    "appeal_reason": null,
    "status": "decided"
  },
  {
    "event_id": "d4e5f6a7-...",
    "event_type": "decision",
    "content_id": "flash-019",
    "creator_id": "user_dan",
    "timestamp": "2026-06-26T11:00:00+00:00",
    "verdict": "ai",
    "confidence": 0.79,
    "llm_score": 0.82,
    "stylo_score": 0.73,
    "label_variant": "high_ai",
    "appeal_reason": null,
    "status": "under_review"
  },
  {
    "event_id": "e5f6a7b8-...",
    "event_type": "appeal",
    "content_id": "flash-019",
    "creator_id": "user_dan",
    "timestamp": "2026-06-26T11:45:00+00:00",
    "verdict": null,
    "confidence": null,
    "llm_score": null,
    "stylo_score": null,
    "label_variant": null,
    "appeal_reason": "I wrote this story entirely myself over three evenings. I sometimes write in a clean, structured style which may have triggered the AI classifier. I can provide my draft history.",
    "status": "under_review"
  }
]
```

---

## Project Structure

```
ai201-project4-provenance-guard/
├── app.py              # Flask API — all routes, signals, scoring, labels
├── seed_db.py          # Populate DB with sample audit entries
├── planning.md         # Architecture design, signal rationale, ADRs
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Known Edge Cases

**Short submissions (< 3 sentences).** Observed in live testing: a two-sentence
passage — *"The sun dipped below the horizon, painting the sky in hues of amber and
rose. I sat on the porch, coffee in hand, watching the neighborhood slowly go quiet."*
— scored `confidence: 0.29` and received an UNCERTAIN label despite the LLM signal
correctly reading it as human (`ai_probability: 0.20`). The stylometric signal scored
it at `0.42` because two sentences produce near-zero sentence-length variance (no
variance to measure) and no paragraph breaks, inflating the AI-probability estimate.
The blend of `0.60×0.20 + 0.40×0.42 = 0.288` landed just above the high-human
threshold of 0.28. This is the expected behavior for very short texts — the system
defaults to uncertain rather than risk a false positive, and the stylometric signal
explicitly degrades to neutral for texts under 20 words.

**Formally written human prose.** Academic or technical writing with uniform sentence
structure will trend AI-like on the stylometric signal. The asymmetric threshold (0.72
to trigger a high-AI label) and the bias zone pull these cases toward uncertain.

**Lightly edited AI output.** A few human edits injecting idiosyncrasy can confuse
both signals enough to produce an uncertain result. The system acknowledges this in
the uncertain label body ("may reflect a mix of approaches").

---

## Design Decisions

**Why asymmetric thresholds?**
On a creative platform, being falsely accused of using AI is a reputational harm.
The system requires a higher P(AI) score (0.72) to issue a high-confidence AI label
than the mirror score needed for a high-confidence human label (0.28). The gray zone
is intentionally wide.

**Why SQLite?**
Zero-dependency, ships with Python, perfectly adequate for the scale of a portfolio
project. Swap for Postgres in production by changing `DB_PATH` and connection handling.

**Why not a third signal?**
Two genuinely independent signals (semantic + structural) were prioritized over three
weakly-independent ones. The LLM signal already aggregates many semantic sub-signals
internally. Adding a third heuristic (e.g., perplexity) would increase complexity
without meaningfully changing calibration.
