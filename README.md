# Drawdown Lab

An evidence-first research platform for comparing index ETF drawdowns and
cash-pool buying strategies.

## Market data contract

The daily cache stores provider facts separately from derived prices:

- `raw_open`, `raw_high`, `raw_low`, and `raw_close` are provider OHLC values.
- `dividend_raw` and `split_ratio` preserve provider corporate actions.
- `price_open`, `price_high`, `price_low`, and `price_close` are adjusted for
  splits only.
- `adj_close` is the provider adjusted close, which may include dividends.

Strategy code must use `price_close` for price drawdowns and must not apply
`split_ratio` again. Total-return analysis can explicitly opt into `adj_close`.

## Report authenticity boundary

The manifest hashes, cross-format checks, and content-addressed export ID detect
partial or accidental bundle changes. They are not cryptographic signatures
because the local exporter has no secret signing key.

Treat Git provenance as the external authenticity boundary. Verify the
report's Git commit (`git_commit`) against the reviewed branch and PR, its
successful CI run, and the expected release tag before treating a published
report as an authentic project output. A coordinated rewrite of the complete
bundle and its provenance cannot be authenticated by local hashes alone.

## Development

```powershell
python -m pip install ".[dev]"
python -m ruff check apps/api
python -m mypy apps/api/src
python -m pytest apps/api/tests/data -q
```

This intentionally uses a non-editable install. It avoids editable `.pth`
files, which can fail to load under legacy Windows code pages when the
workspace path contains Chinese characters.
