import {
  AsYouType,
  getCountries,
  getCountryCallingCode,
  parsePhoneNumberFromString,
  type CountryCode,
} from "libphonenumber-js";

export { getCountries, getCountryCallingCode };
export type { CountryCode };

export function isSupportedCountry(iso: string): iso is CountryCode {
  return getCountries().includes(iso as CountryCode);
}

export function formatNational(iso: CountryCode, digits: string): string {
  const asYouType = new AsYouType(iso);
  return asYouType.input(digits);
}

export function normalizePhone(
  iso: CountryCode,
  value: string,
): string | null {
  const parsed = parsePhoneNumberFromString(value, iso);
  return parsed?.isValid() ? parsed.format("E.164") : null;
}

export function getCountryName(iso: CountryCode, locale = "en"): string {
  try {
    const display = new Intl.DisplayNames([locale], { type: "region" });
    return display.of(iso) ?? iso;
  } catch {
    return iso;
  }
}
