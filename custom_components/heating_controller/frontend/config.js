// Normalising and migrating the card's YAML configuration.

import { HEADER_KEY, DETAIL_KEY } from "./const.js";

// A detail entry is a managed row ({key, ...}), a custom entity ({entity, ...})
// or a bare entity id. Anything without an anchor is dropped so a config
// damaged by an earlier version heals itself.
export const normalizeDetail = (items) =>
  (items ?? [])
    .map((item) =>
      typeof item === "string" ? { entity: item } : { ...(item ?? {}) }
    )
    .filter((item) => item.entity || item.key);

// Accepts a bare entity id or an object with name/icon. Entries without an
// entity are dropped so a config damaged by an earlier version heals itself
// instead of rendering "undefined" rows forever.
export const normalizeItems = (items) =>
  (items ?? [])
    .map((item) =>
      typeof item === "string" ? { entity: item } : { ...(item ?? {}) }
    )
    .filter((item) => item.entity);

// Earlier drafts used a single extra_entities list with a position field.
// Reading it keeps hand-written YAML from silently losing its sensors.
export const migrateLegacyConfig = (config) => {
  if (!config.extra_entities) return config;
  const migrated = { ...config };
  delete migrated.extra_entities;
  for (const item of normalizeItems(config.extra_entities)) {
    const key = item.position === "header" ? HEADER_KEY : DETAIL_KEY;
    delete item.position;
    migrated[key] = [...(migrated[key] ?? []), item];
  }
  return migrated;
};
