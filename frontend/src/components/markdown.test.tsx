import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Markdown } from "./markdown";

afterEach(cleanup);

describe("<Markdown />", () => {
  it("renders citation markers as clickable chips", () => {
    const onCite = vi.fn();
    render(<Markdown content="Gradient descent follows the negative gradient [2]." sourceCount={3} onCite={onCite} />);
    fireEvent.click(screen.getByRole("button", { name: "Show source 2" }));
    expect(onCite).toHaveBeenCalledWith(2);
  });

  it("leaves out-of-range markers as plain text and renders math", () => {
    const { container } = render(<Markdown content="Update rule $\theta - \eta g$ [5]" sourceCount={2} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(container.textContent).toContain("[5]");
    expect(container.querySelector(".katex")).not.toBeNull();
  });
});
