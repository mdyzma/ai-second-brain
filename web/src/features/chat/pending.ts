/** The first question typed on /ask, handed to /ask/$sessionId once the session exists. */
const pending = new Map<string, string>();

export function setPendingQuestion(sessionId: string, question: string): void {
  pending.set(sessionId, question);
}

export function takePendingQuestion(sessionId: string): string | undefined {
  const question = pending.get(sessionId);
  pending.delete(sessionId);
  return question;
}
