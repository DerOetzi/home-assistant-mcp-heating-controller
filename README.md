# Heating Controller

Home Assistant custom integration for MPC-based room heating control — one config
entry per room.

Each room's config entry combines:

- a comfort/eco/boost/frost-protection mode state machine
- a grey-box thermal model (heat-loss + thermal-capacity + per-TRV emitter curves)
  with online self-calibration of the learned `ua_factor`/`capacity_factor`
- rate-limited demand control with hysteresis and hold-time
