import { useEffect, useRef, useState } from "react";
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
  const inFlight = useRef(false);
  const current = useRef(text);
  const canSave = text.trim().length > 0 && !saving;

  useEffect(() => {
    if (open) setError(null);
  }, [open]);

  function change(value: string) {
    current.current = value;
    setText(value);
    setError(null);
    saveDraft(value);
  }

  async function save() {
    if (inFlight.current || text.trim().length === 0) return;
    inFlight.current = true;
    const sent = text;
    setSaving(true);
    setError(null);
    try {
      const result = await captureNote(sent);
      if (result.ok) {
        if (current.current === sent) {
          saveDraft("");
          current.current = "";
          setText("");
        }
        onOpenChange(false);
        onSaved?.(result);
      } else {
        setError(captureErrorCopy(result.status, result.detail));
      }
    } finally {
      inFlight.current = false;
      setSaving(false);
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
          readOnly={saving}
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
