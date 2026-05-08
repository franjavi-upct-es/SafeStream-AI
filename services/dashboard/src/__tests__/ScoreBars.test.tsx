// services/dashboard/src/__tests__/ScoreBars.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ScoreBars } from "../components/ScoreBars";

describe("ScoreBars", () => {
  it("shows an empty state when scores is null", () => {
    render(<ScoreBars scores={null} />);
    expect(screen.getByText(/no scores recorded/i)).toBeInTheDocument();
  });

  it("shows an empty state when scores is empty", () => {
    render(<ScoreBars scores={{}} />);
    expect(screen.getByText(/no scores recorded/i)).toBeInTheDocument();
  });

  it("renders one row per score, sorted high to low", () => {
    render(
      <ScoreBars
        scores={{ insult: 0.32, toxic: 0.94, identity_hate: 0.12 }}
      />,
    );

    expect(screen.getByText(/0.94/)).toBeInTheDocument();
    expect(screen.getByText(/0.32/)).toBeInTheDocument();
    expect(screen.getByText(/0.12/)).toBeInTheDocument();

    // Labels are humanised (underscore -> space).
    expect(screen.getByText(/identity hate/i)).toBeInTheDocument();
  });
});
