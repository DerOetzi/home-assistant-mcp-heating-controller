// Styles for the visual editor's shadow root.
export const EDITOR_STYLES = `
        .list-section { margin-top: 24px; }
        .heading { font-weight: 500; }
        .hint {
          font-size: 0.8rem; color: var(--secondary-text-color);
          margin: 2px 0 10px 0;
        }
        .row {
          display: flex; align-items: center; gap: 4px;
          background: var(--secondary-background-color);
          border-radius: 8px; padding: 6px 8px; margin-bottom: 8px;
        }
        .handle { cursor: grab; color: var(--secondary-text-color); }
        .row .info { flex: 1; min-width: 0; }
        .row .primary {
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .row .secondary {
          font-size: 0.8rem; color: var(--secondary-text-color);
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .adder { margin-top: 4px; }
        .subhead { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
        .subhead .label { font-weight: 500; }
        #detailEntity { margin-bottom: 16px; }
        .ro-field {
          display: flex; flex-direction: column; gap: 2px;
          padding: 8px 12px; border-radius: 4px;
          background: var(--secondary-background-color);
          border: 1px solid var(--divider-color);
        }
        .ro-field .ro-label {
          font-size: 0.75rem; color: var(--secondary-text-color);
        }
        .ro-field .ro-value {
          color: var(--secondary-text-color);
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
`;
