# bsc-approval-audit

List the live token and NFT approvals for a wallet on BNB Smart Chain.

Approvals are how wallets get drained: a market or contract you approved
once can move your tokens forever, until you revoke it. This tool checks
a list of (token, spender) pairs you give it and reports which approvals
are still live — and which are unlimited.

It is read-only and never signs anything.

## Requirements

- Python 3.9+
- No dependencies (standard library only)

## Usage

```bash
python3 audit.py --wallet 0xYourWallet --pairs pairs.txt
python3 audit.py --wallet 0xYourWallet --pairs pairs.txt --json
```

A pairs file is one pair per line: `TOKEN,SPENDER,KIND`, where KIND is
`erc20` or `erc721`. See [examples/pairs-example.txt](examples/pairs-example.txt).

## Example output

Real run — fast re-check of a wallet with one live approval (wallet redacted):

```
wallet:      0xYourWallet...

ERC-20 allowances (0):
  (none)

NFT approvals (1):
  POKECHAIN -> 0x3399e3ac0d6aa973a00d47ff52072906841ee1a7 : ALL token IDs

verdict:     1 live approval(s) — 1 UNLIMITED — review and revoke what you no longer use
```

## How it works

- For ERC-20 pairs it calls `allowance(owner, spender)`; for NFT pairs
  it calls `isApprovedForAll(owner, operator)`. An allowance of 0 or a
  `false` operator check means revoked or spent — filtered out.
- Symbols are read best-effort (`symbol()` as a string, with a bytes32
  fallback); an unknown symbol falls back to the contract address.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Roadmap

- [ ] Revoke helper (`setApprovalForAll` / `approve(0)`) — behind an explicit flag, never by default
- [ ] Log-scan mode to discover approvals you forgot about
- [ ] Multi-chain support (Base, Ethereum)

## License

MIT — see [LICENSE](LICENSE).
