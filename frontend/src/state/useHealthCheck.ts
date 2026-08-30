import { useCallback, useEffect, useRef } from "react";
import { ApiClient } from "../api/ApiClient";
import { useUiStore } from "./useUiStore";

/**
 * Health-check hook (HTTP-3). On mount it probes `/health`; on failure it sets
 * a non-fatal banner. `retry` re-probes. Never throws out of the component.
 */
export function useHealthCheck(client: ApiClient = new ApiClient()) {
  const setBanner = useUiStore((s) => s.setBanner);
  const dismissBanner = useUiStore((s) => s.dismissBanner);
  const clientRef = useRef(client);
  clientRef.current = client;

  const check = useCallback(async () => {
    dismissBanner();
    try {
      const health = await clientRef.current.health();
      if (health.status !== "ok") {
        setBanner(`health status is ${String(health.status)}`, "warning");
      }
    } catch {
      setBanner("Cannot reach the AImation core. Is it running on 127.0.0.1:8765?", "error");
    }
  }, [setBanner, dismissBanner]);

  useEffect(() => {
    void check();
  }, [check]);

  return { retry: check };
}
