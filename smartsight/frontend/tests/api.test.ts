/**
 * Frontend API client and error handling tests.
 */
import { describe, it } from "node:test";
import assert from "node:assert";

import { apiUrl, errorMessage, API_URL } from "../src/lib/api.ts";

describe("Frontend API Client Utilities", () => {
  it("API_URL has a valid default", () => {
    assert.strictEqual(typeof API_URL, "string");
    assert.ok(API_URL.startsWith("http://"));
    assert.ok(!API_URL.endsWith("/"));
  });

  it("apiUrl prepends API_URL with leading slashes normalized", () => {
    assert.strictEqual(apiUrl("/api/camera/stream"), `${API_URL}/api/camera/stream`);
    assert.strictEqual(apiUrl("api/camera/stream"), `${API_URL}/api/camera/stream`);
    assert.strictEqual(apiUrl(""), "");
    assert.strictEqual(apiUrl(null), "");
    assert.strictEqual(apiUrl(undefined), "");
  });

  it("errorMessage extracts API error details from Axios responses", () => {
    const axiosErrorWithDetail = {
      isAxiosError: true,
      response: {
        status: 400,
        statusText: "Bad Request",
        data: { detail: "Unsupported video format. Allowed: mp4, mov" },
      },
    };
    assert.strictEqual(
      errorMessage(axiosErrorWithDetail),
      "Unsupported video format. Allowed: mp4, mov"
    );

    const axiosErrorWithoutDetail = {
      isAxiosError: true,
      response: {
        status: 404,
        statusText: "Not Found",
        data: {},
      },
    };
    assert.strictEqual(errorMessage(axiosErrorWithoutDetail), "404 Not Found");
  });

  it("errorMessage handles network disconnection and timeout errors", () => {
    const timeoutError = {
      isAxiosError: true,
      code: "ECONNABORTED",
    };
    assert.strictEqual(errorMessage(timeoutError), "The request timed out");

    const networkError = {
      isAxiosError: true,
      response: null,
    };
    assert.strictEqual(
      errorMessage(networkError),
      "Cannot reach the SmartSight backend. Is it running on port 8000?"
    );
  });

  it("errorMessage falls back cleanly on standard Error instances", () => {
    const stdError = new Error("Custom client error occurred");
    assert.strictEqual(errorMessage(stdError), "Custom client error occurred");

    assert.strictEqual(errorMessage(null, "Default fallback message"), "Default fallback message");
    assert.strictEqual(errorMessage(undefined, "Default fallback message"), "Default fallback message");
  });
});

