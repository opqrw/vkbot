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


def extract_history(payload: dict) -> dict:
    """Safely extracts player history from callback payload, defaulting to empty dict."""
    return payload.get("history") or {}


def is_ending(step_name: str) -> bool:
    """Checks if the step name represents an ending step (e.g. Ending1, EndingX)."""
    if not step_name:
        return False
    if step_name.startswith("Ending"):
        suffix = step_name[6:]
        return suffix.isdigit()
    return False



def format_current_stats(money: int, guilble: int, stress: int) -> str:
    """Formats a compact status bar appended to case descriptions."""
    return (
        f"\n---\n"
        f"💰 Деньги: {money:,} руб. | 🧠 Доверчивость: {guilble} | ⚡ Стресс: {stress}"
    )


def format_stats_change(money: int, guilble: int, stress: int, cons: dict) -> str:
    """Formats a detailed statistics report showing exact changes in values."""
    lines = ["\n---", "📊 Ваши показатели:"]
    
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


def build_keyboard(step_name: str, step_data: dict, money: int, guilble: int, stress: int, history: dict) -> str:
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
                "stress": stress,
                "history": history
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
                    "stress": INITIAL_STRESS,
                    "history": {}
                }
            else:
                payload = {
                    "action": "go_to",
                    "target": target,
                    "from_step": step_name,
                    "money": money,
                    "guilble": guilble,
                    "stress": stress,
                    "history": history
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
        
    # Start with initial stats and empty history
    keyboard_json = build_keyboard("Start", step_data, INITIAL_MONEY, INITIAL_GUILBLE, INITIAL_STRESS, {})
    
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
        history = extract_history(payload)
        
        if action == "go_to":
            target = payload.get("target")
            from_step = payload.get("from_step")
            interlude_done = payload.get("interlude_done", False)
            if target in scenario:
                step_data = scenario[target]
                
                # Check for interludes
                if not interlude_done and from_step:
                    interludes = step_data.get("Interludes") or step_data.get("interludes")
                    if isinstance(interludes, dict) and from_step in interludes:
                        interlude_data = interludes[from_step]
                        message_text = interlude_data.get("Message", "")
                        
                        # Apply consequences on the transition
                        cons = interlude_data.get("Consequences") or interlude_data.get("consequences") or {}
                        interlude_money = money + cons.get("Money", 0)
                        interlude_guilble = guilble + cons.get("Guilble", 0)
                        interlude_stress = stress + cons.get("Stress", 0)
                        
                        if cons:
                            message_text += format_stats_change(interlude_money, interlude_guilble, interlude_stress, cons)
                            
                        attachment_str = None
                        embeds = interlude_data.get("Embeds") or interlude_data.get("embeds") or {}
                        filename = embeds.get("Embed0")
                        if filename and not filename.startswith("photo"):
                            file_path = os.path.join("embeds", filename)
                            if os.path.exists(file_path):
                                attachment_str = await photo_uploader.upload(file_path, peer_id=event.peer_id)
                        else:
                            attachment_str = filename
                            
                        interlude_keyboard = Keyboard(inline=True)
                        interlude_keyboard.add(
                            Callback("Дальше", payload={
                                "action": "go_to",
                                "target": target,
                                "from_step": from_step,
                                "interlude_done": True,
                                "money": interlude_money,
                                "guilble": interlude_guilble,
                                "stress": interlude_stress,
                                "history": history
                            })
                        )
                        keyboard_json = interlude_keyboard.get_json()
                        await event.edit_message(message=message_text, keyboard=keyboard_json, attachment=attachment_str or "")
                        await event.send_empty_answer()
                        return

                if is_ending(target):
                    ending_keyboard = Keyboard(inline=True)
                    ending_keyboard.add(
                        Callback("Показать результат", payload={
                            "action": "show_result",
                            "money": money,
                            "guilble": guilble,
                            "stress": stress,
                            "history": history
                        })
                    )
                    keyboard_json = ending_keyboard.get_json()
                else:
                    keyboard_json = build_keyboard(target, step_data, money, guilble, stress, history)
                
                # Append compact status bar for case steps (except Start screen and Endings)
                message_text = step_data["Message"]
                if target != "Start" and not is_ending(target):
                    message_text += format_current_stats(money, guilble, stress)
                
                # Check for Embed0 (initial message image)
                attachment_str = None
                embeds = step_data.get("Embeds", {})
                filename = embeds.get("Embed0")
                if filename and not filename.startswith("photo"):
                    file_path = os.path.join("embeds", filename)
                    if os.path.exists(file_path):
                        attachment_str = await photo_uploader.upload(file_path, peer_id=event.peer_id)
                else:
                    attachment_str = filename
                    
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
                
                # Update history
                new_history = dict(history)
                new_history[step] = reply_key
                
                # Append consequences report to outcome text
                final_text = reply_text + format_stats_change(new_money, new_guilble, new_stress, cons)
                
                # Check for choice embed: Embed1 for choice_id "1", etc.
                attachment_str = None
                embeds = step_data.get("Embeds", {})
                filename = embeds.get(f"Embed{choice_id}")
                if filename and not filename.startswith("photo"):
                    file_path = os.path.join("embeds", filename)
                    if os.path.exists(file_path):
                        attachment_str = await photo_uploader.upload(file_path, peer_id=event.peer_id)
                else:
                    attachment_str = filename
                    
                # Determine next transition
                next_step = None
                goto_block = step_data.get("Go-to") or step_data.get("go-to")
                if isinstance(goto_block, dict):
                    # Check both ReplyX and replyX
                    target_step = goto_block.get(f"Reply{choice_id}") or goto_block.get(f"reply{choice_id}")
                    if target_step:
                        if target_step in scenario:
                            next_step = target_step
                        else:
                            logger.warning(f"Target step '{target_step}' defined in Go-to of '{step}' was not found in scenario.")

                reply_keyboard = Keyboard(inline=True)
                
                if next_step:
                    reply_keyboard.add(
                        Callback("Дальше", payload={
                            "action": "go_to",
                            "target": next_step,
                            "from_step": step,
                            "money": new_money,
                            "guilble": new_guilble,
                            "stress": new_stress,
                            "history": new_history
                        })
                    )
                else:
                    reply_keyboard.add(
                        Callback("Начать заново", payload={
                            "action": "go_to",
                            "target": "Start",
                            "money": INITIAL_MONEY,
                            "guilble": INITIAL_GUILBLE,
                            "stress": INITIAL_STRESS,
                            "history": {}
                        })
                    )
                    
                keyboard_json = reply_keyboard.get_json()
                await event.edit_message(message=final_text, keyboard=keyboard_json, attachment=attachment_str or "")
                await event.send_empty_answer()

        elif action == "show_result":
            # 1. Format the final result text
            result_text = "🏆 Итоги квеста\n\n"
            result_text += f"💰 Деньги: {money:,} руб.\n"
            result_text += f"🧠 Доверчивость: {guilble}\n"
            result_text += f"⚡ Стресс: {stress}\n\n"
            result_text += "📝 История ваших действий:\n"
            
            # Sort the history items by scenario keys order to show actions in logical order
            # The scenario keys represent the chronological order of cases: Case 1, Case 2, Case 3, Case 4, etc.
            scenario_keys = list(scenario.keys())
            ordered_history = sorted(history.items(), key=lambda x: scenario_keys.index(x[0]) if x[0] in scenario_keys else 999)
            
            for step_name, reply_key in ordered_history:
                step_data = scenario.get(step_name)
                if step_data:
                    results = step_data.get("Results") or step_data.get("results") or {}
                    action_desc = results.get(reply_key)
                    if action_desc:
                        result_text += f"• {action_desc}\n\n"
            
            # 2. Build the result keyboard (Start again)
            result_keyboard = Keyboard(inline=True)
            result_keyboard.add(
                Callback("Начать заново", payload={
                    "action": "go_to",
                    "target": "Start",
                    "money": INITIAL_MONEY,
                    "guilble": INITIAL_GUILBLE,
                    "stress": INITIAL_STRESS,
                    "history": {}
                })
            )
            keyboard_json = result_keyboard.get_json()
            
            # 3. Edit the message to show final results
            await event.edit_message(message=result_text, keyboard=keyboard_json, attachment="")
            await event.send_empty_answer()

                
    except Exception as e:
        logger.error(f"Error handling callback: {e}", exc_info=True)


if __name__ == "__main__":
    print("Работает?")
    bot.run_forever()
