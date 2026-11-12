# Architecture

## System overview

```
┌────────────┐   ┌────────────┐   ┌────────────────────────────┐
│  Cameras   │   │  Footage   │   │  Documents                 │
│  RTSP      │   │  Upload    │   │  PDF/DOCX/TXT/MD/images    │
│  usb://    │   │  MP4...    │   │  (OCR fallback)            │
│  sim://    │   │            │   │                            │
└─────┬──────┘   └─────┬──────┘   └─────────────┬──────────────┘
      │                │                       │
      ▼                ▼                       ▼
┌─────────────────────────┐        ┌─────────────────────────┐
│ Ingestion workers       │        │ Document pipeline       │
│ 1 capture thread / cam  │        │ parse → chunk → embed   │
│ → 5fps frame sampling   │        └─────────────┬───────────┘
│ → YOLO detect + ByteTrack│                    │
│ → crop CLIP + attrs +   │                     │
│   ReID embed (pool)     │                     │
│ → rolling H.264 clips   │                     │
│ → tracklets (SQLite)    │                     │
└────────────┬────────────┘                     │
             ▼                                  ▼
┌────────────────────────────────────────────────────────────┐
│  Vector store (Chroma / NumPy): collection `factory_intel` │
│  modality-tagged: video-frame + object + clip_event +      │
│  document; second collection `factory_intel_reid` for      │
│  person ReID embeddings (separate metric space)            │
└────────────┬───────────────────────────────┬───────────────┘
             │                               │
             ▼                               ▼
┌──────────────────────────┐   ┌─────────────────────────────┐
│ Search / RAG             │   │ Events & ops                │
│ Frames/Objects/Temporal  │   │ WebSocket activity/alerts   │
│ modes → kNN → rank       │   │ + SQLite (health, alerts,   │
│ → chat/summaries (LLM)   │   │ tracklets, adjacency, logs) │
│ ReID stitching w/ graph  │   │ Nightly compaction+retention│
└──────────────────────────┘   └─────────────────────────────┘
```

## Video ingestion (the core loop)

One **worker thread per camera** (`services/ingestion/camera_worker.py`) does everything on a single source of frames:

1. **Capture** — OpenCV reads RTSP, local file (`file://`), or webcam (`usb://<index>`). RTSP failures trigger reconnect with exponential backoff; status transitions are persisted and pushed over WebSocket.
2. **Preview** — latest frame JPEG in a per-camera buffer, served as MJPEG (throttled ~2 fps) for the Cameras page.
3. **Clip recorder** — rolling H.264 segments (PyAV; OpenCV fallback), retention-limited, so every search hit can be replayed.
4. **Sampling** — every `sample_interval_seconds` (default 0.2 = **5 frames analysed per second**), same for live and uploaded footage:
   - *Live sources* are paced by wall clock.
   - *File sources* are read at full decode speed, so pacing is by **video position** (`CAP_PROP_POS_MSEC`), guaranteeing exactly N frames per second of footage regardless of codec-reported FPS.
5. **Detection & tracking** — YOLOv8 (`detector_model`, default `yolov8n`) finds person/vehicle/… objects above `detector_confidence_threshold`; ByteTrack (supervision) assigns a stable `local_track_id` within the camera stream.
6. **Embedding** — each sample queues up to `CLIP_INFERENCE_THREADS` parallel jobs: one **whole-frame scene embedding** + one **cropped-object embedding per detection** (object crops also get zero-shot attribute labels — color/type/PPE — and OSNet **ReID embeddings** when `reid_model` is enabled). A per-worker in-flight counter drops samples only when the pipeline is saturated; embedding never blocks the capture loop.
7. **Tracklets** — per `(camera, local_track_id)` rows in SQLite (`Tracklet`) accumulate `start_ts/end_ts` and pooled embeddings; finalized tracklets feed the stitching service.
8. **Persistence** — embeddings + metadata (`camera_id`, zone, timestamp, segment id, clip offset, `object_class`, `bbox`, `parent_frame_id`, `attr_*`) → vector store; a per-worker `threading.Lock` serializes SQLite health writes so parallel embedding threads never hit `database is locked`.

Uploaded footage (`POST /api/cameras/upload`) becomes a `file://` camera: the worker indexes it once at the configured rate, then marks it offline with "File finished - indexing complete". Playback is served with Range support from `/api/streams/file/{id}`.

### Embedding & search

- `open_clip` ViT-B-32 (`laion400m_e32`), CPU/GPU auto-detect; texts and images embedded in the **same space**, so a document phrase like *"forklift in the loading dock"* and a video frame of a forklift are comparable.
- Query embedding → cosine kNN over the collection → hybrid rank: similarity, modality match, zone/camera/time filters, recency. Video results carry `clip_offset` for jump-to-moment playback; documents carry chunk text for citation.
- Three search modes (`api/routers/search.py`):
  - **Frames** — whole-frame scene hits (`modality=video`).
  - **Objects** — entity hits (`modality=object`) with optional `object_class` / `attr_color` / `attr_type` filters parsed from the query.
  - **Temporal** — coarse stage-1 frame/object candidates re-ranked by similarity to embeddings of batch-reprocessed 16-frame windows (stride 8, `modality=clip_event`), for motion/action queries.

### Cross-camera stitching (ReID)

- Dedicated **OSNet ReID** space (`factory_intel_reid` collection), computed only on `person` crops — never mixed with CLIP distances.
- `services/reid/stitching.py` walks the **adjacency graph** (`CameraAdjacency`: `from_camera`, `to_camera`, `expected_transit_seconds_min/max`, `direction_label`), scopes candidate search to graph-adjacent cameras **within the transit window**, and scores matches as `α·reid_similarity + β·time_fit + γ·adjacency_confidence` (weights from `STITCH_WEIGHTS`, default equal). Each hop decays confidence (`HOP_DECAY`); trails render as *"68% confidence — Camera 3 at 14:47"* and supervisors can dismiss low-confidence links.

### Batch reprocessing (temporal second pass)

- `services/ingestion/batch_reprocessor.py`: footage older than `BATCH_REPROCESS_AFTER_HOURS` (default 24) is re-read in **overlapping** 16-frame windows (stride 8, so events aren't split at boundaries) and embedded with a temporal video model as `clip_event` modality. Triggered on `file://` upload completion and by the nightly maintenance job — never in the live capture thread.

### RAG / LLM

- Providers: Groq (default), OpenAI, Anthropic, or `mock` (fully offline — answers built only from retrieved context, refuses when nothing relevant).
- Used for: chat answers with citations, shift/incident summaries, per-alert incident reports, anomaly descriptions.

### Anomaly detection (opt-in per camera)

Zero-shot CLIP classification over sampled frames — `no_helmet`, `smoke_fire`, `restricted_zone`, `spill` — with threshold, **per-camera cooldown** (`anomaly_cooldown_seconds`), and a stitched "trail" of recent detections. Alerts carry thumbnail + clip offset so a supervisor replays the moment.

## Data model

- **SQLite** via SQLAlchemy (Postgres-ready `DATABASE_URL`): users, cameras (incl. live health counters), documents, alerts, summaries, search logs, activity events, **tracklets**, **camera adjacency edges**.
- **Vector store** — Chroma (default, persistent) or NumPy JSONL fallback (`VECTOR_STORE_BACKEND=numpy`, hard-capped at `NUMPY_STORE_MAX_VECTORS` = 50k, fails loudly past it). Main collection modality-tagged `video` / `object` / `clip_event` / `document`; separate ReID collection.
- **Files** — `data/{clips,thumbs,uploads}` + uploaded videos; thumbnails rendered from any hit; no original video bytes stored in DB.
- **Retention** — a single scheduled job enforces `RETENTION_HOURS_DEFAULT` across vector rows, clip files, thumbnails, and tracklets; nightly Chroma **compaction** (`COMPACTION_HOUR_UTC`) bounds HNSW tombstone bloat.

## Auth & access control

- JWT lives in an **httpOnly, SameSite=Strict cookie** (`fi_session`), not localStorage; `POST /api/auth/login` is rate-limited (`LOGIN_RATE_LIMIT`, slowapi).
- Media endpoints (`<video>`/`<img>`) use **short-lived (5 min) single-resource tokens** via `?token=` — never the full-privilege access token.
- RBAC: `admin` (all), `supervisor` (ops + zone), `worker` (own zone). **Zone scoping is enforced server-side** (`deps.require_zone_scope`): a zone-restricted user's requests for other zones → 403 or filtered results, across search, documents, alerts, and summaries.
- Production boot is gated: `ENVIRONMENT=production` + dev `SECRET_KEY` → startup refusal.

## Frontend

Next.js 16 (App Router, Tailwind 4, React Query, Recharts). Pages: Cameras (live grid + add/upload), Search (Frames/Objects/Timeline modes + filters + playback), Floorplan (image + camera pins + adjacency edges), Documents, Chat (citations), Alerts (trails with confidence % + dismiss), Summaries, Diagnostics, Setup (onboarding), Settings (users), Login. `<img>`/`<video>` auth via `?token=`; live events over WebSocket at `/api/ws/events`. Builds with `output: "standalone"` for a slim Docker image.

## Concurrency & failure model

| Concern | Design |
|---|---|
| Blocking decode/embed | per-camera capture thread; shared embedding pool |
| One camera's failure | contained; reconnect backoff; status via WS |
| Lost frames | drop, never grow memory (in-flight cap) |
| SQLite write contention | per-worker write lock; throttled health sync (live) vs immediate (files) |
| LLM outage | `mock` fallback keeps search/answers working offline |
| Model download | cached in `~/.cache/huggingface` / Docker `clip-cache` volume |
| Detector/tracker outage | per-camera fallback to whole-frame-only embeddings, worker stays up |

## Scaling notes

- CPU-bound embedding pool is the bottleneck: more cores → `CLIP_INFERENCE_THREADS`; GPU tiers switch `DETECTOR_MODEL` up (`yolov8s`/`yolov8m`).
- SQLite → swap `DATABASE_URL` to Postgres; Chroma can run client/server; the worker topology maps 1:1 onto container per camera for larger fleets.
- `EDGE_ADAPTIVE_LOAD=1` auto-throttles sampling as camera count grows.
- Deployment profiles: `docker-compose.small.yml` (CPU-only), `docker-compose.mid.yml` (1 GPU), `docker-compose.full.yml` (multi-GPU) — differ in detector size, embedding threads, and whether batch reprocessing runs.
- Updates: admin-only signed Ed25519 bundles via `POST /api/admin/updates/verify` (see `docs/updates.md`).
