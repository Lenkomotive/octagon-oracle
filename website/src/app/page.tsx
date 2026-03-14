import data from "@/data/leaderboard.json";
import { LeaderboardTable } from "@/components/leaderboard-table";
import { StatsCards } from "@/components/stats-cards";

export default function Home() {
  const sorted = [...data.analysts].sort((a, b) => b.accuracy - a.accuracy);

  return (
    <main className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-card-border">
        <div className="mx-auto max-w-6xl px-4 py-6">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent/10 text-xl">
              🎯
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-foreground">
                Octagon Oracle
              </h1>
              <p className="text-sm text-muted">
                UFC Prediction Leaderboard
              </p>
            </div>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-4 py-8 space-y-8">
        {/* Overview stats */}
        <StatsCards analysts={sorted} lastUpdated={data.lastUpdated} />

        {/* Latest event badge */}
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-accent/10 px-3 py-1 text-xs font-medium text-accent">
            Latest Event
          </span>
          <span className="text-sm text-muted">{data.event}</span>
        </div>

        {/* Leaderboard */}
        <LeaderboardTable analysts={sorted} />
      </div>
    </main>
  );
}
