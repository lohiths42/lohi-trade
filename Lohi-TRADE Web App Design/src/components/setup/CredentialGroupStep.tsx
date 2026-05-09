import { useState, useCallback } from 'react';
import { ExternalLink, Loader2, CheckCircle2, XCircle } from 'lucide-react';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from '../ui/card';
import { CredentialInput } from './CredentialInput';
import type { CredentialGroupDef, ServiceStatus, TestResult } from '../../lib/setup-types';

/**
 * CredentialGroupStep — Renders a single credential group with inputs,
 * explanations, documentation link, and action buttons (Submit, Test, Skip).
 *
 * Manages local form state for credential inputs and validates against
 * the group's regex patterns before submission.
 *
 * Requirements: 2.1, 2.2, 2.4, 2.5, 3.1, 6.1, 6.2, 6.3, 6.6
 */

export interface CredentialGroupStepProps {
  group: CredentialGroupDef;
  status: ServiceStatus;
  onSubmit: (credentials: Record<string, string>) => Promise<void>;
  onSkip: () => void;
  onTest: () => Promise<TestResult>;
}

export function CredentialGroupStep({
  group,
  status,
  onSubmit,
  onSkip,
  onTest,
}: CredentialGroupStepProps) {
  // Local form state: one entry per credential key
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(group.credential_keys.map((key) => [key, ''])),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  const handleChange = useCallback((key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    // Clear error for this field when user types
    setErrors((prev) => {
      if (!prev[key]) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  /**
   * Validate all credential fields against their regex patterns.
   * Returns true if all fields pass validation.
   */
  const validate = useCallback((): boolean => {
    const newErrors: Record<string, string> = {};

    for (const key of group.credential_keys) {
      const value = values[key] ?? '';
      const pattern = group.validation_patterns[key];

      if (!value.trim()) {
        newErrors[key] = `${key} is required`;
      } else if (pattern) {
        try {
          const regex = new RegExp(pattern);
          if (!regex.test(value)) {
            newErrors[key] = `${key} does not match the expected format`;
          }
        } catch {
          // If pattern is invalid, skip regex validation
        }
      }
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [group.credential_keys, group.validation_patterns, values]);

  const handleSubmit = useCallback(async () => {
    if (!validate()) return;

    setSubmitting(true);
    try {
      await onSubmit(values);
    } finally {
      setSubmitting(false);
    }
  }, [validate, onSubmit, values]);

  const handleTest = useCallback(async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await onTest();
      setTestResult(result);
    } catch {
      setTestResult({
        success: false,
        response_time_ms: null,
        error: 'Connection test failed unexpectedly',
        suggestion: 'Check your network connection and try again',
      });
    } finally {
      setTesting(false);
    }
  }, [onTest]);

  const hasCredentialKeys = group.credential_keys.length > 0;

  return (
    <Card className="w-full max-w-2xl">
      <CardHeader>
        <div className="flex items-center gap-3">
          <CardTitle className="text-xl">{group.name}</CardTitle>
          <Badge variant={group.required ? 'default' : 'secondary'}>
            {group.required ? 'Required' : 'Optional'}
          </Badge>
        </div>
        <CardDescription className="text-sm leading-relaxed">
          {group.description}
        </CardDescription>
        <a
          href={group.documentation_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline mt-1 w-fit"
        >
          <ExternalLink className="size-3.5" />
          View documentation
        </a>
      </CardHeader>

      {hasCredentialKeys && (
        <CardContent className="space-y-4">
          {group.credential_keys.map((key) => (
            <CredentialInput
              key={key}
              label={key}
              name={key}
              value={values[key] ?? ''}
              onChange={(value) => handleChange(key, value)}
              tooltipHint={group.tooltip_hints[key] ?? ''}
              error={errors[key]}
              pattern={group.validation_patterns[key]}
            />
          ))}
        </CardContent>
      )}

      {/* Test Connection result display */}
      {testResult && (
        <CardContent>
          <div
            className={`flex items-start gap-2 rounded-md border p-3 text-sm ${
              testResult.success
                ? 'border-green-200 bg-green-50 text-green-800 dark:border-green-800 dark:bg-green-950 dark:text-green-200'
                : 'border-red-200 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200'
            }`}
            role="status"
            aria-live="polite"
          >
            {testResult.success ? (
              <CheckCircle2 className="size-5 shrink-0 text-green-600 dark:text-green-400" />
            ) : (
              <XCircle className="size-5 shrink-0 text-red-600 dark:text-red-400" />
            )}
            <div className="space-y-1">
              <p className="font-medium">
                {testResult.success
                  ? `Connection successful${testResult.response_time_ms ? ` (${testResult.response_time_ms}ms)` : ''}`
                  : testResult.error ?? 'Connection failed'}
              </p>
              {testResult.suggestion && !testResult.success && (
                <p className="text-xs opacity-80">{testResult.suggestion}</p>
              )}
            </div>
          </div>
        </CardContent>
      )}

      <CardFooter className="flex flex-wrap gap-3">
        {hasCredentialKeys && (
          <>
            <Button
              onClick={handleSubmit}
              disabled={submitting}
            >
              {submitting && <Loader2 className="size-4 animate-spin" />}
              {submitting ? 'Saving...' : 'Submit'}
            </Button>

            <Button
              variant="outline"
              onClick={handleTest}
              disabled={testing || status.status === 'unconfigured'}
            >
              {testing && <Loader2 className="size-4 animate-spin" />}
              {testing ? 'Testing...' : 'Test Connection'}
            </Button>
          </>
        )}

        {!group.required && (
          <Button
            variant="ghost"
            onClick={onSkip}
          >
            Skip for now
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}

export default CredentialGroupStep;
