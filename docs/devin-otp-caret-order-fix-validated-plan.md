# Devin-Ready Plan: 2FA Code Entered Out of Order (Digits Scramble Instead of Appending)

**Status:** Root-caused, fixed, and verified against the test suite in this
branch (`devin/otp-caret-order-fix`). No further investigation should be
needed — this doc records the trace so the fix can be reviewed quickly, and
the regression test now guards it.

## Reported symptom

> When entering 2FA code, its not moving to the next digit. It appears to
> enter the code on the first digit and push the numbers to the right. The
> code is entered backward.

Typing `1 2 3 4 5 6` in order into the OTP field at
`web-ui/components/auth/otp-input.tsx` does not produce `123456`.

## Root cause

`OtpInput` uses a real (visually hidden, `sr-only`) `<input>` as the source
of keyboard truth, plus six decorative `<button>` cells for display. Two
mechanisms both try to keep the *native* DOM caret and the component's
`caretIndex` React state in sync, and they fight each other:

1. `handleKeyDown` computes the correct insertion point and caret position
   for a keystroke, then calls `onChange(next)` + `setCaretIndex(nextCaret)`.
2. After the resulting re-render, a `useLayoutEffect` restores the native
   caret to match the new `caretIndex`:

   ```tsx
   useLayoutEffect(() => {
     inputRef.current?.setSelectionRange(caretIndex, caretIndex);
   }, [caretIndex, digits]);
   ```
3. `HTMLInputElement.setSelectionRange()` fires a native `select` event
   whenever it changes the selection — this is standard input behavior, not
   a test-only artifact (MDN: *"the selectionchange event ... is also fired
   when `setSelectionRange()` ... changes the selection"*; Chrome/Firefox
   additionally fire `select` for a programmatic range change on a focused
   field).
4. That `select` event is wired to `onSelect={updateCaretFromInput}`
   (`otp-input.tsx:187`), which reads `input.selectionStart` off the DOM and
   calls `setCaretIndex(idx)` again — this handler exists to pick up
   *user-driven* selection changes (click, drag-select), but it cannot tell
   the difference between that and a selection change the component itself
   just made.

Net effect: the layout effect's own caret restore for keystroke *N*
re-triggers `updateCaretFromInput`, which overwrites the `caretIndex` that
keystroke *N* had just computed with a stale read. Keystroke *N+1* then
reads the wrong `selectionStart` from `e.currentTarget.selectionStart` in
`handleKeyDown` (`otp-input.tsx:74`) and inserts at the wrong position. The
error compounds every keystroke.

### Empirical confirmation

Instrumented every `setCaretIndex` call site and traced a sequential
`1,2,3,4,5,6` keydown sequence. Reproduced with a `console.log` trace
(trimmed):

```
keydown '1'  start=0 end=0                     setCaretIndex(nextCaret=1)
updateCaretFromInput fires: idx=0 (stale)       setCaretIndex(0)   <- clobbers the 1 above
layoutEffect commits: caretIndex=0, digits='1'
keydown '2'  start=0 end=0  (wrong: should be 1) digitsBefore='1'
  -> next = digits.slice(0,0) + '2' + digits.slice(0) = '21'      <- inserted before '1', not after
...
keydown '3'  start=1 end=1  digitsBefore='21'   setCaretIndex(nextCaret=2)
updateCaretFromInput fires: idx=1 (stale)       setCaretIndex(1)   <- clobbers again
...
final digits: '246531'
```

This is deterministic given the mechanism above and is not an artifact of
the test environment: the same `select`-event feedback loop fires in real
browsers, since `setSelectionRange()` firing `select` on a changed selection
is standard DOM behavior, not something happy-dom invented. This matches
the reported real-device symptom of digits landing out of order.

A regression test reproducing this exact sequence is included below and
currently passes against the fix.

## Fix

Guard the layout effect's own `setSelectionRange()` call so the `select`
event it provokes doesn't feed back into `caretIndex`. A ref flag marks the
very next `select` as self-inflicted; `updateCaretFromInput` consumes and
clears it instead of acting on it. Genuine user-driven selection changes
(click, drag-select) are unaffected — the flag is only ever set by the
effect, immediately before the one DOM call that can trigger it.

`web-ui/components/auth/otp-input.tsx`:

```diff
+  // setSelectionRange() below fires a native "select" event when it changes
+  // the selection (this is standard input behaviour, not test-only), and that
+  // event is wired to updateCaretFromInput via onSelect. Left unguarded, the
+  // component's own caret-restore triggers "user changed selection", which
+  // then overwrites the caretIndex a keystroke just computed with a stale
+  // read — producing scrambled digit order. This flag marks the very next
+  // select event as self-inflicted so updateCaretFromInput can ignore it.
+  const suppressNextSelect = useRef(false);
+
   useLayoutEffect(() => {
+    suppressNextSelect.current = true;
     inputRef.current?.setSelectionRange(caretIndex, caretIndex);
   }, [caretIndex, digits]);

   function updateCaretFromInput() {
+    if (suppressNextSelect.current) {
+      suppressNextSelect.current = false;
+      return;
+    }
     const input = inputRef.current;
     if (!input) return;
     let idx = input.selectionStart ?? digits.length;
     idx = Math.max(0, Math.min(idx, digits.length));
     setCaretIndex(idx);
   }
```

No other function in the file changes. `handleKeyDown`, `handlePaste`, and
`handleChange` already read `start`/`end` straight from the native DOM at
the moment of the event rather than from `caretIndex`, so they were never
the source of the bug — they were just fed a corrupted starting position by
the feedback loop above.

## Regression test

Folded into the existing suite as `otp-input.test.tsx`, new `describe`
block `"typing in order"`:

```tsx
describe("typing in order", () => {
  function Controlled() {
    const [value, setValue] = React.useState("");
    return <OtpInput value={value} onChange={setValue} autoFocus />;
  }

  it("keeps digits in the order they were typed", async () => {
    render(<Controlled />);
    const input = screen.getByLabelText(/verification code/i) as HTMLInputElement;
    for (const digit of ["1", "2", "3", "4", "5", "6"]) {
      fireEvent.keyDown(input, { key: digit });
    }
    await waitFor(() => expect(input.value).toBe("123456"));
  });
});
```

Verified: fails with `expected '246531' to be '123456'` against the
pre-fix code, passes against the fix. Full suite
(`components/auth/otp-input.test.tsx`, 8 tests) passes, including the
pre-existing "correcting a mistake" tests for the earlier autoFocus-related
fix — this change does not touch that code path.

## Verification performed

- `npx vitest run components/auth/otp-input.test.tsx` — 8/8 pass.
- `npx tsc --noEmit` — no errors introduced.
- `npx eslint components/auth/otp-input.tsx components/auth/otp-input.test.tsx` — clean.

## Out of scope

- The pre-existing `act(...)` console warnings on the two "correcting a
  mistake" tests are unrelated and predate this change (same
  autoFocus-effect async-flush timing noted in that describe block's own
  comment); not touched here.
- No change to `handleChange`, `handlePaste`, `handleKeyDown`'s
  arrow/backspace/delete branches, or `focusCell` — all already read caret
  position from the correct source (native DOM at event time, or explicit
  `setCaretIndex` calls) and were not implicated.

## Branch / PR

Branch: `devin/otp-caret-order-fix`, based on
`origin/devin/r-echarts-e2e-validation`. Fix, test, and this doc are the
only changes on the branch.
