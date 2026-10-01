import { useState } from "react";
import { Button } from "@/design-system/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/design-system/ui/dialog";
import { type Captured, captureNote } from "./api";
import { loadDraft, saveDraft } from "./draft";
import { captureErrorCopy } from "./labels";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: (result: Captured) => void;
};

export function CaptureDialog({ open, onOpenChange, onSaved }: Props) {
  const [text, setText] = useState(loadDraft);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canSave = text.trim().length > 0 && !saving;

  function change(value: string) {
    setText(value);
    saveDraft(value);
  }

  async function save() {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    const result = await captureNote(text);
    setSaving(false);
    if (result.ok) {
      saveDraft("");
      setText("");
      onOpenChange(false);
      onSaved?.(result);
    } else {
      setError(captureErrorCopy(result.status, result.detail));
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>Capture a note</DialogTitle>
        <DialogDescription>Saved to the Inbox folder of your vault.</DialogDescription>
        <textarea
          aria-label="Note"
          autoFocus
          rows={8}
          value={text}
          onChange={(e) => change(e.target.value)}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
              e.preventDefault();
              void save();
            }
          }}
          className="mt-4 w-full rounded-md border border-border-input bg-surface p-2 text-sm"
        />
        {error ? (
          <p role="alert" className="mt-2 text-sm text-danger-fg">
            {error}
          </p>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={!canSave}>
            Save
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
