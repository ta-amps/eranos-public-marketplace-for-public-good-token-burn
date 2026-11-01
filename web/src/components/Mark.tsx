/**
 * The tile mark: four rounded tiles in a 100-unit square (tile 44, gap 12, corner 10). Top left and bottom right
 * are noun blue, top right is verb orange, bottom left is ink, which becomes paper in the dark theme. The colours
 * are tokens (`--mark-1` to `--mark-4`), so the mark follows the theme.
 */
export function Mark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <svg
      className={className ? `er-mark ${className}` : "er-mark"}
      width={size}
      height={size}
      viewBox="0 0 100 100"
      aria-hidden="true"
      focusable="false"
    >
      <rect className="er-mark-1" x="0" y="0" width="44" height="44" rx="10" />
      <rect className="er-mark-2" x="56" y="0" width="44" height="44" rx="10" />
      <rect className="er-mark-3" x="0" y="56" width="44" height="44" rx="10" />
      <rect className="er-mark-4" x="56" y="56" width="44" height="44" rx="10" />
    </svg>
  );
}
