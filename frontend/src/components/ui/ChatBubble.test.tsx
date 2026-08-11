import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChatBubble } from "./ChatBubble";

describe("ChatBubble", () => {
  it("labels Dira as an AI companion", () => {
    render(<ChatBubble sender="dira">hello</ChatBubble>);
    expect(screen.getByText(/Dira · AI companion/)).toBeInTheDocument();
  });

  it("shows the clinician name", () => {
    render(
      <ChatBubble sender="clinician" senderName="Your therapist">
        hello
      </ChatBubble>,
    );
    expect(screen.getByText("Your therapist")).toBeInTheDocument();
  });

  it("does not label the patient's own messages", () => {
    render(<ChatBubble sender="patient">hello</ChatBubble>);
    expect(screen.queryByText(/patient/)).not.toBeInTheDocument();
    expect(screen.getByText("hello")).toBeInTheDocument();
  });
});
