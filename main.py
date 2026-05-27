import os
from vkbottle.bot import Bot
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("VK_API2")

bot = Bot(api_key)


@bot.on.message()
async def handler(_) -> str:
    return "Hello, world!"

print("Работает?")
bot.run_forever()
