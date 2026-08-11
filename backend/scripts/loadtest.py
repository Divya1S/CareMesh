"""Small honest load check against a running API (host or containers).

    cd backend && uv run python -m scripts.loadtest [base_url]

Not a benchmark suite. It measures four paths with realistic constraints
and prints p50/p95/max. The platform's own rate limits shape what can be
measured: login allows 5 attempts per minute per address and account, AI
bearing endpoints allow 20 per user per minute. The script deliberately
stays inside those limits instead of switching them off, because the
limits are part of the system under test.

Needs the seeded demo data (scripts.seed).
"""

import asyncio
import statistics
import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
EMAIL = "student@demo.caremesh.org"
PASSWORD = "caremesh-demo"


def summarize(name: str, times: list[float], errors: int) -> None:
    if not times:
        print(f"{name:<28} no successful requests, errors={errors}")
        return
    ordered = sorted(times)
    p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)]
    print(
        f"{name:<28} n={len(times):<4} errors={errors:<3} "
        f"p50={statistics.median(ordered) * 1000:6.1f}ms "
        f"p95={p95 * 1000:6.1f}ms max={ordered[-1] * 1000:6.1f}ms"
    )


async def timed(client: httpx.AsyncClient, method: str, url: str, times: list, errs: list, **kw):
    started = time.perf_counter()
    try:
        response = await client.request(method, url, **kw)
        if response.status_code < 400:
            times.append(time.perf_counter() - started)
        else:
            errs.append(response.status_code)
    except httpx.HTTPError:
        errs.append("transport")


async def run_pool(n: int, concurrency: int, worker) -> tuple[list[float], list]:
    times: list[float] = []
    errs: list = []
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded(i: int):
        async with semaphore:
            await worker(i, times, errs)

    await asyncio.gather(*(bounded(i) for i in range(n)))
    return times, errs


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as client:
        health = await client.get("/healthz")
        health.raise_for_status()
        print(f"Load check against {BASE}\n")

        # 1. Unauthenticated health: raw request overhead, 200 requests.
        times, errs = await run_pool(
            200, 20, lambda i, t, e: timed(client, "GET", "/healthz", t, e)
        )
        summarize("healthz (no auth)", times, len(errs))

        # 2. Login: exactly 3, inside the brute force limit. Argon2id makes
        # this the slowest path on purpose.
        login_times: list[float] = []
        login_errs: list = []
        token = None
        for _ in range(3):
            started = time.perf_counter()
            response = await client.post(
                "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
            )
            if response.status_code == 200:
                login_times.append(time.perf_counter() - started)
                token = response.json()["access_token"]
            else:
                login_errs.append(response.status_code)
        summarize("login (argon2id, 3 max)", login_times, len(login_errs))
        if token is None:
            print("Could not log in; seed the database first.")
            return
        auth = {"Authorization": f"Bearer {token}"}

        # 3. Authenticated read path: conversations list, 200 requests.
        times, errs = await run_pool(
            200,
            20,
            lambda i, t, e: timed(client, "GET", "/api/v1/conversations", t, e, headers=auth),
        )
        summarize("list conversations (authed)", times, len(errs))

        # 4. Chat with a generated Dira reply: 10 sequential messages in one
        # conversation, inside the 20 per minute AI limit. Includes the
        # gateway round trip and both DB writes.
        response = await client.post(
            "/api/v1/conversations", json={"title": "load check"}, headers=auth
        )
        response.raise_for_status()
        conv_id = response.json()["id"]
        times, errs = [], []
        for i in range(10):
            await timed(
                client,
                "POST",
                f"/api/v1/conversations/{conv_id}/messages",
                times,
                errs,
                headers=auth,
                json={"content": f"Load check message {i}, any small tips for stress?"},
            )
        summarize("chat message + Dira reply", times, len(errs))

        print(
            "\nNote: AI paths run the fake provider unless LLM_PROVIDER is "
            "set; a real provider adds its own network latency on top."
        )


if __name__ == "__main__":
    asyncio.run(main())
