import { useContext } from "react";

import { ToastContext, type ToastApi } from "./context";

/** `toast.show(text, kind)` — a short, non-blocking confirmation in the bottom-right corner. */
export function useToast(): ToastApi {
  return useContext(ToastContext);
}
