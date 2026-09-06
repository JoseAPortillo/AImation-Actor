import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { GraphIO, type CatalogProvider } from "./GraphIO";
import { useFlowStore } from "../../state/useFlowStore";
import nodeCatalogFixture from "../../test/fixtures/nodeCatalog.json";
import type { NodeSchema } from "../../api/types";
import { serializeGraph, fromFlow } from "../../core/serialize";

const catalog = nodeCatalogFixture as NodeSchema[];
const videoSource = catalog.find((n) => n.type === "video-source")!;
const catalogProvider: CatalogProvider = () => catalog;

/** v1.0 canonical graph with one node and one edge, for load tests. */
const V10_CANONICAL = `{
  "version": "1.0",
  "nodes": [
    {
      "id": "src",
      "type": "video-source",
      "params": {
        "video_path": "from.file.avi"
      },
      "position": {
        "x": 50,
        "y": 60
      }
    }
  ],
  "edges": [
    {
      "id": "e1",
      "source": {
        "node": "src",
        "port": "frames"
      },
      "target": {
        "node": "p2d",
        "port": "frames"
      }
    }
  ]
}
`;

/** Stale v0.1 file that load must reject without mutation. */
const V01_CANONICAL = V10_CANONICAL.replace('"1.0"', '"0.1"');

beforeEach(() => {
  useFlowStore.setState({ nodes: [], edges: [], selectedNodeId: null, connectionHint: null });
  vi.restoreAllMocks();
});

function makeFile(content: string): File {
  return new File([content], "graph.aimgraph.json", { type: "application/json" });
}

async function readBlob(blob: Blob): Promise<string> {
  return blob.text();
}

function fireChange(input: HTMLInputElement, file: File) {
  fireEvent.change(input, { target: { files: [file] } });
}

describe("GraphIO save (AR-2)", () => {
  it("downloads canonical bytes with an .aimgraph.json filename", async () => {
    useFlowStore.setState({
      nodes: [
        {
          id: "src",
          type: "schema",
          position: { x: 0, y: 0 },
          data: { schema: videoSource, params: { video_path: "clip.avi" } },
        },
      ],
      edges: [
        {
          id: "e1",
          source: "src",
          sourceHandle: "frames",
          target: "p2d",
          targetHandle: "frames",
        },
      ],
    });

    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    let capturedBlob: Blob | undefined;
    let capturedDownload = "";
    vi.spyOn(URL, "createObjectURL").mockImplementation((obj: Blob | MediaSource) => {
      capturedBlob = obj as Blob;
      return "blob:mock";
    });
    vi.spyOn(HTMLAnchorElement.prototype, "download", "get").mockImplementation(function () {
      return capturedDownload;
    });
    vi.spyOn(HTMLAnchorElement.prototype, "download", "set").mockImplementation(function (this: HTMLAnchorElement, v: string) {
      capturedDownload = v;
    });

    render(<GraphIO catalog={catalogProvider} />);
    screen.getByTestId("graphio-save").click();

    await waitFor(() => {
      expect(capturedBlob).toBeDefined();
    });

    const expected = serializeGraph(
      fromFlow(useFlowStore.getState().nodes, useFlowStore.getState().edges),
    );
    expect(await readBlob(capturedBlob!)).toBe(expected);
    expect(capturedDownload).toBe("graph.aimgraph.json");
    expect(click).toHaveBeenCalled();
    expect(revoke).toHaveBeenCalled();
  });
});

describe("GraphIO load (AR-2)", () => {
  it("loads a canonical v1.0 file and merges nodes/edges by id", async () => {
    render(<GraphIO catalog={catalogProvider} />);
    const input = screen.getByTestId("graphio-load") as HTMLInputElement;
    fireChange(input, makeFile(V10_CANONICAL));

    await waitFor(() => {
      expect(useFlowStore.getState().nodes).toHaveLength(1);
    });
    const node = useFlowStore.getState().nodes[0];
    expect(node.id).toBe("src");
    expect(node.data.params.video_path).toBe("from.file.avi");
    expect(node.position).toEqual({ x: 50, y: 60 });
    expect(useFlowStore.getState().edges[0].source).toBe("src");
    expect(useFlowStore.getState().edges[0].sourceHandle).toBe("frames");
  });

  it("rejects an unsupported v0.1 file and shows an error without mutating", async () => {
    useFlowStore.setState({
      nodes: [
        {
          id: "existing",
          type: "schema",
          position: { x: 0, y: 0 },
          data: { schema: videoSource, params: {} },
        },
      ],
    });
    render(<GraphIO catalog={catalogProvider} />);
    const input = screen.getByTestId("graphio-load") as HTMLInputElement;
    fireChange(input, makeFile(V01_CANONICAL));

    await waitFor(() => {
      expect(screen.getByTestId("graphio-error")).toHaveTextContent(/unsupported version/);
    });
    expect(useFlowStore.getState().nodes).toHaveLength(1);
    expect(useFlowStore.getState().nodes[0].id).toBe("existing");
  });
});
