interface Analyst {
  name: string;
  totalPredictions: number;
  correctPredictions: number;
  accuracy: number;
  streak: number;
  streakType: string;
}

export function StatsCards({
  analysts,
  lastUpdated,
}: {
  analysts: Analyst[];
  lastUpdated: string;
}) {
  const totalPredictions = analysts.reduce(
    (sum, a) => sum + a.totalPredictions,
    0
  );
  const totalCorrect = analysts.reduce(
    (sum, a) => sum + a.correctPredictions,
    0
  );
  const avgAccuracy = (
    analysts.reduce((sum, a) => sum + a.accuracy, 0) / analysts.length
  ).toFixed(1);
  const bestStreak = analysts.reduce(
    (best, a) =>
      a.streakType === "W" && a.streak > best.streak ? a : best,
    analysts[0]
  );

  const cards = [
    {
      label: "Analysts Tracked",
      value: analysts.length,
      sub: `Updated ${lastUpdated}`,
    },
    {
      label: "Total Predictions",
      value: totalPredictions,
      sub: `${totalCorrect} correct`,
    },
    {
      label: "Avg Accuracy",
      value: `${avgAccuracy}%`,
      sub: "Across all analysts",
    },
    {
      label: "Best Streak",
      value: `${bestStreak.streak}W`,
      sub: bestStreak.name,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      {cards.map((card) => (
        <div
          key={card.label}
          className="rounded-xl border border-card-border bg-card p-4"
        >
          <p className="text-xs text-muted">{card.label}</p>
          <p className="mt-1 text-2xl font-bold text-foreground">
            {card.value}
          </p>
          <p className="mt-1 text-xs text-muted">{card.sub}</p>
        </div>
      ))}
    </div>
  );
}
