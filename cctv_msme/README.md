# AI-Powered Searchable Factory Intelligence Platform

An MSME Industry 4.0/5.0 MVP that turns existing **CCTV (RTSP) cameras**, **webcam/USB cameras**, **uploaded video footage**, and **factory documents** into a single natural-language-searchable knowledge base.

Ask things like *"show me forklift movement in the loading dock this afternoon"* or *"person in a red shirt near the loading dock"* and get back the exact video moment (with playback) or document passage — no SQL, no manual video scrubbing.

## What it does

| Capability | How |
|---|---|
| Live camera analysis | RTSP streams (`rtsp://`), webcam/USB (`usb://0`), or built-in simulated sources (`sim://`) |
| Object-level detection & tracking | YOLOv8 person/vehicle detection + ByteTrack tracklets per camera (`object_class`, `local_track_id`, stable identities) |
| Footage upload | Drag-and-drop MP4/MOV/AVI/MKV/WebM (2 GB cap) — indexed at 5 fps |
| 5 fps sampling | Every 0.2 s of video becomes one searchable frame (configurable) |
| Entity search | Cropped-object CLIP embeddings with attribute filters (color/type/PPE) — *"person in a red shirt"* |
| Scene search | Whole-frame CLIP embeddings for natural-language scene queries |
| Temporal search | Coarse-to-fine re-ranking of batch-reprocessed footage for motion/action queries |
| Document search | PDF / DOCX / images (OCR) / TXT / MD → chunked + embedded |
| Chat assistant | RAG over search results with citations and video evidence |
| Rolling clips | Continuous H.264 segments per camera + clip playback from search results |
| Cross-camera ReID | OSNet person ReID + floor-plan adjacency graph + transit-time windows → stitched movement trails with per-hop confidence % |
| Anomaly alerts | Zero-shot safety checks (no helmet, smoke/fire, restricted zone, spill), per-camera cooldown, dismissible trails |
| Shift summaries | LLM-generated shift/incident reports, exportable TXT/HTML |
| Access control | httpOnly SameSite=Strict cookie JWT + RBAC (`admin`/`supervisor`/`worker`), zone scoping enforced server-side on every route |
| Operations | Per-camera diagnostics page, signed update bundles (Ed25519), nightly Chroma compaction + retention cleanup, rate-limited login, prod refuses dev secret key |

## Quick start (Docker)

```bash
cp .env.example .env          # optional: set LLM_API_KEY for real chat answers
docker compose up --build
```

Deployment tiers (CPU-only → multi-GPU) are provided as profiles:

```bash
docker compose -f docker-compose.small.yml up --build   # CPU-only, small site
docker compose -f docker-compose.mid.yml   up --build   # single GPU, mid site
docker compose -f docker-compose.full.yml  up --build   # large / multi-GPU
```

- Web app: http://localhost:3000
- API docs: http://localhost:8000/docs
- First boot downloads the CLIP (~340 MB) + YOLOv8n + OSNet ReID models into a cache volume.

**Demo logins**

| Role | Username | Password |
|---|---|---|
| Admin | `admin` | `admin123` |
| Supervisor | `supervisor` | `supervisor123` |
| Worker | `worker` | `worker123` |

With `SEED_DEMO_SIM_CAMERAS=1` (default in Docker) three simulated cameras are seeded automatically. Run `docker compose exec backend python -m scripts.seed_demo` to also index the sample documents.

## Quick start (native, no Docker)

Requirements: Python 3.13+, Node 22+.

```bash
# Backend (Windows PowerShell; use venv on Linux/macOS)
cd backend
python -m venv .venv && .venv\Scripts\activate     # optional but recommended
pip install -r requirements.txt
python -m scripts.seed_demo                        # users + sim cameras + sample docs
.\dev.ps1                                          # dev server (reload scoped to app/ only)
# Linux/macOS: ./dev.sh  (or: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app)

# Frontend (second terminal)
cd frontend
npm install
npm run dev                                        # http://localhost:3000
```

> **Note:** use `--reload-dir app` (as the dev scripts do) instead of bare `--reload`.
> The repo lives inside a OneDrive-synced folder, and a bare `--reload` also watches
> `.venv`, so OneDrive's file touches cause endless false restarts.

Copy `.env.example` to `.env` first if you want to override anything (LLM provider, upload size, CLIP model, sample interval, etc.).

## Two laptops, one shared system (Neon Postgres + Cloudflare R2)

Run the same instance on two laptops (e.g. your workstation + the shop-floor
laptop) with shared state:

1. **Database — [Neon](https://neon.tech) (free tier).** Create a project, copy
   its Postgres connection string, and set the *same* `DATABASE_URL` in both
   `.env` files:
   `DATABASE_URL=postgresql://user:password@ep-xxxx.aws.neon.tech/neondb?sslmode=require`
   - First boot creates all tables + seeds demo users. Later boots are no-ops.
   - `VECTOR_STORE_BACKEND=auto` (default) automatically uses **pgvector**
     (powered by Neon's `pgvector` extension) when the URL is Postgres, so
     video frames and document chunks are searchable from *either* laptop.
2. **Media — [Cloudflare R2](https://developers.cloudflare.com/r2/) (free 10 GB).**
   Create a bucket (e.g. `factory-intel-media`) and an API token with
   **Object Read & Write** access, then set on both laptops:
   ```
   MEDIA_REMOTE_ENABLED=true
   R2_ENDPOINT_URL=https://<accountid>.r2.cloudflarestorage.com
   R2_ACCESS_KEY_ID=<key>
   R2_SECRET_ACCESS_KEY=<secret>
   R2_BUCKET=factory-intel-media
   ```
   Thumbnails, uploaded footage and rolling clips are mirrored to the bucket;
   local disk is only a cache.
3. **Workers — run processing on ONE laptop.** On the second machine set
   `WORKER_ENABLED=false` so the same cameras aren't processed twice. Both
   laptops see the shared cameras, alerts, footage and search results.

> The cameras themselves stream over your local network — each laptop still
> needs RTSP reachability, or use `sim://` sources for a demo.


## Connecting your real cameras

1. Open **Cameras** → *Add camera*.
2. URL:
   - `rtsp://user:pass@192.168.1.50:554/stream1` (H.264/H.265 RTSP; ONVIF cameras work if they expose RTSP)
   - `usb://0` for the machine's webcam or any attached USB camera (index `0`, `1`, …)
   - `sim://` for a built-in simulated source
3. Sample interval `0.2` = 5 frames analysed per second (default) — applies to live *and* uploaded footage.
4. To index old footage instead, use **Upload footage** on the same page.

## Searching

- **Search** page with three modes:
  - *Frames* — scene-level semantic search (*"truck reversing at the dock"*), zone/camera/time filters, ranked moments with thumbnails + one-click clip playback.
  - *Objects* — entity search over detected objects with attribute filters (*"person in a red shirt"*, *"forklift"*).
  - *Timeline* — temporal search over batch-reprocessed footage for motion/action queries (*"person entering through the side door"*).
- **Floorplan** page (admin/supervisor): upload a floor-plan image, drag camera pins, draw directed adjacency edges with expected transit-time ranges — the calibration that powers cross-camera stitching.
- **Alerts** page: anomaly trails with per-camera confidence % and dismiss, filterable by status.
- **Diagnostics** page (admin/supervisor): per-camera health — detections/sec, vector counts, embedding throughput, retention state.
- **Setup** page (admin): guided onboarding — cameras → floor plan → retention → anomaly categories.
- **Chat** page: ask questions conversationally; answers cite the retrieved video moments and document passages with links to replay the clip.

## Config essentials (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` / `LLM_API_KEY` | `mock` / empty | `groq` (free tier works) for real chat/summaries; `mock` = offline context-only answers |
| `ENVIRONMENT` | `dev` | Set `production` — app refuses to boot with the dev `SECRET_KEY` |
| `SECRET_KEY` | dev default | **Change in any shared deployment** |
| `FRAME_SAMPLE_INTERVAL_DEFAULT` | `0.2` | Seconds between embedded frames (0.2 = 5 fps) |
| `VIDEO_UPLOAD_MAX_MB` | `2048` | Upload cap for CCTV footage files |
| `CLIP_MODEL` / `CLIP_PRETRAINED` | `ViT-B-32` / `laion400m_e32` | Scene embedding model; swap for stronger accuracy |
| `DETECTOR_MODEL` | `yolov8n` | `yolov8n` (CPU) \| `yolov8s` \| `yolov8m` (GPU tiers) |
| `REID_MODEL` | `osnet_x1_0_msmt17` | Person ReID model; `disabled` turns it off |
| `VECTOR_STORE_BACKEND` | `auto` | `auto` (pgvector on Postgres, Chroma/NumPy on SQLite) \| `chroma` \| `numpy` \| `postgres` |
| `MEDIA_REMOTE_ENABLED` | `false` | Mirror thumbs/uploads/clips to Cloudflare R2 (shared media across laptops) |
| `R2_ENDPOINT_URL` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` | empty | R2 credentials + bucket for `MEDIA_REMOTE_ENABLED=true` |
| `WORKER_ENABLED` | `true` | `false` on a second laptop that only browses (avoids double-processing cameras) |
| `COMPACTION_HOUR_UTC` | `3` | Nightly Chroma compaction time (bounds HNSW tombstone bloat) |
| `RETENTION_HOURS_DEFAULT` | `72` | Vector rows + clips + thumbnails + tracklets purge window |
| `BATCH_REPROCESS_ENABLED_DEFAULT` | `true` | Temporal second-pass indexing of footage older than `BATCH_REPROCESS_AFTER_HOURS` |
| `UPDATE_PUBLIC_KEY_PATH` | empty | PEM Ed25519 public key; empty = update verification runs unsigned |
| `LOGIN_RATE_LIMIT` | `10/minute` | Rate limit on `POST /api/auth/login` |
| `MEDIA_TOKEN_TTL_MINUTES` | `5` | Short-lived single-resource tokens for `<video>`/`<img>` streaming |

## Updates

Admin-only `POST /api/admin/updates/verify` validates signed update bundles (Ed25519) before they are applied. Build packages with `backend/scripts/update_bundle.py` (`genkey`, `sign`, `verify`). See [docs/updates.md](docs/updates.md).

## Project layout

```
backend/
  app/
    api/routers/     # REST + WebSocket endpoints (auth, cameras, search, alerts,
                     #  summaries, analytics, floorplan, updates, streams, …)
    services/
      ingestion/     # per-camera workers: capture, 5fps sampling, clips, uploads,
                     #  batch reprocessor
      detection/     # YOLO detector, ByteTrack tracker, attribute classifier
      reid/          # OSNet person ReID + adjacency/transit stitching
      embedding/     # CLIP (open_clip)
      vectorstore/   # pgvector (Postgres) / Chroma / NumPy store + R2 media fallback
      rag/           # retrieval + LLM chat, summaries, reports
      documents/     # parse → chunk → embed pipeline
      updates/       # signed bundle verification
    db/              # SQLAlchemy models (SQLite or shared Neon Postgres)
  tests/             # pytest suite (63 tests: auth, zones, search, stitching, updates, …)
  scripts/seed_demo.py
  sample_data/       # demo documents
frontend/            # Next.js 16 App Router, Tailwind 4, React Query
Dockerfile.backend / Dockerfile.frontend / docker-compose.yml / docker-compose.{small,mid,full}.yml
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the data flow and design decisions.
