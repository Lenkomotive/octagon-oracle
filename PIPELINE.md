# Octagon Oracle Pipeline

## Flow

```
┌─────────────────────────────────────────────────────────┐
│                  MONITOR (every 15min)                   │
└────────────────────────┬────────────────────────────────┘
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
            │  3. CLASSIFY VIDEO     │
            │                        │
            │  Quick check:          │
            │  a) Title keywords?    │
            │     → likely prediction│
            │  b) Title mentions     │
            │     upcoming event?    │
            │     → likely prediction│
            │  c) Title says "recap" │
            │     "reaction"?        │
            │     → skip             │
            │  d) Uncertain?         │
            │     → grab first 60s   │
            │       of captions,     │
            │       ask LLM yes/no   │
            │                        │
            │  Save classification   │
            │  to videos table       │
            └───────────┬────────────┘
                        │ is_prediction = true
                        ▼
            ┌────────────────────────┐
            │  4. TRANSCRIPT         │
            │                        │
            │  Try YouTube captions  │
            │  (free, fast)          │
            │  ↓ fallback            │
            │  Groq Whisper          │
            │  (whisper-large-v3)    │
            │                        │
            │  Save to               │
            │  videos.transcript     │
            └───────────┬────────────┘
                        │
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

    YouTube ──→ yt-dlp ──→ Transcript ──→ LLM ──→ Predictions
                                                       │
    ufcstats.com ──→ Results ──→ Fights table ─────────┤
                                                       ▼
                                                    Scores
                                                       │
                                                       ▼
                                                   Website


## Key Rules

1. Only process videos during FIGHT WEEK (upcoming event exists)
2. Only check the LATEST video per channel (not last 10)
3. Classify before processing (don't waste API on recaps)
4. Use event from DB to match, not title parsing
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
