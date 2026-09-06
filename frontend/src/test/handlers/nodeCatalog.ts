import { http, HttpResponse } from "msw";
import nodeCatalogFixture from "../fixtures/nodeCatalog.json";

/** Base URL the test client uses (mirrors the default API origin). */
export const TEST_BASE = "http://127.0.0.1:8765";

export const handlers = [
  http.get(`${TEST_BASE}/nodes/types`, () => {
    return HttpResponse.json(nodeCatalogFixture);
  }),
  http.get(`${TEST_BASE}/health`, () => {
    return HttpResponse.json({ status: "ok" });
  }),
];
