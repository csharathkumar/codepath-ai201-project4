# Provenance Guard — Planning

## Problem Statement

Creative platforms (writing, music, art) need a way to surface attribution context to
readers without policing creativity. Provenance Guard classifies submitted text as
likely-human or likely-AI, scores its confidence honestly, and gives creators a clear
path to contest any decision.

---

## Milestone 1: Architecture

### Architecture Narrative

Here is the complete path a single piece of text takes from the moment a creator
submits it to the moment a reader sees a label on it.

**Step 1 — Submission arrives at the API.**
A creator (or the platform on their behalf) sends a `POST /submit` request containing
the text, an optional content ID, and an optional creator ID. The Flask API receives it.
Before anything else, Flask-Limiter checks whether this IP address has exceeded the
rate limit. If so, it returns a 429 immediately. Otherwise, the request passes
validation (non-empty content, under 20,000 characters).

**Step 2 — Signal 1: LLM Semantic Judge.**
The raw text is sent to the Groq API (llama-3.3-70b-versatile). The model reads the
text holistically and returns a JSON object containing a verdict ("human", "ai", or
"uncertain") and a confidence value. The app converts this into a single number:
P(AI-generated), a probability between 0 and 1. This is the LLM signal score.

**Step 3 — Signal 2: Stylometric Heuristics.**
Simultaneously, the same raw text is passed to a pure-Python function that computes
six statistical properties of the text — sentence-length variance, type-token ratio,
punctuation density, average sentence length, paragraph-length variance, and unique
bigram ratio. Each sub-metric produces a score between 0 and 1 (1 = human-like).
Their mean is inverted to produce a P(AI-generated) stylometric signal score.

**Step 4 — Confidence Scorer blends the signals.**
The two signal scores are combined using a weighted average: 60% LLM, 40% stylometric.
If the blend lands in the gray zone [0.40, 0.65], an asymmetry bias nudges it slightly
downward — reflecting the design principle that false positives (calling human work AI)
are worse than false negatives on a creative platform. The result is a final confidence
score between 0 and 1.

**Step 5 — Transparency Label Generator selects a variant.**
The confidence score is compared against asymmetric thresholds (≥ 0.72 → high-AI,
≤ 0.28 → high-human, everything else → uncertain). The label generator constructs a
plain-language label object with a headline, a body explaining what the score means,
and — for AI or uncertain results — a call to action directing the creator to the
appeal endpoint.

**Step 6 — Audit Log records the decision.**
Before the response is sent, the full decision — content ID, creator ID, timestamp,
both raw signal scores, the blended confidence, the verdict, and the label variant —
is written as a structured row in the SQLite audit log. This is the permanent record
of what the system decided and why.

**Step 7 — Response is returned to the client.**
The API returns a JSON object containing the verdict, confidence score, the full signal
breakdown (so platforms can show their work), and the complete label object. The
platform displays the label to readers.

---

### Submission Flow Diagram

```
Creator / Platform
        │
        │  POST /submit
        │  { content: "...", content_id: "poem-001", creator_id: "alice" }
        ▼
┌───────────────────────────────────────────────────────────────────┐
│  Flask API                                                        │
│  ① Rate Limiter checks IP → 429 if exceeded                      │
│  ② Validates: non-empty, ≤ 20,000 chars                          │
└──────────────────────────┬────────────────────────────────────────┘
                           │ raw text (str)
              ┌────────────┴────────────┐
              │ raw text                │ raw text
              ▼                         ▼
   ┌─────────────────────┐   ┌──────────────────────────┐
   │  Signal 1           │   │  Signal 2                │
   │  LLM Semantic Judge │   │  Stylometric Heuristics  │
   │  (Groq API)         │   │  (pure Python)           │
   │                     │   │                          │
   │  → verdict          │   │  → 6 sub-metric scores   │
   │  → raw confidence   │   │  → mean → invert         │
   │  → convert to       │   │                          │
   │    P(AI)            │   │                          │
   └──────────┬──────────┘   └────────────┬─────────────┘
              │ llm_ai_prob (float)        │ stylo_ai_prob (float)
              └────────────┬──────────────┘
                           │ two P(AI) scores
                           ▼
              ┌────────────────────────┐
              │  Confidence Scorer     │
              │                        │
              │  blend = 0.60×llm      │
              │        + 0.40×stylo    │
              │                        │
              │  if 0.40≤blend≤0.65:   │
              │    final = blend×0.90  │
              │  (asymmetry bias)      │
              └────────────┬───────────┘
                           │ final confidence score (float)
              ┌────────────┴────────────┐
              │ final score             │ final score + both raw scores
              ▼                         ▼
   ┌──────────────────────┐   ┌─────────────────────────────┐
   │  Label Generator     │   │  SQLite Audit Log           │
   │                      │   │                             │
   │  score ≥ 0.72        │   │  Writes one row:            │
   │    → "high_ai"       │   │  event_id, content_id,      │
   │  score ≤ 0.28        │   │  creator_id, timestamp,     │
   │    → "high_human"    │   │  verdict, confidence,       │
   │  else                │   │  llm_score, stylo_score,    │
   │    → "uncertain"     │   │  label_variant, status      │
   │                      │   │                             │
   │  → label object      │   └─────────────────────────────┘
   │    {headline, body,  │
   │     cta, badge}      │
   └──────────┬───────────┘
              │ label object
              ▼
┌─────────────────────────────────────────────────────────────────┐
│  JSON Response                                                  │
│  { content_id, verdict, confidence, signals: {...}, label: {...} } │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
  Platform displays label to readers
```

---

### Appeal Flow Diagram

```
Creator
        │
        │  POST /appeal
        │  { content_id: "poem-001", creator_id: "alice",
        │    reason: "I wrote this myself — I can show my drafts." }
        ▼
┌───────────────────────────────────────────────────────────┐
│  Flask API                                                │
│  ① Rate Limiter checks IP → 429 if exceeded (5/hr)       │
│  ② Validates: content_id and reason present              │
└───────────────────────────┬───────────────────────────────┘
                            │ content_id
                            ▼
              ┌─────────────────────────┐
              │  SQLite: submissions    │
              │  lookup by content_id  │
              └──────────┬──────────────┘
                         │
            ┌────────────┴────────────┐
         not found               found
            │                        │
            ▼                        ▼
       404 response      ┌───────────────────────┐
                         │  Already under_review? │
                         └───────────┬───────────┘
                               ┌─────┴──────┐
                              yes            no
                               │             │
                               ▼             ▼
                         200 "already   ┌────────────────────────────┐
                         under review"  │  SQLite: submissions       │
                                        │  UPDATE status →           │
                                        │  'under_review'            │
                                        └────────────┬───────────────┘
                                                     │
                                                     ▼
                                        ┌────────────────────────────┐
                                        │  SQLite: audit_log         │
                                        │  INSERT new row:           │
                                        │  event_type = 'appeal'     │
                                        │  content_id, creator_id,   │
                                        │  timestamp, appeal_reason, │
                                        │  status = 'under_review'   │
                                        └────────────┬───────────────┘
                                                     │
                                                     ▼
                                        ┌────────────────────────────┐
                                        │  JSON Response             │
                                        │  { message, content_id,    │
                                        │    status, next_steps }    │
                                        └────────────────────────────┘
```

---

### Detection Signals

#### Signal 1 — LLM Semantic Judge (Groq / llama-3.3-70b-versatile)

**What property it measures:** Holistic semantic and stylistic coherence. The model
reads the text and assesses whether it "reads" as machine-generated — looking at things
like overuse of transitional phrases, hedging language ("it is important to note"),
uniform tonal register, perfectly balanced sentence structure, and absence of personal
idiosyncrasy (typos, unusual word choice, opinionated digressions).

**Why this property differs between human and AI writing:** Large language models are
trained to be helpful and clear — which inadvertently produces characteristic patterns.
They over-use connective tissue phrases ("Furthermore," "In conclusion,"), maintain
unnaturally consistent formality, and rarely contradict themselves mid-thought. Human
writers have bad habits, personality, and drift. An LLM reading this as a judge can
recognize its own family's fingerprints in ways statistical tools cannot.

**Blind spots:**
- A skilled human writer who deliberately writes in a clean, formal style (academic
  prose, technical writing) may score falsely as AI. This is the primary source of
  false positives.
- AI output that has been lightly edited by a human will confuse the signal — the edits
  inject idiosyncrasy, which the LLM may read as human.
- Very short texts (under ~50 words) don't give the model enough signal; it will
  default toward "uncertain."
- The model's own biases about what "AI writing looks like" are frozen at its training
  cutoff — newer AI systems that better mimic human variation will degrade this signal
  over time.
- The LLM is itself a black box — we can't fully explain *why* it reaches a verdict,
  which makes it hard to audit or contest specific decisions.

**Weight:** 0.60 (primary — richer, holistic assessment)

---

#### Signal 2 — Stylometric Heuristics (pure Python)

**What property it measures:** Measurable statistical properties of text that differ
between human and AI writing. Specifically: how *uniform* vs. *variable* the text is
across six dimensions — sentence length, vocabulary, punctuation, sentence complexity,
paragraph length, and phrase repetition. AI text is characteristically uniform; human
writing is characteristically variable.

**Why this property differs between human and AI writing:** Language models generate
text token-by-token optimizing for coherence, which produces statistically smoother
output than humans write. Humans have unconscious rhythmic habits that create
variance — a burst of short punchy sentences, then a long meandering one, then a
fragment. They over-use certain punctuation. They repeat their favorite words. This
variance shows up measurably in the statistics even when it's invisible to a casual
reader.

**Blind spots:**
- AI writing that has been "humanized" through post-processing (adding typos,
  breaking up long sentences) will fool this signal directly — it's targeting the
  surface statistics, not the deep structure.
- Very short texts are unreliable; variance measures need at least ~10 sentences to
  stabilize. The signal degrades to 0.5 (neutral) for texts under ~20 words.
- Some legitimate writing styles are naturally uniform: a minimalist short story, a
  listicle, technical documentation. These will score as "AI-like" on this signal
  even if they're entirely human.
- The thresholds used (e.g., "AI text tends to have TTR between 0.45–0.60") were
  calibrated on general web text and may not transfer well to specialized genres
  (poetry, legal writing, children's fiction).
- This signal is entirely structural — it cannot read the meaning of the text at all.
  A human writing in a deliberately flat style and an LLM produce indistinguishable
  statistics.

**Weight:** 0.40 (supporting — structural complement to Signal 1)

---

### False Positive Scenario Trace

**Scenario:** Alice is an academic writing a personal essay for a literary magazine.
She writes in the measured, formal prose style her training ingrained — clear topic
sentences, smooth transitions, no sentence fragments. She submits it to the platform.

**What happens:**

1. The LLM signal sees formal, coherent, transition-heavy prose with a uniform
   tonal register. It returns `verdict: "ai"` with confidence 0.75 (P(AI) = 0.75).
   It can't distinguish Alice's academic habit from an AI's output.

2. The stylometric signal sees slightly-above-average sentence uniformity (Alice
   writes clean, similar-length sentences by habit) and decent vocabulary diversity
   (she's a skilled writer). It returns P(AI) = 0.55 — uncertain, leaning AI.

3. The confidence scorer blends: `0.60×0.75 + 0.40×0.55 = 0.45 + 0.22 = 0.67`.
   This lands in the asymmetry-bias zone [0.40, 0.65]? No — 0.67 is just above it.
   Final score = 0.67. This crosses the HIGH-AI threshold (0.72)? No — 0.67 is below
   0.72. So the label is **UNCERTAIN**.

4. The transparency label reads: *"Our system could not confidently determine whether
   this content was written by a human or generated by AI."* The call to action
   directs Alice to the appeal endpoint.

5. The audit log records: `verdict: "uncertain"`, `confidence: 0.67`,
   `label_variant: "uncertain"`, `status: "decided"`.

6. Alice reads the "Origin Uncertain" badge and disagrees. She submits a `POST /appeal`
   with her reasoning: "I wrote this essay myself over two weeks. I can share my
   drafts and notes."

7. The appeal is logged as a new `audit_log` row with `event_type: "appeal"`. Her
   submission status changes to `under_review`. She receives confirmation.

8. A human moderator reviews the audit trail — both signal scores, Alice's reasoning,
   and the content itself. They override the decision.

**What this scenario shaped in the design:**
- The asymmetric thresholds (0.72 for AI vs. 0.28 for human) mean Alice's 0.67
  score does *not* trigger a high-confidence AI label — it produces the more
  charitable "uncertain" label instead.
- The asymmetry bias zone pulls gray-zone scores further toward uncertain.
- The transparent signal breakdown in the response (both raw scores visible) gives
  Alice and a moderator the information needed to understand *why* the system was
  uncertain.
- The appeal path is always surfaced in the label for AI and uncertain results —
  Alice is never left without recourse.

---

### API Surface

All endpoints accept and return JSON. All error responses follow the shape:
`{ "error": "description" }`.

#### POST /submit

| Field | Type | Required | Description |
|---|---|---|---|
| `content` | string | Yes | The text to analyze (≤ 20,000 chars) |
| `content_id` | string | No | Platform's ID; auto-generated UUID if omitted |
| `creator_id` | string | No | Creator identifier; defaults to "anonymous" |

**Returns 200:**
```json
{
  "content_id": "poem-001",
  "verdict": "human" | "ai" | "uncertain",
  "confidence": 0.0–1.0,
  "signals": {
    "llm": {
      "verdict": "human" | "ai" | "uncertain",
      "ai_probability": 0.0–1.0,
      "reasoning": "one-sentence explanation",
      "weight": 0.6
    },
    "stylometric": {
      "ai_probability": 0.0–1.0,
      "sub_metrics": { "sentence_length_variance": 0.0–1.0, ... },
      "weight": 0.4
    }
  },
  "label": {
    "variant": "high_ai" | "high_human" | "uncertain",
    "headline": "string",
    "body": "string",
    "call_to_action": "string" | null,
    "display_badge": "string"
  },
  "appeal_endpoint": "/appeal"
}
```

**Returns 400** if content is empty or too long.
**Returns 429** if rate limit exceeded.

---

#### POST /appeal

| Field | Type | Required | Description |
|---|---|---|---|
| `content_id` | string | Yes | ID of the submission being contested |
| `creator_id` | string | No | Creator's identifier |
| `reason` | string | Yes | Creator's explanation for the appeal |

**Returns 200:**
```json
{
  "message": "Your appeal has been received and logged...",
  "content_id": "poem-001",
  "status": "under_review",
  "next_steps": "Appeals are reviewed within 5 business days."
}
```

**Returns 400** if content_id or reason missing.
**Returns 404** if no submission with that content_id.
**Returns 429** if rate limit exceeded (5/hr).

---

#### GET /log

| Query param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 20 | Max entries to return (cap: 100) |
| `offset` | int | 0 | Pagination offset |

**Returns 200:**
```json
{
  "total": 42,
  "entries": [ { ...audit_log row... }, ... ]
}
```

---

#### GET /health

No parameters. Returns `{ "status": "ok", "service": "provenance-guard" }`.

---

## Confidence Scoring & Uncertainty

The raw blended score is:

```
blend = 0.60 × llm_ai_prob + 0.40 × stylo_ai_prob
```

**Asymmetry bias:** A false positive (labeling human work as AI) is worse than a false
negative on a creative platform. The final score is nudged toward "uncertain" when the
blend sits in [0.40, 0.65]:

```python
if 0.40 <= blend <= 0.65:
    final = blend * 0.90   # pull toward human-leaning uncertain
```

**Label thresholds:**
- `final >= 0.72` → HIGH-CONFIDENCE AI
- `final <= 0.28` → HIGH-CONFIDENCE HUMAN
- otherwise → UNCERTAIN

These asymmetric thresholds mean the system requires stronger evidence to call
something AI-generated than to call it human-written.

---

## Transparency Label Design

Three variants — written out verbatim in README.

**Design principles:**
- Use plain language; avoid "algorithm" or "classifier"
- Name the confidence level explicitly
- Always mention the appeal path when classification is AI or uncertain
- Treat the creator charitably in uncertain cases

---

## Appeals Workflow

1. Creator calls `POST /appeal` with `content_id`, `creator_id`, and `reason`.
2. System validates that the content exists in the submissions table.
3. Appeal is recorded as a new audit entry (`event_type: "appeal"`) linked by
   `content_id` to the original decision.
4. Content status is updated to `under_review` in the submissions table.
5. Response confirms receipt and explains next steps.
6. A human moderator reviews the full audit trail. Automated re-classification on
   appeal is not implemented.

---

## Rate Limiting

Implemented via Flask-Limiter (in-memory store). See README for chosen values and
rationale.

---

## Audit Log Schema

Every event (attribution decision or appeal) is written to SQLite:

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

---

## Stretch Features (planned)

- [ ] Ensemble detection (3+ signals with documented weighting)
- [ ] Provenance certificate
- [ ] Analytics dashboard
- [ ] Multi-modal support
