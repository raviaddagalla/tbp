/**
 * Frontend Camera Config and URL normalization tests.
 */
import { describe, it } from "node:test";
import assert from "node:assert";

function normalizeCameraUrl(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) return "";
  if (/^(https?|rtsp|sim):\/\//i.test(trimmed)) {
    return trimmed;
  }
  return `http://${trimmed}`;
}

function validateStreamUrl(url: string): { valid: boolean; error?: string } {
  const trimmed = url.trim();
  if (!trimmed) {
    return { valid: false, error: "Enter an ESP32-CAM stream URL" };
  }
  const normalized = normalizeCameraUrl(trimmed);
  if (!/^(https?|rtsp|sim):\/\//i.test(normalized)) {
    return { valid: false, error: "The stream URL must start with http://, https://, or rtsp://" };
  }
  return { valid: true };
}

describe("Frontend Camera URL Normalization & Validation", () => {
  it("normalizes bare IP addresses by adding http://", () => {
    assert.strictEqual(normalizeCameraUrl("192.168.0.132"), "http://192.168.0.132");
    assert.strictEqual(normalizeCameraUrl("10.63.89.95"), "http://10.63.89.95");
  });

  it("normalizes bare IP addresses with port and stream path", () => {
    assert.strictEqual(
      normalizeCameraUrl("192.168.0.132:81/stream"),
      "http://192.168.0.132:81/stream"
    );
    assert.strictEqual(
      normalizeCameraUrl("192.168.0.132/capture"),
      "http://192.168.0.132/capture"
    );
  });

  it("preserves already formatted URLs", () => {
    assert.strictEqual(
      normalizeCameraUrl("http://192.168.0.132:81/stream"),
      "http://192.168.0.132:81/stream"
    );
    assert.strictEqual(
      normalizeCameraUrl("http://192.168.0.132/capture"),
      "http://192.168.0.132/capture"
    );
    assert.strictEqual(
      normalizeCameraUrl("rtsp://192.168.0.132:554/live"),
      "rtsp://192.168.0.132:554/live"
    );
  });

  it("validates stream URL input correctly", () => {
    assert.strictEqual(validateStreamUrl("").valid, false);
    assert.strictEqual(validateStreamUrl("   ").valid, false);
    assert.strictEqual(validateStreamUrl("192.168.0.132").valid, true);
    assert.strictEqual(validateStreamUrl("http://192.168.0.132:81/stream").valid, true);
  });

  it("handles whitespace trimming properly", () => {
    assert.strictEqual(
      normalizeCameraUrl("   http://192.168.0.132:81/stream   "),
      "http://192.168.0.132:81/stream"
    );
    assert.strictEqual(
      normalizeCameraUrl("   192.168.0.132:81/stream   "),
      "http://192.168.0.132:81/stream"
    );
  });
});

