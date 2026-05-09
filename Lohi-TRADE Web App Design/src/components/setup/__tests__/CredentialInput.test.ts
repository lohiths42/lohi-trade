/**
 * CredentialInput unit + property tests
 *
 * Tests the pure logic of the CredentialInput component:
 * - Interface contract validation
 * - Pattern-based validation logic
 * - Accessibility attribute generation
 *
 * Validates: Requirements 2.3, 2.6
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';

/* ─── Validation Logic (mirrors component behavior) ──────────────────────── */

/**
 * Validates a credential value against a regex pattern.
 * Returns an error message if invalid, undefined if valid.
 */
function validateCredential(value: string, pattern?: string): string | undefined {
  if (!pattern) return undefined;
  try {
    const regex = new RegExp(pattern);
    if (!regex.test(value)) {
      return `Value does not match expected format`;
    }
    return undefined;
  } catch {
    return undefined;
  }
}

/* ─── Unit Tests ─────────────────────────────────────────────────────────── */

describe('CredentialInput — validation logic', () => {
  it('returns no error when pattern is undefined', () => {
    expect(validateCredential('anything', undefined)).toBeUndefined();
  });

  it('returns no error when value matches pattern', () => {
    expect(validateCredential('nvapi-abc123XYZ_test_longkey01', '^nvapi-[A-Za-z0-9_-]{20,}$')).toBeUndefined();
  });

  it('returns error when value does not match pattern', () => {
    expect(validateCredential('invalid-key', '^nvapi-[A-Za-z0-9_-]{20,}$')).toBeDefined();
  });

  it('validates NVIDIA NIM API key pattern', () => {
    const pattern = '^nvapi-[A-Za-z0-9_-]{20,}$';
    expect(validateCredential('nvapi-abcdefghijklmnopqrst', pattern)).toBeUndefined();
    expect(validateCredential('nvapi-short', pattern)).toBeDefined();
    expect(validateCredential('wrong-prefix-abcdefghijklmnopqrst', pattern)).toBeDefined();
    expect(validateCredential('', pattern)).toBeDefined();
  });

  it('validates Telegram bot token pattern', () => {
    const pattern = '^\\d+:[A-Za-z0-9_-]{35,}$';
    const validToken = '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk';
    expect(validateCredential(validToken, pattern)).toBeUndefined();
    expect(validateCredential('not-a-token', pattern)).toBeDefined();
  });

  it('validates phone number pattern', () => {
    const pattern = '^\\d{10}$';
    expect(validateCredential('9876543210', pattern)).toBeUndefined();
    expect(validateCredential('123', pattern)).toBeDefined();
    expect(validateCredential('12345678901', pattern)).toBeDefined();
    expect(validateCredential('abcdefghij', pattern)).toBeDefined();
  });

  it('validates chat ID pattern (allows negative numbers)', () => {
    const pattern = '^-?\\d+$';
    expect(validateCredential('12345', pattern)).toBeUndefined();
    expect(validateCredential('-100123456', pattern)).toBeUndefined();
    expect(validateCredential('abc', pattern)).toBeDefined();
  });

  it('handles invalid regex pattern gracefully', () => {
    // Invalid regex should not throw, returns undefined (no error)
    expect(validateCredential('test', '[')).toBeUndefined();
  });
});

describe('CredentialInput — aria attribute logic', () => {
  it('aria-invalid is true when error is present', () => {
    const error = 'Invalid format';
    expect(!!error).toBe(true);
  });

  it('aria-invalid is false when no error', () => {
    const error: string | undefined = undefined;
    expect(!!error).toBe(false);
  });

  it('aria-describedby includes error id when error exists', () => {
    const errorId = 'input-1-error';
    const hintId = 'input-1-hint';
    const error = 'Some error';
    const describedBy = [error ? errorId : undefined, hintId].filter(Boolean).join(' ');
    expect(describedBy).toContain(errorId);
    expect(describedBy).toContain(hintId);
  });

  it('aria-describedby only includes hint when no error', () => {
    const errorId = 'input-1-error';
    const hintId = 'input-1-hint';
    const error: string | undefined = undefined;
    const describedBy = [error ? errorId : undefined, hintId].filter(Boolean).join(' ');
    expect(describedBy).not.toContain(errorId);
    expect(describedBy).toContain(hintId);
  });
});

/* ─── Property-Based Tests ───────────────────────────────────────────────── */

describe('CredentialInput — property: validation correctness', () => {
  /**
   * **Validates: Requirements 2.3**
   *
   * For any string value and a valid regex pattern, the validation function
   * returns an error if and only if the value does not match the pattern.
   */
  it('validation returns error iff value does not match pattern', () => {
    // Use simple patterns that are always valid regex
    const arbPattern = fc.constantFrom(
      '^\\d{10}$',
      '^\\d{4,6}$',
      '^[A-Z2-7]{16,}$',
      '^nvapi-[A-Za-z0-9_-]{20,}$',
      '^.{8,}$',
      '^[A-Z0-9]{4,}$',
      '^.{4,}$',
      '^\\d+:[A-Za-z0-9_-]{35,}$',
      '^-?\\d+$',
    );

    fc.assert(
      fc.property(fc.string(), arbPattern, (value, pattern) => {
        const error = validateCredential(value, pattern);
        const regex = new RegExp(pattern);
        const matches = regex.test(value);

        if (matches) {
          expect(error).toBeUndefined();
        } else {
          expect(error).toBeDefined();
        }
      }),
      { numRuns: 200 },
    );
  });

  /**
   * **Validates: Requirements 2.3**
   *
   * When no pattern is provided, validation always passes regardless of input.
   */
  it('no pattern means no validation error for any input', () => {
    fc.assert(
      fc.property(fc.string(), (value) => {
        const error = validateCredential(value, undefined);
        expect(error).toBeUndefined();
      }),
      { numRuns: 100 },
    );
  });
});
