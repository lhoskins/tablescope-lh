"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "@/lib/cn";

export interface AutosizeTextareaProps
  extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "rows"> {
  minRows?: number;
  maxRows?: number;
}

export const AutosizeTextarea = forwardRef<
  HTMLTextAreaElement,
  AutosizeTextareaProps
>(
  (
    { minRows = 2, maxRows = 8, className, style, value, onKeyDown, ...props },
    forwardedRef,
  ) => {
    const internalRef = useRef<HTMLTextAreaElement>(null);
    useImperativeHandle(forwardedRef, () => internalRef.current!);

    const [isComposing, setIsComposing] = useState(false);

    useEffect(() => {
      const el = internalRef.current;
      if (!el) return;

      const computed = window.getComputedStyle(el);
      const lineHeightStr = computed.lineHeight;
      const lineHeight =
        lineHeightStr === "normal"
          ? parseFloat(computed.fontSize) * 1.2
          : parseFloat(lineHeightStr);

      const minHeight = minRows * lineHeight;
      const maxHeight = maxRows * lineHeight;

      el.style.overflow = "hidden";
      el.style.height = "auto";
      const nextHeight = Math.max(el.scrollHeight, minHeight);
      if (nextHeight > maxHeight) {
        el.style.height = `${maxHeight}px`;
        el.style.overflowY = "auto";
      } else {
        el.style.height = `${nextHeight}px`;
        el.style.overflowY = "hidden";
      }
    }, [value, minRows, maxRows]);

    return (
      <textarea
        ref={internalRef}
        value={value}
        onCompositionStart={(e) => {
          setIsComposing(true);
          props.onCompositionStart?.(e);
        }}
        onCompositionEnd={(e) => {
          setIsComposing(false);
          props.onCompositionEnd?.(e);
        }}
        onKeyDown={(e) => {
          if (isComposing || e.nativeEvent.isComposing) {
            // Let the IME finish composing; never submit while composing.
            return;
          }
          onKeyDown?.(e);
        }}
        rows={minRows}
        className={cn(
          "block w-full resize-none bg-transparent outline-none",
          className,
        )}
        style={{ ...style }}
        {...props}
      />
    );
  },
);

AutosizeTextarea.displayName = "AutosizeTextarea";
