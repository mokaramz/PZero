import { useCallback, useState } from "react";

function read(key: string): boolean {
  try {
    return localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function write(key: string, on: boolean) {
  try {
    localStorage.setItem(key, on ? "1" : "0");
  } catch {
    /* private window: the toggle still works for this session */
  }
}

/** A remembered on/off shell preference ("1" / "0" under `key`), written only when toggled — a convenience, never
 *  required. */
export function useStoredFlag(key: string): [boolean, () => void] {
  const [on, setOn] = useState(() => read(key));
  const toggle = useCallback(
    () =>
      setOn((v) => {
        write(key, !v);
        return !v;
      }),
    [key],
  );
  return [on, toggle];
}
