import os
import re
from colorama import Fore, Style, init
from shared import ollama, assistant_convo, sanitize_filename, MODELS, speak_text, voice_mode, tts_mode

# Initialize colorama
init(autoreset=True)

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
        tutor_path = os.path.join(os.path.dirname(__file__), "tutor_paths")
        safe_filename = sanitize_filename(topic) + ".txt"
        file_path = os.path.join(tutor_path, safe_filename)
        if os.path.exists(file_path):
            os.remove(file_path)
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
        print(f"{Fore.GREEN}- {resource}{Style.RESET_ALL}")
    if voice_mode or tts_mode:
        asyncio.run(speak_text(learning_path))
