"""ESP32-CAM endpoint detection without touching real hardware."""
from __future__ import annotations

from app.services.camera.sources import _candidate_urls


def test_bare_ip_expands_to_common_esp32_endpoints():
    urls = _candidate_urls("192.168.1.50")
    assert urls[0] == "http://192.168.1.50/stream"
    assert "http://192.168.1.50:81/stream" in urls
    assert "http://192.168.1.50/capture" in urls
    assert all(url.startswith("http://") for url in urls)


def test_exact_stream_url_is_not_rewritten():
    assert _candidate_urls("http://192.168.1.50:81/stream") == ["http://192.168.1.50:81/stream"]
    assert _candidate_urls("http://192.168.1.50/capture") == ["http://192.168.1.50/capture"]


def test_host_without_path_gets_stream_and_capture_variants():
    urls = _candidate_urls("http://cam.local:81")
    assert urls[0] == "http://cam.local:81"
    assert "http://cam.local:81/stream" in urls
    assert "http://cam.local:81/capture" in urls


def test_rtsp_and_simulated_sources_are_passed_through():
    assert _candidate_urls("rtsp://192.168.1.50:554/live") == ["rtsp://192.168.1.50:554/live"]
    assert _candidate_urls("sim://demo") == ["sim://demo"]


def test_empty_input_has_no_candidates():
    assert _candidate_urls("   ") == []
