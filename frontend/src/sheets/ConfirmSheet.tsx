import type { ReactNode } from "react";

import Icon from "../components/Icon";
import Sheet from "../components/Sheet";

/** "Are you sure?" for anything that deletes data. Cancel is the safe default focus. */
export default function ConfirmSheet({
  title,
  children,
  confirmLabel,
  busy = false,
  onConfirm,
  onClose,
}: {
  title: string;
  children?: ReactNode;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Sheet title={title} onClose={onClose}>
      {children}
      <div className="row">
        <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="btn primary" onClick={onConfirm} disabled={busy}>
          <Icon name="trash" />{busy ? "Deleting…" : confirmLabel}
        </button>
      </div>
    </Sheet>
  );
}
