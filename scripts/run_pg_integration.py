"""Migrate and run the isolated PostgreSQL suite without printing connection secrets."""
import os
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit

from dotenv import dotenv_values


def main() -> int:
    name = os.getenv("TEST_DATABASE_NAME", "")
    if not name.endswith("_test"):
        raise SystemExit("Set TEST_DATABASE_NAME to a dedicated database name ending in _test")
    env_values = dotenv_values(".env")
    direct = os.getenv("DATABASE_URL_UNPOOLED") or env_values.get("DATABASE_URL_UNPOOLED")
    if not direct:
        raise SystemExit("DATABASE_URL_UNPOOLED must point to the development PostgreSQL server")
    parsed = urlsplit(direct)
    test_url = urlunsplit((parsed.scheme, parsed.netloc, f"/{name}", parsed.query, parsed.fragment))
    env = os.environ.copy()
    env.update({"DATABASE_URL": test_url, "DATABASE_URL_UNPOOLED": test_url, "TEST_DATABASE_URL": test_url})
    for command in (["uv", "run", "alembic", "upgrade", "head"],
                    ["uv", "run", "alembic", "check"], ["uv", "run", "pytest", "-q"]):
        result = subprocess.run(command, env=env, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
