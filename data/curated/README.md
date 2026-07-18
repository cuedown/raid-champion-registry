# Curated mastery builds

Put one or more editorial recommendation JSON files in this directory. The
`build` command imports every `*.json` file here.

Only a build with all of the following may use `"status": "approved"`:

- an exact 15-pick, two-tree, 10/5 mastery path;
- a canonical champion already imported from current game/client data;
- at least one evidence record;
- `reviewed_by` and `reviewed_at` values;
- a current, champion-and-content-specific editorial review.

Historical imports and observed popularity candidates remain `historical` or
`draft`; the app export excludes both by default.
