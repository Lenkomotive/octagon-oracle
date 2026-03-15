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
      <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-red-600 text-sm font-bold text-white shadow-sm">
        1
      </span>
    );
  if (rank === 2)
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-foreground text-sm font-bold text-white shadow-sm">
        2
      </span>
    );
  if (rank === 3)
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-gray-200 text-sm font-bold text-gray-600">
        3
      </span>
    );
  return (
    <span className="flex h-8 w-8 items-center justify-center rounded-xl text-sm font-medium text-muted">
      {rank}
    </span>
  );
}

function AccuracyBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-3">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-full rounded-full bg-red-500 transition-all"
          style={{ width: `${value}%` }}
        />
      </div>
      <span className="text-sm font-semibold text-foreground tabular-nums">{value}%</span>
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
      className={`inline-flex items-center rounded-lg px-2.5 py-1 text-xs font-semibold ${
        isWin
          ? "bg-green-50 text-green-600"
          : "bg-red-50 text-red-500"
      }`}
    >
      {streak}{type}
    </span>
  );
}

function MiniChart({ events }: { events: RecentEvent[] }) {
  return (
    <div className="flex items-end gap-0.5">
      {events.map((e, i) => (
        <div key={i} className="group relative flex flex-col items-center">
          <div
            className="w-4 rounded-sm bg-red-100 transition-colors group-hover:bg-red-400"
            style={{ height: `${Math.max(e.accuracy * 0.35, 4)}px` }}
          />
          <div className="pointer-events-none absolute -top-9 left-1/2 z-10 hidden -translate-x-1/2 whitespace-nowrap rounded-lg bg-foreground px-2.5 py-1.5 text-xs text-white shadow-lg group-hover:block">
            {e.correct}/{e.total} ({e.accuracy}%)
          </div>
        </div>
      ))}
    </div>
  );
}

export function LeaderboardTable({ analysts }: { analysts: Analyst[] }) {
  return (
    <div className="overflow-x-auto rounded-2xl bg-card shadow-sm">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-card-border text-[11px] uppercase tracking-wider text-muted">
            <th className="px-5 py-4 w-12">#</th>
            <th className="px-5 py-4">Analyst</th>
            <th className="px-5 py-4">Record</th>
            <th className="px-5 py-4">Accuracy</th>
            <th className="px-5 py-4">Streak</th>
            <th className="px-5 py-4">Recent</th>
            <th className="px-5 py-4 hidden md:table-cell">KO%</th>
            <th className="px-5 py-4 hidden md:table-cell">Sub%</th>
            <th className="px-5 py-4 hidden md:table-cell">Dec%</th>
          </tr>
        </thead>
        <tbody>
          {analysts.map((analyst, i) => (
            <tr
              key={analyst.name}
              className="border-b border-card-border last:border-0 transition-colors hover:bg-gray-50 cursor-pointer"
            >
              <td className="px-5 py-5">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  <RankBadge rank={i + 1} />
                </Link>
              </td>
              <td className="px-5 py-5">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  <p className="font-semibold text-foreground">
                    {analyst.name}
                  </p>
                  <p className="text-xs text-muted mt-0.5">{analyst.channel}</p>
                </Link>
              </td>
              <td className="px-5 py-5 text-sm text-muted tabular-nums">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  {analyst.correctPredictions}-
                  {analyst.totalPredictions - analyst.correctPredictions}
                </Link>
              </td>
              <td className="px-5 py-5">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  <AccuracyBar value={analyst.accuracy} />
                </Link>
              </td>
              <td className="px-5 py-5">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  <StreakBadge
                    streak={analyst.streak}
                    type={analyst.streakType}
                  />
                </Link>
              </td>
              <td className="px-5 py-5">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  <MiniChart events={analyst.recentEvents} />
                </Link>
              </td>
              <td className="px-5 py-5 hidden md:table-cell text-sm text-muted tabular-nums">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  {analyst.methodAccuracy.ko}%
                </Link>
              </td>
              <td className="px-5 py-5 hidden md:table-cell text-sm text-muted tabular-nums">
                <Link href={`/analyst/${analyst.slug}`} className="block">
                  {analyst.methodAccuracy.submission}%
                </Link>
              </td>
              <td className="px-5 py-5 hidden md:table-cell text-sm text-muted tabular-nums">
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
