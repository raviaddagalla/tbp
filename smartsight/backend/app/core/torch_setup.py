"""Cap PyTorch's intra-op threads.

YOLO and CLIP run on the same laptop. Letting each grab every core makes them
fight each other and slows both down, especially on a modest 4-8 thread CPU.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def configure_torch_threads(override: int = 0) -> int:
    try:
        import torch
    except ImportError:  # pragma: no cover - torch is a hard dependency in practice
        return 0
    threads = override or int(os.environ.get("SMARTSIGHT_TORCH_THREADS", "0") or 0)
    if threads <= 0:
        threads = max(1, min(4, (os.cpu_count() or 4) // 2))
    torch.set_num_threads(threads)
    try:
        torch.set_num_interop_threads(max(1, min(2, threads)))
    except RuntimeError:
        # set_num_interop_threads can only be called once per process.
        pass
    logger.info("PyTorch using %d CPU thread(s)", threads)
    return threads
