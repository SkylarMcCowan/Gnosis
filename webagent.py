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
import yt_dlp
# Import tutor functions
from tutor import create_learning_path, show_learning_path, delete_learning_path, tutor
from news import news_command

# -------------------------------------
# Initialization
# -------------------------------------
init(autoreset=True)

assistant_convo = [sys_msgs.assistant_msg]

voice_mode = False        # live speech input mode
tts_mode = False          # if on, responses are read aloud (in text mode)
stop_voice_flag = False
executor = ThreadPoolExecutor()
web_search_mode = True
reasoning_mode = False
unfiltered_mode = True   # Toggle for unfiltered model mode
coding_mode = False      # Toggle for coding model mode

MODELS = {
    'main': 'llama3.1',            # normal responses
    'search': 'llama3.1',          # reasoning responses (fallback to main)
    'unfiltered': 'llama3.1',      # unfiltered responses (fallback to main)
    'coding': 'llama3.1',          # coding responses (fallback to main)
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
    "🦻 I'm all ears... (Say 'voice stop' to end live input)",
    "🎤 Speak now, or forever hold your peace! (Say 'stop talking' to mute me)",
    "🤖 Listening... Beep boop. (Say 'mute yourself' if you need silence)",
    "👂 Tell me more, I’m intrigued! (Say 'stop speaking' to exit voice mode)",
    "🎧 Tuning in to your frequency... (Say 'voice mode' to switch back to text)",
    "📡 Receiving transmission... (Say 'end voice mode' to stop)",
    "🛸 Scanning for intelligent life... (Say 'voice stop' if you need a break)",
    "🎙️ Ready to record your wisdom! (Speak 'stop talking' to shut me up)",
    "🔊 Amplifying your voice… (Say 'mute yourself' if you want quiet time)",
    "🌀 The AI is listening... (Say 'stop speaking' to return to text mode)",
]

def get_listening_message():
    return random.choice(FUN_LISTENING_MESSAGES)

# -------------------------------------
# Audio Effects Utility
# -------------------------------------
def play_audio_effect(effect_name):
    effect_path = os.path.join("Audio_Files", f"bloop.mp3")
    print(f"Attempting to play effect: {effect_path}")
    if os.path.exists(effect_path):
        if platform.system() == "Windows":
            subprocess.run(["start", "", effect_path], shell=True)
        else:
            subprocess.run(["mpg123", "-q", effect_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print(f"Effect file {effect_path} does not exist.")

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
    print(f"{Fore.YELLOW}Refining search with: {refined}{Style.RESET_ALL}\n")
    return refined

def fetch_page_content(url):
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            extracted_text = trafilatura.extract(r.text)
            return extracted_text if extracted_text else "No extractable content found."
    except:
        pass
    return None

# -------------------------------------
# Voice Handling Functions
# -------------------------------------
def stop_voice():
    global stop_voice_flag, voice_mode
    stop_voice_flag = True
    voice_mode = False
    print(f"{Fore.RED}Voice stopped. Returning to text mode.{Style.RESET_ALL}")
    play_audio_effect("mic_off")
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
            import edge_tts
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

# -------------------------------------
# Streaming Response Function
# -------------------------------------
def stream_response():
    print(f"{Fore.CYAN}Generating response...\n{Style.RESET_ALL}")
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
    # Play a response-end audio effect
    if voice_mode or tts_mode:
        play_audio_effect("response_end")
    return complete_response

# -------------------------------------
# Speech Recognition Function
# -------------------------------------
def recognize_speech():
    global stop_voice_flag, voice_mode, web_search_mode
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print(f"{Fore.YELLOW}{get_listening_message()}{Style.RESET_ALL}")
        try:
            audio = r.listen(source, timeout=5, phrase_time_limit=5)
            speech_text = r.recognize_google(audio).lower()
            stop_cmds = [
                "voice stop", "stop talking", "be quiet", "mute yourself",
                "stop speaking", "end voice mode", "voice mode"
            ]
            if any(cmd in speech_text for cmd in stop_cmds):
                stop_voice_flag = True
                stop_voice()
                voice_mode = False
                print(f"{Fore.RED}Voice OFF.{Style.RESET_ALL}")
                return None
            if "web search stop" in speech_text:
                web_search_mode = False
                print(f"{Fore.YELLOW}Web search OFF.{Style.RESET_ALL}")
                return ""
            return speech_text
        except:
            return ""

# -------------------------------------
# Model & Web Search Functions
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
    except:
        pass
    return extracted_data

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

def generate_dynamic_queries(base_query, max_retries=3):
    """
    Generate multiple dynamic search queries using the dynamic query generator agent.
    """
    prompt = (
        f"{sys_msgs.dynamic_query_generator_msg}\n\n"
        f"USER PROMPT: {base_query}"
    )
    for attempt in range(max_retries):
        try:
            response = ollama.chat(model=MODELS["main"], messages=[{"role": "user", "content": prompt}])
            print(f"{Fore.YELLOW}Attempt {attempt + 1}: Raw response: {response}{Style.RESET_ALL}")
            
            # Extract the content field
            if "message" in response and "content" in response["message"]:
                content = response["message"]["content"]
                
                # Attempt to extract the JSON part from the content
                match = re.search(r"\[\s*\".*?\"\s*(,\s*\".*?\")*\s*\]", content, re.DOTALL)
                if match:
                    json_data = match.group(0)  # Extract the JSON string
                    queries = json.loads(json_data)  # Parse the JSON string
                    if isinstance(queries, list) and len(queries) == 10:
                        return queries
        except json.JSONDecodeError as e:
            print(f"{Fore.RED}JSON decoding error: {e}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Error generating dynamic queries (Attempt {attempt + 1}): {e}{Style.RESET_ALL}")
    
    print(f"{Fore.RED}All attempts to generate dynamic queries failed. Using fallback queries.{Style.RESET_ALL}")
    return [
        base_query,
        f"{base_query} news",
        f"{base_query} 2025",
        f"{base_query} analysis",
        f"{base_query} summary"
    ]

def perform_multiple_searches(base_query):
    """
    Perform multiple searches using dynamically generated queries.
    """
    queries = generate_dynamic_queries(base_query)
    all_results = []
    for query in queries:
        print(f"{Fore.CYAN}Performing search for: {query}{Style.RESET_ALL}")
        results = search_web(query)
        all_results.extend(results)
    return all_results

# -------------------------------------
# Knowledge Base Functions
# -------------------------------------
def record_to_knowledge_base(filename, content):
    kb_path = os.path.join(os.path.dirname(__file__), "knowledge_base")
    if not os.path.exists(kb_path):
        os.makedirs(kb_path)
    safe_filename = sanitize_filename(filename)
    file_path = os.path.join(kb_path, safe_filename)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except:
        pass

def record_learning_path(topic, resources):
    tutor_path = os.path.join(os.path.dirname(__file__), "tutor_paths")
    if not os.path.exists(tutor_path):
        os.makedirs(tutor_path)
    safe_filename = sanitize_filename(topic) + ".txt"
    file_path = os.path.join(tutor_path, safe_filename)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(resources))
    except:
        pass

def load_learning_paths():
    tutor_path = os.path.join(os.path.dirname(__file__), "tutor_paths")
    if not os.path.exists(tutor_path):
        return {}
    paths = {}
    for root, _, files in os.walk(tutor_path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    topic = os.path.splitext(file)[0]
                    resources = f.read().split("\n")
                    paths[topic] = resources
            except:
                pass
    return paths

learning_paths = load_learning_paths()

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
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except:
        pass

# -------------------------------------
# Wikipedia Integration (/askwiki)
# -------------------------------------
def ask_wiki(query):
    topics = query.split()  # Basic split; can be enhanced
    base_url = "https://en.wikipedia.org/wiki/"
    wiki_texts = []
    for topic in topics:
        url = base_url + topic.capitalize()
        print(f"{Fore.CYAN}Fetching Wikipedia page: {url}{Style.RESET_ALL}")
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                content_div = soup.find("div", {"class": "mw-parser-output"})
                if content_div:
                    text = "\n".join(content_div.stripped_strings)
                    if text:
                        wiki_texts.append(text)
                else:
                    wiki_texts.append("No content area found on Wikipedia page.")
            else:
                wiki_texts.append(f"Failed to fetch page, status code: {r.status_code}")
        except Exception as e:
            wiki_texts.append(f"Error fetching Wikipedia page: {e}")
    full_wiki = "\n\n".join(wiki_texts)
    if "No content" in full_wiki or "Failed" in full_wiki or "Error" in full_wiki:
        print(f"{Fore.RED}Wikipedia did not yield useful information. Falling back to web search...{Style.RESET_ALL}")
        full_wiki = iterative_web_search(query)
    record_to_knowledge_base(f"wiki_{sanitize_filename(query)}.txt", full_wiki)
    prompt = (
        f"You are a knowledgeable assistant. Based on the following Wikipedia information:\n\n"
        f"{full_wiki}\n\n"
        f"Please answer the following query: {query}"
    )
    assistant_convo.append({"role": "user", "content": prompt})
    chosen_model = MODELS["search"] if reasoning_mode else MODELS["main"]
    response = ollama.chat(model=chosen_model, messages=assistant_convo)
    final_text = response["message"]["content"]
    assistant_convo.append({"role": "assistant", "content": final_text})
    print(f"{Fore.GREEN}{final_text}{Style.RESET_ALL}\n")
    if voice_mode or tts_mode:
        asyncio.run(speak_text(final_text))

# -------------------------------------
# Historian Integration (/historian)
# -------------------------------------
def historian():
    kb_path = os.path.join(os.path.dirname(__file__), "knowledge_base")
    if not os.path.exists(kb_path):
        print(f"{Fore.RED}Knowledge base directory does not exist.{Style.RESET_ALL}")
        return
    summary = {}
    for root, _, files in os.walk(kb_path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    for keyword in ["dog", "fire", "war", "economy", "politics"]:
                        if keyword in file.lower():
                            summary.setdefault(keyword, []).append(file)
            except:
                pass
    if summary:
        print(f"{Fore.CYAN}Historian Summary:{Style.RESET_ALL}")
        for topic, files in summary.items():
            print(f"{Fore.GREEN}{topic.capitalize()}: {', '.join(files)}{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}No organized topics found in the knowledge base.{Style.RESET_ALL}")

# -------------------------------------
# Learning Path Functions
# -------------------------------------
learning_paths = load_learning_paths()

def create_learning_path(topic, resources):
    learning_paths[topic] = resources
    record_learning_path(topic, resources)
    print(f"{Fore.GREEN}Learning path for '{topic}' created successfully.{Style.RESET_ALL}")

def show_learning_path(topic=None):
    if topic:
        if topic in learning_paths:
            print(f"{Fore.CYAN}Learning Path for {topic}:{Style.RESET_ALL}")
            for resource in learning_paths[topic]:
                print(f"- {resource}")
        else:
            print(f"{Fore.RED}No learning path found for '{topic}'.{Style.RESET_ALL}")
    else:
        if learning_paths:
            print(f"{Fore.CYAN}Saved Learning Paths:{Style.RESET_ALL}")
            for topic in learning_paths:
                print(f"- {topic}")
        else:
            print(f"{Fore.RED}No learning paths saved.{Style.RESET_ALL}")

def delete_learning_path(topic):
    if topic in learning_paths:
        del learning_paths[topic]
        print(f"{Fore.GREEN}Learning path for '{topic}' deleted successfully.{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}No learning path found for '{topic}'.{Style.RESET_ALL}")

def tutor(topic):
    prompt = (
        f"Create a comprehensive learning path for the topic '{topic}'. "
        f"Include the following sections: Introduction, Intermediate Concepts, Advanced Techniques, Best Practices, Case Studies, and Exercises."
    )
    assistant_convo.append({"role": "user", "content": prompt})
    chosen_model = MODELS["coding"]
    response = ollama.chat(model=chosen_model, messages=assistant_convo)
    learning_path = response["message"]["content"]
    resources = learning_path.split("\n")
    create_learning_path(topic, resources)
    print(f"{Fore.CYAN}Generated Learning Path for {topic}:{Style.RESET_ALL}")
    for resource in resources:
        print(f"- {resource}")

# -------------------------------------
# Password Generation Functions
# -------------------------------------
import secrets

def generate_password(length=20):
    alphabet = string.ascii_letters + string.digits + string.punctuation
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def password_command(args=None):
    num_passwords = 5
    if args and args.startswith('-') and args[1:].isdigit():
        num_passwords = int(args[1:])
    passwords = [generate_password() for _ in range(num_passwords)]
    for idx, pwd in enumerate(passwords, 1):
        print(f"{idx}. {pwd}")

# -------------------------------------
# YouTube Download Function
# -------------------------------------
def ytdl_command(url):
    """
    Download YouTube video in highest quality to ~/Downloads
    """
    if not url:
        print(f"{Fore.RED}Please provide a YouTube URL.{Style.RESET_ALL}")
        return
    
    downloads_path = os.path.expanduser("~/Downloads")
    
    ydl_opts = {
        'format': 'best[height<=1080]/best',  # Best quality up to 1080p, fallback to any best
        'outtmpl': f'{downloads_path}/%(title)s.%(ext)s',
        'noplaylist': True,
        'extract_flat': False,
        'ignoreerrors': False,
        # Add user agent and headers to avoid bot detection
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        },
        # Try to use cookies from browser if available
        'cookiesfrombrowser': ('safari',),  # Try Safari cookies first
        'sleep_interval': 1,
        'max_sleep_interval': 5,
    }
    
    try:
        print(f"{Fore.CYAN}Downloading video from: {url}{Style.RESET_ALL}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        print(f"{Fore.GREEN}Download completed! Check ~/Downloads{Style.RESET_ALL}")
    except Exception as e:
        error_msg = str(e)
        if "Sign in to confirm you're not a bot" in error_msg:
            print(f"{Fore.YELLOW}YouTube is blocking the download (bot detection).{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}Trying alternative method...{Style.RESET_ALL}")
            
            # Try without cookies as fallback
            ydl_opts_fallback = ydl_opts.copy()
            ydl_opts_fallback.pop('cookiesfrombrowser', None)
            ydl_opts_fallback['format'] = 'worst'  # Try lowest quality as last resort
            
            try:
                with yt_dlp.YoutubeDL(ydl_opts_fallback) as ydl:
                    ydl.download([url])
                print(f"{Fore.GREEN}Download completed (lower quality)! Check ~/Downloads{Style.RESET_ALL}")
            except Exception as e2:
                print(f"{Fore.RED}Alternative method also failed.{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}Suggestions:{Style.RESET_ALL}")
                print(f"  • Try again in a few minutes")
                print(f"  • Use a different video URL")
                print(f"  • Manual download: yt-dlp --cookies-from-browser safari '{url}'")
        else:
            print(f"{Fore.RED}Error downloading video: {e}{Style.RESET_ALL}")

# -------------------------------------
# MAIN INTERACTION LOOP
# -------------------------------------
def main():
    global assistant_convo, voice_mode, web_search_mode, reasoning_mode, unfiltered_mode, tts_mode, coding_mode
    pull_model()
    while True:
        print()
        if voice_mode:
            prompt = recognize_speech()
            if prompt is None:
                continue
        else:
            prompt = input(f"{Fore.BLUE}{get_fun_prompt()}{Style.RESET_ALL}")
        # Toggle reasoning mode
        if prompt.lower() == "/reason":
            reasoning_mode = not reasoning_mode
            if reasoning_mode:
                unfiltered_mode = False
                coding_mode = False
            which_model = "search" if reasoning_mode else ("unfiltered" if unfiltered_mode else ("coding" if coding_mode else "main"))
            print(f"{Fore.YELLOW}Reasoning mode {'ON' if reasoning_mode else 'OFF'}. Using model: {MODELS[which_model]}")
            continue
        
         # /password command
        if prompt.lower().startswith("/password"):
            parts = prompt.split(maxsplit=1)
            args = parts[1] if len(parts) > 1 else None
            password_command(args)
            continue

        # Toggle unfiltered mode
        if prompt.lower() == "/unfiltered":
            unfiltered_mode = not unfiltered_mode
            if unfiltered_mode:
                reasoning_mode = False
                coding_mode = False
            which_model = "unfiltered" if unfiltered_mode else ("search" if reasoning_mode else ("coding" if coding_mode else "main"))
            print(f"{Fore.YELLOW}Unfiltered mode {'ON' if unfiltered_mode else 'OFF'}. Using model: {MODELS[which_model]}")
            continue
        # Toggle coding mode
        if prompt.lower() == "/coding":
            coding_mode = not coding_mode
            if coding_mode:
                reasoning_mode = False
                unfiltered_mode = False
            which_model = "coding" if coding_mode else ("search" if reasoning_mode else ("unfiltered" if unfiltered_mode else "main"))
            print(f"{Fore.YELLOW}Coding mode {'ON' if coding_mode else 'OFF'}. Using model: {MODELS[which_model]}")
            continue
        # Toggle TTS mode
        if prompt.lower() == "/tts":
            tts_mode = not tts_mode
            if tts_mode and voice_mode:
                voice_mode = False  # Ensure only one audio mode is active
            print(f"{Fore.YELLOW}TTS mode {'ON' if tts_mode else 'OFF'}.")
            continue
        # Toggle web search mode
        if prompt.lower() == "/websearch":
            web_search_mode = not web_search_mode
            print(f"{Fore.YELLOW}Web search {'ON' if web_search_mode else 'OFF'}.")
            continue
        # Historian command
        if prompt.lower() == "/historian":
            historian()
            continue
        # /askwiki command
        if prompt.lower().startswith("/askwiki"):
            parts = prompt.split(maxsplit=1)
            if len(parts) < 2:
                print(f"{Fore.RED}Please provide a query for /askwiki.{Style.RESET_ALL}")
                continue
            wiki_query = parts[1]
            ask_wiki(wiki_query)
            continue
        # /tutor command
        if prompt.lower().startswith("/tutor"):
            parts = prompt.split(maxsplit=1)
            if len(parts) < 2:
                print(f"{Fore.RED}Please provide a topic for /tutor.{Style.RESET_ALL}")
                continue
            topic = parts[1]
            tutor(topic)
            continue
        # /showpath command
        if prompt.lower().startswith("/showpath"):
            parts = prompt.split(maxsplit=1)
            topic = parts[1] if len(parts) > 1 else None
            show_learning_path(topic)
            continue
        # /delpath command
        if prompt.lower().startswith("/delpath"):
            parts = prompt.split(maxsplit=1)
            if len(parts) < 2:
                print(f"{Fore.RED}Please provide a topic for /delpath.{Style.RESET_ALL}")
                continue
            topic = parts[1]
            delete_learning_path(topic)
            continue
                # /news command
        if prompt.lower().startswith("/news"):
            parts = prompt.split(maxsplit=1)
            args = parts[1] if len(parts) > 1 else None
            news_command(args)
            continue
        
        # /ytdl command
        if prompt.lower().startswith("/ytdl"):
            parts = prompt.split(maxsplit=1)
            url = parts[1] if len(parts) > 1 else None
            ytdl_command(url)
            continue
        # Help and exit commands
        if prompt.lower() in ["/help", "/exit", "/clear", "/voice", "/stopvoice"]:
            if prompt.lower() == "/help":
                print("\nCommands:")
                print("/archives [topic] - Search knowledge base for [topic]")
                print("/askwiki [query] - Query Wikipedia and interpret the information")
                print("/clear - Reset conversation")
                print("/coding - Toggle coding mode (nous-hermes2:10.7b)")
                print("/delpath [topic] - Delete the learning path for the given topic")
                print("/exit - Save and exit")
                print("/historian - Organize and summarize knowledge base contents")
                print("/help - Show help")
                print("/news - Fetch latest news headlines")
                print("/password [-N] - Generate N (default 5) complex passwords, each 20 characters")
                print("/reason - Toggle reasoning mode (deepseek-r1:14b)")
                print("/showpath [topic] - Show the learning path for the given topic")
                print("/tarot - Perform a single-deck Tree of Life Tarot reading")
                print("/tutor [topic] - Create a learning path for the given topic")
                print("/tts - Toggle TTS mode (read responses aloud)")
                print("/unfiltered - Toggle unfiltered mode (r1-1776:70b)")
                print("/voice - Toggle voice mode (for live input)")
                print("/websearch - Toggle web search mode")
                print("/ytdl <url> - Download YouTube video in highest quality to ~/Downloads")
            elif prompt.lower() == "/exit":
                print(f"{Fore.MAGENTA}Exiting...")
                exit()
            elif prompt.lower() == "/clear":
                assistant_convo = [sys_msgs.assistant_msg]
                print(f"{Fore.YELLOW}Conversation reset.")
            elif prompt.lower() == "/voice":
                voice_mode = not voice_mode
                if voice_mode and tts_mode:
                    tts_mode = False
                if voice_mode:
                    play_audio_effect("mic_on")
                print(f"{Fore.YELLOW}Voice {'ON' if voice_mode else 'OFF'}.")
            elif prompt.lower() == "/stopvoice":
                stop_voice()
                print(f"{Fore.RED}Voice stopped.")
            continue
        # Archives command
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
                print(f"{Fore.RED}No results found for '{topic}' in knowledge base.")
            continue
        # Tarot reading command
        if prompt.lower() == "/tarot":
            from tarot import tarot_reading
            tarot_reading()
            continue
        # Learning path commands
        if prompt.lower().startswith("/createpath"):
            parts = prompt.split(maxsplit=2)
            if len(parts) < 3:
                print(f"{Fore.RED}Please provide a topic and resources for /createpath.{Style.RESET_ALL}")
                continue
            topic = parts[1]
            resources = parts[2].split(",")
            create_learning_path(topic, resources)
            continue

        if prompt.lower().startswith("/showpath"):
            parts = prompt.split(maxsplit=1)
            if len(parts) < 2:
                print(f"{Fore.RED}Please provide a topic for /showpath.{Style.RESET_ALL}")
                continue
            topic = parts[1]
            show_learning_path(topic)
            continue
        # Web Search Mode Handling
        if web_search_mode and not prompt.startswith("/"):
            all_results = perform_multiple_searches(prompt)
            if all_results:
                context_snippets = []
                for result in all_results:
                    summary = summarize_text(result["content"])
                    if summary.strip():
                        context_snippets.append(f"{result['title']}: {summary}")
                if context_snippets:
                    joined = "\n\n".join(context_snippets)
                    assistant_convo.append({"role": "system", "content": f"Here is data:\n{joined}"})
                    record_to_knowledge_base(prompt, joined)
            
            if unfiltered_mode:
                chosen_model = MODELS["unfiltered"]
            elif reasoning_mode:
                chosen_model = MODELS["search"]
            elif coding_mode:
                chosen_model = MODELS["coding"]
            else:
                chosen_model = MODELS["main"]
            
            assistant_convo.append({"role": "user", "content": prompt})
            stream_response()  # ✅ This prints the response dynamically, no need for extra print

            continue
        # Standard conversation
        assistant_convo.append({"role": "user", "content": prompt})
        stream_response()

if __name__ == "__main__":
    main()