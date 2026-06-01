import os
import logging
import json
from vkbottle import Callback, GroupEventType, Keyboard, PhotoMessageUploader
from vkbottle.bot import Bot, Message, MessageEvent

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Game Constants
INITIAL_MONEY = 50000
INITIAL_GUILBLE = 0
INITIAL_STRESS = 0

api_key = os.getenv("VK_API2")
if not api_key:
    logger.error("VK_API2 key is not defined in .env file.")
bot = Bot(api_key)
photo_uploader = PhotoMessageUploader(bot.api)


try:
    with open('scenario.json', 'r', encoding='utf-8') as file:
        scenario = json.load(file)
    logger.info("Successfully loaded scenario.json")
except Exception as e:
    logger.error(f"Failed to load scenario.json: {e}")
    scenario = {}


def get_next_step(current_step: str) -> str | None:
    """Finds the next logical step in the scenario after the current one."""
    steps = list(scenario.keys())
    try:
        idx = steps.index(current_step)
        if idx + 1 < len(steps):
            return steps[idx + 1]
    except ValueError:
        pass
    return None


def extract_stats(payload: dict) -> tuple[int, int, int]:
    """Safely extracts player statistics from callback payload, defaulting to initial values."""
    money = payload.get("money", INITIAL_MONEY)
    guilble = payload.get("guilble", INITIAL_GUILBLE)
    stress = payload.get("stress", INITIAL_STRESS)
    return money, guilble, stress


def format_current_stats(money: int, guilble: int, stress: int) -> str:
    """Formats a compact status bar appended to case descriptions."""
    return (
        f"\n---\n"
        f"💰 Деньги: {money:,} руб. | 🧠 Доверчивость: {guilble} | ⚡ Стресс: {stress}"
    )


def format_stats_change(money: int, guilble: int, stress: int, cons: dict) -> str:
    """Formats a detailed statistics report showing exact changes in values."""
    lines = ["\n---", "📊 **Ваши показатели:**"]
    
    # Format Money change
    money_str = f"💰 Деньги: {money:,} руб."
    if cons and cons.get("Money", 0) != 0:
        val = cons["Money"]
        sign = "+" if val > 0 else ""
        emoji = "🟢" if val > 0 else "🔴"
        money_str += f" ({emoji} {sign}{val:,} руб.)"
    lines.append(money_str)
    
    # Format Gullibility change (Guilble key in JSON)
    guilble_str = f"🧠 Доверчивость: {guilble}"
    if cons and cons.get("Guilble", 0) != 0:
        val = cons["Guilble"]
        sign = "+" if val > 0 else ""
        emoji = "🔴" if val > 0 else "🟢"  # Gullibility increase is bad, decrease is good
        guilble_str += f" ({emoji} {sign}{val})"
    lines.append(guilble_str)
    
    # Format Stress change
    stress_str = f"⚡ Стресс: {stress}"
    if cons and cons.get("Stress", 0) != 0:
        val = cons["Stress"]
        sign = "+" if val > 0 else ""
        emoji = "🔴" if val > 0 else "🟢"  # Stress increase is bad, decrease is good
        stress_str += f" ({emoji} {sign}{val})"
    lines.append(stress_str)
    
    return "\n".join(lines)


def build_keyboard(step_name: str, step_data: dict, money: int, guilble: int, stress: int) -> str:
    """Dynamically builds an inline keyboard with stats state propagation."""
    keyboard = Keyboard(inline=True)
    buttons = step_data.get("Buttons", {})
    
    # Sort buttons to keep order (Button1, Button2, etc.)
    sorted_buttons = sorted(buttons.items(), key=lambda x: x[0])
    
    for i, (btn_key, btn_text) in enumerate(sorted_buttons):
        choice_id = btn_key.replace("Button", "")
        
        # VK API has a strict 40-character maximum limit for button labels
        label = btn_text
        if len(label) > 40:
            label = label[:37] + "..."
            
        if "Replies" in step_data:
            payload = {
                "action": "show_reply",
                "step": step_name,
                "choice_id": choice_id,
                "money": money,
                "guilble": guilble,
                "stress": stress
            }
        else:
            next_step = get_next_step(step_name)
            target = next_step if next_step else "Start"
            
            # Reset stats on restarting
            if target == "Start":
                payload = {
                    "action": "go_to",
                    "target": target,
                    "money": INITIAL_MONEY,
                    "guilble": INITIAL_GUILBLE,
                    "stress": INITIAL_STRESS
                }
            else:
                payload = {
                    "action": "go_to",
                    "target": target,
                    "money": money,
                    "guilble": guilble,
                    "stress": stress
                }
            
        keyboard.add(Callback(label, payload=payload))
        if i < len(sorted_buttons) - 1:
            keyboard.row()
            
    return keyboard.get_json()


@bot.on.message()
async def start_handler(message: Message):
    """Triggers the start of the scenario when any message is received."""
    step_data = scenario.get("Start")
    if not step_data:
        await message.answer("Сценарий не найден.")
        return
        
    # Start with initial stats
    keyboard_json = build_keyboard("Start", step_data, INITIAL_MONEY, INITIAL_GUILBLE, INITIAL_STRESS)
    
    # Check for Embed0 (initial message image)
    attachment_str = None
    embeds = step_data.get("Embeds", {})
    filename = embeds.get("Embed0")
    if filename:
        file_path = os.path.join("embeds", filename)
        if os.path.exists(file_path):
            attachment_str = await photo_uploader.upload(file_path, peer_id=message.peer_id)
            
    await message.answer(step_data["Message"], keyboard=keyboard_json, attachment=attachment_str)


@bot.on.raw_event(GroupEventType.MESSAGE_EVENT, MessageEvent)
async def handle_callback(event: MessageEvent):
    """Handles all button clicks statelessly, propagating stats in payloads."""
    try:
        # Load and parse payload safely
        try:
            payload = event.get_payload_json()
        except Exception:
            payload = event.payload
            if isinstance(payload, str):
                payload = json.loads(payload)
                
        if not payload or not isinstance(payload, dict):
            return
            
        action = payload.get("action")
        money, guilble, stress = extract_stats(payload)
        
        if action == "go_to":
            target = payload.get("target")
            if target in scenario:
                step_data = scenario[target]
                keyboard_json = build_keyboard(target, step_data, money, guilble, stress)
                
                # Append compact status bar for case steps (except Start screen)
                message_text = step_data["Message"]
                if target != "Start":
                    message_text += format_current_stats(money, guilble, stress)
                
                # Check for Embed0 (initial message image)
                attachment_str = None
                embeds = step_data.get("Embeds", {})
                filename = embeds.get("Embed0")
                if filename:
                    file_path = os.path.join("embeds", filename)
                    if os.path.exists(file_path):
                        attachment_str = await photo_uploader.upload(file_path, peer_id=event.peer_id)
                    
                await event.edit_message(message=message_text, keyboard=keyboard_json, attachment=attachment_str or "")
                await event.send_empty_answer()
                
        elif action == "show_reply":
            step = payload.get("step")
            choice_id = payload.get("choice_id")
            
            if step in scenario:
                step_data = scenario[step]
                
                # Extract outcome text
                replies = step_data.get("Replies", {})
                reply_key = f"Reply{choice_id}"
                reply_text = replies.get(reply_key, "Ответ не найден.")
                
                # Calculate and apply consequences
                cons_block = step_data.get("Consequences", {})
                cons = cons_block.get(f"cons{choice_id}", {})
                
                new_money = money + cons.get("Money", 0)
                new_guilble = guilble + cons.get("Guilble", 0)
                new_stress = stress + cons.get("Stress", 0)
                
                # Append consequences report to outcome text
                final_text = reply_text + format_stats_change(new_money, new_guilble, new_stress, cons)
                
                # Check for choice embed: Embed1 for choice_id "1", etc.
                attachment_str = None
                embeds = step_data.get("Embeds", {})
                filename = embeds.get(f"Embed{choice_id}")
                if filename:
                    file_path = os.path.join("embeds", filename)
                    if os.path.exists(file_path):
                        attachment_str = await photo_uploader.upload(file_path, peer_id=event.peer_id)
                
                # Determine next transition
                next_step = get_next_step(step)
                reply_keyboard = Keyboard(inline=True)
                
                if next_step:
                    reply_keyboard.add(
                        Callback("Дальше", payload={
                            "action": "go_to",
                            "target": next_step,
                            "money": new_money,
                            "guilble": new_guilble,
                            "stress": new_stress
                        })
                    )
                else:
                    reply_keyboard.add(
                        Callback("Начать заново", payload={
                            "action": "go_to",
                            "target": "Start",
                            "money": INITIAL_MONEY,
                            "guilble": INITIAL_GUILBLE,
                            "stress": INITIAL_STRESS
                        })
                    )
                    
                keyboard_json = reply_keyboard.get_json()
                await event.edit_message(message=final_text, keyboard=keyboard_json, attachment=attachment_str or "")
                await event.send_empty_answer()
                
    except Exception as e:
        logger.error(f"Error handling callback: {e}", exc_info=True)


if __name__ == "__main__":
    print("Работает?")
    bot.run_forever()
