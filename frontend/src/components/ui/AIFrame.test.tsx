import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AIFrame } from "./AIFrame";

describe("AIFrame", () => {
  it("always shows the AI generated chip", () => {
    render(<AIFrame>content</AIFrame>);
    expect(screen.getByText(/AI generated/)).toBeInTheDocument();
    expect(screen.getByText("content")).toBeInTheDocument();
  });

  it("shows a SIMULATED chip for fake provider output", () => {
    render(<AIFrame simulated>content</AIFrame>);
    expect(screen.getByText("SIMULATED")).toBeInTheDocument();
  });

  it("hides the SIMULATED chip for real output", () => {
    render(<AIFrame>content</AIFrame>);
    expect(screen.queryByText("SIMULATED")).not.toBeInTheDocument();
  });

  it("exposes model and prompt version as provenance", () => {
    render(
      <AIFrame model="fake-model" promptVersion="dira-v1">
        content
      </AIFrame>,
    );
    expect(screen.getByTitle("fake-model · dira-v1")).toBeInTheDocument();
  });
});
