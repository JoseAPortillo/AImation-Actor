import { useEffect } from "react";
import { useFlowStore } from "../../state/useFlowStore";

/**
 * Canvas keyboard shortcuts (KP-1).
 *
 * - Delete / Backspace → delete the selected node (history-backed, unlike React
 *   Flow's built-in remove changes, which bypass the store snapshot).
 * - Ctrl/Cmd+Z → undo; Ctrl/Cmd+Shift+Z / Ctrl+Y → redo.
 * - Ctrl/Cmd+D → duplicate the selected node.
 * - Escape → clear selection.
 *
 * Global shortcuts are suppressed while a text input, textarea, or content-
 * editable element has focus so typing never deletes canvas state. Only Escape
 * remains active there (it never mutates graph content).
 */
export function useKeyboardShortcuts(): void {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const typing =
        !!target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable);

      if (e.key === "Escape") {
        useFlowStore.getState().selectNode(null);
        return;
      }
      if (typing) return;

      const flow = useFlowStore.getState();
      const mod = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();

      if (mod && key === "z") {
        e.preventDefault();
        if (e.shiftKey) {
          flow.redo();
        } else {
          flow.undo();
        }
        return;
      }
      if (mod && key === "y") {
        e.preventDefault();
        flow.redo();
        return;
      }
      if (mod && key === "d") {
        e.preventDefault();
        if (flow.selectedNodeId) {
          flow.duplicateNode(flow.selectedNodeId);
        }
        return;
      }
      if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        if (flow.selectedNodeId) {
          flow.removeNode(flow.selectedNodeId);
          flow.selectNode(null);
        }
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}