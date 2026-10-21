"""Quick helper to find valid workflow_id + user_id for load testing."""
import asyncio, ssl, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for ln in _env.read_text().splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, _, v = ln.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    e = create_async_engine(
        os.environ["DATABASE_URL"],
        connect_args={"ssl": ctx, "prepared_statement_cache_size": 0},
    )
    async with e.begin() as c:
        r = await c.execute(text(
            "SELECT w.id, w.name, w.user_id, w.status "
            "FROM workflows w WHERE w.status = 'active' "
            "ORDER BY w.updated_at DESC LIMIT 10"
        ))
        rows = r.fetchall()
        if not rows:
            print("No active workflows found!")
        else:
            print(f"{'ID':>6}  {'USER_ID':>8}  {'STATUS':<10}  NAME")
            print("-" * 60)
            for row in rows:
                print(f"{row[0]:>6}  {row[2]:>8}  {row[3]:<10}  {row[1]}")
    await e.dispose()

asyncio.run(main())
