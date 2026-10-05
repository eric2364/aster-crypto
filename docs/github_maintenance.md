# Private GitHub maintenance

Private repository: [eric2364/aster-crypto](https://github.com/eric2364/aster-crypto). Creation, private visibility and account admin/push permissions have been verified. The local origin uses the existing authenticated SSH key. Upload source/tests/docs/configuration and compact research evidence through ordinary Git commits; working environments, raw market archives and full generated ledgers remain ignored.

GitHub Actions verifies pushes and pull requests using the locked environment, the full regression suite, and spot/funding smoke runs. Dependabot is configured to propose monthly uv/GitHub Actions updates. No automatic merge or deployment is configured. Source/data manifests and report assumptions should be reviewed with every behavior change.

## Routine changes

```bash
git status
git switch -c research/my-change
uv sync --locked --extra dev
.venv/bin/python -m pytest -q
.venv/bin/python main.py demo --market spot --strategy buy_hold --periods 100 --out results/check-spot
.venv/bin/python main.py demo --market perpetual --strategy funding --periods 100 --out results/check-funding
git add <specific changed files>
git commit -m 'Describe the tested behavior change'
git push -u origin research/my-change
```

Open a pull request against `main`. Review accounting/execution changes and run independent audit before merge. Check Actions passes; CI verification covers unit/adversarial tests and offline spot/funding smoke backtests. Downloading live archives is a separate reproducible research task, not a network-dependent CI gate. Monthly Dependabot proposes GitHub Actions and uv dependency updates; merge only after tests and reports remain valid. Keep `uv.lock` with dependency changes. A proposed update is not automatic deployment or automatic merge.

Update architecture/decisions/limitations when assumptions change. Record source hashes, data manifests and strategy version for every reported result. Preserve historical data files locally by content hash; download revisions may change the same archive URL. Never commit exchange account secrets or private wallet data. There is no live trading deployment in this repository.

If maintaining manually, `git pull --ff-only` before edits and ordinary `git push` preserve history. Do not force-push main. Large raw datasets should stay outside Git; avoid checking in confidential ledgers even to private repositories without choosing their destination deliberately. Real-data source licensing still applies to private uploads.
