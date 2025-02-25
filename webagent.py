import ollama
import sys_msgs
import requests
import trafilatura
import json
import speech_recognition as sr
import edge_tts  # More natural text-to-speech
import threading
import os
from bs4 import BeautifulSoup
from colorama import init, Fore, Style
from PyPDF2 import PdfReader
import subprocess
import sys
import time  # For typing effect
from concurrent.futures import ThreadPoolExecutor

init(autoreset=True)
assistant_convo = [sys_msgs.assistant_msg]
voice_mode = False  # Toggle for voice input
stop_voice_flag = False  # Flag to stop voice playback
executor = ThreadPoolExecutor()  # Background operations

# Models configuration
MODELS = {
    'main': 'llama3.2',
    'search': 'deepseek-r1:14b',
}

# Stop voice function
def stop_voice():
    global stop_voice_flag
    stop_voice_flag = True
    os.system("pkill mpg123")  # Kill audio playback (Linux/macOS)
    os.system("taskkill /IM mpg123.exe /F")  # Windows

# Text-to-Speech using Edge-TTS (UK Male, No Async)
def speak_text(text):
    global stop_voice_flag
    if voice_mode:
        stop_voice_flag = False  # Reset stop flag
        temp_audio = "tts_output.mp3"  # Temp file for speech

        tts = edge_tts.Communicate(text, voice="en-GB-RyanNeural")  # UK Male Voice
        tts.save(temp_audio)  # Save TTS output to file

        if stop_voice_flag:  # Check before playing
            return

        os.system(f"mpg123 {temp_audio}")  # Play audio synchronously
        os.remove(temp_audio)  # Delete temp file after playback

# Streaming response (Fastest possible typing, short and direct)
def stream_response():
    print(f"{Fore.CYAN}Generating response...\n")
    complete_response = ""

    response_stream = ollama.chat(model=MODELS["main"], messages=assistant_convo, stream=True)

    for chunk in response_stream:
        text_chunk = chunk["message"]["content"]
        complete_response += text_chunk

        # Print text as soon as it's received
        print(f"{Fore.GREEN}{text_chunk}", end="", flush=True)

    print()  # Move to next line

    # Speak response using Edge-TTS
    speak_text(complete_response)  

    # Keep responses short and direct
    trimmed_response = complete_response.split(". ")[0] + "." if "." in complete_response else complete_response
    assistant_convo.append({"role": "assistant", "content": trimmed_response})

# Load models
def pull_model():
    for model in MODELS.values():
        print(f"{Fore.CYAN}Pulling model '{model}'...")
        ollama.pull(model=model)
        print(f"{Fore.GREEN}Model '{model}' pulled successfully.")

# Perform a web search
def duckduckgo_search(query):
    headers = {"User-Agent": "Mozilla/5.0"}
    url = f"https://duckduckgo.com/html/?q={query}"

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        results = []

        for i, result in enumerate(soup.find_all("div", class_="result")):
            if i >= 5:  # Limit to top 5 results
                break

            title_tag = result.find("a", class_="result__a")
            if not title_tag:
                continue

            title = title_tag.text.strip()
            link = title_tag["href"]
            snippet_tag = result.find("a", class_="result__snippet")
            snippet = snippet_tag.text.strip() if snippet_tag else "No description available."

            results.append({"title": title, "link": link, "snippet": snippet})

        return results if results else None

    except Exception as e:
        print(f"{Fore.RED}Error fetching search results: {e}")
        return None

# Scrape a webpage for content
def scrape_webpage(url):
    try:
        downloaded = trafilatura.fetch_url(url)
        content = trafilatura.extract(downloaded)
        return content if content else None
    except Exception as e:
        print(f"{Fore.RED}Error scraping webpage: {e}")
        return None

# Voice Input with Exit Handling (Interrupt AI speech with Mic)
def recognize_speech():
    global stop_voice_flag
    recognizer = sr.Recognizer()
    
    with sr.Microphone() as source:
        print(f"{Fore.YELLOW}🎤 Listening... (Say '{Fore.CYAN}exit voice{Fore.YELLOW}' or '{Fore.CYAN}stop listening{Fore.YELLOW}' to return to text mode)")
        
        try:
            stop_voice_flag = True  # Stop AI speech immediately when user starts talking
            stop_voice()  # Stop current playback
            
            audio = recognizer.listen(source)
            text = recognizer.recognize_google(audio).lower()

            if "exit voice" in text or "stop listening" in text:
                print(f"{Fore.RED}Voice mode OFF.")
                return "/voice_exit"

            return text
        except sr.UnknownValueError:
            print(f"{Fore.RED}Could not understand audio.")
        except sr.RequestError:
            print(f"{Fore.RED}Speech recognition service unavailable.")
    return ""

# Main Interaction Loop
def main():
    global assistant_convo, voice_mode
    pull_model()

    while True:
        print()
        if voice_mode:
            prompt = recognize_speech()
            if prompt == "/voice_exit":
                voice_mode = False
                continue
        else:
            prompt = input(f"{Fore.BLUE}USER: ")

        # Handle Commands
        if prompt.lower() in ["/help", "/exit", "/clear", "/voice", "/stopvoice", "/websearch", "/scrape"]:
            if prompt.lower() == "/help":
                print("\nCommands:")
                print("/help - Show this message")
                print("/exit - Save and exit")
                print("/clear - Reset conversation")
                print("/voice - Toggle voice mode (Say 'exit voice' or 'stop listening' to return to text mode)")
                print("/stopvoice - Stop AI from speaking mid-response")
                print("/websearch [query] - Search the internet using DuckDuckGo and get the top results")
                print("/scrape [url] - Scrape and summarize the content of a webpage")
                print()
            elif prompt.lower() == "/exit":
                print(f"{Fore.MAGENTA}Exiting...")
                exit()
            elif prompt.lower() == "/clear":
                assistant_convo = [sys_msgs.assistant_msg]
                print(f"{Fore.YELLOW}Session reset.")
            elif prompt.lower() == "/voice":
                voice_mode = not voice_mode
                print(f"{Fore.YELLOW}Voice mode {'ON' if voice_mode else 'OFF'}.")
            elif prompt.lower() == "/stopvoice":
                stop_voice()
                print(f"{Fore.RED}🔇 Voice stopped.")
            continue

        # Add user input to conversation history
        assistant_convo.append({"role": "user", "content": prompt})

        # **For all other inputs, generate response in real-time streaming (FASTEST possible)**
        stream_response()

if __name__ == "__main__":
    main()