export const OUTCOME_LABEL: Record<string, string> = {
  resolved: "Kesin çözüm",
  workaround: "Geçici çözüm",
  explained: "Ürün davranışı",
  not_reproduced: "Tekrarlanamadı",
  unresolved: "Çözülmedi",
};

export const OUTCOME_BADGE_COLOR: Record<
  string,
  "success" | "warning" | "info" | "error" | "light"
> = {
  resolved: "success",
  workaround: "warning",
  explained: "info",
  not_reproduced: "light",
  unresolved: "error",
};
