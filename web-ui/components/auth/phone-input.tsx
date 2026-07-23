"use client";

import { useId, useMemo } from "react";
import {
  formatNational,
  getCountries,
  getCountryCallingCode,
  getCountryName,
  isSupportedCountry,
  type CountryCode,
} from "@/lib/phone";

export interface PhoneInputProps {
  countryIso: string;
  nationalDigits: string;
  onCountryChange: (iso: string) => void;
  onNationalChange: (digits: string) => void;
  label?: string;
  hint?: string;
  error?: string | null;
  disabled?: boolean;
  placeholder?: string;
}

export function PhoneInput({
  countryIso,
  nationalDigits,
  onCountryChange,
  onNationalChange,
  label = "Mobile phone number",
  hint,
  error,
  disabled,
  placeholder,
}: PhoneInputProps) {
  const id = useId();
  const selectId = `${id}-country`;
  const inputId = `${id}-phone`;

  const safeIso = isSupportedCountry(countryIso) ? countryIso : "US";

  const countryOptions = useMemo(() => {
    return getCountries()
      .map((iso) => ({
        iso,
        name: getCountryName(iso),
        callingCode: `+${getCountryCallingCode(iso)}`,
      }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, []);

  const display = useMemo(
    () => formatNational(safeIso as CountryCode, nationalDigits),
    [safeIso, nationalDigits],
  );

  function handleCountryChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const iso = e.target.value;
    if (isSupportedCountry(iso)) {
      onCountryChange(iso);
    }
  }

  function handlePhoneChange(e: React.ChangeEvent<HTMLInputElement>) {
    const digits = e.target.value.replace(/\D/g, "");
    onNationalChange(digits);
  }

  return (
    <div className="space-y-1.5">
      <label htmlFor={inputId} className="block text-sm font-medium text-ink-secondary">
        {label}
      </label>
      <div className="flex gap-2">
        <label htmlFor={selectId} className="sr-only">
          Country
        </label>
        <select
          id={selectId}
          value={safeIso}
          onChange={handleCountryChange}
          disabled={disabled}
          className="shrink-0 rounded-md border border-line-tertiary bg-white px-2 py-2 text-sm text-ink-primary focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        >
          {countryOptions.map(({ iso, name, callingCode }) => (
            <option key={iso} value={iso}>
              {name} ({callingCode})
            </option>
          ))}
        </select>
        <input
          id={inputId}
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          value={display}
          onChange={handlePhoneChange}
          disabled={disabled}
          placeholder={placeholder}
          aria-invalid={Boolean(error)}
          className="min-w-0 flex-1 rounded-md border border-line-tertiary bg-white px-3 py-2 text-sm text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
      </div>
      {hint && <p className="text-caption text-ink-tertiary">{hint}</p>}
      {error && <p className="text-small text-danger">{error}</p>}
    </div>
  );
}
