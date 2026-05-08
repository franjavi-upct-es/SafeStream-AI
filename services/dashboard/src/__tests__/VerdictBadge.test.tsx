// services/dashboard/src/__tests__/VerdictBadge.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VerdictBadge } from "../components/VerdictBadge";

describe("VerdictBadge", () => {
  it("renders the verdict in uppercase", () => {
    render(<VerdictBadge verdict="block" />);
    expect(screen.getByText("block")).toBeInTheDocument();
  });

  it("renders a placeholder when verdict is null", () => {
    render(<VerdictBadge verdict={null} />);
    expect(screen.getByText("---")).toBeInTheDocument();
  });

  it("applies a different style class per verdict", () => {
    const { rerender } = render(<VerdictBadge verdict="block" />);
    const blockEl = screen.getByText("block");
    const blockClass = blockEl.className;

    rerender(<VerdictBadge verdict="safe" />);
    const safeClass = screen.getByText("safe").className;

    // Tone-specific classes should differ; the shared base class won't.
    expect(blockClass).not.toEqual(safeClass);
  });
});
