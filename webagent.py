import ollama
import sys_msgs
import requests
import trafilatura
import json
import speech_recognition as sr
import edge_tts
import threading
import os
import platform
from bs4 import BeautifulSoup
from colorama import init, Fore, Style
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
import tempfile
import subprocess
import random
import re
import sys
import string
from duckduckgo_search import DDGS

# -------------------------------------
# Initialization
# -------------------------------------
init(autoreset=True)

assistant_convo = [sys_msgs.assistant_msg]

voice_mode = False
stop_voice_flag = False
executor = ThreadPoolExecutor()
web_search_mode = False
reasoning_mode = False
unfiltered_mode = False  # NEW toggle for unfiltered
tts_mode = False         # NEW toggle for TTS mode

MODELS = {
    'main': 'llama3.2',             # normal
    'search': 'deepseek-r1:14b',      # reasoning
    'unfiltered': 'r1-1776:70b',      # unfiltered
}

FUN_PROMPTS = [
    "Your move, adventurer! ➜ ",
    "Speak, oh wise one! ➜ ",
    "Ready when you are! ➜ ",
    "Awaiting your command... ➜ ",
    "What shall we discuss? ➜ ",
    "Tell me your secrets! ➜ ",
    "A thought, a question, an idea? ➜ ",
    "Loading brain cells... Done! ➜ ",
    "I sense a great query incoming... ➜ ",
    "Hit me with your best shot! ➜ ",
    "The scrolls are ready... What knowledge do you seek? ➜ ",
    "Unleash your curiosity! ➜ ",
    "Mysterious forces whisper... Ask your question! ➜ ",
    "Loading witty response generator... Ready! ➜ ",
    "The Oracle is listening... What is your inquiry? ➜ ",
    "Summoning infinite knowledge... What shall I reveal? ➜ ",
    "Daring adventurer, your path awaits! What’s next? ➜ ",
    "I have prepared my wisdom... Now, ask away! ➜ ",
    "Echoes of the universe await your voice... Speak! ➜ ",
    "I've seen things you wouldn't believe... Now, what do you wish to know? ➜ ",
    "Initializing query subroutine... Ready for input! ➜ ",
    "The Force is strong with this one... Ask away! ➜ ",
    "By the power of Grayskull... What do you seek? ➜ ",
    "Engaging warp drive... Destination: knowledge! ➜ ",
    "I've calculated a 99.7% probability that you have a question. Fire away! ➜ ",
    "Compiling brain.exe... No syntax errors detected! Ask your question. ➜ ",
    "It's dangerous to go alone! Take this answer. ➜ ",
    "Roll for investigation... You rolled a 20! What do you want to know? ➜ ",
    "Welcome, traveler! What knowledge do you seek from the archives? ➜ ",
    "In an alternate timeline, you already asked this... But let’s do it again! ➜ ",
]

def get_fun_prompt():
    return random.choice(FUN_PROMPTS)

FUN_LISTENING_MESSAGES = [
    "🦻 I'm all ears... (Say 'voice stop' if you want me to stop listening)",
    "🎤 Speak now, or forever hold your peace! (Say 'stop talking' to mute me)",
    "🤖 Listening... Beep boop. (Say 'mute yourself' if you need some silence)",
    "👂 Tell me more, I’m intrigued! (Say 'stop speaking' to exit voice mode)",
    "🎧 Tuning in to your frequency... (Say 'voice mode' to switch back to text)",
    "📡 Receiving transmission... (Say 'end voice mode' if you want me to stop)",
    "🛸 Scanning for intelligent life... (Say 'voice stop' if you need a break)",
    "🎙️ Ready to record your wisdom! (Say 'stop talking' to shut me up)",
    "🔊 Amplifying your voice… (Say 'mute yourself' if you want quiet time)",
    "🌀 The AI is listening... (Say 'stop speaking' to return to text mode)",
]

def get_listening_message():
    return random.choice(FUN_LISTENING_MESSAGES)

# Funny messages after each card is drawn
DRAW_MESSAGES = [
    "The spirits whisper secrets...",
    "A cosmic giggle resonates in the ether...",
    "Fate smiles, placing this card at your feet...",
    "Reality quivers as the card is revealed...",
    "An astral hush, then the card arrives...",
    "A subtle cosmic hum signals the card's appearance...",
    "The card glows with hidden possibility...",
    "Destiny unravels with a flourish of the deck...",
    "The veil parts, revealing your next card...",
    "A soft bell-like chime resonates. The card emerges..."
]

def random_draw_msg():
    return random.choice(DRAW_MESSAGES)

# -------------------------------------
# Utility Functions
# -------------------------------------
def summarize_text(text, max_sentences=3):
    sentences = text.split(". ")
    return ". ".join(sentences[:max_sentences]) + "." if sentences else text

def sanitize_filename(filename):
    valid_chars = f"-_.() {string.ascii_letters}{string.digits}"
    return "".join(c for c in filename if c in valid_chars).replace(" ", "_")

def needs_more_search(response_text):
    triggers = [
        "i don't have enough information",
        "i need more details",
        "i couldn't find enough data",
        "let me check further",
        "unclear results"
    ]
    return any(t in response_text.lower() for t in triggers)

def refine_query(response_text):
    missing_keywords = []
    words = response_text.split()
    for i, word in enumerate(words):
        if word.lower() in ["about", "regarding", "on", "of"] and (i + 1 < len(words)):
            missing_keywords.append(words[i + 1])
    refined = " ".join(missing_keywords) if missing_keywords else response_text[:50]
    print(f"{Fore.YELLOW}Refining search with: {refined}{Style.RESET_ALL}")
    return refined

# -------------------------------------
# Voice Handling Functions
# -------------------------------------
def stop_voice():
    global stop_voice_flag, voice_mode
    stop_voice_flag = True
    voice_mode = False
    print(f"{Fore.RED}Voice stopped. Returning to text mode.{Style.RESET_ALL}")
    if platform.system() == "Windows":
        os.system("taskkill /IM mpg123.exe /F")
    else:
        os.system("pkill -STOP mpg123")
        time.sleep(0.5)
        os.system("pkill mpg123")

async def speak_text(text):
    global stop_voice_flag
    if voice_mode or tts_mode:
        stop_voice_flag = False
        speed = "+50%" if "?" in text else "+30%" if len(text) > 150 else "+40%"
        clean_text = re.sub(r'[*_`]', '', text)
        temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_audio_path = temp_audio.name
        temp_audio.close()
        try:
            tts = edge_tts.Communicate(clean_text, voice="en-GB-RyanNeural", rate=speed)
            await tts.save(temp_audio_path)
        except Exception as e:
            print(f"{Fore.RED}edge-tts error: {e}{Style.RESET_ALL}")
            return
        if stop_voice_flag:
            os.unlink(temp_audio_path)
            return
        if not stop_voice_flag:
            if platform.system() == "Windows":
                subprocess.run(["start", "", temp_audio_path], shell=True)
            else:
                process = subprocess.Popen(["mpg123", "-q", temp_audio_path],
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
                while process.poll() is None:
                    if stop_voice_flag:
                        process.terminate()
                        break
                    await asyncio.sleep(0.1)
        os.unlink(temp_audio_path)

# Specialized TTS for Tarot readings (witchy voice)
async def speak_tarot_text(text):
    custom_voice = "en-GB-LibbyNeural"  # Use a custom witchy voice
    speed = "+50%" if "?" in text else "+30%" if len(text) > 150 else "+40%"
    clean_text = re.sub(r'[*_`]', '', text)
    temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    temp_audio_path = temp_audio.name
    temp_audio.close()
    try:
        tts = edge_tts.Communicate(clean_text, voice=custom_voice, rate=speed)
        await tts.save(temp_audio_path)
    except Exception as e:
        print(f"{Fore.RED}edge-tts error (tarot): {e}{Style.RESET_ALL}")
        return
    if not stop_voice_flag:
        if platform.system() == "Windows":
            subprocess.run(["start", "", temp_audio_path], shell=True)
        else:
            process = subprocess.Popen(["mpg123", "-q", temp_audio_path],
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
            while process.poll() is None:
                if stop_voice_flag:
                    process.terminate()
                    break
                await asyncio.sleep(0.1)
    os.unlink(temp_audio_path)

# -------------------------------------
# Streaming Response Function
# -------------------------------------
def stream_response():
    if not reasoning_mode:
        print(f"{Fore.CYAN}Generating response...{Style.RESET_ALL}\n")
    complete_response = ""
    if unfiltered_mode:
        chosen_model = MODELS["unfiltered"]
    elif reasoning_mode:
        chosen_model = MODELS["search"]
    else:
        chosen_model = MODELS["main"]
    response_stream = ollama.chat(model=chosen_model, messages=assistant_convo, stream=True)
    last_spoken_index = 0
    async def speak_in_background():
        nonlocal last_spoken_index
        while last_spoken_index < len(complete_response):
            await asyncio.sleep(0.2)
            new_text = complete_response[last_spoken_index:]
            last_spoken_index = len(complete_response)
            await speak_text(new_text)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    speech_task = loop.create_task(speak_in_background())
    for chunk in response_stream:
        text_chunk = chunk["message"]["content"]
        complete_response += text_chunk
        print(f"{Fore.GREEN}{text_chunk}{Style.RESET_ALL}", end="", flush=True)
    print()
    loop.run_until_complete(speech_task)
    loop.close()
    assistant_convo.append({"role": "assistant", "content": complete_response})

# -------------------------------------
# Recognize Speech Function (Improved)
# -------------------------------------
def recognize_speech():
    global stop_voice_flag, voice_mode, web_search_mode
    r = sr.Recognizer()
    r.pause_threshold = 0.8
    audio_chunks = []
    with sr.Microphone() as source:
        print(f"{Fore.YELLOW}{get_listening_message()}{Style.RESET_ALL}")
        last_audio_time = time.time()
        while True:
            try:
                chunk = r.listen(source, timeout=5, phrase_time_limit=5)
                audio_chunks.append(chunk)
                last_audio_time = time.time()
            except sr.WaitTimeoutError:
                break
            if time.time() - last_audio_time > 5:
                break
    if not audio_chunks:
        return ""
    recognized_text = ""
    for chunk in audio_chunks:
        try:
            recognized_text += r.recognize_google(chunk) + " "
        except Exception:
            continue
    if any(cmd in recognized_text.lower() for cmd in ["voice stop", "stop talking", "be quiet", "mute yourself", "stop speaking", "end voice mode", "voice mode"]):
        stop_voice_flag = True
        stop_voice()
        voice_mode = False
        print(f"{Fore.RED}Voice OFF.{Style.RESET_ALL}")
        return None
    if "web search stop" in recognized_text.lower():
        web_search_mode = False
        print(f"{Fore.YELLOW}Web search OFF.{Style.RESET_ALL}")
        return ""
    return recognized_text.lower().strip()

# -------------------------------------
# Model and Web Search Functions
# -------------------------------------
def pull_model():
    for model_key, model_val in MODELS.items():
        print(f"{Fore.CYAN}Pulling model '{model_val}' for key '{model_key}'...{Style.RESET_ALL}")
        ollama.pull(model=model_val)
        print(f"{Fore.GREEN}Model '{model_val}' pulled successfully.{Style.RESET_ALL}")

def search_web(query):
    results = []
    extracted_data = []
    try:
        with DDGS() as ddgs:
            for result in ddgs.text(query, max_results=5):
                url = result["href"]
                title = result["title"]
                results.append({"title": title, "url": url})
                page_content = fetch_page_content(url)
                if page_content:
                    extracted_data.append({"title": title, "url": url, "content": page_content})
    except Exception:
        pass
    return extracted_data

def fetch_page_content(url):
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            extracted_text = trafilatura.extract(r.text)
            return extracted_text if extracted_text else "No extractable content found."
    except Exception:
        pass
    return None

def iterative_web_search(query, max_retries=5):
    retries = 0
    accumulated_context = ""
    while retries < max_retries:
        print(f"{Fore.CYAN}[Search Attempt {retries + 1}/{max_retries}] Searching for: {query}{Style.RESET_ALL}\n")
        results = search_web(query)
        if not results:
            retries += 1
            continue
        context_snippets = []
        for result in results:
            summary = summarize_text(result["content"])
            context_snippets.append(f"{result['title']}: {summary}")
        accumulated_context += "\n\n".join(context_snippets) + "\n\n"
        assistant_convo.append({"role": "system", "content": f"Here is some info:\n{accumulated_context}"})
        if unfiltered_mode:
            model_key = "unfiltered"
        elif reasoning_mode:
            model_key = "search"
        else:
            model_key = "main"
        response = ollama.chat(model=MODELS[model_key], messages=assistant_convo)
        assistant_convo.append({"role": "assistant", "content": response["message"]["content"]})
        if not needs_more_search(response["message"]["content"]):
            return response["message"]["content"]
        query = refine_query(response["message"]["content"])
        retries += 1
    return response["message"]["content"]

# -------------------------------------
# Knowledge Base Functions
# -------------------------------------
def search_knowledge_base(topic):
    kb_path = os.path.join(os.path.dirname(__file__), "knowledge_base")
    results = []
    for root, _, files in os.walk(kb_path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if re.search(topic, content, re.IGNORECASE):
                        results.append((file, content))
            except:
                pass
    return results

def record_to_knowledge_base(filename, content):
    kb_path = os.path.join(os.path.dirname(__file__), "knowledge_base")
    if not os.path.exists(kb_path):
        os.makedirs(kb_path)
    safe_filename = sanitize_filename(filename)
    file_path = os.path.join(kb_path, safe_filename)
    try:
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(content)
        print(f"{Fore.GREEN}Information recorded to '{safe_filename}' in knowledge_base.{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}Failed to record information: {e}{Style.RESET_ALL}")

# -------------------------------------
# Tarot Data and Reading
# -------------------------------------
MAJOR_ARCANA = [
    "0. The Fool", "I. The Magician", "II. The High Priestess", "III. The Empress",
    "IV. The Emperor", "V. The Hierophant", "VI. The Lovers", "VII. The Chariot",
    "VIII. Strength", "IX. The Hermit", "X. Wheel of Fortune", "XI. Justice",
    "XII. The Hanged Man", "XIII. Death", "XIV. Temperance", "XV. The Devil",
    "XVI. The Tower", "XVII. The Star", "XVIII. The Moon", "XIX. The Sun",
    "XX. Judgement", "XXI. The World"
]

MINOR_ARCANA = [
    "Ace of Wands", "Two of Wands", "Three of Wands", "Four of Wands", "Five of Wands",
    "Six of Wands", "Seven of Wands", "Eight of Wands", "Nine of Wands", "Ten of Wands",
    "Page of Wands", "Knight of Wands", "Queen of Wands", "King of Wands",
    "Ace of Cups", "Two of Cups", "Three of Cups", "Four of Cups", "Five of Cups",
    "Six of Cups", "Seven of Cups", "Eight of Cups", "Nine of Cups", "Ten of Cups",
    "Page of Cups", "Knight of Cups", "Queen of Cups", "King of Cups",
    "Ace of Swords", "Two of Swords", "Three of Swords", "Four of Swords", "Five of Swords",
    "Six of Swords", "Seven of Swords", "Eight of Swords", "Nine of Swords", "Ten of Swords",
    "Page of Swords", "Knight of Swords", "Queen of Swords", "King of Swords",
    "Ace of Pentacles", "Two of Pentacles", "Three of Pentacles", "Four of Pentacles", "Five of Pentacles",
    "Six of Pentacles", "Seven of Pentacles", "Eight of Pentacles", "Nine of Pentacles", "Ten of Pentacles",
    "Page of Pentacles", "Knight of Pentacles", "Queen of Pentacles", "King of Pentacles"
]

SEPHIROTH = [
    "1. Kether (Crown) - Divine Consciousness",
    "2. Chokmah (Wisdom) - Creative Spark",
    "3. Binah (Understanding) - Form & Limitation",
    "4. Chesed (Mercy) - Expansion & Generosity",
    "5. Geburah (Strength) - Power & Discipline",
    "6. Tiphareth (Beauty) - Harmony & Balance",
    "7. Netzach (Victory) - Emotion & Desire",
    "8. Hod (Glory) - Intellect & Analysis",
    "9. Yesod (Foundation) - Subconscious & Dreams",
    "10. Malkuth (Kingdom) - Manifestation & Reality"
]

def random_draw_msg():
    return random.choice(DRAW_MESSAGES)

def tarot_reading():
    print(f"{Fore.MAGENTA}The mystic energies align... What question do you seek guidance on?")
    question = input(f"{Fore.YELLOW}Your question: ")
    print(f"{Fore.CYAN}\nDrawing from a single 78-card deck. Minor Arcana fill the 10 Sephiroth; Majors go on the Path...\n")
    deck = MAJOR_ARCANA + MINOR_ARCANA
    used = set()
    seph_cards = [None] * 10
    path_cards = []
    minors_filled = 0
    while minors_filled < 10:
        card = random.choice(deck)
        if card in used:
            continue
        used.add(card)
        print(f"{Fore.YELLOW}**Drew card**: {Fore.WHITE}{card}")
        print(f"{Fore.CYAN}{random_draw_msg()}\n")
        time.sleep(1.0)
        if card in MAJOR_ARCANA:
            path_cards.append(card)
        else:
            seph_cards[minors_filled] = card
            minors_filled += 1
    reading_text = f"**Question**: {question}\n\n"
    reading_text += "**Sephiroth (Minors)**:\n"
    for idx, s in enumerate(SEPHIROTH):
        reading_text += f"{s}: {seph_cards[idx]}\n"
    reading_text += "\n**Paths (Majors) in the order drawn**:\n"
    if path_cards:
        for i, c in enumerate(path_cards, start=1):
            reading_text += f"Path #{i}: {c}\n"
    else:
        reading_text += "None drawn.\n"
    print(f"{Fore.BLUE}\n--- Final Tree of Life Layout ---\n{reading_text}\n")
    decision = input(f"{Fore.MAGENTA}Would you like me to interpret these cards? (yes/no) ➜ ").strip().lower()
    if decision not in ["y", "yes"]:
        print(f"{Fore.YELLOW}Alright, the reading stands on its own. Farewell!")
        return
    if unfiltered_mode:
        chosen_model = MODELS["unfiltered"]
    elif reasoning_mode:
        chosen_model = MODELS["search"]
    else:
        chosen_model = MODELS["main"]
    interpret_prompt = (
        f"You are a Tarot sage. The question is: {question}\n\n"
        f"Here is the final Tree of Life reading, with 10 minor arcana assigned to the Sephiroth in the order they appeared, "
        f"and any major arcana placed as path cards:\n\n{reading_text}\n"
        f"Please provide a cohesive, mystical interpretation of how these cards might answer the question."
    )
    assistant_convo.append({"role": "user", "content": interpret_prompt})
    print(f"{Fore.CYAN}Generating interpretation from the model {chosen_model}...\n")
    response_stream = ollama.chat(model=chosen_model, messages=assistant_convo, stream=True)
    final_text = ""
    for chunk in response_stream:
        text_chunk = chunk["message"]["content"]
        final_text += text_chunk
        print(f"{Fore.GREEN}{text_chunk}{Style.RESET_ALL}", end="", flush=True)
    print()
    assistant_convo.append({"role": "assistant", "content": final_text})
    print(f"\n{Fore.MAGENTA}--- End of Interpretation ---\n")
    if voice_mode or tts_mode:
        asyncio.run(speak_tarot_text(final_text))

# -------------------------------------
# MAIN INTERACTION LOOP
# -------------------------------------
def main():
    global assistant_convo, voice_mode, web_search_mode, reasoning_mode, unfiltered_mode, tts_mode
    pull_model()
    while True:
        print()
        if voice_mode:
            prompt = recognize_speech()
            if prompt is None:
                continue
        else:
            prompt = input(f"{Fore.BLUE}{get_fun_prompt()}{Style.RESET_ALL}")
        if prompt.lower() == "/reason":
            reasoning_mode = not reasoning_mode
            if reasoning_mode:
                unfiltered_mode = False
            which_model = "search" if reasoning_mode else ("unfiltered" if unfiltered_mode else "main")
            print(f"{Fore.YELLOW}Reasoning mode {'ON' if reasoning_mode else 'OFF'}. Using model: {MODELS[which_model]}{Style.RESET_ALL}")
            continue
        if prompt.lower() == "/unfiltered":
            unfiltered_mode = not unfiltered_mode
            if unfiltered_mode:
                reasoning_mode = False
            which_model = "unfiltered" if unfiltered_mode else ("search" if reasoning_mode else "main")
            print(f"{Fore.YELLOW}Unfiltered mode {'ON' if unfiltered_mode else 'OFF'}. Using model: {MODELS[which_model]}{Style.RESET_ALL}")
            continue
        if prompt.lower() == "/tts":
            tts_mode = not tts_mode
            if tts_mode and voice_mode:
                voice_mode = False
                print(f"{Fore.YELLOW}Voice mode turned OFF because TTS mode is ON.{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}TTS mode {'ON' if tts_mode else 'OFF'}.{Style.RESET_ALL}")
            continue
        if prompt.lower() == "/websearch":
            web_search_mode = not web_search_mode
            print(f"{Fore.YELLOW}Web search {'ON' if web_search_mode else 'OFF'}.{Style.RESET_ALL}")
            continue
        if prompt.lower() in ["/help", "/exit", "/clear", "/voice", "/stopvoice"]:
            if prompt.lower() == "/help":
                print(f"{Style.RESET_ALL}\nCommands:")
                print("/help - Show help")
                print("/exit - Save and exit")
                print("/clear - Reset conversation")
                print("/voice - Toggle voice mode (turns off TTS mode)")
                print("/stopvoice - Stop AI speaking mid-response")
                print("/reason - Toggle reasoning mode (deepseek-r1:14b)")
                print("/unfiltered - Toggle unfiltered mode (r1-1776:70b)")
                print("/tts - Toggle TTS mode (reads responses aloud)")
                print("/websearch - Toggle web search mode (Say 'web search stop' to disable it)")
                print("/tarot - Perform a single-deck Tree of Life Tarot reading")
                print("/archives [topic] - Search knowledge base for [topic]\n")
            elif prompt.lower() == "/exit":
                print(f"{Fore.MAGENTA}Exiting...{Style.RESET_ALL}")
                exit()
            elif prompt.lower() == "/clear":
                assistant_convo = [sys_msgs.assistant_msg]
                print(f"{Fore.YELLOW}Conversation reset.{Style.RESET_ALL}")
            elif prompt.lower() == "/voice":
                voice_mode = not voice_mode
                if voice_mode and tts_mode:
                    tts_mode = False
                    print(f"{Fore.YELLOW}TTS mode turned OFF because Voice mode is ON.{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}Voice {'ON' if voice_mode else 'OFF'}.{Style.RESET_ALL}")
            elif prompt.lower() == "/stopvoice":
                stop_voice()
                print(f"{Fore.RED}Voice stopped.{Style.RESET_ALL}")
            continue
        if prompt.lower().startswith("/archives"):
            parts = prompt.split(maxsplit=1)
            if len(parts) < 2:
                continue
            topic = parts[1]
            found = search_knowledge_base(topic)
            if found:
                for fname, text in found:
                    print(f"\nFound in {fname}:\n{text}\n")
            else:
                print(f"{Fore.RED}No results found for '{topic}' in knowledge_base.{Style.RESET_ALL}")
            continue
        if prompt.lower() == "/tarot":
            tarot_reading()
            continue
        if web_search_mode and not prompt.startswith("/"):
            results = search_web(prompt)
            if results:
                context_snippets = []
                for r in results:
                    c = summarize_text(r["content"])
                    if c.strip():
                        context_snippets.append(f"{r['title']}: {c}")
                if context_snippets:
                    joined = "\n\n".join(context_snippets)
                    assistant_convo.append({"role": "system", "content": f"Here is data:\n{joined}"})
                    record_to_knowledge_base(prompt, joined)
            if unfiltered_mode:
                chosen_model = MODELS["unfiltered"]
            elif reasoning_mode:
                chosen_model = MODELS["search"]
            else:
                chosen_model = MODELS["main"]
            assistant_convo.append({"role": "user", "content": prompt})
            response = ollama.chat(model=chosen_model, messages=assistant_convo)
            final_text = response["message"]["content"]
            assistant_convo.append({"role": "assistant", "content": final_text})
            print(f"\n{Fore.GREEN}{final_text}{Style.RESET_ALL}\n")
            if voice_mode or tts_mode:
                asyncio.run(speak_text(final_text))
            continue
        assistant_convo.append({"role": "user", "content": prompt})
        stream_response()
        if voice_mode or tts_mode:
            last_resp = assistant_convo[-1]["content"]
            asyncio.run(speak_text(last_resp))

if __name__ == "__main__":
    main()