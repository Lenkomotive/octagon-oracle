import Link from "next/link";
import { notFound } from "next/navigation";
import data from "@/data/leaderboard.json";

interface Prediction {
  fighter: string;
  opponent: string;
  method: string;
  confidence: string;
  result: string;
}

interface RecentEvent {
  event: string;
  correct: number;
  total: number;
  accuracy: number;
  predictions: Prediction[];
}

export function generateStaticParams() {
  return data.analysts.map((a) => ({ slug: a.slug }));
}

export function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  return params.then(({ slug }) => {
    const analyst = data.analysts.find((a) => a.slug === slug);
    return {
      title: analyst
        ? `${analyst.name} — Octagon Oracle`
        : "Analyst Not Found",
    };
  });
}

function ConfidenceDot({ level }: { level: string }) {
  const colors: Record<string, string> = {
    high: "bg-green",
    medium: "bg-yellow-500",
    low: "bg-red",
  };
  return (
    <span className="flex items-center gap-1.5">
      <span className={`inline-block h-2 w-2 rounded-full ${colors[level] ?? "bg-muted"}`} />
      <span className="text-xs text-muted capitalize">{level}</span>
    </span>
  );
}

function ResultBadge({ result }: { result: string }) {
  const isCorrect = result === "correct";
  return (
    <span
      className={`rounded-md px-2 py-0.5 text-xs font-medium ${
        isCorrect ? "bg-green/10 text-green" : "bg-red/10 text-red"
      }`}
    >
      {isCorrect ? "W" : "L"}
    </span>
  );
}

export default async function AnalystPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const analyst = data.analysts.find((a) => a.slug === slug);

  if (!analyst) notFound();

  return (
    <main className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-card-border">
        <div className="mx-auto max-w-6xl px-4 py-6">
          <Link
            href="/"
            className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground transition-colors mb-4"
          >
            &larr; Back to Leaderboard
          </Link>
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-foreground">
                {analyst.name}
              </h1>
              <p className="text-sm text-muted">{analyst.channel}</p>
            </div>
            <div className="text-right">
              <p className="text-3xl font-bold text-accent">
                {analyst.accuracy}%
              </p>
              <p className="text-xs text-muted">
                {analyst.correctPredictions}-
                {analyst.totalPredictions - analyst.correctPredictions} overall
              </p>
            </div>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-4 py-8 space-y-8">
        {/* Method accuracy cards */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: "KO/TKO", value: analyst.methodAccuracy.ko },
            { label: "Submission", value: analyst.methodAccuracy.submission },
            { label: "Decision", value: analyst.methodAccuracy.decision },
          ].map((m) => (
            <div
              key={m.label}
              className="rounded-xl border border-card-border bg-card p-4 text-center"
            >
              <p className="text-xs text-muted">{m.label}</p>
              <p className="mt-1 text-xl font-bold text-foreground">
                {m.value}%
              </p>
            </div>
          ))}
        </div>

        {/* Recent events with predictions */}
        {analyst.recentEvents.map((event: RecentEvent) => (
          <div
            key={event.event}
            className="rounded-xl border border-card-border overflow-hidden"
          >
            {/* Event header */}
            <div className="flex items-center justify-between bg-card px-4 py-3 border-b border-card-border">
              <h2 className="font-medium text-foreground">{event.event}</h2>
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted">
                  {event.correct}/{event.total}
                </span>
                <span className="rounded-md bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent">
                  {event.accuracy}%
                </span>
              </div>
            </div>

            {/* Predictions table */}
            {event.predictions.length > 0 ? (
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-card-border text-xs uppercase tracking-wider text-muted">
                    <th className="px-4 py-2">Pick</th>
                    <th className="px-4 py-2">Opponent</th>
                    <th className="px-4 py-2">Method</th>
                    <th className="px-4 py-2">Confidence</th>
                    <th className="px-4 py-2 text-right">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {event.predictions.map((p: Prediction, i: number) => (
                    <tr
                      key={i}
                      className="border-b border-card-border last:border-0 transition-colors hover:bg-card/30"
                    >
                      <td className="px-4 py-3 text-sm font-medium text-foreground">
                        {p.fighter}
                      </td>
                      <td className="px-4 py-3 text-sm text-muted">
                        {p.opponent}
                      </td>
                      <td className="px-4 py-3 text-sm text-muted">
                        {p.method}
                      </td>
                      <td className="px-4 py-3">
                        <ConfidenceDot level={p.confidence} />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <ResultBadge result={p.result} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="px-4 py-6 text-center text-sm text-muted">
                Detailed predictions not yet available for this event.
              </div>
            )}
          </div>
        ))}
      </div>
    </main>
  );
}
