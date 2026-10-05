export const LANGUAGES: Record<string, string> = {
  en: "English",
  ar: "Arabic",
  "ar-JO": "Jordanian Arabic",
  "ar-EG": "Egyptian Arabic",
  es: "Spanish",
  "es-MX": "Mexican Spanish",
  fr: "French",
  hi: "Hindi",
  ur: "Urdu",
  zh: "Mandarin Chinese",
  pt: "Portuguese",
  tr: "Turkish",
};

export const languageName = (code: string) => LANGUAGES[code] ?? code;
export const baseLanguage = (code: string) => code.split("-")[0];

/** 2 = same dialect, 1 = same base language, 0 = no match. */
export function languageFit(requested: string, spoken: string[]): number {
  if (spoken.includes(requested)) return 2;
  const base = baseLanguage(requested);
  return spoken.some((s) => baseLanguage(s) === base) ? 1 : 0;
}
