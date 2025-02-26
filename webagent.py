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

init(autoreset=True)

# Initial conversation state
assistant_convo = [sys_msgs.assistant_msg]

# Modes and flags
voice_mode = False
stop_voice_flag = False
executor = ThreadPoolExecutor()
web_search_mode = False
reasoning_mode = False  # ➜ Toggles between 'main' and 'search' models

MODELS = {
    'main': 'llama3.2',
    'search': 'deepseek-r1:14b',  # Model to use when reasoning mode is ON
}

# Prompts for text input
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

# Voice mode listening messages
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

def summarize_text(text, max_sentences=3):
    sentences = text.split(". ")
    return ". ".join(sentences[:max_sentences]) + "." if sentences else text

def sanitize_filename(filename):
    valid_chars = f"-_.() {string.ascii_letters}{string.digits}"
    return "".join(c for c in filename if c in valid_chars).replace(" ", "_")

def needs_more_search(response_text):
    lower_response = response_text.lower()
    return any(
        phrase in lower_response
        for phrase in [
            "i don't have enough information",
            "i need more details",
            "i couldn't find enough data",
            "let me check further",
            "unclear results",
        ]
    )

def refine_query(response_text):
    missing_keywords = []
    words = response_text.split()
    for i, word in enumerate(words):
        if word.lower() in ["about", "regarding", "on", "of"] and i + 1 < len(words):
            missing_keywords.append(words[i + 1])
    refined_query = " ".join(missing_keywords) if missing_keywords else response_text[:50]
    print(f"{Fore.YELLOW}Refining search with: {refined_query}\n")
    return refined_query

def stop_voice():
    global stop_voice_flag, voice_mode
    stop_voice_flag = True
    voice_mode = False
    print(f"{Fore.RED}Voice stopped. Returning to text mode.")

    if platform.system() == "Windows":
        os.system("taskkill /IM mpg123.exe /F")
    else:
        os.system("pkill -STOP mpg123")
        time.sleep(0.5)
        os.system("pkill mpg123")

async def speak_text(text):
    global stop_voice_flag
    if voice_mode:
        stop_voice_flag = False
        speed = "+50%" if "?" in text else "+30%" if len(text) > 150 else "+40%"
        clean_text = re.sub(r'[*_`]', '', text)

        temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_audio_path = temp_audio.name
        temp_audio.close()

        tts = edge_tts.Communicate(clean_text, voice="en-GB-RyanNeural", rate=speed)
        await tts.save(temp_audio_path)

        if stop_voice_flag:
            os.unlink(temp_audio_path)
            return

        if not stop_voice_flag:
            if platform.system() == "Windows":
                subprocess.run(["start", "", temp_audio_path], shell=True)
            else:
                process = subprocess.Popen(["mpg123", "-q", temp_audio_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                while process.poll() is None:
                    if stop_voice_flag:
                        process.terminate()
                        break
                    await asyncio.sleep(0.1)

        os.unlink(temp_audio_path)

def stream_response():
    """
    Streams the assistant's response from the chosen model.
    If reasoning_mode is ON, use search model, otherwise use main model.
    """
    print(f"{Fore.CYAN}Generating response...\n")
    complete_response = ""
    last_spoken_index = 0

    # Decide which model to use based on reasoning_mode
    chosen_model = MODELS["search"] if reasoning_mode else MODELS["main"]

    response_stream = ollama.chat(model=chosen_model, messages=assistant_convo, stream=True)

    async def speak_in_background():
        nonlocal last_spoken_index
        while last_spoken_index < len(complete_response):
            await asyncio.sleep(0.2)
            if last_spoken_index < len(complete_response):
                new_text = complete_response[last_spoken_index:]
                last_spoken_index = len(complete_response)
                await speak_text(new_text)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    speech_task = loop.create_task(speak_in_background())

    for chunk in response_stream:
        text_chunk = chunk["message"]["content"]
        complete_response += text_chunk
        print(f"{Fore.GREEN}{text_chunk}", end="", flush=True)

    print()
    loop.run_until_complete(speech_task)
    loop.close()

    assistant_convo.append({"role": "assistant", "content": complete_response})

def recognize_speech():
    global stop_voice_flag, voice_mode, web_search_mode
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print(f"{Fore.YELLOW}{get_listening_message()}")
        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=8)
            speech_text = recognizer.recognize_google(audio).lower()

            stop_commands = [
                "voice stop", "stop talking", "be quiet", "mute yourself",
                "stop speaking", "end voice mode", "voice mode"
            ]
            if any(cmd in speech_text for cmd in stop_commands):
                stop_voice_flag = True
                stop_voice()
                voice_mode = False
                print(f"{Fore.RED}Voice OFF.")
                return None

            if "web search stop" in speech_text:
                web_search_mode = False
                print(f"{Fore.YELLOW}Web search OFF.")
                return ""

            return speech_text
        except (sr.UnknownValueError, sr.RequestError):
            return ""

def pull_model():
    for model in MODELS.values():
        print(f"{Fore.CYAN}Pulling model '{model}'...")
        ollama.pull(model=model)
        print(f"{Fore.GREEN}Model '{model}' pulled successfully.")

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
                    extracted_data.append({
                        "title": title,
                        "url": url,
                        "content": page_content
                    })
    except Exception as e:
        print(f"Search or scraping failed: {e}")

    return extracted_data

def fetch_page_content(url):
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            extracted_text = trafilatura.extract(response.text)
            return extracted_text if extracted_text else "No extractable content found."
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return None

def iterative_web_search(query, max_retries=5):
    retries = 0
    accumulated_context = ""

    while retries < max_retries:
        print(f"{Fore.CYAN}[Search Attempt {retries + 1}/{max_retries}] Searching for: {query}\n")
        results = search_web(query)

        if not results:
            print(f"{Fore.RED}No results found for '{query}'. Retrying with refinement...\n")
            retries += 1
            continue

        context_snippets = []
        for result in results:
            print(f"{Fore.GREEN}{result['title']}\n{Fore.BLUE}{result['url']}\n")
            summarized_content = summarize_text(result['content'])
            context_snippets.append(f"{result['title']}: {summarized_content}")

        accumulated_context += "\n\n".join(context_snippets) + "\n\n"
        assistant_convo.append({
            "role": "system",
            "content": f"Here is some information from the web:\n{accumulated_context}"
        })

        # Decide model based on reasoning_mode
        chosen_model = MODELS["search"] if reasoning_mode else MODELS["main"]
        response = ollama.chat(model=chosen_model, messages=assistant_convo)
        assistant_convo.append({"role": "assistant", "content": response["message"]["content"]})
        print(f"{Fore.MAGENTA}Assistant's response:\n{Fore.GREEN}{response['message']['content']}\n")

        if not needs_more_search(response["message"]["content"]):
            return response["message"]["content"]

        query = refine_query(response["message"]["content"])
        retries += 1

    print(f"{Fore.YELLOW}Max retries reached. Returning best available answer.\n")
    return response["message"]["content"]

def search_knowledge_base(topic):
    knowledge_base_path = os.path.join(os.path.dirname(__file__), "knowledge_base")
    results = []

    for root, _, files in os.walk(knowledge_base_path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if re.search(topic, content, re.IGNORECASE):
                        results.append((file, content))
            except FileNotFoundError:
                print(f"{Fore.RED}File '{file}' not found in knowledge_base.")

    return results

def record_to_knowledge_base(filename, content):
    knowledge_base_path = os.path.join(os.path.dirname(__file__), "knowledge_base")
    if not os.path.exists(knowledge_base_path):
        os.makedirs(knowledge_base_path)

    safe_filename = sanitize_filename(filename)
    file_path = os.path.join(knowledge_base_path, safe_filename)

    try:
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(content)
        print(f"{Fore.GREEN}Information recorded to '{file_path}' in knowledge_base.")
    except Exception as e:
        print(f"{Fore.RED}Failed to record information: {e}")

def main():
    global assistant_convo, voice_mode, web_search_mode, reasoning_mode

    pull_model()

    while True:
        print()
        if voice_mode:
            prompt = recognize_speech()
            if prompt is None:
                continue
        else:
            prompt = input(f"{Fore.BLUE}{get_fun_prompt()}")

        # Reasoning mode toggle
        if prompt.lower() == "/reason":
            reasoning_mode = not reasoning_mode
            print(f"{Fore.YELLOW}Reasoning mode {'ON' if reasoning_mode else 'OFF'}. Using model '{MODELS['search'] if reasoning_mode else MODELS['main']}'.")
            continue

        # Toggle web search
        if prompt.lower() == "/websearch":
            web_search_mode = not web_search_mode
            print(f"{Fore.YELLOW}Web search {'ON' if web_search_mode else 'OFF'}.")
            continue

        # Handle commands
        if prompt.lower() in ["/help", "/exit", "/clear", "/voice", "/stopvoice", "/scrape"]:
            if prompt.lower() == "/help":
                print("\nCommands:")
                print("/help - Show this message")
                print("/exit - Save and exit")
                print("/clear - Reset conversation")
                print("/voice - Toggle voice mode (Say 'voice stop' to return to text)")
                print("/websearch - Toggle web search mode (Say 'web search stop' to disable)")
                print("/scrape [url] - Scrape and summarize the content of a webpage")
                print("/archives [topic] - Search the knowledge base for a topic")
                print("/reason - Toggle reasoning mode (switch LLM model to deepseek-r1:14b)")
            elif prompt.lower() == "/exit":
                print(f"{Fore.MAGENTA}Exiting...")
                exit()
            elif prompt.lower() == "/clear":
                assistant_convo = [sys_msgs.assistant_msg]
                print(f"{Fore.YELLOW}Session reset.")
            elif prompt.lower() == "/voice":
                voice_mode = not voice_mode
                print(f"{Fore.YELLOW}Voice {'ON' if voice_mode else 'OFF'}.")
            elif prompt.lower() == "/stopvoice":
                stop_voice()
                print(f"{Fore.RED}Voice stopped.")
            continue

        # Archives search
        if prompt.lower().startswith("/archives"):
            parts = prompt.split(maxsplit=1)
            if len(parts) < 2:
                print(f"{Fore.RED}Please specify a topic to search in the knowledge base.")
                continue

            topic = parts[1]
            results = search_knowledge_base(topic)

            if results:
                for filename, content in results:
                    print(f"{Fore.GREEN}Found in '{filename}':\n{Fore.WHITE}{content}")
            else:
                print(f"{Fore.RED}No results found for '{topic}' in the knowledge_base.")
            continue

        # Web search mode handling
        if web_search_mode and not prompt.startswith("/"):
            print(f"{Fore.CYAN}Searching the web for: {prompt}...\n")
            results = search_web(prompt)

            if results:
                context_snippets = []
                for result in results:
                    print(f"{Fore.GREEN}{result['title']}\n{Fore.BLUE}{result['url']}\n")
                    content = fetch_page_content(result["url"])
                    if content:
                        summary = summarize_text(content)
                        if summary.strip():
                            context_snippets.append(f"{result['title']}: {summary}")

                if context_snippets:
                    web_context = "\n\n".join(context_snippets)
                    assistant_convo.append({
                        "role": "system",
                        "content": f"Here is web data:\n{web_context}"
                    })
                    print(f"{Fore.YELLOW}Using extracted info to answer your question...\n")
                    record_to_knowledge_base(prompt, web_context)
                else:
                    print(f"{Fore.RED}No useful web content found. Answering with existing knowledge.")
                    assistant_convo.append({
                        "role": "system",
                        "content": "I couldn't find relevant web data, but I'll answer based on what I know."
                    })
            else:
                print(f"{Fore.RED}No search results found.")

            assistant_convo.append({"role": "user", "content": prompt})

            # Decide model based on reasoning mode
            chosen_model = MODELS["search"] if reasoning_mode else MODELS["main"]
            response = ollama.chat(model=chosen_model, messages=assistant_convo)
            assistant_convo.append({"role": "assistant", "content": response["message"]["content"]})

            print(f"{Fore.MAGENTA}Assistant's response:\n{Fore.GREEN}{response['message']['content']}\n")

            if voice_mode:
                asyncio.run(speak_text(response["message"]["content"]))

            continue

        # Standard assistant conversation
        # direct stream (with correct model)
        assistant_convo.append({"role": "user", "content": prompt})
        stream_response()

        # If voice is on, speak the last message
        if voice_mode:
            last_response = assistant_convo[-1]["content"]
            asyncio.run(speak_text(last_response))

if __name__ == "__main__":
    main()