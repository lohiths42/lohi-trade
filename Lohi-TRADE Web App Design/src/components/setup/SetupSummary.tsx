import { CheckCircle2, AlertTriangle, ArrowRight } from 'lucide-react';
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
import type { ServiceStatus } from '../../lib/setup-types';

/**
 * SetupSummary — Final summary step of the setup wizard.
 *
 * Displays all configured services with green status, all skipped services
 * with amber status and their affected features, a "Complete Setup" button
 * to finalize, and a link to configure skipped services later.
 *
 * Requirements: 3.6
 */

export interface SetupSummaryProps {
  services: ServiceStatus[];
  onComplete: () => void;
  completing?: boolean;
}

export function SetupSummary({ services, onComplete, completing = false }: SetupSummaryProps) {
  const configuredServices = services.filter((s) => s.status === 'configured');
  const skippedServices = services.filter((s) => s.status === 'skipped');
  const unconfiguredServices = services.filter((s) => s.status === 'unconfigured');
  const errorServices = services.filter((s) => s.status === 'error');

  return (
    <Card className="w-full max-w-2xl">
      <CardHeader>
        <CardTitle className="text-xl">Setup Summary</CardTitle>
        <CardDescription className="text-sm leading-relaxed">
          Review your configuration before completing setup. You can always
          update these settings later from{' '}
          <span className="font-medium">Settings → Integrations</span>.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* Configured Services */}
        {configuredServices.length > 0 && (
          <section aria-labelledby="configured-heading">
            <h3
              id="configured-heading"
              className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground"
            >
              Configured
            </h3>
            <ul className="space-y-2" role="list">
              {configuredServices.map((service) => (
                <li
                  key={service.group_id}
                  className="flex items-center gap-3 rounded-md border border-green-200 bg-green-50 px-4 py-3 dark:border-green-800 dark:bg-green-950"
                >
                  <CheckCircle2
                    className="size-5 shrink-0 text-green-600 dark:text-green-400"
                    aria-hidden="true"
                  />
                  <span className="text-sm font-medium text-green-800 dark:text-green-200">
                    {service.name}
                  </span>
                  <Badge
                    variant="outline"
                    className="ml-auto border-green-300 text-green-700 dark:border-green-700 dark:text-green-300"
                  >
                    Ready
                  </Badge>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Skipped Services */}
        {skippedServices.length > 0 && (
          <section aria-labelledby="skipped-heading">
            <h3
              id="skipped-heading"
              className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground"
            >
              Skipped
            </h3>
            <ul className="space-y-2" role="list">
              {skippedServices.map((service) => (
                <li
                  key={service.group_id}
                  className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-800 dark:bg-amber-950"
                >
                  <div className="flex items-center gap-3">
                    <AlertTriangle
                      className="size-5 shrink-0 text-amber-600 dark:text-amber-400"
                      aria-hidden="true"
                    />
                    <span className="text-sm font-medium text-amber-800 dark:text-amber-200">
                      {service.name}
                    </span>
                    <Badge
                      variant="outline"
                      className="ml-auto border-amber-300 text-amber-700 dark:border-amber-700 dark:text-amber-300"
                    >
                      Skipped
                    </Badge>
                  </div>
                  {service.features_affected.length > 0 && (
                    <p className="mt-2 ml-8 text-xs text-amber-700 dark:text-amber-300">
                      <span className="font-medium">Affected features: </span>
                      {service.features_affected
                        .map((f) => f.replace(/_/g, ' '))
                        .join(', ')}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Unconfigured Services (not yet visited) */}
        {unconfiguredServices.length > 0 && (
          <section aria-labelledby="unconfigured-heading">
            <h3
              id="unconfigured-heading"
              className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground"
            >
              Not Configured
            </h3>
            <ul className="space-y-2" role="list">
              {unconfiguredServices.map((service) => (
                <li
                  key={service.group_id}
                  className="flex items-center gap-3 rounded-md border px-4 py-3 text-muted-foreground"
                >
                  <span className="size-5 shrink-0 rounded-full border-2 border-muted-foreground/40" />
                  <span className="text-sm">{service.name}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Error Services */}
        {errorServices.length > 0 && (
          <section aria-labelledby="error-heading">
            <h3
              id="error-heading"
              className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground"
            >
              Connection Error
            </h3>
            <ul className="space-y-2" role="list">
              {errorServices.map((service) => (
                <li
                  key={service.group_id}
                  className="flex items-center gap-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 dark:border-red-800 dark:bg-red-950"
                >
                  <AlertTriangle
                    className="size-5 shrink-0 text-red-600 dark:text-red-400"
                    aria-hidden="true"
                  />
                  <span className="text-sm font-medium text-red-800 dark:text-red-200">
                    {service.name}
                  </span>
                  <Badge
                    variant="outline"
                    className="ml-auto border-red-300 text-red-700 dark:border-red-700 dark:text-red-300"
                  >
                    Error
                  </Badge>
                </li>
              ))}
            </ul>
          </section>
        )}
      </CardContent>

      <CardFooter className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        <Button onClick={onComplete} disabled={completing}>
          {completing ? 'Completing...' : 'Complete Setup'}
          {!completing && <ArrowRight className="ml-2 size-4" />}
        </Button>

        {skippedServices.length > 0 && (
          <a
            href="/settings"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-primary hover:underline"
          >
            Configure skipped services later
            <ArrowRight className="size-3.5" />
          </a>
        )}
      </CardFooter>
    </Card>
  );
}

export default SetupSummary;
