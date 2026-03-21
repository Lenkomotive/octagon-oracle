import { Pool } from "pg";

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

export async function query(text: string, params?: unknown[]) {
  const res = await pool.query(text, params);
  return res.rows;
}

export interface AnalystData {
  slug: string;
  name: string;
  totalPredictions: number;
  correctPredictions: number;
  accuracy: number;
  recentEvents: {
    event: string;
    correct: number;
    total: number;
    accuracy: number;
  }[];
}

export async function getLeaderboard(): Promise<AnalystData[]> {
  // Get all channels with their prediction counts and scores
  const analysts = await query(`
    SELECT
      c.id,
      c.name,
      LOWER(REPLACE(c.name, ' ', '-')) as slug,
      COUNT(p.id) as total_predictions,
      COUNT(s.id) FILTER (WHERE s.correct = true) as correct_predictions
    FROM channels c
    LEFT JOIN predictions p ON p.channel_id = c.id
    LEFT JOIN scores s ON s.prediction_id = p.id
    GROUP BY c.id, c.name
    HAVING COUNT(p.id) > 0
    ORDER BY
      CASE WHEN COUNT(s.id) > 0
        THEN COUNT(s.id) FILTER (WHERE s.correct = true)::float / COUNT(s.id)
        ELSE 0
      END DESC
  `);

  // Get recent events per channel
  const recentEvents = await query(`
    SELECT DISTINCT ON (p.channel_id, e.id)
      p.channel_id,
      e.name as event,
      e.date,
      COUNT(p.id) OVER (PARTITION BY p.channel_id, e.id) as total,
      COUNT(s.id) FILTER (WHERE s.correct = true) OVER (PARTITION BY p.channel_id, e.id) as correct
    FROM predictions p
    JOIN events e ON p.event_id = e.id
    LEFT JOIN scores s ON s.prediction_id = p.id
    ORDER BY p.channel_id, e.id, e.date DESC
  `);

  // Group recent events by channel
  const recentByChannel: Record<number, typeof recentEvents> = {};
  for (const row of recentEvents) {
    const chId = row.channel_id;
    if (!recentByChannel[chId]) recentByChannel[chId] = [];
    recentByChannel[chId].push(row);
  }

  return analysts.map((a) => {
    const total = Number(a.total_predictions);
    const correct = Number(a.correct_predictions);
    const recent = (recentByChannel[a.id] || [])
      .sort((x: { date: string }, y: { date: string }) =>
        new Date(y.date).getTime() - new Date(x.date).getTime()
      )
      .slice(0, 5)
      .map((r: { event: string; correct: string; total: string }) => ({
        event: r.event,
        correct: Number(r.correct),
        total: Number(r.total),
        accuracy: Number(r.total) > 0
          ? Math.round((Number(r.correct) / Number(r.total)) * 1000) / 10
          : 0,
      }));

    return {
      slug: a.slug,
      name: a.name,
      totalPredictions: total,
      correctPredictions: correct,
      accuracy: total > 0 ? Math.round((correct / total) * 1000) / 10 : 0,
      recentEvents: recent,
    };
  });
}
