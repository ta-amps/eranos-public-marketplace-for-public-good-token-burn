const modules = import.meta.glob<unknown>("../../snapshot/**/*.json", {
  eager: true,
  import: "default",
});

export const SNAPSHOT_DATA: Readonly<Record<string, unknown>> = Object.fromEntries(
  Object.entries(modules).map(([path, data]) => [
    path.replace("../../snapshot/", "").replace(/\.json$/, ""),
    data,
  ]),
);
