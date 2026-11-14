export type ShiftType = 'early' | 'late' | 'night';

export const SHIFT_TYPES: readonly ShiftType[] = ['early', 'late', 'night'] as const;

export interface ParsedShiftKey {
  date: string;
  shiftType: ShiftType;
}

const SHIFT_KEY_PATTERN = /^\d{4}-\d{2}-\d{2}-(early|late|night)$/;
const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * Checks if a given 4-digit year is a leap year in the Gregorian calendar.
 */
export function isLeapYear(year: number): boolean {
  return (year % 4 === 0 && year % 100 !== 0) || (year % 400 === 0);
}

/**
 * Validates whether year, month (1-12), and day (1-31) form a valid Gregorian calendar date.
 */
export function isValidCalendarDate(year: number, month: number, day: number): boolean {
  if (isNaN(year) || isNaN(month) || isNaN(day)) return false;
  if (year < 1 || year > 9999) return false;
  if (month < 1 || month > 12) return false;
  if (day < 1) return false;

  const daysInMonth = [
    31,
    isLeapYear(year) ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ];

  return day <= daysInMonth[month - 1];
}

/**
 * Checks if a date string in YYYY-MM-DD format is a valid Gregorian date.
 */
export function isValidDateString(dateStr: string): boolean {
  if (typeof dateStr !== 'string') return false;
  const match = dateStr.match(DATE_PATTERN);
  if (!match) return false;
  const year = parseInt(match[1], 10);
  const month = parseInt(match[2], 10);
  const day = parseInt(match[3], 10);
  return isValidCalendarDate(year, month, day);
}

/**
 * Validates whether key strictly matches ^\d{4}-\d{2}-\d{2}-(early|late|night)$
 * AND contains a valid Gregorian calendar date.
 */
export function isValidShiftKey(key: string): boolean {
  if (typeof key !== 'string' || !SHIFT_KEY_PATTERN.test(key)) {
    return false;
  }
  const lastHyphenIndex = key.lastIndexOf('-');
  const datePart = key.slice(0, lastHyphenIndex);
  return isValidDateString(datePart);
}

/**
 * Parses a valid shiftKey into { date, shiftType }, or returns null if invalid.
 */
export function parseShiftKey(key: string): ParsedShiftKey | null {
  if (!isValidShiftKey(key)) {
    return null;
  }
  const lastHyphenIndex = key.lastIndexOf('-');
  const date = key.slice(0, lastHyphenIndex);
  const shiftType = key.slice(lastHyphenIndex + 1) as ShiftType;
  return { date, shiftType };
}

/**
 * Concatenates date and shiftType into canonical YYYY-MM-DD-(early|late|night).
 */
export function formatShiftKey(date: string, shiftType: ShiftType): string {
  return `${date}-${shiftType}`;
}

/**
 * Returns today's local calendar date formatted as YYYY-MM-DD without timezone drift.
 */
export function getLocalDateString(referenceDate?: Date): string {
  const ref = referenceDate ?? new Date();
  const year = String(ref.getFullYear()).padStart(4, '0');
  const month = String(ref.getMonth() + 1).padStart(2, '0');
  const day = String(ref.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Returns a valid shiftKey for today's local calendar date in YYYY-MM-DD and default 'early' shift type.
 */
export function getDefaultShiftKey(referenceDate?: Date): string {
  const dateStr = getLocalDateString(referenceDate);
  return formatShiftKey(dateStr, 'early');
}

/**
 * Increments or decrements a YYYY-MM-DD date string by deltaDays calendar days.
 * Preserves pure calendar calculation without local DST drift.
 */
export function stepCalendarDate(dateStr: string, deltaDays: number): string | null {
  if (!isValidDateString(dateStr)) return null;
  const match = dateStr.match(DATE_PATTERN);
  if (!match) return null;
  const year = parseInt(match[1], 10);
  const month = parseInt(match[2], 10);
  const day = parseInt(match[3], 10);

  const d = new Date(Date.UTC(0, 0, 1));
  d.setUTCFullYear(year, month - 1, day + deltaDays);

  const newYear = String(d.getUTCFullYear()).padStart(4, '0');
  const newMonth = String(d.getUTCMonth() + 1).padStart(2, '0');
  const newDay = String(d.getUTCDate()).padStart(2, '0');
  return `${newYear}-${newMonth}-${newDay}`;
}
