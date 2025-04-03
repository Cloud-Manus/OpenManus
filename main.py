import asyncio

from app.agent.manus import Manus
from app.event import EventManager
from app.logger import logger


async def main():
    event_manager = EventManager()
    q = asyncio.Queue()
    await event_manager.connect_client(q)

    agent = Manus(event_manager=event_manager)

    try:
        prompt = input("Enter your prompt: ")
        if not prompt.strip():
            logger.warning("Empty prompt provided.")
            return

        logger.warning("Processing your request...")
        await agent.run(prompt)
        logger.info("Request processing completed.")
    except KeyboardInterrupt:
        logger.warning("Operation interrupted.")


async def event_handler(q: asyncio.Queue):
    while True:
        event = await q.get()
        print(event)


if __name__ == "__main__":
    asyncio.run(main())
