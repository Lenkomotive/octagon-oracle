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
    high: "bg-green-500",
    medium: "bg-yellow-400",
    low: "bg-red-400",
  };
  return (
    <span className="flex items-center gap-1.5">
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${colors[level] ?? "bg-muted"}`} />
      <span className="text-xs text-muted capitalize">{level}</span>
    </span>
  );
}

function ResultBadge({ result }: { result: string }) {
  const isCorrect = result === "correct";
  return (
    <span
      className={`inline-flex items-center rounded-lg px-2.5 py-1 text-xs font-semibold ${
        isCorrect ? "bg-green-50 text-green-600" : "bg-red-50 text-red-500"
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
      <header className="bg-card sticky top-0 z-10 backdrop-blur-md bg-white/80 border-b border-card-border">
        <div className="mx-auto max-w-5xl px-6 py-5">
          <Link
            href="/"
            className="inline-flex items-center gap-1 text-xs font-medium text-muted hover:text-foreground transition-colors mb-4"
          >
            ← Back
          </Link>
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-foreground">
                {analyst.name}
              </h1>
              <p className="text-sm text-muted">{analyst.channel}</p>
            </div>
            <div className="text-right">
              <p className="text-4xl font-black text-red-600 tracking-tight">
                {analyst.accuracy}%
              </p>
              <p className="text-xs text-muted mt-0.5">
                {analyst.correctPredictions}-
                {analyst.totalPredictions - analyst.correctPredictions} overall
              </p>
            </div>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-6 py-10 space-y-8">
        {/* Method accuracy cards */}
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: "KO/TKO", value: analyst.methodAccuracy.ko },
            { label: "Submission", value: analyst.methodAccuracy.submission },
            { label: "Decision", value: analyst.methodAccuracy.decision },
          ].map((m) => (
            <div
              key={m.label}
              className="rounded-2xl bg-card p-5 shadow-sm text-center"
            >
              <p className="text-xs font-medium text-muted uppercase tracking-wider">{m.label}</p>
              <p className="mt-2 text-2xl font-bold text-foreground tracking-tight">
                {m.value}%
              </p>
            </div>
          ))}
        </div>

        {/* Recent events with predictions */}
        {analyst.recentEvents.map((event: RecentEvent) => (
          <div
            key={event.event}
            className="rounded-2xl bg-card shadow-sm overflow-hidden"
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-card-border">
              <h2 className="font-semibold text-foreground">{event.event}</h2>
              <div className="flex items-center gap-3">
                <span className="text-sm text-muted tabular-nums">
                  {event.correct}/{event.total}
                </span>
                <span className="rounded-lg bg-red-50 px-2.5 py-1 text-xs font-semibold text-red-600">
                  {event.accuracy}%
                </span>
              </div>
            </div>

            {event.predictions.length > 0 ? (
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-card-border text-[11px] uppercase tracking-wider text-muted">
                    <th className="px-5 py-3">Pick</th>
                    <th className="px-5 py-3">Opponent</th>
                    <th className="px-5 py-3">Method</th>
                    <th className="px-5 py-3 text-right">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {event.predictions.map((p: Prediction, i: number) => (
                    <tr
                      key={i}
                      className="border-b border-card-border last:border-0 transition-colors hover:bg-gray-50"
                    >
                      <td className="px-5 py-3.5 text-sm font-medium text-foreground">
                        {p.fighter}
                      </td>
                      <td className="px-5 py-3.5 text-sm text-muted">
                        {p.opponent}
                      </td>
                      <td className="px-5 py-3.5 text-sm text-muted">
                        {p.method}
                      </td>
                      <td className="px-5 py-3.5 text-right">
                        <ResultBadge result={p.result} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="px-5 py-8 text-center text-sm text-muted">
                Detailed predictions not yet available for this event.
              </div>
            )}
          </div>
        ))}
      </div>
    </main>
  );
}
