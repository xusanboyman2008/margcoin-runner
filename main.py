import asyncio
import os
import sys
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

start_time = None
pause_event = asyncio.Event()
pause_event.set()

turbo_event = asyncio.Event()
turbo_event.clear()
turbo_active_until = 0


def get_uptime() -> str:
    elapsed = int(time.time() - start_time)
    hours, remainder = divmod(elapsed, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


async def auto_login(session):
    """Refreshes Bearer token automatically using initData."""
    print("🔑 Auto-logging in via initData...")
    payload = orjson.dumps({"initData": INIT_DATA})
    async with session.post(LOGIN_URL, data=payload, headers=HEADERS, ssl=False) as resp:
        if resp.status == 200:
            data = await resp.json()
            token = f"Bearer {data['token']}"
            HEADERS["Authorization"] = token
            user = data.get("user", {})
            print(f"✅ Login Successful | User: {user.get('username')} | Balance: {user.get('balance'):,.2f} | Energy: {user.get('energy')}/{user.get('maxEnergy')}\n")
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
            await asyncio.sleep(2.0)
    except Exception as e:
        print(f"⚠️ Task claimer error: {e}")


async def drain_energy_and_refill(session):
    """Drains remaining energy with taps and uses fullEnergy boosts automatically."""
    for b_idx in range(3):
        # Burst down available energy in 1 single 6424-tap request
        payload = orjson.dumps({"taps": 6424})
        try:
            async with session.post(TAP_URL, data=payload, headers=HEADERS, ssl=False) as resp:
                body = await resp.text()
                if resp.status == 200:
                    print(f"⚡ [{get_uptime()}] [ENERGY DRAIN] Status: {resp.status} | Response: {body}")
        except Exception:
            pass

        await asyncio.sleep(0.85)

        # Refill energy via boost
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
    """Probes and triggers Rocket Boost on exact cooldown."""
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
                    print(f"🚀 [{get_uptime()}] [ROCKET #{idx}] Activated Turbo! Ends: {data.get('turboActiveUntil')} | Balance: {data.get('balance'):,.2f} | Response: {body}")
                    if data.get("turboActive"):
                        turbo_active_until = data.get("turboActiveUntil", 0) / 1000.0
                        turbo_event.set()
                        # Sleep through turbo active window + cooldown before next probe
                        await asyncio.sleep(50.0)
                        continue
                elif resp.status == 400:
                    pass
                else:
                    print(f"⏱️ [{get_uptime()}] [ROCKET #{idx}] Status: {resp.status} | Response: {body}")

                idx += 1
        except Exception as e:
            print(f"⏱️ [{get_uptime()}] [ROCKET #{idx}] Error: {type(e).__name__} ({e})")

        elapsed = time.time() - req_start
        await asyncio.sleep(max(0.0, 3.5 - elapsed))


async def tap_worker(session, total_taps):
    """Executes 6424-tap payloads continuously when Rocket Turbo is active with optimal 0.85s pacing."""
    global turbo_active_until
    idx = 1
    # 0.85s is the optimal sustained rate (zero 429 lock penalties)
    tap_interval = 0.85

    while idx <= total_taps:
        await pause_event.wait()

        if not turbo_event.is_set():
            await turbo_event.wait()

        # Stop 0.5s before turbo expires
        if time.time() >= (turbo_active_until - 0.5):
            turbo_event.clear()
            print(f"⏳ [{get_uptime()}] Turbo expired. Waiting for next rocket...")
            continue

        payload = orjson.dumps({"taps": 6424})

        try:
            req_start = time.time()
            async with session.post(TAP_URL, data=payload, headers=HEADERS, ssl=False) as resp:
                body = await resp.text()

                if resp.status in (401, 403):
                    await auto_login(session)
                    continue

                if resp.status == 429:
                    print(f"⚠️ [{get_uptime()}] [TAP #{idx}] 429 Hit. Waiting exact recovery window (6.0s)...")
                    await asyncio.sleep(6.0)
                    continue

                if resp.status == 200:
                    data = orjson.loads(body)
                    if not data.get("turboActive"):
                        turbo_event.clear()
                    print(f"⚡ [{get_uptime()}] [TAP #{idx}/{total_taps}] Status: {resp.status} | Response: {body}")
                    idx += 1
                else:
                    print(f"⚠️ [{get_uptime()}] [TAP #{idx}/{total_taps}] Status: {resp.status} | Response: {body}")

        except Exception as e:
            print(f"⏱️ [{get_uptime()}] [TAP #{idx}] Error: {type(e).__name__} ({e})")

        elapsed = time.time() - req_start
        await asyncio.sleep(max(0.0, tap_interval - elapsed))


async def main():
    global start_time
    start_time = time.time()
    total_taps = int(os.getenv("TOTAL_REQUESTS", "50000"))

    run_tasks = any(arg.lower() == "t" for arg in sys.argv[1:])

    connector = aiohttp.TCPConnector(limit=10, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        token = await auto_login(session)
        if not token:
            print("❌ Exiting due to login failure.")
            return

        if run_tasks:
            print("⚡ 't' flag detected: Running Task Claimer...")
            await auto_claim_tasks(session)

        print(f"🚀 Running Maximum Single-Account Yield Engine | Goal: {total_taps} Taps\n")

        # Step 1: Drain initial regular energy pool + use free Full Energy boosts
        await drain_energy_and_refill(session)

        # Step 2: Continuous Rocket Boost + Turbo tapping loop
        await asyncio.gather(
            rocket_worker(session),
            tap_worker(session, total_taps)
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n🛑 Stopped. Total uptime was {get_uptime()}.")
