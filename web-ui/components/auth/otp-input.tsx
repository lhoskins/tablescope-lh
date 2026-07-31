"use client";

import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

export interface OtpInputProps {
  value: string;
  onChange: (value: string) => void;
  length?: number;
  label?: string;
  autoFocus?: boolean;
  disabled?: boolean;
  error?: boolean;
}

export function OtpInput({
  value,
  onChange,
  length = 6,
  label = "Verification code",
  autoFocus = false,
  disabled = false,
  error = false,
}: OtpInputProps) {
  const id = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [caretIndex, setCaretIndex] = useState(0);
  const [focused, setFocused] = useState(false);

  const digits = value.replace(/\D/g, "").slice(0, length);

  // Mount only. Keying this on `digits.length` meant every deletion re-ran it
  // and slammed the caret back to the end: correcting a mistyped middle digit
  // deleted it, jumped to the end, and re-inserted the fix in the wrong place —
  // so a wrong code could not be corrected, only cleared and retyped.
  const autoFocused = useRef(false);
  useEffect(() => {
    if (!autoFocus || autoFocused.current) return;
    autoFocused.current = true;
    inputRef.current?.focus();
    setCaretIndex(digits.length);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoFocus]);

  // setSelectionRange() below fires a native "select" event when it changes
  // the selection (this is standard input behaviour, not test-only), and that
  // event is wired to updateCaretFromInput via onSelect. Left unguarded, the
  // component's own caret-restore triggers "user changed selection", which
  // then overwrites the caretIndex a keystroke just computed with a stale
  // read — producing scrambled digit order. This flag marks the very next
  // select event as self-inflicted so updateCaretFromInput can ignore it.
  const suppressNextSelect = useRef(false);

  useLayoutEffect(() => {
    suppressNextSelect.current = true;
    inputRef.current?.setSelectionRange(caretIndex, caretIndex);
  }, [caretIndex, digits]);

  function updateCaretFromInput() {
    if (suppressNextSelect.current) {
      suppressNextSelect.current = false;
      return;
    }
    const input = inputRef.current;
    if (!input) return;
    let idx = input.selectionStart ?? digits.length;
    idx = Math.max(0, Math.min(idx, digits.length));
    setCaretIndex(idx);
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const raw = e.target.value;
    const next = raw.replace(/\D/g, "").slice(0, length);
    const input = e.target;
    let nextCaret = input.selectionStart ?? next.length;
    nextCaret = Math.max(0, Math.min(nextCaret, next.length));
    onChange(next);
    setCaretIndex(nextCaret);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    const input = e.currentTarget;
    const start = input.selectionStart ?? digits.length;
    const end = input.selectionEnd ?? digits.length;

    switch (e.key) {
      case "ArrowLeft":
        e.preventDefault();
        setCaretIndex(Math.max(0, start - 1));
        return;
      case "ArrowRight":
        e.preventDefault();
        setCaretIndex(Math.min(digits.length, start + 1));
        return;
      case "Home":
        e.preventDefault();
        setCaretIndex(0);
        return;
      case "End":
        e.preventDefault();
        setCaretIndex(digits.length);
        return;
      case "Backspace":
      case "Delete": {
        e.preventDefault();
        const isBackspace = e.key === "Backspace";
        let next = digits;
        let nextCaret = start;
        if (start !== end) {
          next = digits.slice(0, start) + digits.slice(end);
          nextCaret = start;
        } else if (isBackspace && start > 0) {
          next = digits.slice(0, start - 1) + digits.slice(start);
          nextCaret = start - 1;
        } else if (!isBackspace && start < digits.length) {
          next = digits.slice(0, start) + digits.slice(start + 1);
          nextCaret = start;
        }
        onChange(next);
        setCaretIndex(Math.max(0, nextCaret));
        return;
      }
      default:
        if (/^[0-9]$/.test(e.key)) {
          e.preventDefault();
          const hasSelection = start !== end;
          let next: string;
          let nextCaret: number;
          if (hasSelection) {
            next = digits.slice(0, start) + e.key + digits.slice(end);
            nextCaret = start + 1;
          } else if (digits.length >= length) {
            // Overwrite the digit at the caret when the code is full.
            next = digits.slice(0, start) + e.key + digits.slice(start + 1);
            nextCaret = Math.min(length, start + 1);
          } else {
            next = digits.slice(0, start) + e.key + digits.slice(start);
            nextCaret = Math.min(length, start + 1);
          }
          onChange(next.slice(0, length));
          setCaretIndex(nextCaret);
        }
    }
  }

  function handlePaste(e: React.ClipboardEvent<HTMLInputElement>) {
    e.preventDefault();
    const pasted = e.clipboardData.getData("text");
    const pastedDigits = pasted.replace(/\D/g, "").slice(0, length);
    const input = inputRef.current;
    const start = input?.selectionStart ?? digits.length;
    const end = input?.selectionEnd ?? digits.length;
    const next = digits.slice(0, start) + pastedDigits + digits.slice(end);
    const trimmed = next.slice(0, length);
    onChange(trimmed);
    setCaretIndex(Math.min(length, start + pastedDigits.length));
  }

  function focusCell(index: number) {
    inputRef.current?.focus();
    setCaretIndex(Math.min(index, digits.length));
    setFocused(true);
  }

  return (
    <div className="space-y-1.5">
      <label
        htmlFor={id}
        className="block text-sm font-medium text-ink-secondary"
      >
        {label}
      </label>
      <div
        className="relative inline-flex gap-2"
        onClick={() => {
          if (!disabled) {
            inputRef.current?.focus();
            setFocused(true);
          }
        }}
      >
        <input
          ref={inputRef}
          id={id}
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          autoComplete="one-time-code"
          maxLength={length}
          value={digits}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onSelect={updateCaretFromInput}
          onClick={updateCaretFromInput}
          disabled={disabled}
          aria-invalid={error}
          className="sr-only"
        />
        {Array.from({ length }).map((_, i) => {
          const isActive = focused && i === caretIndex;
          const hasValue = i < digits.length;
          return (
            <button
              key={i}
              type="button"
              tabIndex={-1}
              aria-hidden="true"
              disabled={disabled}
              onClick={(e) => {
                e.stopPropagation();
                focusCell(i);
              }}
              className={[
                "flex h-12 w-10 items-center justify-center rounded-md border text-center text-lg font-medium transition-all",
                error
                  ? "border-danger"
                  : isActive
                    ? "border-brand-500 ring-2 ring-brand-500"
                    : "border-line-tertiary",
                hasValue ? "text-ink-primary" : "text-ink-tertiary",
                disabled ? "cursor-not-allowed opacity-50" : "",
              ].join(" ")}
            >
              {hasValue ? digits[i] : isActive ? "▏" : ""}
            </button>
          );
        })}
      </div>
    </div>
  );
}
