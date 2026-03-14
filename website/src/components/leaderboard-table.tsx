import Link from "next/link";

interface RecentEvent {
  event: string;
  correct: number;
  total: number;
  accuracy: number;
}

interface MethodAccuracy {
  ko: number;
  submission: number;
  decision: number;
}

interface Analyst {
  slug: string;
  name: string;
  channel: string;
  totalPredictions: number;
  correctPredictions: number;
  accuracy: number;
  streak: number;
  streakType: string;
  recentEvents: RecentEvent[];
  methodAccuracy: MethodAccuracy;
}

function RankBadge({ rank }: { rank: number }) {
  if (rank === 1)
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-yellow-500/20 text-sm font-bold text-yellow-400">
        1
      </span>
    );
  if (rank === 2)
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-400/20 text-sm font-bold text-gray-300">
        2
      </span>
    );
  if (rank === 3)
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-amber-700/20 text-sm font-bold text-amber-600">
        3
      </span>
    );
  return (
    <span className="flex h-8 w-8 items-center justify-center text-sm text-muted">
      {rank}
    </span>
  );
}

function AccuracyBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-20 overflow-hidden rounded-full bg-card-border">
        <div
          className="h-full rounded-full bg-accent"
          style={{ width: `${value}%` }}
        />
      </div>
      <span className="text-sm font-medium text-foreground">{value}%</span>
    </div>
  );
}

function StreakBadge({
  streak,
  type,
}: {
  streak: number;
  type: string;
}) {
  const isWin = type === "W";
  return (
    <span
      className={`rounded-md px-2 py-0.5 text-xs font-medium ${
        isWin
          ? "bg-green/10 text-green"
          : "bg-red/10 text-red"
      }`}
    >
      {streak}
      {type}
    </span>
  );
}

function MiniChart({ events }: { events: RecentEvent[] }) {
  return (
    <div className="flex items-end gap-1">
      {events.map((e, i) => (
        <div key={i} className="group relative flex flex-col items-center">
          <div
            className="w-5 rounded-sm bg-accent/60 transition-colors group-hover:bg-accent"
            style={{ height: `${Math.max(e.accuracy * 0.4, 4)}px` }}
          />
          <div className="pointer-events-none absolute -top-10 left-1/2 z-10 hidden -translate-x-1/2 whitespace-nowrap rounded bg-card border border-card-border px-2 py-1 text-xs text-foreground shadow-lg group-hover:block">
            {e.correct}/{e.total} ({e.accuracy}%)
          </div>
        </div>
      ))}
    </div>
  );
}

export function LeaderboardTable({ analysts }: { analysts: Analyst[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-card-border">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-card-border bg-card text-xs uppercase tracking-wider text-muted">
            <th className="px-4 py-3 w-12">#</th>
            <th className="px-4 py-3">Analyst</th>
            <th className="px-4 py-3">Record</th>
            <th className="px-4 py-3">Accuracy</th>
            <th className="px-4 py-3">Streak</th>
            <th className="px-4 py-3">Recent</th>
            <th className="px-4 py-3 hidden md:table-cell">KO%</th>
            <th className="px-4 py-3 hidden md:table-cell">Sub%</th>
            <th className="px-4 py-3 hidden md:table-cell">Dec%</th>
          </tr>
        </thead>
        <tbody>
          {analysts.map((analyst, i) => (
            <tr
              key={analyst.name}
              className="border-b border-card-border last:border-0 transition-colors hover:bg-card/50 cursor-pointer"
            >
              <td className="px-4 py-4">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  <RankBadge rank={i + 1} />
                </Link>
              </td>
              <td className="px-4 py-4">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  <p className="font-medium text-foreground">
                    {analyst.name}
                  </p>
                  <p className="text-xs text-muted">{analyst.channel}</p>
                </Link>
              </td>
              <td className="px-4 py-4 text-sm text-muted">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  {analyst.correctPredictions}-
                  {analyst.totalPredictions - analyst.correctPredictions}
                </Link>
              </td>
              <td className="px-4 py-4">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  <AccuracyBar value={analyst.accuracy} />
                </Link>
              </td>
              <td className="px-4 py-4">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  <StreakBadge
                    streak={analyst.streak}
                    type={analyst.streakType}
                  />
                </Link>
              </td>
              <td className="px-4 py-4">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  <MiniChart events={analyst.recentEvents} />
                </Link>
              </td>
              <td className="px-4 py-4 hidden md:table-cell text-sm text-muted">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  {analyst.methodAccuracy.ko}%
                </Link>
              </td>
              <td className="px-4 py-4 hidden md:table-cell text-sm text-muted">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  {analyst.methodAccuracy.submission}%
                </Link>
              </td>
              <td className="px-4 py-4 hidden md:table-cell text-sm text-muted">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  {analyst.methodAccuracy.decision}%
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
