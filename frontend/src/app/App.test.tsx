import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { App } from "../app/App";

describe("App shell", () => {
  it("renders the application title", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "AImation Flow" })).toBeInTheDocument();
  });
});
