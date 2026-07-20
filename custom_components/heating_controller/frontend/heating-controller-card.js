/*
 * Entry point for the Heating Controller Lovelace card.
 *
 * Registers the custom elements and announces the card to the card picker.
 * Everything else lives in the sibling modules — vanilla ES modules on
 * purpose, since this repo has no JS build tooling.
 */

import { CARD_TAG, EDITOR_TAG } from "./const.js";
import { HeatingControllerCard } from "./card.js";
import { HeatingControllerCardEditor } from "./editor.js";
import { TRANSLATIONS } from "./translations.js";

customElements.define(CARD_TAG, HeatingControllerCard);
customElements.define(EDITOR_TAG, HeatingControllerCardEditor);

window.customCards = window.customCards ?? [];
window.customCards.push({
  type: CARD_TAG,
  // The picker reads this once at load time, before any hass is available, so
  // it cannot be localised per user — English is the neutral choice.
  name: TRANSLATIONS.en.card_name,
  description: TRANSLATIONS.en.card_description,
  preview: true,
  documentationURL:
    "https://github.com/DerOetzi/home-assistant-mcp-heating-controller",
});

console.info(`%c ${CARD_TAG} %c loaded`, "color: white; background: #d35400", "");
