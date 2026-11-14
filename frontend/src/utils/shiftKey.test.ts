import { describe, it, expect } from 'vitest';
import {
  isValidShiftKey,
  parseShiftKey,
  formatShiftKey,
  getDefaultShiftKey,
  isLeapYear,
  isValidCalendarDate,
  isValidDateString,
  getLocalDateString,
  stepCalendarDate,
} from './shiftKey';

describe('shiftKey utility module', () => {
  describe('isLeapYear', () => {
    it('correctly identifies leap years and non-leap years', () => {
      expect(isLeapYear(2028)).toBe(true);
      expect(isLeapYear(2024)).toBe(true);
      expect(isLeapYear(2000)).toBe(true); // divisible by 400
      expect(isLeapYear(1900)).toBe(false); // divisible by 100 but not 400
      expect(isLeapYear(2026)).toBe(false);
      expect(isLeapYear(2025)).toBe(false);
    });
  });

  describe('isValidCalendarDate', () => {
    it('validates 31-day months', () => {
      expect(isValidCalendarDate(2026, 1, 31)).toBe(true);
      expect(isValidCalendarDate(2026, 1, 32)).toBe(false);
      expect(isValidCalendarDate(2026, 7, 31)).toBe(true);
      expect(isValidCalendarDate(2026, 8, 31)).toBe(true);
      expect(isValidCalendarDate(2026, 12, 31)).toBe(true);
    });

    it('validates 30-day months', () => {
      expect(isValidCalendarDate(2026, 4, 30)).toBe(true);
      expect(isValidCalendarDate(2026, 4, 31)).toBe(false);
      expect(isValidCalendarDate(2026, 6, 30)).toBe(true);
      expect(isValidCalendarDate(2026, 6, 31)).toBe(false);
      expect(isValidCalendarDate(2026, 9, 30)).toBe(true);
      expect(isValidCalendarDate(2026, 9, 31)).toBe(false);
      expect(isValidCalendarDate(2026, 11, 30)).toBe(true);
      expect(isValidCalendarDate(2026, 11, 31)).toBe(false);
    });

    it('validates February for leap and non-leap years', () => {
      expect(isValidCalendarDate(2028, 2, 29)).toBe(true);
      expect(isValidCalendarDate(2028, 2, 30)).toBe(false);
      expect(isValidCalendarDate(2026, 2, 28)).toBe(true);
      expect(isValidCalendarDate(2026, 2, 29)).toBe(false);
      expect(isValidCalendarDate(2000, 2, 29)).toBe(true);
      expect(isValidCalendarDate(1900, 2, 29)).toBe(false);
    });

    it('rejects invalid month numbers or day numbers', () => {
      expect(isValidCalendarDate(2026, 0, 15)).toBe(false);
      expect(isValidCalendarDate(2026, 13, 1)).toBe(false);
      expect(isValidCalendarDate(2026, 5, 0)).toBe(false);
      expect(isValidCalendarDate(2026, 5, -1)).toBe(false);
    });
  });

  describe('isValidDateString', () => {
    it('returns true for valid YYYY-MM-DD strings', () => {
      expect(isValidDateString('2026-11-14')).toBe(true);
      expect(isValidDateString('2028-02-29')).toBe(true);
    });

    it('returns false for malformed or invalid dates', () => {
      expect(isValidDateString('2026-2-14')).toBe(false);
      expect(isValidDateString('26-11-14')).toBe(false);
      expect(isValidDateString('2026-02-29')).toBe(false);
      expect(isValidDateString('2026/11/14')).toBe(false);
      expect(isValidDateString('')).toBe(false);
    });
  });

  describe('isValidShiftKey', () => {
    it('returns true for valid canonical shift keys across all shift types', () => {
      expect(isValidShiftKey('2026-11-14-early')).toBe(true);
      expect(isValidShiftKey('2026-11-14-late')).toBe(true);
      expect(isValidShiftKey('2026-11-14-night')).toBe(true);
      expect(isValidShiftKey('2028-02-29-early')).toBe(true); // Leap year
      expect(isValidShiftKey('2024-12-31-night')).toBe(true);
    });

    it('returns false for malformed patterns', () => {
      expect(isValidShiftKey('')).toBe(false);
      expect(isValidShiftKey('2026-11-14')).toBe(false);
      expect(isValidShiftKey('2026-11-14-afternoon')).toBe(false);
      expect(isValidShiftKey('2026-11-14-EARLY')).toBe(false);
      expect(isValidShiftKey('14-11-2026-early')).toBe(false);
      expect(isValidShiftKey('2026/11/14-early')).toBe(false);
      expect(isValidShiftKey('2026-11-14-early-extra')).toBe(false);
      expect(isValidShiftKey('random-string')).toBe(false);
    });

    it('returns false for invalid calendar dates matching the regex structure', () => {
      expect(isValidShiftKey('2026-02-31-early')).toBe(false);
      expect(isValidShiftKey('2026-04-31-late')).toBe(false);
      expect(isValidShiftKey('2026-13-01-night')).toBe(false);
      expect(isValidShiftKey('2026-00-10-early')).toBe(false);
      expect(isValidShiftKey('2026-02-29-early')).toBe(false); // Non-leap year
      expect(isValidShiftKey('1900-02-29-late')).toBe(false); // Centurial non-leap
    });
  });

  describe('parseShiftKey', () => {
    it('parses valid shiftKey into date and shiftType', () => {
      expect(parseShiftKey('2026-11-14-early')).toEqual({
        date: '2026-11-14',
        shiftType: 'early',
      });
      expect(parseShiftKey('2026-11-14-late')).toEqual({
        date: '2026-11-14',
        shiftType: 'late',
      });
      expect(parseShiftKey('2028-02-29-night')).toEqual({
        date: '2028-02-29',
        shiftType: 'night',
      });
    });

    it('returns null for any invalid or malformed key', () => {
      expect(parseShiftKey('')).toBeNull();
      expect(parseShiftKey('2026-11-14')).toBeNull();
      expect(parseShiftKey('2026-11-14-afternoon')).toBeNull();
      expect(parseShiftKey('2026-02-31-early')).toBeNull();
      expect(parseShiftKey('2026-02-29-early')).toBeNull();
      expect(parseShiftKey('invalid')).toBeNull();
    });
  });

  describe('formatShiftKey', () => {
    it('returns the concatenated canonical string YYYY-MM-DD-(early|late|night)', () => {
      expect(formatShiftKey('2026-11-14', 'early')).toBe('2026-11-14-early');
      expect(formatShiftKey('2026-11-14', 'late')).toBe('2026-11-14-late');
      expect(formatShiftKey('2026-11-14', 'night')).toBe('2026-11-14-night');
    });
  });

  describe('getDefaultShiftKey & getLocalDateString', () => {
    it('returns a valid shiftKey for a provided referenceDate with default early shift without timezone drift', () => {
      const fixedDate = new Date(2026, 4, 15, 14, 30, 0); // May 15, 2026
      expect(getLocalDateString(fixedDate)).toBe('2026-05-15');
      expect(getDefaultShiftKey(fixedDate)).toBe('2026-05-15-early');
      expect(isValidShiftKey(getDefaultShiftKey(fixedDate))).toBe(true);
    });

    it('returns a valid shiftKey for today when referenceDate is omitted', () => {
      const defaultKey = getDefaultShiftKey();
      expect(isValidShiftKey(defaultKey)).toBe(true);
      expect(defaultKey).toMatch(/^\d{4}-\d{2}-\d{2}-early$/);
    });
  });

  describe('stepCalendarDate', () => {
    it('increments and decrements days within the same month', () => {
      expect(stepCalendarDate('2026-11-14', 1)).toBe('2026-11-15');
      expect(stepCalendarDate('2026-11-14', -1)).toBe('2026-11-13');
    });

    it('rolls over month and year boundaries correctly', () => {
      expect(stepCalendarDate('2026-12-31', 1)).toBe('2027-01-01');
      expect(stepCalendarDate('2027-01-01', -1)).toBe('2026-12-31');
    });

    it('handles leap year boundaries correctly', () => {
      // Leap year 2028: Feb 28 -> Feb 29 -> Mar 01
      expect(stepCalendarDate('2028-02-28', 1)).toBe('2028-02-29');
      expect(stepCalendarDate('2028-02-29', 1)).toBe('2028-03-01');
      expect(stepCalendarDate('2028-03-01', -1)).toBe('2028-02-29');

      // Non-leap year 2026: Feb 28 -> Mar 01
      expect(stepCalendarDate('2026-02-28', 1)).toBe('2026-03-01');
      expect(stepCalendarDate('2026-03-01', -1)).toBe('2026-02-28');
    });

    it('returns null if input date is invalid', () => {
      expect(stepCalendarDate('invalid-date', 1)).toBeNull();
      expect(stepCalendarDate('2026-02-29', 1)).toBeNull();
    });
  });
});
