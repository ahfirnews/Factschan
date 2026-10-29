# Fact Voltage

**Fast Facts. High Voltage.**

Fact Voltage is an automated YouTube Shorts pipeline for cinematic, three-beat
fact countdowns. It discovers currently available text models at runtime, tries
eight provider routes, and falls back to a transactional SQLite reserve with
2,304 unique ready-to-render episodes.

## Channel identity

- YouTube name: **Fact Voltage**
- Requested handle: **@FactVoltage**
- Logo: [`assets/branding/logo.png`](assets/branding/logo.png)
- Banner: [`assets/branding/banner.jpg`](assets/branding/banner.jpg)

> The repository cannot rename the YouTube account itself. Apply the name,
> handle, logo, banner, and description once in YouTube Studio.

### Description

Facts should hit harder than filler. Fact Voltage ranks the world's wildest
science, space, history, nature, technology, and human-body truths in fast
cinematic countdowns. Every Short starts with the strongest contradiction,
builds through three verified comparisons, and saves the highest-voltage fact
for last. Subscribe for fast facts, clear sources, and zero dead air.

## Reliability design

- Live model discovery: Groq, Cerebras, Mistral, NVIDIA NIM, Gemini, and Claude.
- Managed free routers: OpenRouter Free and Hugging Face Router.
- Offline reserve: `fact_voltage_prompt_reserve.sqlite3` with 2,304 unique rows.
- A reserve row is deleted only after YouTube confirms a successful upload.
- Titles, scripts, and visual IDs are retained permanently in `shorts_db.db`.
- Three script-matched visual beats come from Pexels, Pixabay, Wikimedia
  Commons, NASA, Openverse, and the Art Institute of Chicago.
- Blank/flat visual detection fails the build instead of publishing a black or
  colored-placeholder video.
- Edge neural narration provides exact word timings for synced captions; the
  configured Deepgram route remains a fallback.
- GitHub Actions publishes once every 12 hours with concurrency protection.

No provider can promise a permanent free tier. Runtime model discovery,
independent failover routes, daily catalog checks, and the offline reserve make
the workflow resilient without falsely claiming that an outside service can
never change.

## Setup

1. Rotate all credentials mentioned in [`SECURITY.md`](SECURITY.md).
2. Add the required `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, and `YT_REFRESH_TOKEN`
   GitHub Actions secrets.
3. Add at least one AI key. More configured routes mean fewer reserve uses.
4. Add Pexels and Pixabay keys for the largest stock-video pool; four keyless
   public/licensed media routes remain available.
5. Run a safe local preview with:

   ```bash
   UPLOAD_TO_YOUTUBE=false NUM_VIDEOS=1 python fact_voltage.py
   ```

The preview does not consume uniqueness history or delete a reserve row.
