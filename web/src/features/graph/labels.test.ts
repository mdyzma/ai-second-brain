import { describe, expect, it } from "vitest";
import { BUSY, entityErrorCopy, extractErrorCopy, queuedCopy, RELATION_LABEL } from "./labels";

describe("RELATION_LABEL", () => {
  it("maps every relation to forward and reverse wording", () => {
    expect(RELATION_LABEL).toEqual({
      runs_on: ["runs on", "runs"],
      uses: ["uses", "used by"],
      works_with: ["works with", "works with"],
      part_of: ["part of", "contains"],
      about: ["about", "discussed in"],
      mentions: ["mentions", "mentioned in"],
    });
  });
});

describe("entityErrorCopy", () => {
  it("maps codes to calm copy", () => {
    expect(entityErrorCopy(409, "name_taken", "tool")).toBe(
      "Another tool already has this name — merge instead?",
    );
    expect(entityErrorCopy(409, "busy")).toBe(BUSY);
    expect(BUSY).toBe("Someone else is changing the graph right now. Try again.");
    expect(entityErrorCopy(422, "parent_cycle")).toBe("That would make a loop.");
    expect(entityErrorCopy(422, "type_mismatch")).toBe(
      "Only entities of the same type can be merged.",
    );
    expect(entityErrorCopy(422, "invalid_action")).toBe("That change isn't allowed.");
    expect(entityErrorCopy(404, "not_found")).toBe("That entity is no longer in the review queue.");
    expect(entityErrorCopy(503)).toBe("The database is unavailable. Try again in a moment.");
    expect(entityErrorCopy(401)).toBe("Your session ended. Sign in again.");
    expect(entityErrorCopy(0)).toBe("Can't reach the server.");
    expect(entityErrorCopy(500, "boom <b>secret</b>")).toBe(
      "Couldn't save that change. Try again.",
    );
  });
});

describe("extract copy", () => {
  it("maps extraction errors and the queued line", () => {
    expect(extractErrorCopy(409, "extraction_unavailable")).toBe(
      "No local model is configured for extraction.",
    );
    expect(extractErrorCopy(503)).toBe("The database is unavailable. Try again in a moment.");
    expect(queuedCopy(1)).toBe("Queued 1 note for extraction.");
    expect(queuedCopy(3)).toBe("Queued 3 notes for extraction.");
  });
});
