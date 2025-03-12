import os
import re
import string
from colorama import Fore, Style
import ollama

# Initialize colorama
from colorama import init
init(autoreset=True)

assistant_convo = []
voice_mode = False
tts_mode = False

MODELS = {
    'main': 'llama3.2',
    'search': 'deepseek-r1:14b',
    'unfiltered': 'llama2-uncensored',
    'coding': 'nous-hermes2:10.7b',
}

def sanitize_filename(filename):
    valid_chars = f"-_.() {string.ascii_letters}{string.digits}"
    return "".join(c for c in filename if c in valid_chars).replace(" ", "_")

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
