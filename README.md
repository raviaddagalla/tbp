# TBP: Smart AI Security Camera & Semantic Video Intelligence Platform

**TBP** is an end-to-end AI security surveillance and semantic retrieval platform. It integrates ESP32-CAM wireless video hardware with real-time computer vision (YOLOv8 + ByteTrack) and natural language semantic video search powered by OpenCLIP and ChromaDB vector storage.

---

## 📁 Repository Layout

```text
TBP/
├── smartsight/         # Primary AI Security Platform (Production)
│   ├── backend/        # FastAPI, YOLOv8n, ByteTrack, OpenCLIP ViT-B-32, SQLite, ChromaDB
│   │   ├── app/        # API routers, camera services, vector store, indexer
│   │   └── tests/      # Automated backend test suite (39 tests)
│   └── frontend/       # Next.js 16 (App Router), React 19, Tailwind CSS, TanStack Query
│       ├── src/        # Dashboard (Overview, Live Stream, Search, Recordings, Settings)
│       └── tests/      # Automated frontend test suite (23 tests)
├── cctv_msme/          # MSME CCTV Surveillance & Video Analytics Reference System
└── stitch_design/      # UI/UX design specifications, HTML wireframes, and dashboard screens
```

---

## ⚡ Core Features

- **ESP32-CAM Live Stream & Auto-Discovery**: Automatic detection of MJPEG streams (`:81/stream`) and snapshot endpoints (`/capture`) from ESP32-CAM firmware with reconnection resilience.
- **Real-Time Detection & Multi-Object Tracking**: Server-side YOLOv8n inference with ByteTrack object identity tracking across frames.
- **Semantic Video & Object Retrieval**: Dual OpenCLIP embeddings (full scene + cropped objects) enabling natural language search (e.g. *"person in red shirt"*, *"white car"*).
- **Exact Timestamp Seek & Range Playback**: Instant seek in indexed video recordings and captured snapshots.
- **Robust Automated Test Suites**: Comprehensive end-to-end test coverage for all backend endpoints and frontend components.

---

## 🚀 Quick Start Guide

### 1. Backend Setup

```powershell
cd smartsight\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# Start backend server on port 8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
- API Health: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)
- Swagger Docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 2. Frontend Setup

```powershell
cd smartsight\frontend
npm install

# Start development server on port 3000
npm run dev
```
- Web Dashboard: [http://localhost:3000](http://localhost:3000)
- Live Camera: [http://localhost:3000/live](http://localhost:3000/live)

---

## 🧪 Running Automated Tests

### Backend Tests (39 tests)
```powershell
cd smartsight\backend
.\.venv\Scripts\python.exe -m pytest
```

### Frontend Tests (23 tests)
```powershell
cd smartsight\frontend
npm test
```

---

## 📄 License
MIT License
