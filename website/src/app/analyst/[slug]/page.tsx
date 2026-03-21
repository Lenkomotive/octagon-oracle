import Link from "next/link";
import { notFound } from "next/navigation";
import { query } from "@/lib/db";

export const dynamic = "force-dynamic";

export default async function AnalystPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;

  // Find channel
  const channels = await query(
    `SELECT * FROM channels WHERE LOWER(REPLACE(name, ' ', '-')) = $1`,
    [slug]
  );
  if (!channels.length) notFound();
  const channel = channels[0];

  // Get stats
  const stats = await query(`
    SELECT
      COUNT(p.id) as total,
      COUNT(s.id) FILTER (WHERE s.correct = true) as correct
    FROM predictions p
    LEFT JOIN scores s ON s.prediction_id = p.id
    WHERE p.channel_id = $1
  `, [channel.id]);

  const total = Number(stats[0].total);
  const correct = Number(stats[0].correct);
  const accuracy = total > 0 ? Math.round((correct / total) * 1000) / 10 : 0;

  // Get predictions grouped by event
  const predictions = await query(`
    SELECT
      e.name as event,
      e.date,
      p.fighter_picked,
      p.fighter_against,
      p.method,
      p.confidence,
      s.correct as result
    FROM predictions p
    JOIN events e ON p.event_id = e.id
    LEFT JOIN scores s ON s.prediction_id = p.id
    WHERE p.channel_id = $1
    ORDER BY e.date DESC, p.id
  `, [channel.id]);

  // Group by event
  const eventMap = new Map<string, { event: string; date: string; predictions: typeof predictions }>();
  for (const p of predictions) {
    if (!eventMap.has(p.event)) {
      eventMap.set(p.event, { event: p.event, date: p.date, predictions: [] });
    }
    eventMap.get(p.event)!.predictions.push(p);
  }
  const events = Array.from(eventMap.values());

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
                {channel.name}
              </h1>
              <p className="text-sm text-muted">{events.length} events covered</p>
            </div>
            <div className="text-right">
              <p className="text-4xl font-black text-red-600 tracking-tight">
                {accuracy}%
              </p>
              <p className="text-xs text-muted mt-0.5">
                {correct}-{total - correct} · {total} predictions
              </p>
            </div>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-6 py-10 space-y-8">
        {events.map((event) => {
          const eventCorrect = event.predictions.filter((p: { result: boolean | null }) => p.result === true).length;
          const eventScored = event.predictions.filter((p: { result: boolean | null }) => p.result !== null).length;

          return (
            <div
              key={event.event}
              className="rounded-2xl bg-card shadow-sm overflow-hidden"
            >
              <div className="flex items-center justify-between px-5 py-4 border-b border-card-border">
                <h2 className="font-semibold text-foreground">{event.event}</h2>
                <div className="flex items-center gap-3">
                  {eventScored > 0 ? (
                    <>
                      <span className="text-sm text-muted tabular-nums">
                        {eventCorrect}/{eventScored}
                      </span>
                      <span className="rounded-lg bg-red-50 px-2.5 py-1 text-xs font-semibold text-red-600">
                        {Math.round((eventCorrect / eventScored) * 100)}%
                      </span>
                    </>
                  ) : (
                    <span className="rounded-lg bg-gray-100 px-2.5 py-1 text-xs font-medium text-muted">
                      {event.predictions.length} picks · not scored
                    </span>
                  )}
                </div>
              </div>

              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-card-border text-[11px] uppercase tracking-wider text-muted">
                    <th className="px-5 py-3">Pick</th>
                    <th className="px-5 py-3">Over</th>
                    <th className="px-5 py-3">Method</th>
                    <th className="px-5 py-3 text-right">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {event.predictions.map((p: { fighter_picked: string; fighter_against: string; method: string | null; result: boolean | null }, i: number) => (
                    <tr
                      key={i}
                      className="border-b border-card-border last:border-0 transition-colors hover:bg-gray-50"
                    >
                      <td className="px-5 py-3.5 text-sm font-medium text-foreground">
                        {p.fighter_picked}
                      </td>
                      <td className="px-5 py-3.5 text-sm text-muted">
                        {p.fighter_against}
                      </td>
                      <td className="px-5 py-3.5 text-sm text-muted">
                        {p.method || "—"}
                      </td>
                      <td className="px-5 py-3.5 text-right">
                        {p.result === true ? (
                          <span className="inline-flex items-center rounded-lg px-2.5 py-1 text-xs font-semibold bg-green-50 text-green-600">W</span>
                        ) : p.result === false ? (
                          <span className="inline-flex items-center rounded-lg px-2.5 py-1 text-xs font-semibold bg-red-50 text-red-500">L</span>
                        ) : (
                          <span className="inline-flex items-center rounded-lg px-2.5 py-1 text-xs font-medium bg-gray-100 text-muted">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        })}
      </div>
    </main>
  );
}
