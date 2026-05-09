import { useState, useId } from 'react';
import { Eye, EyeOff, Info } from 'lucide-react';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { Button } from '../ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '../ui/tooltip';
import { cn } from '../ui/utils';

/**
 * CredentialInput — A masked input with reveal toggle, tooltip hint,
 * and inline validation error display.
 *
 * Used within the Setup Wizard for entering sensitive credential values
 * (API keys, tokens, passwords). Supports pattern-based client-side
 * validation and accessible labeling.
 *
 * Requirements: 2.3, 2.6
 */

export interface CredentialInputProps {
  label: string;
  name: string;
  value: string;
  onChange: (value: string) => void;
  tooltipHint: string;
  error?: string;
  pattern?: string;
}

export function CredentialInput({
  label,
  name,
  value,
  onChange,
  tooltipHint,
  error,
  pattern,
}: CredentialInputProps) {
  const [revealed, setRevealed] = useState(false);
  const id = useId();
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange(e.target.value);
  };

  return (
    <div className="space-y-1.5">
      {/* Label row with tooltip */}
      <div className="flex items-center gap-1.5">
        <Label htmlFor={id}>{label}</Label>
        {tooltipHint && (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="inline-flex items-center justify-center rounded-full text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label={`Info about ${label}`}
              >
                <Info className="size-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent
              id={hintId}
              side="top"
              className="max-w-xs"
            >
              {tooltipHint}
            </TooltipContent>
          </Tooltip>
        )}
      </div>

      {/* Input with reveal toggle */}
      <div className="relative">
        <Input
          id={id}
          name={name}
          type={revealed ? 'text' : 'password'}
          value={value}
          onChange={handleChange}
          pattern={pattern}
          aria-invalid={!!error}
          aria-describedby={cn(
            error ? errorId : undefined,
            tooltipHint ? hintId : undefined,
          )}
          className={cn(
            'pr-10',
            error && 'border-destructive focus-visible:border-destructive focus-visible:ring-destructive/20',
          )}
          autoComplete="off"
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="absolute right-0 top-0 h-9 w-9 text-muted-foreground hover:text-foreground"
          onClick={() => setRevealed((prev) => !prev)}
          aria-label={revealed ? 'Hide credential value' : 'Reveal credential value'}
          tabIndex={-1}
        >
          {revealed ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </Button>
      </div>

      {/* Inline validation error */}
      {error && (
        <p
          id={errorId}
          role="alert"
          className="text-sm text-destructive"
        >
          {error}
        </p>
      )}
    </div>
  );
}

export default CredentialInput;
