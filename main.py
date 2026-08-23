import asyncio
import os
import random
import time
import aiohttp
import orjson

try:
    import uvloop
    uvloop.install()
except ImportError:
    pass

# API Endpoints
TAP_URL = "https://server.margcoin.fun/api/game/tap"
ROCKET_URL = "https://server.margcoin.fun/api/game/boost/rocket"
LOGIN_URL = "https://server.margcoin.fun/api/auth/login"
BOOST_USE_URL = "https://server.margcoin.fun/api/game/boost/use"
TASKS_URL = "https://server.margcoin.fun/api/game/tasks"
TASK_START_URL = "https://server.margcoin.fun/api/game/tasks/start"
TASK_VERIFY_URL = "https://server.margcoin.fun/api/game/tasks/verify"

# Credentials and WebAppData
INIT_DATA = "user=%7B%22id%22%3A6588631008%2C%22first_name%22%3A%22%28%E2%96%BA__%E2%97%84%29%20T_T%20X_X%20xusanboyman%22%2C%22last_name%22%3A%22%F0%9F%87%BA%F0%9F%87%BF%22%2C%22username%22%3A%22xusanboyman200%22%2C%22language_code%22%3A%22en%22%2C%22allows_write_to_pm%22%3Atrue%2C%22photo_url%22%3A%22https%3A%5C%2F%5C%2Ft.me%5C%2Fi%5C%2Fuserpic%5C%2F320%5C%2FABKucBBOPE9qSGZbrWEF4xW6wrAlil-YqDxjQfABvEOlAI0lJIBU15Q2npDYdUbN.svg%22%7D&chat_instance=-2406350833743842394&chat_type=sender&auth_date=1787454304&signature=7DelGIa6S-TA-0ijebX74pZKz-ilY-CfoMVokykMggNmtW6IWa765X7a8zv8WRISfHLTedx8BAdZlKLQ714jAw&hash=90f4916d044fde118d0ad6ce00f2808556315827ef6aa313f37c9a4915f51774"

HEADERS = {
    "Host": "server.margcoin.fun",
    "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/60.5 Safari/605.1.15",
    "Accept": "*/*",
    "Accept-Language": "en-US",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://app.margcoin.fun/",
    "Content-Type": "application/json",
    "Origin": "https://app.margcoin.fun",
    "x-tg-init-data": INIT_DATA,
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Connection": "keep-alive"
}

# Global State & Control
start_time = None
pause_event = asyncio.Event()
pause_event.set()

turbo_event = asyncio.Event()
turbo_event.clear()
turbo_active_until = 0
auth_lock = asyncio.Lock()


def get_uptime() -> str:
    elapsed = int(time.time() - start_time)
    hours, remainder = divmod(elapsed, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


async def auto_login(session):
    """Refreshes Bearer token automatically using initData without needing bot polling."""
    print("🔑 Auto-logging in via initData...")
    payload = orjson.dumps({"initData": INIT_DATA})
    async with session.post(LOGIN_URL, data=payload, headers=HEADERS, ssl=False) as resp:
        if resp.status == 200:
            data = await resp.json()
            token = f"Bearer {data['token']}"
            HEADERS["Authorization"] = token
            user = data.get("user", {})
            print(f"✅ Login Successful | User: {user.get('username')} | Balance: {user.get('balance'):,.2f} | Energy: {user.get('energy')}/{user.get('maxEnergy')}")
            return token
        else:
            text = await resp.text()
            print(f"❌ Login Failed: {resp.status} - {text}")
            return None


async def auto_claim_tasks(session):
    """Scans and auto-claims all available bypassable tasks."""
    print("📋 Checking uncompleted tasks...")
    try:
        async with session.get(TASKS_URL, headers=HEADERS, ssl=False) as resp:
            if resp.status != 200:
                return
            tasks = await resp.json()

        # Get already completed list from user state
        async with session.get("https://server.margcoin.fun/api/game/state", headers=HEADERS, ssl=False) as s_resp:
            if s_resp.status == 200:
                u_data = await s_resp.json()
                completed = set(u_data.get("completedTasks", []))
            else:
                completed = set()

        uncompleted = [t for t in tasks if t.get("_id") not in completed]
        if not uncompleted:
            print("✅ All tasks already completed.")
            return

        started = []
        for t in uncompleted:
            tid = t.get("_id")
            try:
                payload = orjson.dumps({"taskId": tid})
                async with session.post(TASK_START_URL, data=payload, headers=HEADERS, ssl=False) as st_resp:
                    if st_resp.status == 200:
                        started.append(t)
            except Exception:
                pass

        if not started:
            return

        print(f"⏳ Waiting 16s to verify {len(started)} pending task timers...")
        await asyncio.sleep(16)

        for t in started:
            tid = t.get("_id")
            title = t.get("title", "")
            reward = t.get("reward", 0)
            payload = orjson.dumps({"taskId": tid})
            try:
                async with session.post(TASK_VERIFY_URL, data=payload, headers=HEADERS, ssl=False) as v_resp:
                    if v_resp.status == 200:
                        res = await v_resp.json()
                        if res.get("ok"):
                            print(f"🎉 Claimed Task: {title} (+{reward:,}) | Balance: {res.get('balance', 0):,.2f}")
            except Exception:
                pass
            await asyncio.sleep(1.5)
    except Exception as e:
        print(f"⚠️ Task claimer error: {e}")


async def drain_energy_and_refill(session):
    """Drains remaining energy with taps and uses fullEnergy boosts automatically."""
    for b_idx in range(3):
        # 1. Tap down available energy
        for _ in range(12):
            payload = orjson.dumps({"taps": 600})
            try:
                async with session.post(TAP_URL, data=payload, headers=HEADERS, ssl=False) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        energy = data.get("energy", 0)
                        if energy < 500:
                            break
                    elif resp.status == 429:
                        await asyncio.sleep(1.2)
            except Exception:
                pass
            await asyncio.sleep(1.05)

        # 2. Use free Full Energy boost
        boost_payload = orjson.dumps({"type": "fullEnergy"})
        try:
            async with session.post(BOOST_USE_URL, data=boost_payload, headers=HEADERS, ssl=False) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"🔋 [{get_uptime()}] Energy Refilled via Boost! Uses left: {data.get('fullEnergyUsesLeft')}")
                else:
                    break
        except Exception:
            break


async def rocket_worker(session):
    """Triggers Rocket Boost on exact cooldown without 429 errors."""
    global turbo_active_until
    idx = 1

    while True:
        await pause_event.wait()
        req_start = time.time()

        try:
            async with session.post(ROCKET_URL, data=b"", headers=HEADERS, ssl=False) as resp:
                body = await resp.text()

                if resp.status in (401, 403):
                    await auto_login(session)
                    continue

                if resp.status == 200:
                    data = orjson.loads(body)
                    print(f"🚀 [{get_uptime()}] [ROCKET #{idx}] Activated Turbo! Ends: {data.get('turboActiveUntil')} | Balance: {data.get('balance'):,.2f}")
                    if data.get("turboActive"):
                        turbo_active_until = data.get("turboActiveUntil", 0) / 1000.0
                        turbo_event.set()
                elif resp.status == 400:
                    # On cooldown
                    pass
                else:
                    print(f"⏱️ [{get_uptime()}] [ROCKET #{idx}] Status: {resp.status} | {body}")

                idx += 1
        except Exception as e:
            print(f"⏱️ [{get_uptime()}] [ROCKET #{idx}] Failed: {type(e).__name__}")

        elapsed = time.time() - req_start
        await asyncio.sleep(max(0.0, 16.5 - elapsed))


async def tap_worker(session, total_taps):
    """High-yield precision tap worker with adaptive pacing."""
    global turbo_active_until
    idx = 1
    tap_interval = 1.05

    while idx <= total_taps:
        await pause_event.wait()

        if not turbo_event.is_set():
            await turbo_event.wait()

        # Stop 0.5s before turbo expires to prevent wasting energy
        if time.time() >= (turbo_active_until - 0.5):
            turbo_event.clear()
            print(f"⏳ [{get_uptime()}] Turbo expired. Waiting for next rocket...")
            continue

        payload = orjson.dumps({"taps": 600})

        try:
            req_start = time.time()
            async with session.post(TAP_URL, data=payload, headers=HEADERS, ssl=False) as resp:
                body = await resp.text()

                if resp.status in (401, 403):
                    await auto_login(session)
                    continue

                if resp.status == 429:
                    print(f"⚠️ [{get_uptime()}] [TAP #{idx}] Rate limited (429). Pacing up to {tap_interval + 0.2:.2f}s...")
                    tap_interval += 0.2
                    await asyncio.sleep(tap_interval)
                    continue

                if resp.status == 200:
                    data = orjson.loads(body)
                    if not data.get("turboActive"):
                        turbo_event.clear()
                    print(f"⚡ [{get_uptime()}] [TAP #{idx}/{total_taps}] Sent: 600 | Credited: +{data.get('tapped')} | Balance: {data.get('balance'):,.2f}")
                    idx += 1
                    tap_interval = max(1.02, tap_interval - 0.05)

        except Exception as e:
            print(f"⏱️ [{get_uptime()}] [TAP #{idx}] Error: {type(e).__name__} ({e})")

        elapsed = time.time() - req_start
        await asyncio.sleep(max(0.0, tap_interval - elapsed))


async def main():
    global start_time
    start_time = time.time()
    total_taps = int(os.getenv("TOTAL_REQUESTS", "5000"))

    connector = aiohttp.TCPConnector(limit=10, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Step 1: Auto-Login via initData
        token = await auto_login(session)
        if not token:
            print("❌ Exiting due to login failure.")
            return

        # Step 2: Auto-check and claim any pending tasks
        await auto_claim_tasks(session)

        print(f"\n🚀 Running Autonomous Engine | Goal: {total_taps} Taps\n")
        
        # Step 3: Drain initial regular energy pool + use free Full Energy boosts
        await drain_energy_and_refill(session)

        # Step 4: Run continuous synchronized Rocket Turbo loop + adaptive tap engine
        await asyncio.gather(
            rocket_worker(session),
            tap_worker(session, total_taps)
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n🛑 Stopped. Total uptime was {get_uptime()}.")
