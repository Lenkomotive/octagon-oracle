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
                     │  LLM checks transcript:│
                     │  "Is this a prediction │
                     │   video for an         │
                     │   upcoming UFC event?" │
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
                     │  LLM: DeepSeek v3      │
                     │  (via OpenRouter)      │
                     │                        │
                     │  Input:                │
                     │  - transcript          │
                     │  - fight card from     │
                     │    fights table        │
                     │                        │
                     │  Output:               │
                     │  - fighter_picked      │
                     │  - fighter_against     │
                     │  - method              │
                     │  - confidence          │
                     │                        │
                     │  Validate all names    │
                     │  against card, retry   │
                     │  if mismatch           │
                     │                        │
                     │  Save video with       │
                     │  transcript + picks    │
                     │  to DB                 │
                     └────────────────────────┘


## Data Flow

    Wikipedia ──→ Events + fight cards (before event)
                      │
    YouTube ──→ Whisper ──→ Transcript ──→ LLM ──→ Predictions
                                                       │
    Wikipedia ──→ Results (after event) ──→ Fights ────┤
                                                       ▼
                                                    Scores
                                                       │
                                                       ▼
                                                   Website


## Key Rules

1. Only process videos during FIGHT WEEK (upcoming event exists)
2. Only check the LATEST video per channel (not last 10)
3. Always transcribe, then LLM classifies from transcript
4. No keyword filtering — LLM decides if it's a prediction video
5. Only save transcript to DB if it's a prediction video
6. Scoring piggybacks on step 0 — when results are fetched for a
   completed event, all unscored predictions are scored immediately


## Models

| Step        | Model                          | Provider    |
|-------------|--------------------------------|-------------|
| Transcript  | whisper-large-v3               | Groq        |
| Classify    | deepseek/deepseek-chat-v3-0324 | OpenRouter  |
| Extraction  | deepseek/deepseek-chat-v3-0324 | OpenRouter  |


## Database Tables

    channels → videos → predictions → scores
                            ↓
    events → fights ────────┘
