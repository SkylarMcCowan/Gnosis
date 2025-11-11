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
web_search_mode = False
reasoning_mode = False
unfiltered_mode = False   # Toggle for unfiltered model mode
coding_mode = False      # Toggle for coding model mode
current_agent = None     # Current specialized agent persona

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
    base_prompt = random.choice(FUN_PROMPTS)
    if current_agent:
        agent_name = AVAILABLE_AGENTS[current_agent]['name']
        return f"[{agent_name}] {base_prompt}"
    return base_prompt

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
from datetime import datetime, timezone
import pytz

def get_current_datetime():
    """Get current date and time with timezone info"""
    now = datetime.now()
    return {
        'date': now.strftime('%Y-%m-%d'),
        'time': now.strftime('%H:%M:%S'),
        'datetime': now.strftime('%Y-%m-%d %H:%M:%S'),
        'weekday': now.strftime('%A'),
        'month': now.strftime('%B'),
        'year': now.year,
        'timestamp': now.timestamp()
    }

def get_datetime_context():
    """Get formatted datetime context for AI"""
    dt = get_current_datetime()
    return f"Current date and time: {dt['datetime']} ({dt['weekday']}, {dt['month']} {dt['date'].split('-')[2]}, {dt['year']})"

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
        # Skip system URLs
        if url.startswith("system://"):
            return None
            
        # Longer timeout and better headers for reliability
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'close'  # Don't keep connections open
        }
        
        # Increased timeout for better reliability (was 3s, now 8s)
        r = requests.get(url, timeout=8, headers=headers, allow_redirects=True)
        
        if r.status_code == 200:
            # Quick extraction with size limit
            extracted_text = trafilatura.extract(r.text, include_comments=False, include_tables=False)
            if extracted_text and len(extracted_text.strip()) > 50:
                # Limit content size for faster processing
                return extracted_text[:1200] if len(extracted_text) > 1200 else extracted_text
            else:
                # Fallback to basic text extraction
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r.text, 'html.parser')
                text = soup.get_text()
                clean_text = ' '.join(text.split())[:800]  # Clean and limit
                return clean_text if len(clean_text) > 50 else "Limited content available"
            
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, Exception):
        # Silently handle errors - fallback will provide user feedback
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
    """Web search with intelligent fallback for network-restricted environments"""
    
    # Skip DuckDuckGo entirely since it's blocked on this network
    print(f"{Fore.CYAN}🧠 Generating intelligent response for: {query}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}ℹ️ Using offline knowledge base (web search unavailable due to network restrictions){Style.RESET_ALL}")
    
    # Use enhanced fallback with contextual intelligence
    return search_fallback(query)

def search_duckduckgo(query):
    """DuckDuckGo search with enhanced timeout handling"""
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError("DuckDuckGo search timed out")
    
    extracted_data = []
    try:
        # Set a 10-second timeout for the entire DuckDuckGo operation
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(10)
        
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            
        signal.alarm(0)  # Cancel timeout
        
        for result in results:
            url = result["href"]
            title = result["title"]
            
            # Quick content extraction with timeout
            page_content = fetch_page_content(url)
            if page_content and len(page_content) > 100:
                if len(page_content) > 2000:
                    page_content = page_content[:2000] + "..."
                extracted_data.append({"title": title, "url": url, "content": page_content})
                
    except (TimeoutError, Exception) as e:
        signal.alarm(0)  # Ensure alarm is cancelled
        # Return empty list to trigger fallback
        return []
    
    return extracted_data

def search_fallback(query):
    """Enhanced fallback with intelligent context generation"""
    # Generate contextual response based on query analysis
    query_lower = query.lower()
    
    # Analyze query to provide relevant context
    context_response = generate_contextual_response(query_lower)
    
    fallback_content = f"""
Web search is currently unavailable due to network restrictions, but I can help with your query about "{query}".

{context_response}

For real-time information, you might want to check:
- News websites directly in your browser
- Official sources and documentation
- Social media for current updates

I'm still fully capable of helping with analysis, explanations, coding, and discussions that don't require live web data!
"""
    
    return [{
        "title": f"Contextual Response: {query}",
        "url": "system://intelligent-fallback",
        "content": fallback_content.strip()
    }]

def generate_contextual_response(query_lower):
    """Generate intelligent contextual responses based on query analysis"""
    
    # Programming/Tech queries
    if any(term in query_lower for term in ['python', 'code', 'programming', 'javascript', 'react', 'algorithm', 'debug']):
        return """Based on my knowledge of programming and software development, I can provide guidance on:
- Code examples and best practices
- Algorithm explanations and implementations  
- Debugging strategies and common solutions
- Framework usage and patterns
- Development methodologies and tools"""
    
    # Current events/news
    elif any(term in query_lower for term in ['news', 'current', 'today', 'latest', 'recent', 'breaking']):
        return f"""While I cannot access current news feeds, I can help you understand:
- Historical context and background information
- How to evaluate news sources and credibility
- Analysis frameworks for current events
- Suggested reliable news sources to check directly"""
    
    # Science/research topics
    elif any(term in query_lower for term in ['science', 'research', 'study', 'theory', 'physics', 'biology', 'chemistry']):
        return """I can provide detailed information about scientific concepts including:
- Established theories and principles
- Research methodologies and analysis
- Scientific explanations and mechanisms
- Historical discoveries and breakthroughs
- Connections between different scientific fields"""
    
    # Philosophy/wisdom
    elif any(term in query_lower for term in ['philosophy', 'meaning', 'consciousness', 'meditation', 'wisdom', 'ethics']):
        return """I can explore philosophical topics and wisdom traditions:
- Ancient and modern philosophical frameworks
- Contemplative practices and insights
- Ethical analysis from multiple perspectives
- Consciousness studies and awareness practices
- Practical applications of philosophical wisdom"""
    
    # Business/economics
    elif any(term in query_lower for term in ['business', 'economy', 'market', 'finance', 'investment', 'startup']):
        return """I can discuss business and economic concepts:
- Business strategy and management principles
- Economic theories and market dynamics
- Financial planning and investment strategies
- Entrepreneurship and startup guidance
- Industry analysis and trends (historical context)"""
    
    # Health/wellness
    elif any(term in query_lower for term in ['health', 'fitness', 'nutrition', 'diet', 'exercise', 'wellness']):
        return """I can provide information about health and wellness:
- Evidence-based health principles
- Nutrition science and dietary guidelines
- Exercise physiology and fitness strategies
- Mental health and wellness practices
- Preventive care and lifestyle factors
Note: Always consult healthcare professionals for medical advice."""
    
    # General knowledge fallback
    else:
        return f"""I can provide comprehensive information about "{query_lower}" including:
- Background context and fundamental concepts
- Historical perspective and development
- Related topics and connections
- Practical applications and implications
- Different viewpoints and approaches"""

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

def perform_hybrid_search(base_query):
    """
    Optimized hybrid search: automatic date context + minimal dynamic queries.
    Reduces queries from 5 to 3, eliminates LLM dependency for dynamic generation.
    """
    import datetime
    current_year = datetime.datetime.now().year
    current_month = datetime.datetime.now().strftime("%B")
    
    # Three strategic queries with automatic date context
    optimized_queries = [
        f"{base_query} {current_year} {current_month}",  # Current context
        f"{base_query} latest news updates",  # Recent information
        base_query  # Original query for broader context
    ]
    
    all_results = []
    for query in optimized_queries:
        print(f"{Fore.CYAN}Searching: {query}{Style.RESET_ALL}")
        results = search_web(query)
        all_results.extend(results)
        
        # Stop early if we have enough quality results
        if len(all_results) >= 9:
            break
    
    # Remove duplicates by URL
    seen_urls = set()
    unique_results = []
    for result in all_results:
        if result['url'] not in seen_urls:
            seen_urls.add(result['url'])
            unique_results.append(result)
    
    return unique_results[:6]  # Return top 6 unique results

# Note: generate_smart_queries function removed - no longer needed with optimized search

def should_agent_search(prompt, agent_name):
    """
    Intelligent decision making for when agents should search vs use existing knowledge
    """
    if not agent_name:
        return True  # Default mode searches more frequently
    
    agent_info = AVAILABLE_AGENTS.get(agent_name, {})
    
    # Keywords that suggest current information is needed
    current_info_keywords = [
        'latest', 'recent', 'current', 'now', 'today', '2025', 'update', 
        'news', 'happening', 'trending', 'breaking', 'new', 'just'
    ]
    
    # Keywords that suggest established knowledge is sufficient
    established_knowledge_keywords = [
        'explain', 'what is', 'how does', 'theory', 'concept', 'principle',
        'philosophy', 'meditation', 'debugging', 'algorithm', 'method'
    ]
    
    prompt_lower = prompt.lower()
    
    # Check for current info indicators
    needs_current_info = any(keyword in prompt_lower for keyword in current_info_keywords)
    
    # Check for established knowledge requests
    uses_established_knowledge = any(keyword in prompt_lower for keyword in established_knowledge_keywords)
    
    # Agent-specific logic
    if agent_name == 'fact_checker':
        return True  # Fact checker almost always needs to search
    elif agent_name == 'philosophy':
        return needs_current_info  # Philosophy uses existing wisdom unless current events
    elif agent_name == 'tutor':
        return needs_current_info or 'example' in prompt_lower  # Tutor searches for examples and current info
    elif agent_name == 'debugger':
        return 'error' in prompt_lower or 'latest' in prompt_lower  # Search for current error patterns
    elif agent_name == 'comedian':
        return 'news' in prompt_lower or needs_current_info  # Comedy benefits from current events
    elif agent_name == 'counselor':
        return False  # Counselor rarely needs web search, focuses on support
    
    # Default: search if current info needed and not clearly established knowledge
    return needs_current_info and not uses_established_knowledge

def process_search_tags(prompt):
    """
    Process @keyword@ tags in user prompt and perform targeted web searches.
    Returns the modified prompt with search results integrated.
    Optimized for speed with parallel processing and minimal content extraction.
    """
    import re
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    # Find all @keyword@ patterns
    tag_pattern = r'@([^@]+)@'
    tags = re.findall(tag_pattern, prompt)
    
    if not tags:
        return prompt  # No tags found, return original prompt
    
    modified_prompt = prompt
    search_results_context = []
    
    def clean_markdown_formatting(text):
        """Remove common markdown formatting characters from text"""
        import re
        # Remove markdown formatting: **bold**, *italic*, __underline__, `code`, [links](url), # headers
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)  # **bold** -> bold
        text = re.sub(r'\*(.*?)\*', r'\1', text)      # *italic* -> italic
        text = re.sub(r'__(.*?)__', r'\1', text)      # __underline__ -> underline
        text = re.sub(r'`(.*?)`', r'\1', text)        # `code` -> code
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)  # [text](url) -> text
        text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)  # # headers -> headers
        text = re.sub(r'\s+', ' ', text)              # normalize whitespace
        return text.strip()

    def fast_tag_search(tag):
        """Optimized single tag search with minimal processing"""
        try:
            print(f"{Fore.CYAN}🔍 {tag}{Style.RESET_ALL}", end=" ", flush=True)
            
            # Use only 1 targeted query instead of 3 for speed
            import datetime
            current_year = datetime.datetime.now().year
            query = f"{tag} {current_year}"
            
            # Get only top 2 results instead of 6
            results = search_web(query)[:2]
            
            if results:
                # Create ultra-concise context - just titles and first 100 chars
                tag_context = f"\n[{tag}: "
                snippets = []
                for result in results:
                    # Clean markdown formatting and use first 100 chars
                    cleaned_content = clean_markdown_formatting(result["content"])
                    snippet = cleaned_content[:100].replace('\n', ' ')
                    clean_title = clean_markdown_formatting(result['title'][:50])
                    snippets.append(f"{clean_title}... {snippet}...")
                tag_context += " | ".join(snippets) + "]"
                return tag_context
        except:
            pass
        return None
    
    # Process tags in parallel for speed
    if len(tags) == 1:
        # Single tag - no need for threading overhead
        context = fast_tag_search(tags[0])
        if context:
            search_results_context.append(context)
    else:
        # Multiple tags - use parallel processing
        with ThreadPoolExecutor(max_workers=min(3, len(tags))) as executor:
            future_to_tag = {executor.submit(fast_tag_search, tag): tag for tag in tags}
            
            for future in as_completed(future_to_tag):
                context = future.result()
                if context:
                    search_results_context.append(context)
    
    print()  # New line after all search indicators
    
    # Clean up tags from prompt
    for tag in tags:
        modified_prompt = re.sub(f'@{re.escape(tag)}@', tag, modified_prompt)
    
    # Add search context to the prompt
    if search_results_context:
        context_block = "\n".join(search_results_context)
        modified_prompt = f"{modified_prompt}\n{context_block}"
    
    return modified_prompt

# -------------------------------------
# User Profile Functions
# -------------------------------------
def load_user_profile():
    """Load user profile from user_details.log"""
    profile_path = os.path.join(os.path.dirname(__file__), "user_details.log")
    profile = {
        'name': 'User',
        'preferences': [],
        'interests': [],
        'location': '',
        'timezone': '',
        'notes': '',
        'recent_explorations': []
    }
    
    if os.path.exists(profile_path):
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                content = f.read()
                # Parse key-value pairs
                for line in content.split('\n'):
                    if ':' in line and not line.strip().startswith('#'):
                        key, value = line.split(':', 1)
                        key = key.strip().lower()
                        value = value.strip()
                        if key in profile:
                            if key in ['preferences', 'interests', 'recent_explorations']:
                                profile[key] = [item.strip() for item in value.split(',') if item.strip()]
                            else:
                                profile[key] = value
        except:
            pass
    
    return profile

def save_user_profile(profile):
    """Save user profile to user_details.log"""
    profile_path = os.path.join(os.path.dirname(__file__), "user_details.log")
    try:
        with open(profile_path, "w", encoding="utf-8") as f:
            f.write("# User Profile - Edit this file to customize your AI assistant\n")
            f.write("# Lines starting with # are comments\n\n")
            f.write(f"name: {profile.get('name', 'User')}\n")
            f.write(f"location: {profile.get('location', '')}\n")
            f.write(f"timezone: {profile.get('timezone', '')}\n")
            f.write(f"preferences: {', '.join(profile.get('preferences', []))}\n")
            f.write(f"interests: {', '.join(profile.get('interests', []))}\n")
            f.write(f"recent_explorations: {', '.join(profile.get('recent_explorations', []))}\n")
            f.write(f"notes: {profile.get('notes', '')}\n")
    except:
        pass

def get_user_context():
    """Get formatted user context for AI"""
    profile = load_user_profile()
    context_parts = []
    
    if profile['name'] != 'User':
        context_parts.append(f"User's name: {profile['name']}")
    
    if profile['location']:
        context_parts.append(f"Location: {profile['location']}")
    
    if profile['preferences']:
        context_parts.append(f"Preferences: {', '.join(profile['preferences'])}")
    
    if profile['interests']:
        context_parts.append(f"Interests: {', '.join(profile['interests'])}")
    
    if profile['recent_explorations']:
        context_parts.append(f"Recently explored: {', '.join(profile['recent_explorations'])}")
    
    if profile['notes']:
        context_parts.append(f"Additional notes: {profile['notes']}")
    
    return "; ".join(context_parts) if context_parts else "No user profile information available"

def analyze_conversation_patterns(user_input, agent_response=""):
    """Advanced conversation pattern analysis for enhanced learning"""
    import random
    from datetime import datetime
    
    # Only analyze 20% of conversations to avoid over-processing
    if random.random() > 0.2:
        return
    
    profile = load_user_profile()
    
    # Analyze different aspects of the conversation
    insights = {
        'expertise_indicators': extract_expertise_signals(user_input),
        'communication_style': analyze_communication_style(user_input),
        'recurring_themes': identify_recurring_themes(user_input, profile),
        'learning_patterns': detect_learning_patterns(user_input),
        'problem_solving_approach': analyze_problem_solving_style(user_input)
    }
    
    # Update profile based on insights
    update_profile_from_insights(profile, insights)

def extract_expertise_signals(text):
    """Identify areas where user demonstrates expertise"""
    text_lower = text.lower()
    expertise_signals = []
    
    # Technical expertise indicators
    if any(term in text_lower for term in ['implement', 'refactor', 'optimize', 'algorithm', 'debugging']):
        expertise_signals.append('programming')
    
    # Philosophical depth indicators  
    if any(term in text_lower for term in ['contemplative', 'mindfulness', 'consciousness', 'philosophy', 'wisdom']):
        expertise_signals.append('philosophy')
    
    # Business/leadership indicators
    if any(term in text_lower for term in ['strategy', 'team', 'management', 'leadership', 'scaling']):
        expertise_signals.append('leadership')
    
    # Creative indicators
    if any(term in text_lower for term in ['design', 'creative', 'artistic', 'innovative', 'inspiration']):
        expertise_signals.append('creativity')
    
    return expertise_signals

def analyze_communication_style(text):
    """Analyze preferred communication patterns"""
    style_indicators = {
        'detail_oriented': len(text.split()) > 50,  # Longer messages
        'direct': text.count('?') > 0 and len(text.split()) < 20,  # Short questions
        'collaborative': any(word in text.lower() for word in ['we', 'us', 'together', 'team']),
        'analytical': any(word in text.lower() for word in ['analyze', 'compare', 'evaluate', 'consider']),
        'practical': any(word in text.lower() for word in ['how', 'implement', 'apply', 'use', 'practical'])
    }
    
    return {k: v for k, v in style_indicators.items() if v}

def identify_recurring_themes(text, profile):
    """Identify themes that keep coming up in conversations"""
    themes = []
    recent_explorations = profile.get('recent_explorations', [])
    
    # Check if current text relates to recent explorations
    text_words = set(text.lower().split())
    for exploration in recent_explorations:
        if exploration.lower() in text.lower():
            themes.append(f"recurring_{exploration.lower()}")
    
    return themes

def detect_learning_patterns(text):
    """Identify how user prefers to learn"""
    learning_patterns = []
    text_lower = text.lower()
    
    if any(term in text_lower for term in ['example', 'show me', 'demonstrate']):
        learning_patterns.append('example_driven')
    
    if any(term in text_lower for term in ['why', 'explain', 'understand', 'concept']):
        learning_patterns.append('conceptual_learner')
    
    if any(term in text_lower for term in ['step by step', 'guide', 'tutorial', 'how to']):
        learning_patterns.append('procedural_learner')
    
    return learning_patterns

def analyze_problem_solving_style(text):
    """Identify problem-solving approach preferences"""
    text_lower = text.lower()
    approaches = []
    
    if any(term in text_lower for term in ['systematic', 'methodical', 'step by step']):
        approaches.append('systematic')
    
    if any(term in text_lower for term in ['creative', 'innovative', 'outside the box']):
        approaches.append('creative')
    
    if any(term in text_lower for term in ['collaborate', 'discuss', 'team', 'together']):
        approaches.append('collaborative')
    
    return approaches

def update_profile_from_insights(profile, insights):
    """Update user profile based on conversation insights"""
    from datetime import datetime
    
    # Update expertise areas
    if insights['expertise_indicators']:
        current_interests = profile.get('interests', [])
        for expertise in insights['expertise_indicators']:
            if expertise not in current_interests:
                current_interests.append(expertise)
        profile['interests'] = current_interests
    
    # Update communication preferences
    if insights['communication_style']:
        current_prefs = profile.get('preferences', [])
        for style, present in insights['communication_style'].items():
            if present and style not in current_prefs:
                current_prefs.append(style.replace('_', ' '))
        profile['preferences'] = current_prefs
    
    # Add learning patterns to notes
    if insights['learning_patterns']:
        notes = profile.get('notes', '')
        learning_note = f"Learning style: {', '.join(insights['learning_patterns'])}"
        if learning_note not in notes:
            profile['notes'] = f"{notes} | {learning_note}" if notes else learning_note
    
    save_user_profile(profile)

def update_user_notes_softly(search_query, search_results):
    """Occasionally update recent_explorations based on search patterns - very light touch"""
    import random
    
    # Only update 10% of the time (soft nudge)
    if random.random() > 0.1:
        return
    
    profile = load_user_profile()
    current_explorations = profile.get('recent_explorations', [])
    
    # Extract potential interests from search query
    interesting_terms = []
    query_lower = search_query.lower()
    
    # Comprehensive keyword extraction for potential interests with subsections
    potential_interests = [
        # Programming & Technology
        'python', 'javascript', 'typescript', 'java', 'c++', 'rust', 'go', 'swift', 'kotlin',
        'react', 'vue', 'angular', 'node.js', 'django', 'flask', 'spring', 'docker', 'kubernetes',
        'aws', 'azure', 'gcp', 'devops', 'ci/cd', 'git', 'linux', 'unix', 'bash', 'powershell',
        'sql', 'postgresql', 'mysql', 'mongodb', 'redis', 'elasticsearch', 'graphql', 'rest api',
        'microservices', 'serverless', 'blockchain', 'web3', 'ethereum', 'bitcoin', 'cryptocurrency',
        
        # AI & Machine Learning
        'ai', 'machine learning', 'deep learning', 'neural networks', 'computer vision', 'nlp',
        'tensorflow', 'pytorch', 'scikit-learn', 'pandas', 'numpy', 'jupyter', 'data science',
        'data analysis', 'statistics', 'big data', 'hadoop', 'spark', 'llm', 'gpt', 'transformers',
        'reinforcement learning', 'supervised learning', 'unsupervised learning', 'regression',
        'classification', 'clustering', 'feature engineering', 'model deployment', 'mlops',
        
        # Philosophy & Spirituality
        'philosophy', 'ethics', 'metaphysics', 'epistemology', 'logic', 'phenomenology',
        'existentialism', 'stoicism', 'buddhism', 'hinduism', 'taoism', 'zen', 'mindfulness',
        'meditation', 'vipassana', 'transcendental meditation', 'contemplation', 'awareness',
        'consciousness', 'enlightenment', 'dharma', 'karma', 'rebirth', 'nirvana',
        'non-duality', 'advaita', 'sufism', 'kabbalah', 'mysticism', 'spiritual practice',
        
        # Health & Fitness
        'fitness', 'health', 'nutrition', 'diet', 'keto', 'intermittent fasting', 'veganism',
        'vegetarianism', 'paleo', 'mediterranean diet', 'yoga', 'pilates', 'crossfit',
        'weightlifting', 'cardio', 'running', 'cycling', 'swimming', 'martial arts',
        'tai chi', 'qigong', 'stretching', 'mobility', 'physical therapy', 'massage',
        'acupuncture', 'chiropractic', 'naturopathy', 'holistic health', 'mental health',
        
        # Nature & Science
        'botany', 'plants', 'gardening', 'horticulture', 'permaculture', 'ecology',
        'biology', 'chemistry', 'physics', 'astronomy', 'astrophysics', 'cosmology',
        'space', 'nasa', 'Neil DeGrasse Tyson', 'Einstein', 'mars', 'moon', 'satellites', 'telescopes',
        'quantum physics', 'relativity', 'particle physics', 'geology', 'meteorology',
        'climate science', 'environmental science', 'conservation', 'sustainability',
        'renewable energy', 'solar', 'wind', 'hydroelectric', 'nuclear',
        
        # Arts & Creativity
        'art', 'painting', 'drawing', 'sculpture', 'digital art', 'graphic design',
        'photography', 'portrait photography', 'landscape photography', 'street photography',
        'music', 'guitar', 'piano', 'drums', 'violin', 'singing', 'composition',
        'jazz', 'classical', 'rock', 'electronic music', 'hip hop', 'folk',
        'writing', 'poetry', 'fiction', 'non-fiction', 'journalism', 'blogging',
        'screenwriting', 'storytelling', 'literature', 'creative writing',
        
        # Hobbies & Lifestyle
        'cooking', 'baking', 'fermentation', 'brewing', 'wine', 'coffee', 'tea',
        'travel', 'backpacking', 'hiking', 'camping', 'mountaineering', 'rock climbing',
        'skiing', 'snowboarding', 'surfing', 'diving', 'sailing', 'fishing',
        'woodworking', 'metalworking', 'electronics', 'arduino', 'raspberry pi',
        'diy', 'crafting', 'knitting', 'sewing', 'pottery', 'jewelry making',
        
        # Business & Finance
        'entrepreneurship', 'startups', 'business', 'marketing', 'sales', 'seo',
        'social media marketing', 'content marketing', 'email marketing', 'copywriting',
        'finance', 'investing', 'stocks', 'bonds', 'real estate', 'personal finance',
        'budgeting', 'retirement planning', 'taxes', 'accounting', 'economics',
        'project management', 'leadership', 'team management', 'productivity',
        
        # Gaming & Entertainment
        'gaming', 'video games', 'board games', 'chess', 'poker', 'esports',
        'game development', 'unity', 'unreal engine', 'indie games', 'retro gaming', 'Dungeons & Dragons',
        'streaming', 'twitch', 'youtube', 'podcast', 'movies', 'cinema',
        'animation', 'anime', 'manga', 'comics', 'graphic novels',
        
        # Education & Learning
        'education', 'teaching', 'learning', 'moocs', 'online courses', 'certification',
        'languages', 'spanish', 'french', 'german', 'japanese', 'chinese', 'italian',
        'linguistics', 'etymology', 'history', 'archaeology', 'anthropology',
        'psychology', 'sociology', 'political science', 'law', 'medicine'
    ]
    
    for term in potential_interests:
        if term in query_lower and term not in profile.get('interests', []) and term not in current_explorations:
            interesting_terms.append(term.title())
    
    # Only add if we found something interesting and new
    if interesting_terms and len(interesting_terms) <= 2:  # Keep it minimal
        # Add to recent_explorations, keeping only last 10 items
        updated_explorations = current_explorations + interesting_terms
        profile['recent_explorations'] = updated_explorations[-10:]  # Keep last 10
        save_user_profile(profile)

def create_default_user_profile():
    """Create a default user profile file if it doesn't exist"""
    profile_path = os.path.join(os.path.dirname(__file__), "user_details.log")
    if not os.path.exists(profile_path):
        default_profile = {
            'name': 'User',
            'location': '',
            'timezone': '',
            'preferences': ['helpful responses', 'detailed explanations'],
            'interests': [],
            'recent_explorations': [],
            'notes': 'Edit this file to personalize your AI assistant'
        }
        save_user_profile(default_profile)
        print(f"{Fore.YELLOW}Created default user profile: user_details.log{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}Edit this file to personalize your AI assistant!{Style.RESET_ALL}")

# -------------------------------------
# Conversational Search Functions
# -------------------------------------
def update_concerning_search(query):
    """
    Softly note concerning searches in user profile
    """
    import random
    
    # Only update 20% of the time for concerning content (higher than normal)
    if random.random() > 0.2:
        return
    
    profile = load_user_profile()
    current_notes = profile.get('notes', '')
    
    # Add a subtle note without being too invasive
    from datetime import datetime
    date_str = datetime.now().strftime('%Y-%m-%d')
    concern_note = f"Note: User searched for potentially concerning topic on {date_str}"
    
    # Only add if not already noted recently
    if 'concerning topic' not in str(current_notes):
        if isinstance(current_notes, list):
            current_notes.append(concern_note)
        else:
            # Handle both string and list formats
            if current_notes and current_notes != 'Edit this file to personalize your AI assistant':
                current_notes = str(current_notes) + f" | {concern_note}"
            else:
                current_notes = concern_note
        
        profile['notes'] = current_notes
        save_user_profile(profile)

def enhance_conversation_with_search(query, search_results):
    """
    Use search results to create conversational flow with multiple perspectives
    """
    user_context = get_user_context()
    datetime_context = get_datetime_context()
    
    # Analyze the query for potential social concerns
    concerning_keywords = [
        'hate', 'violence', 'illegal', 'harmful', 'dangerous', 'exploit', 
        'scam', 'fraud', 'weapon', 'drug', 'suicide', 'self-harm',
        'bomb', 'terror', 'kill', 'murder', 'abuse', 'trafficking'
    ]
    
    is_concerning = any(keyword in query.lower() for keyword in concerning_keywords)
    
    # Create search context summary
    if search_results:
        try:
            context_summary = "\n".join([
                f"Perspective {i+1}: {summarize_text(result.get('content', 'No content available'), max_sentences=2)}"
                for i, result in enumerate(search_results[:3])
                if result and 'content' in result
            ])
            if not context_summary:
                context_summary = "Search results found but no readable content available."
        except Exception as e:
            context_summary = f"Error processing search results: {str(e)}"
    else:
        context_summary = "No additional web context found."
    
    # Build the enhanced prompt
    if is_concerning:
        conversation_prompt = f"""
        {datetime_context}
        User context: {user_context}
        
        The user asked about: "{query}"
        
        Web research shows:
        {context_summary}
        
        Please:
        1. Answer their question factually but responsibly
        2. Express concern about potential risks or ethical issues
        3. Suggest healthier alternatives or resources for help if appropriate
        4. Keep the tone respectful but clearly convey any social concerns
        """
        
        # Add concerning search to user notes (soft learning)
        update_concerning_search(query)
        
    else:
        conversation_prompt = f"""
        {datetime_context}
        User context: {user_context}
        
        The user asked about: "{query}"
        
        Web research shows:
        {context_summary}
        
        Please provide a thoughtful response that:
        1. Shares the most relevant information from research
        2. Offers your perspective based on the data
        3. Presents alternative viewpoints if they exist
        4. Connects to the user's known interests when relevant
        5. Keeps the conversation flowing naturally
        """
    
    return conversation_prompt

def perform_conversational_search(query):
    """
    Enhanced search that feeds into conversation flow
    """
    try:
        # Get search results using existing optimized search
        search_results = perform_hybrid_search(query)
        
        # Create conversational prompt with multiple perspectives
        enhanced_prompt = enhance_conversation_with_search(query, search_results)
        
        # Use appropriate model based on content sensitivity
        concerning_keywords = ['hate', 'violence', 'illegal', 'harmful', 'dangerous']
        is_concerning = any(keyword in query.lower() for keyword in concerning_keywords)
        
        if is_concerning:
            chosen_model = MODELS["main"]  # Use main model for responsible responses
        elif reasoning_mode:
            chosen_model = MODELS["search"]
        elif coding_mode:
            chosen_model = MODELS["coding"]
        else:
            chosen_model = MODELS["main"]
        
        # Create a fresh conversation for this search to avoid context pollution
        search_conversation = [
            {"role": "system", "content": enhanced_prompt},
            {"role": "user", "content": query}
        ]
        
        response = ollama.chat(model=chosen_model, messages=search_conversation)
        return response["message"]["content"]
        
    except Exception as e:
        print(f"{Fore.RED}Error in conversational search: {e}{Style.RESET_ALL}")
        # Fallback to simple response
        return f"I found some information about '{query}' but encountered an error processing it. Could you rephrase your question?"

# -------------------------------------
# Agent System Functions
# -------------------------------------
AVAILABLE_AGENTS = {
    'research': {
        'name': 'Research Synthesizer',
        'description': 'Cross-references sources, identifies contradictions, synthesizes viewpoints',
        'knowledge_path': 'agent_knowledge/research_synthesizer',
        'persona': 'You are a Research Synthesizer agent. You excel at cross-referencing multiple academic sources, identifying contradicting viewpoints, and generating evidence-based syntheses. You provide citation-backed summaries and help users understand complex topics from multiple perspectives.'
    },
    'philosophy': {
        'name': 'Philosophy Bridge',
        'description': 'Connects ancient wisdom with modern challenges',
        'knowledge_path': 'agent_knowledge/philosophy_bridge',
        'persona': 'You are a Philosophy Bridge agent. You specialize in connecting ancient wisdom traditions (Buddhist, Stoic, Taoist) with modern technological and life challenges. You help users apply contemplative insights to practical problems and find philosophical depth in technical work.'
    },
    'space': {
        'name': 'Space Consciousness',
        'description': 'Explores connections between space exploration and consciousness',
        'knowledge_path': 'agent_knowledge/space_consciousness',
        'persona': 'You are a Space Consciousness agent. You explore the connections between space exploration and consciousness studies, drawing on astronaut psychology, the overview effect, and cosmic perspective to provide insights about awareness, isolation, and the human experience of vastness.'
    },
    'ethics': {
        'name': 'Ethics Advisor',
        'description': 'Multi-framework ethical analysis and guidance',
        'knowledge_path': 'agent_knowledge/ethics_advisor',
        'persona': 'You are an Ethics Advisor agent. You provide multi-framework ethical analysis using Buddhist ethics, utilitarian calculus, deontological duty, and virtue ethics. You help users navigate complex moral decisions, especially in technology development and AI ethics.'
    },
    'creative': {
        'name': 'Creative Connector',
        'description': 'Generates unexpected connections between disparate fields',
        'knowledge_path': 'agent_knowledge/creative_connector',
        'persona': 'You are a Creative Connector agent. You excel at finding unexpected connections between disparate fields, generating biomimicry insights, and fostering interdisciplinary innovation. You help users see familiar problems from new angles and make creative leaps.'
    },
    'tutor': {
        'name': 'Master Tutor',
        'description': 'Personalized learning paths and step-by-step explanations',
        'knowledge_path': 'agent_knowledge/master_tutor',
        'persona': 'You are a Master Tutor agent. You excel at breaking down complex topics into digestible steps, creating personalized learning paths, and adapting explanations to different learning styles. You use analogies, examples, and progressive difficulty to ensure understanding. Always assess comprehension and adjust your teaching approach accordingly.'
    },
    'fact_checker': {
        'name': 'Fact Checker',
        'description': 'Verifies claims, checks sources, identifies misinformation',
        'knowledge_path': 'agent_knowledge/fact_checker',
        'persona': 'You are a Fact Checker agent. You specialize in verifying claims, cross-referencing sources, identifying potential misinformation, and providing evidence-based assessments. You examine the credibility of sources, look for primary evidence, and flag when information cannot be verified. You present findings objectively and highlight uncertainty when it exists.'
    },
    'comedian': {
        'name': 'Digital Comedian',
        'description': 'Witty responses, clever observations, and appropriate humor',
        'knowledge_path': 'agent_knowledge/digital_comedian',
        'persona': 'You are a Digital Comedian agent. You specialize in witty observations, clever wordplay, and finding humor in everyday situations while remaining appropriate and inclusive. You excel at timing, callback references, and adapting your humor style to the conversation context. You avoid offensive content and focus on clever, uplifting humor.'
    },
    'debugger': {
        'name': 'Code Debugger',
        'description': 'Analyzes code issues, suggests fixes, explains debugging strategies',
        'knowledge_path': 'agent_knowledge/code_debugger',
        'persona': 'You are a Code Debugger agent. You excel at analyzing code issues, identifying bugs, suggesting fixes, and teaching debugging strategies. You systematically work through problems, explain your reasoning, and help users understand not just what to fix, but why issues occurred and how to prevent them.'
    },
    'counselor': {
        'name': 'Digital Counselor',
        'description': 'Supportive guidance, emotional intelligence, wellness focus',
        'knowledge_path': 'agent_knowledge/digital_counselor',
        'persona': 'You are a Digital Counselor agent. You provide supportive, empathetic responses with focus on emotional intelligence and wellness. You help users process thoughts and feelings, suggest healthy coping strategies, and encourage self-reflection. You maintain appropriate boundaries and always recommend professional help for serious mental health concerns.'
    }
}

def get_agent_knowledge(agent_name):
    """Load knowledge base content for a specific agent"""
    if agent_name not in AVAILABLE_AGENTS:
        return ""
    
    agent_path = os.path.join(os.path.dirname(__file__), AVAILABLE_AGENTS[agent_name]['knowledge_path'])
    knowledge_content = []
    
    if os.path.exists(agent_path):
        for root, dirs, files in os.walk(agent_path):
            for file in files:
                if file.endswith('.md'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            knowledge_content.append(f"=== {file} ===\n{content}\n")
                    except:
                        pass
    
    return "\n".join(knowledge_content) if knowledge_content else "No specialized knowledge base found."

# -------------------------------------
# Agent Memory System
# -------------------------------------
def load_agent_memory(agent_name):
    """Load conversation memory for a specific agent"""
    if not agent_name:
        return []
    
    memory_path = os.path.join(os.path.dirname(__file__), "agent_memory")
    if not os.path.exists(memory_path):
        os.makedirs(memory_path)
    
    memory_file = os.path.join(memory_path, f"{agent_name}_memory.json")
    
    if os.path.exists(memory_file):
        try:
            with open(memory_file, 'r', encoding='utf-8') as f:
                import json
                memory_data = json.load(f)
                return memory_data.get('conversations', [])
        except:
            pass
    
    return []

def save_agent_memory(agent_name, conversation_summary):
    """Save important conversation points for agent memory"""
    if not agent_name or not conversation_summary:
        return
    
    memory_path = os.path.join(os.path.dirname(__file__), "agent_memory")
    if not os.path.exists(memory_path):
        os.makedirs(memory_path)
    
    memory_file = os.path.join(memory_path, f"{agent_name}_memory.json")
    
    # Load existing memory
    memory_data = {'conversations': []}
    if os.path.exists(memory_file):
        try:
            with open(memory_file, 'r', encoding='utf-8') as f:
                import json
                memory_data = json.load(f)
        except:
            pass
    
    # Add new conversation summary
    from datetime import datetime
    new_entry = {
        'date': datetime.now().isoformat(),
        'summary': conversation_summary,
        'topics': extract_topics_from_summary(conversation_summary)
    }
    
    memory_data['conversations'].append(new_entry)
    
    # Keep only last 20 conversations to manage memory size
    memory_data['conversations'] = memory_data['conversations'][-20:]
    
    # Save updated memory
    try:
        with open(memory_file, 'w', encoding='utf-8') as f:
            import json
            json.dump(memory_data, f, indent=2, ensure_ascii=False)
    except:
        pass

def extract_topics_from_summary(summary):
    """Extract key topics from conversation summary for memory indexing"""
    # Simple keyword extraction - could be enhanced with NLP
    common_words = {'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'was', 'are', 'were', 'a', 'an'}
    words = summary.lower().split()
    topics = [word.strip('.,!?') for word in words if len(word) > 3 and word not in common_words]
    return list(set(topics))[:10]  # Return up to 10 unique topics

def get_relevant_agent_memory(agent_name, current_topic):
    """Get relevant past conversations for current context"""
    memory = load_agent_memory(agent_name)
    if not memory:
        return ""
    
    # Simple relevance matching - could be enhanced
    relevant_conversations = []
    current_words = set(current_topic.lower().split())
    
    for conv in memory[-10:]:  # Check last 10 conversations
        topics = conv.get('topics', [])
        if any(topic in current_words for topic in topics):
            relevant_conversations.append(conv)
    
    if relevant_conversations:
        context = f"\n=== Relevant Past Conversations ===\n"
        for conv in relevant_conversations[-3:]:  # Last 3 relevant conversations
            context += f"Date: {conv['date'][:10]} - {conv['summary'][:200]}...\n"
        return context
    
    return ""

def switch_agent(agent_name):
    """Switch to a specialized agent persona"""
    global current_agent
    
    if agent_name is None or agent_name == 'default':
        current_agent = None
        return "Switched to default mode."
    
    if agent_name not in AVAILABLE_AGENTS:
        available = ', '.join(AVAILABLE_AGENTS.keys())
        return f"Unknown agent '{agent_name}'. Available agents: {available}"
    
    current_agent = agent_name
    agent_info = AVAILABLE_AGENTS[agent_name]
    
    # Load agent knowledge and memory
    knowledge = get_agent_knowledge(agent_name)
    memory_context = get_relevant_agent_memory(agent_name, "general_context")
    
    # Add agent persona, knowledge, and memory to conversation
    persona_prompt = f"""
{agent_info['persona']}

Your specialized knowledge base:
{knowledge}

{memory_context}

User context: {get_user_context()}
Current time: {get_datetime_context()}

Respond in character as the {agent_info['name']} agent. Draw on your knowledge base and remember our past conversations when relevant.
"""
    
    assistant_convo.append({"role": "system", "content": persona_prompt})
    
    return f"✨ Switched to {agent_info['name']} agent.\n{agent_info['description']}\n\nHow can I assist you from this specialized perspective?"

def setup_multi_agent_collaboration(agent_names):
    """Setup collaboration between multiple agents"""
    global current_agent
    
    valid_agents = []
    for agent_name in agent_names:
        if agent_name in AVAILABLE_AGENTS:
            valid_agents.append(agent_name)
    
    if not valid_agents:
        return "No valid agents specified for collaboration."
    
    # Set primary agent as current
    current_agent = valid_agents[0]
    
    # Create collaborative context
    collaborative_personas = []
    combined_knowledge = []
    
    for agent_name in valid_agents:
        agent_info = AVAILABLE_AGENTS[agent_name]
        collaborative_personas.append(f"**{agent_info['name']}**: {agent_info['persona']}")
        knowledge = get_agent_knowledge(agent_name)
        if knowledge and knowledge != "No specialized knowledge base found.":
            combined_knowledge.append(f"=== {agent_info['name']} Knowledge ===\n{knowledge}")
    
    collaboration_prompt = f"""
You are part of a collaborative team of AI agents working together to provide comprehensive assistance.

ACTIVE AGENTS IN THIS COLLABORATION:
{chr(10).join(collaborative_personas)}

COMBINED KNOWLEDGE BASE:
{chr(10).join(combined_knowledge) if combined_knowledge else "Using general knowledge."}

COLLABORATION GUIDELINES:
- Draw insights from all agent perspectives
- When responding, indicate which agent perspective is most relevant
- Integrate different viewpoints for richer analysis
- If agents would disagree, present multiple perspectives
- Use each agent's specialized knowledge appropriately

User context: {get_user_context()}
Current time: {get_datetime_context()}

Respond as a collaborative team of specialized agents, with {AVAILABLE_AGENTS[current_agent]['name']} taking the lead.
"""
    
    assistant_convo.append({"role": "system", "content": collaboration_prompt})
    
    agent_names_formatted = [AVAILABLE_AGENTS[name]['name'] for name in valid_agents]
    return f"🤝 Collaborative mode activated!\n\nActive agents: {', '.join(agent_names_formatted)}\nLead agent: {AVAILABLE_AGENTS[current_agent]['name']}\n\nHow can our team assist you?"

def job_command(args=None):
    """Handle the /job command with support for multi-agent collaboration"""
    if not args:
        # Show available agents
        result = "🤖 Available Agent Personas:\n\n"
        for key, agent in AVAILABLE_AGENTS.items():
            status = " (ACTIVE)" if current_agent == key else ""
            result += f"**{key}**: {agent['name']}{status}\n"
            result += f"   └─ {agent['description']}\n\n"
        
        result += f"Current agent: {AVAILABLE_AGENTS[current_agent]['name'] if current_agent else 'Default mode'}\n"
        result += "\nUsage: /job <agent_name> or /job default"
        result += "\nMulti-agent: /job agent1,agent2,agent3"
        result += "\n\nExample: /job philosophy,ethics (for ethical philosophy discussions)"
        return result
    
    args_cleaned = args.strip().lower()
    
    # Check for multi-agent collaboration (comma-separated)
    if ',' in args_cleaned:
        agent_names = [name.strip() for name in args_cleaned.split(',')]
        return setup_multi_agent_collaboration(agent_names)
    
    # Single agent
    return switch_agent(args_cleaned)

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
# Context-Aware Agent Suggestions & Knowledge Auto-Updates
# -------------------------------------
def suggest_agent_for_context(user_input):
    """Suggest the most appropriate agent based on context"""
    if current_agent:  # Don't suggest if already using an agent
        return None
    
    text_lower = user_input.lower()
    
    # Debug/coding indicators
    if any(term in text_lower for term in ['bug', 'error', 'debug', 'code', 'fix', 'syntax', 'algorithm']):
        return 'debugger'
    
    # Fact-checking indicators
    if any(term in text_lower for term in ['is this true', 'verify', 'fact check', 'source', 'evidence', 'claim']):
        return 'fact_checker'
    
    # Learning/teaching indicators
    if any(term in text_lower for term in ['explain', 'teach', 'learn', 'understand', 'how does', 'what is']):
        return 'tutor'
    
    # Philosophy/contemplative indicators
    if any(term in text_lower for term in ['wisdom', 'philosophy', 'meaning', 'purpose', 'consciousness', 'meditation']):
        return 'philosophy'
    
    # Ethics indicators
    if any(term in text_lower for term in ['ethical', 'moral', 'right', 'wrong', 'should i', 'values']):
        return 'ethics'
    
    # Emotional support indicators
    if any(term in text_lower for term in ['feeling', 'stressed', 'anxious', 'support', 'help me cope', 'overwhelmed']):
        return 'counselor'
    
    # Creative thinking indicators
    if any(term in text_lower for term in ['creative', 'innovative', 'brainstorm', 'ideas', 'inspiration']):
        return 'creative'
    
    # Research indicators
    if any(term in text_lower for term in ['research', 'analyze', 'compare', 'study', 'investigation']):
        return 'research'
    
    # Humor indicators (if user seems to want lightness)
    if any(term in text_lower for term in ['joke', 'funny', 'humor', 'laugh', 'comedy']):
        return 'comedian'
    
    return None

def should_save_to_knowledge_base(user_input, response):
    """Determine if conversation contains valuable insights worth saving"""
    # Save if response is substantial and informative
    if len(response) < 100:
        return False
    
    # Save if it contains technical insights, philosophical depth, or learning content
    valuable_indicators = [
        'methodology', 'technique', 'principle', 'framework', 'approach',
        'insight', 'understanding', 'analysis', 'connection', 'parallel',
        'example', 'case study', 'research', 'evidence', 'solution'
    ]
    
    response_lower = response.lower()
    return any(indicator in response_lower for indicator in valuable_indicators)

def save_conversation_insights(agent_name, user_input, response):
    """Save valuable conversation insights to agent knowledge base"""
    if not agent_name or not should_save_to_knowledge_base(user_input, response):
        return
    
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d")
    
    # Create insight file name
    topic = user_input[:50].replace(' ', '_').replace('?', '').replace('!', '')
    safe_topic = sanitize_filename(topic)
    insight_filename = f"conversation_insight_{timestamp}_{safe_topic}.md"
    
    # Format as structured insight
    insight_content = f"""# Conversation Insight: {topic}

**Date**: {timestamp}
**Agent**: {AVAILABLE_AGENTS[agent_name]['name']}
**User Context**: {get_user_context()[:200]}...

## User Question
{user_input}

## Key Insights
{response[:500]}...

## Patterns Identified
- Generated through natural conversation
- Demonstrates {agent_name} agent expertise
- User showed interest in: {', '.join(extract_topics_from_summary(user_input)[:3])}

## Applications
This insight could be valuable for:
- Similar future questions about {topic}
- Understanding user's learning patterns
- Building on this topic in future conversations
"""
    
    # Save to agent's knowledge base
    agent_path = os.path.join(os.path.dirname(__file__), AVAILABLE_AGENTS[agent_name]['knowledge_path'])
    if not os.path.exists(agent_path):
        os.makedirs(agent_path)
    
    insight_path = os.path.join(agent_path, insight_filename)
    try:
        with open(insight_path, 'w', encoding='utf-8') as f:
            f.write(insight_content)
        print(f"{Fore.GREEN}💾 Saved insight to {agent_name} knowledge base{Style.RESET_ALL}")
    except:
        pass

# -------------------------------------
# MAIN INTERACTION LOOP
# -------------------------------------
def main():
    global assistant_convo, voice_mode, web_search_mode, reasoning_mode, unfiltered_mode, tts_mode, coding_mode, current_agent
    
    # Initialize agent to default mode on startup
    current_agent = None
    
    # Create default user profile if it doesn't exist
    create_default_user_profile()
    
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

        # /job command
        if prompt.lower().startswith("/job"):
            parts = prompt.split(maxsplit=1)
            args = parts[1] if len(parts) > 1 else None
            result = job_command(args)
            print(f"{Fore.CYAN}{result}{Style.RESET_ALL}")
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
        
        # /profile command
        if prompt.lower().startswith("/profile"):
            parts = prompt.split(maxsplit=1)
            if len(parts) == 1:
                # Show current profile
                profile = load_user_profile()
                print(f"{Fore.CYAN}Current User Profile:{Style.RESET_ALL}")
                print(f"Name: {profile['name']}")
                print(f"Location: {profile['location']}")
                print(f"Preferences: {', '.join(profile['preferences'])}")
                print(f"Interests: {', '.join(profile['interests'])}")
                print(f"Recent Explorations: {', '.join(profile['recent_explorations'])}")
                print(f"Notes: {profile['notes']}")
                print(f"{Fore.YELLOW}Edit user_details.log to modify your profile{Style.RESET_ALL}")
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
                print("/job [agent] - Switch to specialized agent persona (research, philosophy, space, ethics, creative)")
                print("/news - Fetch latest news headlines")
                print("/password [-N] - Generate N (default 5) complex passwords, each 20 characters")
                print("/profile - Show current user profile (edit user_details.log to modify)")
                print("/reason - Toggle reasoning mode (deepseek-r1:14b)")
                print("/showpath [topic] - Show the learning path for the given topic")
                print("/tarot - Perform a single-deck Tree of Life Tarot reading")
                print("/tutor [topic] - Create a learning path for the given topic")
                print("/tts - Toggle TTS mode (read responses aloud)")
                print("/unfiltered - Toggle unfiltered mode (r1-1776:70b)")
                print("/voice - Toggle voice mode (for live input)")
                print("/websearch - Toggle conversational web search mode (multiple perspectives)")
                print("/ytdl <url> - Download YouTube video in highest quality to ~/Downloads")
                print("\n💡 Pro Tip: Use @keyword@ tags in any message to search for current info!")
                print("   Example: 'When are @midterm elections@ happening?'")
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
        
        # Catch unrecognized slash commands
        if prompt.startswith("/"):
            funny_errors = [
                f"🤔 '{prompt}' is not a command I recognize. Did you mean to search for that instead?",
                f"🚫 Unknown command: '{prompt}'. I'm smart, but not THAT smart!",
                f"❓ '{prompt}' - That's not in my command vocabulary. Try /help for actual commands!",
                f"🤷 I don't speak '{prompt}'. Maybe you meant to ask me something without the slash?",
                f"💭 '{prompt}' sounds mysterious, but it's not a real command. /help might be more helpful!",
                f"🎯 Command '{prompt}' not found. My programming is good, but my mind-reading needs work!",
                f"⚡ '{prompt}' - Nice try! But I only respond to commands I actually know. Check /help!",
                f"🎪 '{prompt}' would be a cool command... if it existed! Try /help for real ones.",
                f"🔍 Searching my command database for '{prompt}'... Nope! Nothing found. Try /help instead.",
                f"🎭 '{prompt}' - Creative! But not actually a command. I'm an AI, not a magic 8-ball!"
            ]
            print(f"{Fore.YELLOW}{random.choice(funny_errors)}{Style.RESET_ALL}")
            continue
        
        # Web Search Mode Handling - Enhanced Conversational Approach
        if web_search_mode and not prompt.startswith("/"):
            # Update user explorations softly
            update_user_notes_softly(prompt, [])
            
            print(f"{Fore.CYAN}🔍 Searching and analyzing perspectives...{Style.RESET_ALL}\n")
            
            # Get search results
            all_results = perform_hybrid_search(prompt)
            
            if all_results:
                # Create conversational context
                user_context = get_user_context()
                datetime_context = get_datetime_context()
                
                # Check for concerning content
                concerning_keywords = ['hate', 'violence', 'illegal', 'harmful', 'dangerous']
                is_concerning = any(keyword in prompt.lower() for keyword in concerning_keywords)
                
                # Prepare search context
                context_snippets = []
                for i, result in enumerate(all_results[:3]):
                    if result and 'content' in result:
                        summary = summarize_text(result["content"], max_sentences=2)
                        if summary.strip():
                            context_snippets.append(f"Perspective {i+1}: {summary}")
                
                if context_snippets:
                    search_context = "\n\n".join(context_snippets)
                    
                    # Create conversational prompt
                    if is_concerning:
                        conversation_prompt = f"{datetime_context}\nUser context: {user_context}\n\nThe user asked about: '{prompt}'\n\nWeb research shows:\n{search_context}\n\nPlease answer responsibly, express any concerns about risks or ethics, and suggest healthier alternatives if appropriate."
                        update_concerning_search(prompt)
                    else:
                        conversation_prompt = f"{datetime_context}\nUser context: {user_context}\n\nThe user asked about: '{prompt}'\n\nWeb research shows:\n{search_context}\n\nPlease provide a thoughtful response that shares relevant information, offers your perspective, presents alternative viewpoints if they exist, and connects to the user's interests when relevant."
                    
                    # Add conversational context and user prompt
                    assistant_convo.append({"role": "system", "content": conversation_prompt})
                    assistant_convo.append({"role": "user", "content": prompt})
                    
                    # Record to knowledge base
                    record_to_knowledge_base(prompt, search_context)
                    
                else:
                    # No good content found
                    assistant_convo.append({"role": "user", "content": prompt})
            else:
                # No search results
                assistant_convo.append({"role": "user", "content": prompt})
            
            # Generate response
            stream_response()
            continue
        # Standard conversation
        # Process @keyword@ search tags first
        processed_prompt = process_search_tags(prompt)
        
        # Add contextual information for better responses
        context_info = []
        context_info.append(get_datetime_context())
        user_context = get_user_context()
        if user_context != "No user profile information available":
            context_info.append(f"User context: {user_context}")
        
        # Add context as system message before user prompt
        if context_info:
            context_message = " | ".join(context_info)
            assistant_convo.append({"role": "system", "content": f"[Context: {context_message}]"})
        
        assistant_convo.append({"role": "user", "content": processed_prompt})
        
        # Context-aware agent suggestions
        suggested_agent = suggest_agent_for_context(processed_prompt)
        if suggested_agent and suggested_agent != current_agent:
            agent_name = AVAILABLE_AGENTS[suggested_agent]['name']
            print(f"{Fore.YELLOW}💡 This looks like a job for the {agent_name}! Switch with `/job {suggested_agent}`?{Style.RESET_ALL}")
        
        # Advanced conversation pattern analysis
        analyze_conversation_patterns(processed_prompt)
        
        response = stream_response()
        
        # Save insights to agent memory and knowledge base
        if current_agent and response:
            save_agent_memory(current_agent, f"User: {processed_prompt[:100]}... Response: {response[:200]}...")
            
            # Auto-update knowledge base with valuable insights
            if should_save_to_knowledge_base(processed_prompt, response):
                save_conversation_insights(current_agent, processed_prompt, response)

if __name__ == "__main__":
    main()