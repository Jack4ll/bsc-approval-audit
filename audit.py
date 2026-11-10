#!/usr/bin/env python3
"""bsc-approval-audit: list the live token/NFT approvals for a wallet on BSC.

Approvals are how wallets get drained: a market or contract you approved
once can move your tokens forever, until you revoke it. This tool checks
a list of (token, spender) pairs you give it and reports which approvals
are still live — and which are unlimited.

Usage:
    python3 audit.py --wallet 0xYourWallet --pairs pairs.txt
    python3 audit.py --wallet 0xYourWallet --pairs pairs.txt --json

A pairs file is one pair per line: TOKEN,SPENDER,KIND
where KIND is erc20 (a token allowance) or erc721 (an NFT operator
approval). Lines starting with # are comments.
See examples/pairs-example.txt.

Read-only; the tool never signs anything.

Requires Python 3.9+ and nothing else (standard library only).
"""

import argparse
import http.client
import json
import sys
import urllib.error
import urllib.request

# Function selectors (first 4 bytes of keccak256, verified).
SEL_ALLOWANCE = "dd62ed3e"            # allowance(address,address)
SEL_IS_APPROVED_FOR_ALL = "e985e9c5"  # isApprovedForAll(address,address)
SEL_SYMBOL = "95d89b41"               # symbol()

UINT256_MAX = (1 << 256) - 1

DEFAULT_RPCS = [
    "https://bsc-dataseed1.bnbchain.org",
    "https://bsc-dataseed2.bnbchain.org",
    "https://bsc-dataseed3.bnbchain.org",
    "https://rpc-bsc.48.club",
]


def encode_address(address: str) -> str:
    """Encode an address as a 32-byte ABI word (hex, no 0x)."""
    addr = address.lower().removeprefix("0x")
    if len(addr) != 40 or any(c not in "0123456789abcdef" for c in addr):
        raise ValueError(f"not an address: {address}")
    return "0" * 24 + addr


def encode_uint(value: int) -> str:
    """Encode an integer as a 32-byte ABI word (hex, no 0x)."""
    if value < 0 or value >= 1 << 256:
        raise ValueError(f"uint256 out of range: {value}")
    return f"{value:064x}"


def rpc_call(rpc: str, method: str, params: list) -> object:
    """One JSON-RPC call. Returns the result, raises on error."""
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode()
    req = urllib.request.Request(
        rpc, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.load(resp)
    except (urllib.error.URLError, TimeoutError, http.client.HTTPException,
            OSError) as exc:
        raise RuntimeError(f"RPC {rpc} unreachable: {exc}") from exc
    if "error" in result:
        raise ValueError(result["error"].get("message", "RPC error"))
    return result.get("result")


def rpc_with_fallback(rpcs: list[str], method: str, params: list) -> object:
    """Try each RPC in order; return the first success."""
    last_error: Exception | None = None
    for rpc in rpcs:
        try:
            return rpc_call(rpc, method, params)
        except RuntimeError as exc:
            last_error = exc
    raise RuntimeError(f"all RPCs failed (last: {last_error})")


def eth_call(rpcs: list[str], to: str, data: str) -> str:
    """Read-only eth_call; returns raw hex (raises if it reverts)."""
    return rpc_with_fallback(
        rpcs, "eth_call", [{"to": to, "data": data}, "latest"]
    )


def decode_symbol(data: str) -> str | None:
    """Best-effort symbol() decode: ABI string first, bytes32 fallback."""
    raw = bytes.fromhex(data.removeprefix("0x"))
    if len(raw) >= 64:
        try:
            length = int.from_bytes(raw[32:64], "big")
            if 0 < length <= len(raw) - 64:
                text = raw[64:64 + length].decode("utf-8")
                if text.isprintable():
                    return text
        except (ValueError, UnicodeDecodeError):
            pass
    try:
        text = raw.rstrip(b"\x00").decode("utf-8")
        if text and text.isprintable():
            return text
    except UnicodeDecodeError:
        return None
    return None


def get_symbol(rpcs: list[str], token: str) -> str | None:
    """Read a token/NFT symbol; None if the contract has none."""
    try:
        return decode_symbol(eth_call(rpcs, token, "0x" + SEL_SYMBOL))
    except (ValueError, RuntimeError):
        return None


def load_pairs(path: str) -> list[dict]:
    """Parse a pairs file: TOKEN,SPENDER,KIND per line (# = comment)."""
    pairs: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 3 or parts[2] not in ("erc20", "erc721"):
                raise ValueError(
                    f"{path}:{lineno}: expected TOKEN,SPENDER,"
                    "erc20|erc721 — got {line!r}")
            token, spender, kind = parts
            encode_address(token)
            encode_address(spender)
            pairs.append({"token": token.lower(), "spender": spender.lower(),
                          "kind": kind})
    return pairs


def is_unlimited(amount: int | None) -> bool:
    """True when an ERC-20 allowance is the max uint256 (unlimited)."""
    return amount is not None and amount == UINT256_MAX


def verify_entry(rpcs: list[str], wallet: str,
                 entry: dict) -> dict | None:
    """Re-check one approval on-chain; the entry if still live, else None."""
    if entry["kind"] == "erc20":
        data = ("0x" + SEL_ALLOWANCE + encode_address(wallet)
                + encode_address(entry["spender"]))
        try:
            allowance = int(eth_call(rpcs, entry["token"], data), 16)
        except (ValueError, RuntimeError):
            return None
        if allowance == 0:
            return None  # revoked or fully spent
        entry["allowance"] = allowance
        entry["unlimited"] = is_unlimited(allowance)
    else:
        data = ("0x" + SEL_IS_APPROVED_FOR_ALL + encode_address(wallet)
                + encode_address(entry["spender"]))
        try:
            approved = int(eth_call(rpcs, entry["token"], data), 16) != 0
        except (ValueError, RuntimeError):
            return None
        if not approved:
            return None  # revoked
        entry["allowance"] = None
        entry["unlimited"] = True  # operator can move every token ID
    entry["symbol"] = get_symbol(rpcs, entry["token"])
    return entry


def check_pairs(rpcs: list[str], wallet: str,
                pairs: list[dict]) -> list[dict]:
    """Verify a list of known pairs; return the ones still live."""
    live: list[dict] = []
    for pair in pairs:
        entry = verify_entry(rpcs, wallet, dict(pair))
        if entry is not None:
            live.append(entry)
    live.sort(key=lambda e: (e["kind"], e["token"], e["spender"]))
    return live


def verdict(live: list[dict]) -> str:
    """One-line verdict from the live approvals."""
    if not live:
        return "CLEAN — no live approvals"
    unlimited = sum(1 for e in live if e["unlimited"])
    parts = [f"{len(live)} live approval(s)"]
    if unlimited:
        parts.append(f"{unlimited} UNLIMITED")
    return " — ".join(parts) + " — review and revoke what you no longer use"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List the live token/NFT approvals for a BSC wallet.")
    parser.add_argument("--wallet", required=True,
                        help="wallet to audit (0x...); read-only")
    parser.add_argument("--pairs", required=True, action="append",
                        help="pairs file (TOKEN,SPENDER,erc20|erc721 per "
                             "line); repeatable")
    parser.add_argument("--rpc", action="append", default=None,
                        help="RPC endpoint (repeatable; defaults to "
                             "public BSC endpoints)")
    parser.add_argument("--json", action="store_true",
                        help="print machine-readable JSON")
    args = parser.parse_args(argv)

    rpcs = args.rpc or DEFAULT_RPCS
    latest = int(rpc_with_fallback(rpcs, "eth_blockNumber", []), 16)

    pairs: list[dict] = []
    for path in args.pairs:
        pairs.extend(load_pairs(path))
    live = check_pairs(rpcs, args.wallet, pairs)
    result = verdict(live)

    if args.json:
        print(json.dumps({
            "wallet": args.wallet,
            "latestBlock": latest,
            "live": [{
                "token": e["token"],
                "symbol": e["symbol"],
                "spender": e["spender"],
                "kind": e["kind"],
                "allowance": e["allowance"],
                "unlimited": e["unlimited"],
            } for e in live],
            "verdict": result,
        }, indent=2))
        return 0

    erc20 = [e for e in live if e["kind"] == "erc20"]
    nfts = [e for e in live if e["kind"] == "erc721"]
    print(f"wallet:      {args.wallet}")
    print(f"\nERC-20 allowances ({len(erc20)}):")
    if not erc20:
        print("  (none)")
    for e in erc20:
        amount = ("UNLIMITED" if e["unlimited"]
                  else f"{e['allowance']:,}")
        print(f"  {e['symbol'] or e['token']} -> {e['spender']} : {amount}")
    print(f"\nNFT approvals ({len(nfts)}):")
    if not nfts:
        print("  (none)")
    for e in nfts:
        print(f"  {e['symbol'] or e['token']} -> {e['spender']} "
              ": ALL token IDs")
    print(f"\nverdict:     {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
