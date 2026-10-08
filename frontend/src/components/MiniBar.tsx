/** `■■■■······` progress bar. Purely decorative; put the numbers next to it. */
export default function MiniBar({ value, total, slots = 10 }: { value: number; total: number; slots?: number }) {
  const filled = total ? Math.round((value / total) * slots) : 0;
  return (
    <span className="bar" aria-hidden="true">
      {"■".repeat(Math.max(0, Math.min(slots, filled)))}
      <span className="n">{"·".repeat(Math.max(0, slots - filled))}</span>
    </span>
  );
}
