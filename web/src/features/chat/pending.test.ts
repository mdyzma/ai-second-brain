import { expect, it } from "vitest";
import { setPendingQuestion, takePendingQuestion } from "./pending";

it("hands a question over exactly once", () => {
  setPendingQuestion("s1", "Hello?");
  expect(takePendingQuestion("s1")).toBe("Hello?");
  expect(takePendingQuestion("s1")).toBeUndefined();
});
