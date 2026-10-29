# Fact Voltage

**Fast Facts. High Voltage.**

Fact Voltage is an automated YouTube Shorts pipeline for cinematic, three-beat
fact countdowns. It discovers currently available text models at runtime, tries
eleven provider routes, and falls back to a transactional SQLite reserve with
2,304 unique ready-to-render episodes.

## Channel identity

- YouTube name: **Fact Voltage**
- YouTube handle: **@FactVoltageDaily**
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

- Live model discovery: Groq, Cerebras, Mistral, NVIDIA NIM, SambaNova,
  Cloudflare Workers AI, Cohere, Gemini, and Claude.
- Groq, Gemini, and Claude never use pinned fallback IDs: every run reads the
  provider's live catalog and skips that route if discovery is unavailable.
- Managed free routers: OpenRouter Free and Hugging Face Router.
- Offline reserve: `fact_voltage_prompt_reserve.sqlite3` with 2,304 unique rows.
- A reserve row is deleted only after YouTube confirms a successful upload.
- Titles, scripts, and visual IDs are retained permanently in `shorts_db.db`.
- Three script-matched visual beats come from Pexels, Pixabay, Wikimedia
  Commons, NASA, Openverse, and the Art Institute of Chicago.
- Every visual query must name the corresponding spoken subject. Catalog-title
  relevance checks reject unrelated results before download.
- Sources are ranked 4K, then 1080p, then 720p. FFprobe rejects anything below
  the 720p floor before it can be enlarged into a blurry 1080x1920 Short.
- Spatial-detail detection fails the build instead of publishing a black,
  solid-color, flat, or placeholder video.
- Edge neural narration provides exact word boundaries for short, high-contrast
  two-line captions. The currently spoken word turns yellow; key figures remain
  cyan. The configured Deepgram route remains a fallback.
- GitHub Actions publishes once every 12 hours with concurrency protection.
- Manual workflow runs default to safe preview mode; uploading must be selected
  explicitly. Scheduled runs continue to upload automatically.

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
   preview_dir="$(mktemp -d)"
   cp shorts_db.db "$preview_dir/shorts.db"
   cp fact_voltage_prompt_reserve.sqlite3 "$preview_dir/reserve.sqlite3"
   UPLOAD_TO_YOUTUBE=false NUM_VIDEOS=1 \
     SHORTS_DB_PATH="$preview_dir/shorts.db" \
     PROMPT_RESERVE_PATH="$preview_dir/reserve.sqlite3" \
     OUTPUT_DIR=output/local-preview WORK_DIR="$preview_dir/work" \
     python fact_voltage.py
   ```

The preview does not consume uniqueness history or delete a reserve row.
