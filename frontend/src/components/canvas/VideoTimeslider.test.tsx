import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act, within } from "@testing-library/react";
import { ApiClient } from "../../api/ApiClient";
import { MockTransport, type Transport } from "../../api/transport";
import { usePinsStore } from "../../state/usePinsStore";
import { VideoTimeslider } from "./VideoTimeslider";

/**
 * Transport that resolves /media/frame immediately (with a fixed frame count)
 * but defers /detect responses until the test resolves them — used for the
 * D1 in-flight guard test (same deferral idea as usePinsStore.test.ts).
 */
class DeferredDetectTransport implements Transport {
  requests: { method: string; url: string }[] = [];
  private frameResp: Response;
  private pendingDetect: Array<(resp: Response) => void> = [];

  constructor(frameCount = 10) {
    this.frameResp = new Response(new Uint8Array([1, 2, 3]), {
      status: 200,
      headers: new Headers({ "X-Frame-Count": String(frameCount) }),
    });
  }

  request(path: string, init?: RequestInit): Promise<Response> {
    this.requests.push({ method: init?.method ?? "GET", url: path });
    if (path.includes("/media/frame")) {
      return Promise.resolve(this.frameResp);
    }
    return new Promise((resolve) => {
      this.pendingDetect.push(resolve);
    });
  }

  resolveDetect(body: unknown, status = 200): void {
    const resolve = this.pendingDetect.shift();
    resolve?.(
      new Response(JSON.stringify(body), {
        status,
        headers: new Headers({ "Content-Type": "application/json" }),
      }),
    );
  }
}

/** Scripted 17-keypoint detection mirroring the synthetic backend (COCO-17). */
const POSE = {
  keypoints: [
    { label: "nose", x: 0.5, y: 0.2, confidence: 0.95 },
    { label: "left_eye", x: 0.52, y: 0.18, confidence: 0.95 },
    { label: "right_eye", x: 0.48, y: 0.18, confidence: 0.95 },
    { label: "left_ear", x: 0.54, y: 0.18, confidence: 0.95 },
    { label: "right_ear", x: 0.46, y: 0.18, confidence: 0.95 },
    { label: "left_shoulder", x: 0.45, y: 0.35, confidence: 0.95 },
    { label: "right_shoulder", x: 0.55, y: 0.35, confidence: 0.95 },
    { label: "left_elbow", x: 0.38, y: 0.5, confidence: 0.95 },
    { label: "right_elbow", x: 0.62, y: 0.5, confidence: 0.95 },
    { label: "left_wrist", x: 0.32, y: 0.62, confidence: 0.95 },
    { label: "right_wrist", x: 0.68, y: 0.62, confidence: 0.95 },
    { label: "left_hip", x: 0.44, y: 0.6, confidence: 0.95 },
    { label: "right_hip", x: 0.56, y: 0.6, confidence: 0.95 },
    { label: "left_knee", x: 0.43, y: 0.75, confidence: 0.95 },
    { label: "right_knee", x: 0.57, y: 0.75, confidence: 0.95 },
    { label: "left_ankle", x: 0.42, y: 0.9, confidence: 0.95 },
    { label: "right_ankle", x: 0.58, y: 0.9, confidence: 0.95 },
  ],
  confidence: 0.95,
};

const VIDEO = "uploads/ab12_video.mp4";

function makeClient() {
  const transport = new MockTransport();
  const api = new ApiClient("http://127.0.0.1:8765", "tok", transport);
  return { transport, api };
}

/** Queue a JPEG frame blob with an X-Frame-Count header for the MockTransport. */
async function enqueueFrame(transport: MockTransport, frameCount = 10): Promise<void> {
  await transport.enqueueBlob(new Blob([new Uint8Array([1, 2, 3])], { type: "image/jpeg" }), 200, {
    "X-Frame-Count": String(frameCount),
  });
}

function overlayRectMock(target: HTMLElement) {
  return vi
    .spyOn(target, "getBoundingClientRect")
    .mockReturnValue({
      left: 0,
      width: 100,
      top: 0,
      height: 12,
      right: 100,
      bottom: 12,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
}

beforeEach(() => {
  usePinsStore.setState({ pinsByNode: {} });
});

// The play test uses fake timers; restore real ones so later waitFor/findBy
// polling (which relies on setTimeout) is not blocked.
afterEach(() => {
  vi.useRealTimers();
});

describe("VideoTimeslider placeholder (golden-poses-ux: no video)", () => {
  it("shows a placeholder and issues NO frame request when no video is selected", () => {
    const { transport, api } = makeClient();
    render(<VideoTimeslider nodeId="n1" videoPath={null} api={api} />);

    expect(screen.getByTestId("timeslider-placeholder")).toHaveTextContent(/no video/i);
    expect(transport.requests).toHaveLength(0);
  });
});

describe("VideoTimeslider scrub/play (golden-poses-ux: video timeslider)", () => {
  it("loads the range from X-Frame-Count and scrubbing updates the displayed frame", async () => {
    const { transport, api } = makeClient();
    await enqueueFrame(transport, 10); // initial frame 1
    render(<VideoTimeslider nodeId="n1" videoPath={VIDEO} api={api} />);

    const img = await screen.findByTestId("timeslider-frame");
    expect(screen.getByTestId("timeslider-frame-label")).toHaveTextContent("1 / 10");
    const firstSrc = img.getAttribute("src");
    expect(firstSrc).toMatch(/^blob:/);

    await enqueueFrame(transport, 10); // scrub target frame 5
    fireEvent.change(screen.getByTestId("timeslider-scrub"), { target: { value: "5" } });

    await waitFor(() =>
      expect(screen.getByTestId("timeslider-frame-label")).toHaveTextContent("5 / 10"),
    );
    expect(
      transport.requests.some((r) => r.url.includes("frame_index=5")),
    ).toBe(true);
    expect(img.getAttribute("src")).not.toBe(firstSrc);
  });

  it("play advances frames over time and stops at the last frame", async () => {
    const { transport, api } = makeClient();
    await enqueueFrame(transport, 10);
    render(<VideoTimeslider nodeId="n1" videoPath={VIDEO} api={api} />);
    await screen.findByTestId("timeslider-frame");

    vi.useFakeTimers();
    fireEvent.click(screen.getByTestId("timeslider-play"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(screen.getByTestId("timeslider-frame-label")).toHaveTextContent("10 / 10");
    expect(screen.getByTestId("timeslider-play")).toHaveTextContent("Play");
  });

  it("shows a hover thumbnail while hovering over the track and clears it on leave", async () => {
    const { transport, api } = makeClient();
    await enqueueFrame(transport, 10);
    render(<VideoTimeslider nodeId="n1" videoPath={VIDEO} api={api} />);
    await screen.findByTestId("timeslider-frame");

    const track = screen.getByTestId("timeslider-track");
    overlayRectMock(track);
    await enqueueFrame(transport, 10); // hover thumbnail fetch
    fireEvent.mouseMove(track, { clientX: 45 });

    const thumb = await screen.findByTestId("timeslider-hover-thumb");
    expect(thumb.getAttribute("src")).toMatch(/^blob:/);
    // Thumbnails are fetched at a reduced width to keep hovering light.
    expect(
      transport.requests.some((r) => r.url.includes("/media/frame") && r.url.includes("width=160")),
    ).toBe(true);

    fireEvent.mouseLeave(track);
    expect(screen.queryByTestId("timeslider-hover-thumb")).not.toBeInTheDocument();
  });
});

describe("VideoTimeslider golden pins ⏳→✓/✗ (golden-poses-ux: per-pin detection)", () => {
  it("marks a pin at the current frame as ⏳ processing, then ✓ with confidence", async () => {
    const transport = new DeferredDetectTransport(10);
    const api = new ApiClient("http://127.0.0.1:8765", "tok", transport);
    render(<VideoTimeslider nodeId="n1" videoPath={VIDEO} api={api} />);
    await screen.findByTestId("timeslider-frame");

    fireEvent.click(screen.getByTestId("timeslider-add-pin"));

    const pin = await screen.findByTestId("timeslider-pin");
    expect(pin.dataset.label).toBe("G1");
    expect(pin.dataset.frame).toBe("1");
    expect(pin.dataset.status).toBe("processing");
    expect(pin).toHaveTextContent("⏳");

    transport.resolveDetect(POSE);
    await waitFor(() => expect(pin.dataset.status).toBe("success"));
    expect(pin).toHaveTextContent("✓");
    expect(pin).toHaveTextContent("0.95");
  });

  it("shows ✗ on detection failure and keeps the pin editable", async () => {
    const { transport, api } = makeClient();
    await enqueueFrame(transport, 10);
    transport.enqueue(501, { detail: "single-frame detection unavailable" });
    render(<VideoTimeslider nodeId="n1" videoPath={VIDEO} api={api} />);
    await screen.findByTestId("timeslider-frame");

    fireEvent.click(screen.getByTestId("timeslider-add-pin"));

    const pin = await screen.findByTestId("timeslider-pin");
    await waitFor(() => expect(pin.dataset.status).toBe("error"));
    expect(pin).toHaveTextContent("✗");
    expect(screen.getByTestId("timeslider-delete-pin")).toBeInTheDocument();
  });

  it("deletes a pin and keeps the remaining pins' labels", async () => {
    const { transport, api } = makeClient();
    await enqueueFrame(transport, 10);
    transport.enqueue(200, POSE); // G1 detect
    transport.enqueue(200, POSE); // G2 detect
    render(<VideoTimeslider nodeId="n1" videoPath={VIDEO} api={api} />);
    await screen.findByTestId("timeslider-frame");

    const addPin = screen.getByTestId("timeslider-add-pin");
    fireEvent.click(addPin);
    fireEvent.click(addPin);
    await waitFor(() => expect(screen.getAllByTestId("timeslider-pin")).toHaveLength(2));

    const pins = screen.getAllByTestId("timeslider-pin");
    expect(pins[0].dataset.label).toBe("G1");
    expect(pins[1].dataset.label).toBe("G2");

    fireEvent.click(within(pins[0]).getByTestId("timeslider-delete-pin"));
    const remaining = screen.getAllByTestId("timeslider-pin");
    expect(remaining).toHaveLength(1);
    expect(remaining[0].dataset.label).toBe("G2");
  });
});

describe("VideoTimeslider drag + D1 no-overlap guard", () => {
  it("dragging repositions a pin and re-detection does NOT overlap an in-flight request", async () => {
    const transport = new DeferredDetectTransport(10);
    const api = new ApiClient("http://127.0.0.1:8765", "tok", transport);
    usePinsStore.setState({ api });
    render(<VideoTimeslider nodeId="n1" videoPath={VIDEO} api={api} />);
    await screen.findByTestId("timeslider-frame");
    expect(screen.getByTestId("timeslider-frame-label")).toHaveTextContent("1 / 10");

    fireEvent.click(screen.getByTestId("timeslider-add-pin"));
    const pin = await screen.findByTestId("timeslider-pin");
    expect(transport.requests.filter((r) => r.url.includes("/detect/"))).toHaveLength(1);

    // Drag G1 from frame 1 toward frame 3 and drop it on the track.
    const track = screen.getByTestId("timeslider-track");
    overlayRectMock(track);
    fireEvent.mouseDown(pin, { clientX: 0, clientY: 0 });
    fireEvent.mouseMove(track, { clientX: 22.2, clientY: 0 });
    fireEvent.mouseUp(track, { clientX: 22.2, clientY: 0 });

    // The pin moved to frame 3 and its re-detect call was swallowed by the
    // per-pin in-flight guard: still exactly ONE /detect request.
    expect(pin.dataset.frame).toBe("3");
    expect(transport.requests.filter((r) => r.url.includes("/detect/"))).toHaveLength(1);

    // The original in-flight detection resolves normally afterwards.
    transport.resolveDetect(POSE);
    await waitFor(() => expect(pin.dataset.status).toBe("success"));
  });
});

describe("VideoTimeslider overlay toggle (golden-poses-ux: 2D skeleton overlay)", () => {
  it("draws the skeleton for the current frame and toggles off/on", async () => {
    const { transport, api } = makeClient();
    await enqueueFrame(transport, 10);
    transport.enqueue(200, POSE);
    render(<VideoTimeslider nodeId="n1" videoPath={VIDEO} api={api} />);
    await screen.findByTestId("timeslider-frame");

    fireEvent.click(screen.getByTestId("timeslider-add-pin"));
    const pin = await screen.findByTestId("timeslider-pin");
    await waitFor(() => expect(pin.dataset.status).toBe("success"));

    // All 17 scripted keypoints present → all 16 COCO bones drawable.
    const canvas = screen.getByTestId("timeslider-overlay");
    expect(Number(canvas.dataset.segments)).toBe(16);
    expect(Number(canvas.dataset.points)).toBe(17);

    fireEvent.click(screen.getByTestId("timeslider-overlay-toggle"));
    expect(screen.queryByTestId("timeslider-overlay")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("timeslider-overlay-toggle"));
    expect(screen.getByTestId("timeslider-overlay")).toBeInTheDocument();
  });
});