import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SeverityLabel } from "./SeverityLabel";

describe("SeverityLabel", () => {
  it("always renders a text label, never color alone", () => {
    render(<SeverityLabel severity={3} />);
    expect(screen.getByText(/Severity 3: High/)).toBeInTheDocument();
  });

  it("labels every level", () => {
    for (const [severity, label] of [
      [0, "No concern"],
      [1, "Low"],
      [2, "Elevated"],
    ] as const) {
      const { unmount } = render(<SeverityLabel severity={severity} />);
      expect(screen.getByText(new RegExp(label))).toBeInTheDocument();
      unmount();
    }
  });
});
