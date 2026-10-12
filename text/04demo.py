# 04_simple_cross_thread.py —— 跨线程发消息的最简例子
# 角色只有两个：主事件循环（前台）+ 普通线程（外勤）
# 直击一个核心：外勤线程不能直接跑"协程"，必须打电话委托主循环

import asyncio
import threading
import time

async def main():
    #当前正在执行的 asyncio 事件循环实例对象
    loop = asyncio.get_running_loop()   # 拿到"前台电话线"（主事件循环）
    print("===== 外勤查询完数据，想让前台把结果发给用户 =====")

    # 【前台】本职：一直值班收消息（模拟 WebSocket 监听）
    async def receptionist():
        for i in range(3):
            print(f"  [前台] 值班中...处理第 {i} 件日常事务")
            await asyncio.sleep(1)
    asyncio.create_task(receptionist())

    # 【外勤】一个普通线程，在"外面"干活
    def field_worker(name):
        time.sleep(1.5)   # 1. 模拟在外面跑腿（搜网页 / 查数据库）
        print(f"  [外勤{name}] 跑腿完成，想把结果发给用户...")
        print(f"  [外勤{name}] 但『发消息』是个协程，只能在主循环里跑！")

        # 『发消息』这个动作（协程）
        async def send_message():
            await asyncio.sleep(0.2)   # 模拟网络 IO
            return f"报告已发给用户（来自外勤{name}）"

        # 2. 打电话委托前台：把协程投递给主循环
        future = asyncio.run_coroutine_threadsafe(send_message(), loop)
        # 3. 握着电话等回执（只阻塞自己，主循环不受影响）
        result = future.result(timeout=5)
        print(f"  [外勤{name}] 收到前台回执 -> {result}")

    # 派两名外勤出去
    threading.Thread(target=field_worker, args=("A",), daemon=True).start()
    threading.Thread(target=field_worker, args=("B",), daemon=True).start()

    # 主循环继续值班（模拟 FastAPI 还在处理其他请求）
    await asyncio.sleep(4)
    print("===== 场景结束 =====")

asyncio.run(main())