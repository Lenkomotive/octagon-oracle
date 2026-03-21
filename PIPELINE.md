# Octagon Oracle Pipeline

## Flow

```
┌─────────────────────────────────────────────────────────┐
│              MONITOR (every 15min)                       │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
            ┌────────────────────────┐
            │  0. REFRESH UPCOMING   │
            │                        │
            │  Scrape Wikipedia:     │
            │  List_of_UFC_events    │
            │  - Add new upcoming    │
            │    events to DB        │
            │                        │
            │  (Old events already   │
            │   seeded in DB)        │
            └───────────┬────────────┘
                        │
                ┌───────┴───────┐
                │               │
                ▼               ▼
  ┌──────────────────┐  ┌──────────────────┐
  │ 0a. CHECK PAST   │  │ 1. GET UPCOMING  │
  │                   │  │    EVENT         │
  │ Last 3 past       │  │                  │
  │ events have       │  │ Query events     │
  │ results in DB?    │  │ table for next   │
  │                   │  │ event where      │
  │ No → fetch from   │  │ date >= today    │
  │      Wikipedia    │  │                  │
  │    → score all    │  │ No upcoming?     │
  │      unscored     │  │ → SKIP to sleep  │
  │      predictions  │  └────────┬─────────┘
  │                   │           │
  │ Yes → skip        │           │
  └───────────────────┘           │
                                  │ event found
                                  ▼
                     ┌────────────────────────┐
                     │  2. SCAN CHANNELS      │
                     │                        │
                     │  For each channel:     │
                     │  - Fetch LAST video    │
                     │    (yt-dlp, playlist   │
                     │     end=1)             │
                     │  - Already in DB?      │
                     │    → skip              │
                     └───────────┬────────────┘
                                 │ new video found
                                 ▼
                     ┌────────────────────────┐
                     │  3. TRANSCRIPT         │
                     │                        │
                     │  Groq Whisper          │
                     │  (whisper-large-v3)    │
                     │  ↓ fallback            │
                     │  YouTube captions      │
                     │                        │
                     │  Keep in memory only   │
                     └───────────┬────────────┘
                                 │
                                 ▼
                     ┌────────────────────────┐
                     │  4. CLASSIFY VIDEO     │
                     │                        │
                     │  2 models in parallel: │
                     │  - DeepSeek V3.2       │
                     │  - Gemini 2.5 Flash    │
                     │    Lite                │
                     │                        │
                     │  Majority vote:        │
                     │  "Is this a prediction │
                     │   video?"              │
                     │                        │
                     │  No → save video,      │
                     │       is_prediction=F  │
                     │       no transcript    │
                     │       → next channel   │
                     └───────────┬────────────┘
                                 │ is_prediction = true
                                 ▼
                     ┌────────────────────────┐
                     │  5. EXTRACT PICKS      │
                     │                        │
                     │  Same 3 models in      │
                     │  parallel, consensus:  │
                     │                        │
                     │  Input:                │
                     │  - transcript          │
                     │  - fight card from     │
                     │    fights table        │
                     │                        │
                     │  Output: raw picks     │
                     │  per model             │
                     └───────────┬────────────┘
                                 │
                                 ▼
                     ┌────────────────────────┐
                     │  5a. NORMALIZE NAMES   │
                     │                        │
                     │  LLM maps all fighter  │
                     │  names from all models │
                     │  to official card names│
                     │  in one shot           │
                     │                        │
                     │  "Chanel Dyer"         │
                     │    → "Shanelle Dyer"   │
                     │  "Shamrock"            │
                     │    → "Shaqueme Rock"   │
                     └───────────┬────────────┘
                                 │
                                 ▼
                     ┌────────────────────────┐
                     │  5b. CONSENSUS         │
                     │                        │
                     │  Compare normalized    │
                     │  picks across models   │
                     │                        │
                     │  Pick included only if │
                     │  2+ models agree       │
                     │                        │
                     │  Confidence:           │
                     │  3/3 = high            │
                     │  2/3 = medium          │
                     │                        │
                     │  Save video with       │
                     │  transcript + picks    │
                     │  to DB                 │
                     └────────────────────────┘


## Data Flow

    Wikipedia ──→ Events + fight cards (before event)
                      │
    YouTube ──→ Whisper ──→ Transcript ──→ 4x LLMs ──→ Consensus Predictions
                                                            │
    Wikipedia ──→ Results (after event) ──→ Fights ─────────┤
                                                            ▼
                                                         Scores
                                                            │
                                                            ▼
                                                        Website


## Key Rules

1. Only process videos during FIGHT WEEK (upcoming event exists)
2. Only check the LATEST video per channel (not last 10)
3. Always transcribe, then LLMs classify from transcript
4. No keyword filtering — both LLMs must agree
5. Only save transcript to DB if it's a prediction video
6. Extraction uses 2 models in parallel, both must agree
7. Confidence = high (2/2 agree on method too), medium (2/2 winner only)
8. Scoring piggybacks on step 0 — when results are fetched for a
   completed event, all unscored predictions are scored immediately


## Models (all free on OpenRouter)

| Step        | Models                                                    |
|-------------|-----------------------------------------------------------|
| Transcript  | whisper-large-v3 (Groq) → YouTube captions fallback       |
| Classify    | DeepSeek V3.2, Gemini 2.5 Flash Lite                      |
| Extraction  | DeepSeek V3.2, Gemini 2.5 Flash Lite                      |


## Database Tables

    channels → videos → predictions → scores
                            ↓
    events → fights ────────┘
