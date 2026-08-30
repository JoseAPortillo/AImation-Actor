import { useUiStore } from "../../state/useUiStore";

interface ConnectionBannerProps {
  onRetry: () => void;
}

/**
 * Non-fatal connection banner (HTTP-3). Shown when the core is down, a request
 * times out, or auth fails. Offers a Retry action and a dismiss. The rest of
 * the app shell stays interactive behind it.
 */
export function ConnectionBanner({ onRetry }: ConnectionBannerProps) {
  const banner = useUiStore((s) => s.banner);
  const dismissBanner = useUiStore((s) => s.dismissBanner);

  if (!banner) return null;

  return (
    <div
      role="alert"
      style={{
        padding: "8px 12px",
        background: banner.kind === "error" ? "#fdecea" : "#fff4e5",
        border: "1px solid currentColor",
        color: "#8a1f11",
        display: "flex",
        gap: "8px",
        alignItems: "center",
      }}
    >
      <span data-testid="banner-message">{banner.message}</span>
      <button type="button" onClick={onRetry}>
        Retry
      </button>
      <button type="button" onClick={dismissBanner}>
        Dismiss
      </button>
    </div>
  );
}
