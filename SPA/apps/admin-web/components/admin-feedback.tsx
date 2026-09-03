"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type ReactNode
} from "react";

type ToastTone = "success" | "error" | "info";

type ToastInput = {
  tone: ToastTone;
  title: string;
  message?: string;
  durationMs?: number;
};

type Toast = ToastInput & { id: number };

type ConfirmationOptions = {
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  tone?: "default" | "danger";
  input?: {
    label: string;
    placeholder?: string;
    required?: boolean;
    maxLength?: number;
  };
};

type ConfirmationResult = { confirmed: boolean; inputValue: string };

type AdminFeedbackValue = {
  notify: (toast: ToastInput) => void;
  requestConfirmation: (options: ConfirmationOptions) => Promise<ConfirmationResult>;
};

const AdminFeedbackContext = createContext<AdminFeedbackValue | null>(null);

export function useAdminFeedback() {
  const value = useContext(AdminFeedbackContext);
  if (!value) throw new Error("useAdminFeedback must be used inside AdminFeedbackProvider");
  return value;
}

export function AdminFeedbackProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [confirmation, setConfirmation] = useState<ConfirmationOptions | null>(null);
  const [inputValue, setInputValue] = useState("");
  const nextToastId = useRef(0);
  const timers = useRef(new Map<number, number>());
  const confirmationResolver = useRef<((result: ConfirmationResult) => void) | null>(null);
  const inputValueRef = useRef("");
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const descriptionId = useId();
  const inputId = useId();

  const dismissToast = useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (timer) window.clearTimeout(timer);
    timers.current.delete(id);
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback((toast: ToastInput) => {
    const id = ++nextToastId.current;
    setToasts((current) => [...current.slice(-2), { ...toast, id }]);
    const timer = window.setTimeout(() => dismissToast(id), toast.durationMs ?? 4_000);
    timers.current.set(id, timer);
  }, [dismissToast]);

  const requestConfirmation = useCallback((options: ConfirmationOptions) => {
    confirmationResolver.current?.({ confirmed: false, inputValue: "" });
    inputValueRef.current = "";
    setInputValue("");
    setConfirmation(options);
    return new Promise<ConfirmationResult>((resolve) => {
      confirmationResolver.current = resolve;
    });
  }, []);

  const closeConfirmation = useCallback((confirmed: boolean) => {
    confirmationResolver.current?.({ confirmed, inputValue: confirmed ? inputValueRef.current.trim() : "" });
    confirmationResolver.current = null;
    setConfirmation(null);
    inputValueRef.current = "";
    setInputValue("");
  }, []);

  useEffect(() => () => {
    timers.current.forEach((timer) => window.clearTimeout(timer));
    confirmationResolver.current?.({ confirmed: false, inputValue: "" });
  }, []);

  useEffect(() => {
    if (!confirmation) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (confirmation.input) inputRef.current?.focus();
    else cancelButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeConfirmation(false);
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      event.stopPropagation();
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), textarea:not([disabled])"
      ));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
      previousFocusRef.current?.focus();
    };
  }, [confirmation, closeConfirmation]);

  function submitConfirmation(event: FormEvent) {
    event.preventDefault();
    if (confirmation?.input?.required && !inputValue.trim()) return;
    closeConfirmation(true);
  }

  return <AdminFeedbackContext.Provider value={{ notify, requestConfirmation }}>
    {children}
    <div className="toast-region" aria-live="polite" aria-relevant="additions">
      {toasts.map((toast) => <div key={toast.id} className={`admin-toast ${toast.tone}`} role={toast.tone === "error" ? "alert" : "status"}>
        <span className="toast-icon" aria-hidden="true">{toast.tone === "success" ? "✓" : toast.tone === "error" ? "!" : "i"}</span>
        <div><strong>{toast.title}</strong>{toast.message && <p>{toast.message}</p>}</div>
        <button type="button" aria-label="Dismiss notification" onClick={() => dismissToast(toast.id)}>×</button>
        <span className="toast-progress" aria-hidden="true" style={{ animationDuration: `${toast.durationMs ?? 4_000}ms` }} />
      </div>)}
    </div>
    {confirmation && <div className="modal-backdrop confirmation-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closeConfirmation(false); }}>
      <div ref={dialogRef} className="confirmation-dialog" role="alertdialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId}>
        <form onSubmit={submitConfirmation}>
          <div className={`confirmation-symbol ${confirmation.tone === "danger" ? "danger" : ""}`} aria-hidden="true">{confirmation.tone === "danger" ? "!" : "✓"}</div>
          <h2 id={titleId}>{confirmation.title}</h2>
          <p id={descriptionId}>{confirmation.message}</p>
          {confirmation.input && <label htmlFor={inputId}>{confirmation.input.label}<textarea ref={inputRef} id={inputId} value={inputValue} onChange={(event) => { inputValueRef.current = event.target.value; setInputValue(event.target.value); }} placeholder={confirmation.input.placeholder} required={confirmation.input.required} maxLength={confirmation.input.maxLength ?? 300} /></label>}
          <div className="dialog-actions">
            <button ref={cancelButtonRef} type="button" onClick={() => closeConfirmation(false)}>{confirmation.cancelLabel}</button>
            <button type="submit" className={confirmation.tone === "danger" ? "danger-button" : "confirm-button"} disabled={confirmation.input?.required && !inputValue.trim()}>{confirmation.confirmLabel}</button>
          </div>
        </form>
      </div>
    </div>}
  </AdminFeedbackContext.Provider>;
}
