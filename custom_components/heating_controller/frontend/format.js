// Value formatting and small state helpers.

// Formats for the viewer, not for the machine: a German user gets "21,5" and a
// bare "21" instead of "21.5"/"21.0". `digits` is the maximum, not a fixed
// width, so trailing zeros disappear. Falls back to the plain number if the
// runtime has no Intl (which is the case in the QuickJS test harness).
export const num = (value, digits = 1, locale) => {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) return "–";
  const factor = 10 ** digits;
  const rounded = Math.round(parsed * factor) / factor;
  try {
    return rounded.toLocaleString(locale, { maximumFractionDigits: digits });
  } catch (err) {
    return String(rounded);
  }
};

export const localeOf = (hass) => hass?.locale?.language;

export const isOn = (stateObj) => stateObj?.state === "on";
