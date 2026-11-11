import { createContext } from "react";

export type ToastKind = "ok" | "error" | "info";
export type ToastApi = { show: (text: string, kind?: ToastKind) => void };

export const ToastContext = createContext<ToastApi>({ show: () => undefined });
