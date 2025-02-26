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
import random  # 🔹 Import for randomizing prompts
from duckduckgo_search import DDGS  # ✅ Use DuckDuckGo for web searches

init(autoreset=True)
assistant_convo = [sys_msgs.assistant_msg]
voice_mode = False
stop_voice_flag = False
executor = ThreadPoolExecutor()
web_search_mode = False  # Track whether web search mode is enabled

MODELS = {
    'main': 'llama3.2',
    'search': 'deepseek-r1:14b',
}

# 🎭 Fun prompts for text mode input
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

# 🎤 Fun listening messages when in voice mode
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
    """Extract key sentences from text."""
    sentences = text.split(". ")
    return ". ".join(sentences[:max_sentences]) + "." if sentences else text

def needs_more_search(response_text):
    """Determine if the AI needs more context based on response content."""
    lower_response = response_text.lower()
    return any(phrase in lower_response for phrase in [
        "i don't have enough information",
        "i need more details",
        "i couldn't find enough data",
        "let me check further",
        "unclear results"
    ])

def refine_query(response_text):
    """Extract key missing details from AI's response to refine the search query."""
    # Look for keywords the AI says are missing
    missing_keywords = []
    words = response_text.split()
    
    for i, word in enumerate(words):
        if word.lower() in ["about", "regarding", "on", "of"] and i + 1 < len(words):
            missing_keywords.append(words[i + 1])

    # Create a refined search query
    refined_query = " ".join(missing_keywords) if missing_keywords else response_text[:50]
    print(f"{Fore.YELLOW}Refining search with: {refined_query}\n")
    return refined_query

# Stop voice function - Now also resets voice_mode
def stop_voice():
    global stop_voice_flag, voice_mode
    stop_voice_flag = True  # Set flag so async function stops immediately
    voice_mode = False  # Force return to text mode

    print(f"{Fore.RED}Voice stopped. Returning to text mode.")  # Inform the user

    if platform.system() == "Windows":
        os.system("taskkill /IM mpg123.exe /F")  # Ensure mpg123 is killed
    else:
        os.system("pkill -STOP mpg123")
        time.sleep(0.5)
        os.system("pkill mpg123")

# Text-to-Speech using Edge-TTS with streaming
async def speak_text(text):
    global stop_voice_flag
    if voice_mode:
        stop_voice_flag = False
        speed = "+50%" if "?" in text else "+30%" if len(text) > 150 else "+40%"

        # ✅ Strip asterisks, underscores, and other markdown symbols
        clean_text = re.sub(r'[*_`]', '', text)

        # Create a temporary audio file
        temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_audio_path = temp_audio.name
        temp_audio.close()  # Close the file so edge-tts can write to it

        # Generate the TTS audio and save it
        tts = edge_tts.Communicate(clean_text, voice="en-GB-RyanNeural", rate=speed)
        await tts.save(temp_audio_path)

        # If stop flag was set during generation, delete the file and return
        if stop_voice_flag:
            os.unlink(temp_audio_path)
            return
        
        # Play the generated speech without printing mpg123 output
        if not stop_voice_flag:
            if platform.system() == "Windows":
                subprocess.run(["start", "", temp_audio_path], shell=True)  # Use start command on Windows
            else:
                process = subprocess.Popen(["mpg123", "-q", temp_audio_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                # Monitor playback and stop if flag is set
                while process.poll() is None:
                    if stop_voice_flag:
                        process.terminate()
                        break
                    await asyncio.sleep(0.1)  # Check every 100ms

        # Cleanup: Remove temporary audio file after playback
        os.unlink(temp_audio_path)

# Streaming response for real-time typing effect with continuous speech
def stream_response():
    print(f"{Fore.CYAN}Generating response...\n")
    complete_response = ""
    last_spoken_index = 0  # Track last spoken position

    response_stream = ollama.chat(model=MODELS["main"], messages=assistant_convo, stream=True)

    async def speak_in_background():
        nonlocal last_spoken_index
        while last_spoken_index < len(complete_response):  # Only runs while text is being generated
            await asyncio.sleep(0.2)  # Faster speech updates
            if last_spoken_index < len(complete_response):
                new_text = complete_response[last_spoken_index:]
                last_spoken_index = len(complete_response)  # Update spoken position
                await speak_text(new_text)  # Speak only the new part

    # Create a new event loop for async speech processing
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    speech_task = loop.create_task(speak_in_background())

    for chunk in response_stream:
        text_chunk = chunk["message"]["content"]
        complete_response += text_chunk
        print(f"{Fore.GREEN}{text_chunk}", end="", flush=True)

    print()

    # Ensure speech finishes
    loop.run_until_complete(speech_task)
    loop.close()

    assistant_convo.append({"role": "assistant", "content": complete_response})

# Recognize speech input
def recognize_speech():
    global stop_voice_flag, voice_mode, web_search_mode
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print(f"{Fore.YELLOW}{get_listening_message()}")  # Fun listening message
        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=8)  # Extended listening time
            speech_text = recognizer.recognize_google(audio).lower()

            # ✅ Expanded Voice Stop Commands (Includes "Voice Mode")
            stop_commands = ["voice stop", "stop talking", "be quiet", "mute yourself", "stop speaking", "end voice mode", "voice mode"]
            if any(cmd in speech_text for cmd in stop_commands):
                stop_voice_flag = True
                stop_voice()
                voice_mode = False
                print(f"{Fore.RED}Voice OFF.")
                return None  # Ensures text mode resumes

            # Web search stop command (while keeping voice mode ON)
            if "web search stop" in speech_text:
                web_search_mode = False
                print(f"{Fore.YELLOW}Web search OFF.")
                return ""  # Continue voice input but without web search mode

            return speech_text  # Return recognized speech
        except (sr.UnknownValueError, sr.RequestError):
            return ""

# Load models
def pull_model():
    for model in MODELS.values():
        print(f"{Fore.CYAN}Pulling model '{model}'...")
        ollama.pull(model=model)
        print(f"{Fore.GREEN}Model '{model}' pulled successfully.")

def search_web(query):
    """Perform a web search using DuckDuckGo, scrape top results, and return extracted text."""
    results = []
    extracted_data = []
    
    try:
        with DDGS() as ddgs:
            for result in ddgs.text(query, max_results=5):
                url = result["href"]
                title = result["title"]
                results.append({"title": title, "url": url})
                
                # Scrape the webpage
                page_content = fetch_page_content(url)
                if page_content:
                    extracted_data.append({"title": title, "url": url, "content": page_content})

    except Exception as e:
        print(f"Search or scraping failed: {e}")

    return extracted_data  # Return the scraped content instead of just links

def fetch_page_content(url):
    """Fetch and extract text content from a given URL."""
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            extracted_text = trafilatura.extract(response.text)
            return extracted_text if extracted_text else "No extractable content found."
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return None

def iterative_web_search(query, max_retries=5):
    """Perform a web search, scrape results, and iteratively refine search if needed."""
    retries = 0
    accumulated_context = ""  # Store all gathered context

    while retries < max_retries:
        print(f"{Fore.CYAN}[Search Attempt {retries + 1}/{max_retries}] Searching for: {query}\n")
        results = search_web(query)

        if not results:
            print(f"{Fore.RED}No results found for '{query}'. Retrying with refinement...\n")
            retries += 1
            continue  # Try again with a refined query (to be improved later)

        # Summarize and accumulate the retrieved information
        context_snippets = []
        for result in results:
            print(f"{Fore.GREEN}{result['title']}\n{Fore.BLUE}{result['url']}\n")
            summarized_content = summarize_text(result['content'])
            context_snippets.append(f"{result['title']}: {summarized_content}")

        # Store accumulated context
        accumulated_context += "\n\n".join(context_snippets) + "\n\n"

        # Add current context to conversation
        assistant_convo.append({"role": "system", "content": f"Here is some information from the web:\n{accumulated_context}"})

        # Ask the AI if it now has enough context
        response = ollama.chat(model=MODELS["main"], messages=assistant_convo)
        assistant_convo.append({"role": "assistant", "content": response["message"]["content"]})

        print(f"{Fore.MAGENTA}Assistant's response:\n{Fore.GREEN}{response['message']['content']}\n")

        # If the response is confident, stop searching
        if not needs_more_search(response["message"]["content"]):
            return response["message"]["content"]  # Return final answer

        # Otherwise, refine query and retry
        query = refine_query(response["message"]["content"])
        retries += 1

    print(f"{Fore.YELLOW}Max retries reached. Returning best available answer.\n")
    return response["message"]["content"]

# Main interaction loop
def main():
    global assistant_convo, voice_mode, web_search_mode
    pull_model()  # Load models at startup

    while True:
        print()

        # Get input (voice or text)
        if voice_mode:
            prompt = recognize_speech()
            if prompt is None:
                continue
        else:
            prompt = input(f"{Fore.BLUE}{get_fun_prompt()}")

        # Toggle Web Search Mode
        if prompt.lower() == "/websearch":
            web_search_mode = not web_search_mode
            print(f"{Fore.YELLOW}Web search {'ON' if web_search_mode else 'OFF'}.")
            continue

        # Handle Commands
        if prompt.lower() in ["/help", "/exit", "/clear", "/voice", "/stopvoice", "/scrape"]:
            if prompt.lower() == "/help":
                print("\nCommands:")
                print("/help - Show this message")
                print("/exit - Save and exit")
                print("/clear - Reset conversation")
                print("/voice - Toggle voice mode (Say 'voice stop' to return to text mode)")
                print("/websearch - Toggle web search mode (Say 'web search stop' to disable)")
                print("/stopvoice - Stop AI from speaking mid-response")
                print("/scrape [url] - Scrape and summarize the content of a webpage")
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

        # ✅ 🔹 Web Search Mode Handling (Now Works in Both Voice & Text Modes)
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
                        if summary.strip():  # Ensure it's not empty
                            context_snippets.append(f"{result['title']}: {summary}")

                if context_snippets:
                    # ✅ Add extracted web info as system context
                    web_context = "\n\n".join(context_snippets)
                    assistant_convo.append({"role": "system", "content": f"Here is web data:\n{web_context}"})
                    print(f"{Fore.YELLOW}Using extracted info to answer your question...\n")

                else:
                    print(f"{Fore.RED}No useful web content found. Answering with existing knowledge.")
                    assistant_convo.append({"role": "system", "content": "I couldn't find relevant web data, but I'll answer based on what I know."})

            else:
                print(f"{Fore.RED}No search results found.")

            # ✅ Ensure AI still answers, even if web search fails
            assistant_convo.append({"role": "user", "content": prompt})
            response = ollama.chat(model=MODELS["main"], messages=assistant_convo)
            assistant_convo.append({"role": "assistant", "content": response["message"]["content"]})

            print(f"{Fore.MAGENTA}Assistant's response:\n{Fore.GREEN}{response['message']['content']}\n")

            # ✅ If Voice Mode is ON, Speak the Response
            if voice_mode:
                asyncio.run(speak_text(response["message"]["content"]))

            continue  # Skip normal processing

        # 🔹 Standard Assistant Conversation (No Web Search)
        assistant_convo.append({"role": "user", "content": prompt})
        response = stream_response()

        # ✅ If Voice Mode is ON, Speak the Response
        if voice_mode:
            asyncio.run(speak_text(response))

if __name__ == "__main__":
    main()