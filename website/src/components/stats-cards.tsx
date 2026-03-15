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
      label: "Analysts",
      value: analysts.length,
      sub: `Updated ${lastUpdated}`,
    },
    {
      label: "Predictions",
      value: totalPredictions,
      sub: `${totalCorrect} correct`,
    },
    {
      label: "Avg Accuracy",
      value: `${avgAccuracy}%`,
      sub: "All analysts",
    },
    {
      label: "Best Streak",
      value: `${bestStreak.streak}W`,
      sub: bestStreak.name,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {cards.map((card) => (
        <div
          key={card.label}
          className="rounded-2xl bg-card p-5 shadow-sm"
        >
          <p className="text-xs font-medium text-muted uppercase tracking-wider">{card.label}</p>
          <p className="mt-2 text-3xl font-bold text-foreground tracking-tight">
            {card.value}
          </p>
          <p className="mt-1 text-xs text-muted">{card.sub}</p>
        </div>
      ))}
    </div>
  );
}
