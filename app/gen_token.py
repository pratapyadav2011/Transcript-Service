"""
Mint a signed access token from the command line.

    python -m app.gen_token            # token valid 1 hour
    python -m app.gen_token 28800      # token valid 8 hours (seconds)

Uses API_SECRET_KEY from the environment / .env. Your website normally mints
these itself (see README) — this is for testing.
"""
import sys

from app.core.security import make_token


def main() -> None:
    ttl = int(sys.argv[1]) if len(sys.argv) > 1 else 3600
    token = make_token(ttl)
    print(token)
    print(f"\nEntry link:  http://localhost:8000/?token={token}", file=sys.stderr)
    print(f"API header:  Authorization: Bearer {token}", file=sys.stderr)


if __name__ == "__main__":
    main()
