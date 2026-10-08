const KEY = "aral-passcode";
export const PASSCODE_EVENT = "aral:passcode-needed";

export function getPasscode(): string {
  try {
    return localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function setPasscode(v: string): void {
  try {
    if (v) localStorage.setItem(KEY, v);
    else localStorage.removeItem(KEY);
  } catch {
    /* private mode */
  }
}

/** Fired by the API client on a 401; App shows the passcode sheet. */
export function requestPasscode(wrong: boolean): void {
  window.dispatchEvent(new CustomEvent(PASSCODE_EVENT, { detail: { wrong } }));
}
