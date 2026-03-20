# Octagon Oracle Pipeline

## Two pipelines

### Pipeline A: COLLECT PREDICTIONS (before event, every 15min)

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
                        ▼
            ┌────────────────────────┐
            │  1. GET UPCOMING EVENT │
            │                        │
            │  Query events table    │
            │  for next event where  │
            │  date >= today         │
            │                        │
            │  No upcoming event?    │
            │  → SKIP cycle          │
            └───────────┬────────────┘
                        │ event found (e.g. "UFC 328")
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
```


### Pipeline B: SCORE PREDICTIONS (after event)

```
┌─────────────────────────────────────────────────────────┐
│          TRIGGERED: after event completes               │
│          (check on refresh_upcoming cycle)              │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
            ┌────────────────────────┐
            │  1. FETCH RESULTS      │
            │                        │
            │  Scrape Wikipedia      │
            │  event page for        │
            │  fight results         │
            │                        │
            │  Update fights table   │
            │  with winner, method,  │
            │  round, time           │
            └───────────┬────────────┘
                        │
                        ▼
            ┌────────────────────────┐
            │  2. SCORE PREDICTIONS  │
            │                        │
            │  Find all unscored     │
            │  predictions for this  │
            │  event                 │
            │                        │
            │  Match each pick to    │
            │  fight result:         │
            │  - correct / incorrect │
            │  - method_correct      │
            │                        │
            │  Save to scores table  │
            └────────────────────────┘
```


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
6. Scoring is SEPARATE — runs after event completes, not during collection


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
