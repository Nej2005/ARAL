import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import Icon from "../components/Icon";
import Sheet from "../components/Sheet";
import { setPasscode } from "../lib/passcode";

export default function PasscodeSheet({ wrong, onDone }: { wrong: boolean; onDone: () => void }) {
  const qc = useQueryClient();
  const [value, setValue] = useState("");
  return (
    <Sheet title="Passcode" onClose={onDone}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!value.trim()) return;
          setPasscode(value.trim());
          void qc.invalidateQueries();
          onDone();
        }}
        style={{ display: "grid", gap: 14 }}
      >
        <input className="input" type="password" autoFocus value={value} onChange={(e) => setValue(e.target.value)} aria-label="Passcode" placeholder={wrong ? "Wrong passcode" : "Enter passcode"} />
        <button className="btn primary big block" type="submit" disabled={!value.trim()}>
          <Icon name="check" />Unlock
        </button>
      </form>
    </Sheet>
  );
}
