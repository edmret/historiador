import asyncio
from backend.database import init_db, engine

async def run_migrations():
    await init_db()
    print("Database tables created successfully")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(run_migrations())
