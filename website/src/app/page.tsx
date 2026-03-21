import { getLeaderboard } from "@/lib/db";
import { LeaderboardTable } from "@/components/leaderboard-table";

export const dynamic = "force-dynamic";

export default async function Home() {
  const analysts = await getLeaderboard();
  const sorted = [...analysts].sort((a, b) => b.accuracy - a.accuracy);

  return (
    <main className="min-h-screen bg-background">
      {/* Header */}
      <header className="bg-card sticky top-0 z-10 backdrop-blur-md bg-white/80 border-b border-card-border">
        <div className="mx-auto max-w-5xl px-6 py-5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-red-600 text-sm font-black text-white tracking-tight">
              OO
            </div>
            <div>
              <h1 className="text-lg font-semibold tracking-tight text-foreground">
                Octagon Oracle
              </h1>
              <p className="text-xs text-muted -mt-0.5">
                UFC Prediction Leaderboard
              </p>
            </div>
          </div>
          <span className="rounded-full bg-red-50 px-3 py-1 text-xs font-medium text-red-600">
            {analysts.length} analysts · {analysts.reduce((s, a) => s + a.totalPredictions, 0)} predictions
          </span>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-6 py-10 space-y-10">
        <LeaderboardTable analysts={sorted} />
      </div>
    </main>
  );
}
