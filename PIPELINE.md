# Octagon Oracle Pipeline

## Flow

```
┌─────────────────────────────────────────────────────────┐
│                  MONITOR (every 15min)                   │
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
            │  - Fetch results for   │
            │    last 3 completed    │
            │    events if missing   │
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
                        │ new videos found
                        ▼
            ┌────────────────────────┐
            │  3. TRANSCRIPT         │
            │                        │
            │  For each new video:   │
            │  Groq Whisper          │
            │  (whisper-large-v3)    │
            │  ↓ fallback            │
            │  YouTube captions      │
            │                        │
            │  Save to               │
            │  videos.transcript     │
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
            │  Save to               │
            │  predictions table     │
            └───────────┬────────────┘
                        │
                        ▼
            ┌────────────────────────┐
            │  6. SCORE              │
            │                        │
            │  If event has results: │
            │  - Match each pick to  │
            │    fights table        │
            │  - correct / incorrect │
            │  - method_correct      │
            │                        │
            │  If event upcoming:    │
            │  - Skip scoring        │
            │  - Score later when    │
            │    results come in     │
            │                        │
            │  Save to scores table  │
            └───────────┬────────────┘
                        │
                        ▼
            ┌────────────────────────┐
            │  7. RESULTS REFRESH    │
            │  (Monday after event)  │
            │                        │
            │  Fetch results from    │
            │  ufcstats.com          │
            │  Update fights table   │
            │  Score any unscored    │
            │  predictions           │
            └────────────────────────┘


## Data Flow

    Wikipedia ──→ Events list (upcoming + past)
                      │
    YouTube ──→ yt-dlp ──→ Transcript ──→ LLM ──→ Predictions
                                                       │
    Wikipedia event page ──→ Results ──→ Fights ───────┤
    (or ufcstats.com)                                  │
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
5. Score happens twice:
   - Immediately if results exist
   - Deferred after event completes (Monday refresh)


## Models

| Step        | Model                          | Provider    |
|-------------|--------------------------------|-------------|
| Transcript  | whisper-large-v3               | Groq        |
| Extraction  | deepseek/deepseek-chat-v3-0324 | OpenRouter  |
| Classify    | deepseek/deepseek-chat-v3-0324 | OpenRouter  |


## Database Tables

    channels → videos → predictions → scores
                            ↓
    events → fights ────────┘
