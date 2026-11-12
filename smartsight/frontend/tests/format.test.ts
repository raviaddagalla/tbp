/**
 * Frontend format and localization utility tests.
 */
import { describe, it } from "node:test";
import assert from "node:assert";

import {
  compactNumber,
  formatClock,
  formatDuration,
  scorePercent,
  titleCase,
  timeAgo,
  formatDateTime,
  formatTime,
} from "../src/lib/format.ts";

describe("Frontend Format Utilities", () => {
  it("compactNumber formats numbers into human readable strings", () => {
    assert.strictEqual(compactNumber(0), "0");
    assert.strictEqual(compactNumber(500), "500");
    assert.strictEqual(compactNumber(1000), "1,000");
    assert.strictEqual(compactNumber(12500), "12.5k");
    assert.strictEqual(compactNumber(1500000), "1.5M");
    assert.strictEqual(compactNumber(null), "0");
    assert.strictEqual(compactNumber(undefined), "0");
  });

  it("formatClock formats seconds into video player time codes", () => {
    assert.strictEqual(formatClock(0), "00:00");
    assert.strictEqual(formatClock(45), "00:45");
    assert.strictEqual(formatClock(65), "01:05");
    assert.strictEqual(formatClock(3665), "1:01:05");
    assert.strictEqual(formatClock(null), "00:00");
    assert.strictEqual(formatClock(undefined), "00:00");
  });

  it("formatDuration formats seconds into human duration strings", () => {
    assert.strictEqual(formatDuration(0), "0s");
    assert.strictEqual(formatDuration(42), "42s");
    assert.strictEqual(formatDuration(125), "2m 5s");
    assert.strictEqual(formatDuration(3660), "1h 1m");
  });

  it("scorePercent clamps confidence scores between 0 and 100", () => {
    assert.strictEqual(scorePercent(0.0), 0);
    assert.strictEqual(scorePercent(0.854), 85);
    assert.strictEqual(scorePercent(0.999), 100);
    assert.strictEqual(scorePercent(1.2), 100);
    assert.strictEqual(scorePercent(-0.5), 0);
  });

  it("titleCase capitalizes words and handles underscores", () => {
    assert.strictEqual(titleCase("person"), "Person");
    assert.strictEqual(titleCase("traffic_light"), "Traffic Light");
    assert.strictEqual(titleCase("esp32_cam_stream"), "Esp32 Cam Stream");
  });

  it("timeAgo generates relative timestamps correctly", () => {
    const now = new Date().toISOString();
    assert.strictEqual(timeAgo(now), "just now");

    const tenSecAgo = new Date(Date.now() - 10_000).toISOString();
    assert.strictEqual(timeAgo(tenSecAgo), "10s ago");

    const fiveMinAgo = new Date(Date.now() - 5 * 60_000).toISOString();
    assert.strictEqual(timeAgo(fiveMinAgo), "5m ago");

    const twoHoursAgo = new Date(Date.now() - 2 * 3600_000).toISOString();
    assert.strictEqual(timeAgo(twoHoursAgo), "2h ago");

    const threeDaysAgo = new Date(Date.now() - 3 * 86400_000).toISOString();
    assert.strictEqual(timeAgo(threeDaysAgo), "3d ago");

    assert.strictEqual(timeAgo(""), "—");
    assert.strictEqual(timeAgo(null), "—");
  });

  it("formatDateTime and formatTime handle null and invalid values", () => {
    assert.strictEqual(formatDateTime(""), "—");
    assert.strictEqual(formatDateTime(null), "—");
    assert.strictEqual(formatTime(""), "—");
    assert.strictEqual(formatTime(null), "—");

    const validIso = "2026-11-11T12:00:00.000Z";
    assert.notStrictEqual(formatDateTime(validIso), "—");
    assert.notStrictEqual(formatTime(validIso), "—");
  });
});

