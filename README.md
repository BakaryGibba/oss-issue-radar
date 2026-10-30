# OSS Issue Radar

Finds new, **unclaimed** issues in the open-source research projects I contribute to, so I can offer help while an issue is still open for a contributor.

Every 6 hours a GitHub Action checks the projects in [`watchlist.json`](watchlist.json) for issues opened in the last 7 days and skips any that:

- already have a linked pull request or an assignee;
- have a comment claiming the work ("I'd like to work on this", "I opened a PR", …);
- were filed by a reporter who ticked "I'd be interested in making a PR";
- have more than two comments or an excluded label.

Remaining issues are posted as one issue in this repository, which triggers a normal GitHub notification. Reported issues are remembered in `seen.json`.

## Run locally

```bash
GITHUB_TOKEN=$(gh auth token) python radar.py   # dry run, prints candidates
```

## Configure

Edit `watchlist.json` to change the projects, the look-back window or the filters.
