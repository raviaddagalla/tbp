"""Global runtime singletons, wired up in the FastAPI lifespan."""
from __future__ import annotations

from app.core.config import Settings, get_settings


class AppState:
    def __init__(self) -> None:
        self.settings: Settings = get_settings()
        self.embedder = None
        self.vector_store = None
        self.llm = None
        self.orchestrator = None
        self.worker_manager = None
        self.anomaly_detector = None
        self.ready = False


state = AppState()


def init_state() -> None:
    from app.services.activity import event_hub
    from app.services.alerts.anomaly import AnomalyDetector
    from app.services.embedding.clip import ClipEmbedder
    from app.services.ingestion.manager import CameraWorkerManager
    from app.services.rag.llm.factory import get_llm
    from app.services.rag.orchestrator import RagOrchestrator
    from app.services.vectorstore.factory import get_vector_store

    state.embedder = ClipEmbedder()
    state.vector_store = get_vector_store()
    state.llm = get_llm()
    state.anomaly_detector = AnomalyDetector(state.embedder, event_hub)
    state.orchestrator = RagOrchestrator(state.llm, state.embedder, state.vector_store)
    state.worker_manager = CameraWorkerManager(
        state.embedder, state.vector_store, state.anomaly_detector
    )
    state.ready = True
