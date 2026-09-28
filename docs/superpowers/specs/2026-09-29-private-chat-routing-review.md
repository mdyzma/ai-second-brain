## Spec Review

**Spec:** [Private chat routing](2026-09-29-private-chat-routing-design.md)

**Reviewer:** independent general-purpose subagent, 2026-09-29.

**Status:** Approved

**Issues (if any):** None that block implementation planning.

The first review found an undefined context-budget requirement. The revision explicitly defers token-exact budgeting, acknowledges possible local runtime truncation, and defines handling of provider-reported limit errors. The reviewer approved the revised scope, routing boundaries, configuration, failures, compatibility and acceptance criteria.

**Recommendations (advisory, do not block approval):**

- Give cloud mode a system prompt that does not claim access to local memory. Incorporated in section 4.
- Carry the documented context-truncation limitation into operator instructions.
- Report deployment smoke checks separately from automated tests. Document approval does not establish runtime readiness.

Approval applies to this first implementation slice. The original full prompt remains too broad and underspecified for one plan; see the [assessment](2026-09-29-second-brain-assessment.md). Human approval of the proposed direction remains separate from this technical review.

Validation performed for this documentation task: repository/source inspection, placeholder scan and local Markdown-link checks. No application code changed, and no runtime tests, database connections, model calls or hardware actions were performed.
