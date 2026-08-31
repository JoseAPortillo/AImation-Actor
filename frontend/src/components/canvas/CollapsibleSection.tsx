import { useState, type ReactNode } from "react";

interface CollapsibleSectionProps {
  title: string;
  defaultOpen?: boolean;
  children: ReactNode;
}

export function CollapsibleSection({
  title,
  defaultOpen = true,
  children,
}: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        style={{
          background: "none",
          border: "none",
          borderTop: open ? "1px solid #2a2a2a" : "none",
          color: "#999",
          fontSize: 9,
          fontWeight: 600,
          textAlign: "left",
          padding: "3px 0",
          cursor: "pointer",
          fontFamily: "inherit",
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <span>{title}</span>
        <span style={{ fontSize: 8, color: "#555" }}>
          {open ? "▼" : "▶"}
        </span>
      </button>
      {open && <div>{children}</div>}
    </div>
  );
}
