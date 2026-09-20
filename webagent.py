import os
import sys


def _relaunch_with_project_venv():
    """Run the terminal app with this checkout's interpreter when available."""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(project_dir, "venv", "bin", "python")
    if not os.path.isfile(venv_python):
        return
    if os.path.realpath(sys.executable) == os.path.realpath(venv_python):
        return

    os.execv(venv_python, [venv_python, os.path.abspath(__file__), *sys.argv[1:]])


if __name__ == "__main__":
    _relaunch_with_project_venv()

from core import config as core_config
from core.events import (
    events, SEARCH_COMPLETED, TASK_COMPLETED, SKILL_CREATED,
    KNOWLEDGE_UPDATED, MEMORY_CREATED, TEST_PASSED, TEST_FAILED,
    TOOL_SELECTION_MADE, TOOL_EXECUTION_COMPLETED, APP_STARTED,
)
from core.activity_log import record_activity
from core.command_router import CommandRouter
from core.context import context
from core.exceptions import ModelUnavailableError, ChatCancelled
from core.orchestrator import Orchestrator
from core import subscriptions
from tools.base import Permission
from tools.registry import registry as tool_registry
from tools.web.search import WebSearchTool
from tools.web.fetch import WebFetchTool
from tools.live.weather import LiveWeatherTool
from tools.live.stock import LiveStockQuoteTool
from tools.live.soccer import LiveSoccerResultTool
from tools.knowledge.search import KnowledgeSearchTool
from tools.knowledge.write import KnowledgeWriteTool
from tools.subscriptions.list import SubscriptionsListTool
from tools.scheduler.add import CronAddTool
from tools.scheduler.edit import CronEditTool
from tools.scheduler.list import CronListTool
from tools.scheduler.remove import CronRemoveTool
from tools.scheduler.run import CronRunTool
from tools.shell.git_status import GitStatusTool
from tools.shell.git_diff import GitDiffTool
from tools.shell.test_run import TestRunTool
from tools.shell.sandboxed_run import ShellSandboxedRunTool
from sandbox.commands import run_sandboxed_command
from sandbox.workspace import Workspace
from sandbox.sessions import open_session, close_session
from sandbox.files import read_file, write_file
from tools.sandbox.open_session import SandboxOpenTool
from tools.sandbox.close_session import SandboxCloseTool
from tools.filesystem.read import FilesystemReadTool
from tools.filesystem.write import FilesystemWriteTool
from tools.repository.audit import RepoAuditTool
from tools.repository.audit_advanced import RepoAuditAdvancedTool
from tools.design.list_projects import DesignListProjectsTool
from tools.design.create_project import DesignCreateProjectTool
from tools.design.list_files import DesignListFilesTool
from tools.design.create_file import DesignCreateFileTool
from tools.design.get_file import DesignGetFileTool
from tools.design.add_board import DesignAddBoardTool
from tools.design.add_shape import DesignAddShapeTool
from tools.conversation.inspect import ConversationInspectTool
from tools.evidence.verify import EvidenceVerifyTool
from tools.knowledge.related import KnowledgeRelatedTool
from tools.knowledge.forget import KnowledgeForgetTool
from tools.repository.inspect import RepoInspectTool
from tools.models.status import ModelStatusTool
from tools.planning.task_plan import TaskPlanTool
import penpot
from skills.registry import registry as skill_registry
from skills.research.topic import ResearchTopicSkill
from skills.conversation.recover import ConversationRecoverSkill
from skills.research.verify import ResearchVerifySkill
from skills.knowledge.maintain import KnowledgeMaintainSkill
from skills.repository.change_review import RepositoryChangeReviewSkill
from memory.experience import build_experience, record_experience
from learning.evaluator import evaluate_recent_performance
from learning.critic import critique_recent_failures
from learning.reflection import consolidated_lessons
from planning.planner import is_stuck_goal
from builder.pipeline import run_tool_generation_cycle
from reviewers.panel import run_review_panel
from reviewers.release_manager import summarize_reviews
from observability.metrics import (
    task_completion_stats, search_quality_stats, tool_usage_stats, self_improve_target_file_stats,
)
from core.models import (
    ollama,
    MODELS,
    chat as model_chat,
    cloud_models,
    MODEL_CONTEXT, DEFAULT_CONTEXT, thinking_options,
    pull_all as pull_all_models,
)

from core.chat_optimization import is_direct_chat, budget_messages
from core.topic_guard import candidate_matches_request, relevance_signals

import sys_msgs
import agent_dialogue
import requests
try:
    import trafilatura
    has_trafilatura = True
except ImportError:
    trafilatura = None
    has_trafilatura = False
import json
import hashlib
from urllib.parse import urlparse
try:
    import speech_recognition as sr
    has_speech_recognition = True
except ImportError:
    sr = None
    has_speech_recognition = False
try:
    import pyttsx3
    has_pyttsx3 = True
except ImportError:
    pyttsx3 = None
    has_pyttsx3 = False
import threading
import platform
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
from colorama import init, Fore, Style
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
import tempfile
import subprocess
import random
import re
import ast
import string
import uuid
import shlex
try:
    import yt_dlp
    has_yt_dlp = True
except ImportError:
    yt_dlp = None
    has_yt_dlp = False
import select
try:
    import termios
    import tty
except ImportError:  # Windows has neither; typeahead capture just no-ops there.
    termios = None
    tty = None
from collections import deque
from news import news_command

# -------------------------------------
# Initialization
# -------------------------------------
init(autoreset=True)

context.assistant_convo = [sys_msgs.assistant_msg]

stop_voice_flag = False
active_pyttsx3_engine = None
active_pyttsx3_thread = None
pyttsx3_lock = threading.Lock()
# pyttsx3's driver event loop is process-wide on some platforms.  Keep the
# complete engine lifecycle single-filed, not just the active-engine pointer.
pyttsx3_speech_lock = threading.Lock()
active_tts_process = None
tts_process_lock = threading.Lock()
executor = ThreadPoolExecutor()

# Lines the user finished typing (pressed Enter) while a response was still
# streaming. Consumed in FIFO order by the terminal loop before it prompts again.
_typeahead_queue = deque()
# An in-progress line the user had started but not yet submitted when the
# response finished streaming; pre-filled into the next input() prompt.
_typeahead_partial = ""


class _TypeaheadCapture:
    """Capture keystrokes typed while the assistant is still streaming output.

    A blocking terminal loop only calls input() after streaming finishes, but
    the TTY keeps echoing keystrokes the moment they're typed regardless of
    whether anything is reading them. That echo lands wherever the streaming
    text has scrolled to, so a command like "/deepthink" typed mid-response
    would get scattered into the middle of that response and appear to
    "disappear" once the next prompt actually showed up. This suppresses that
    raw echo, buffers the keystrokes instead, and hands them back so the
    caller can replay them cleanly against the next prompt.

    No-ops outside an interactive POSIX TTY (Windows, piped input, or a
    non-terminal stdout) - callers just get an empty buffer and behavior
    falls back to plain input().
    """

    def __init__(self):
        self.buffer = ""
        self._active = False
        self._fd = None
        self._old_settings = None

    def __enter__(self):
        if termios is None or tty is None or not sys.stdin.isatty():
            return self
        try:
            self._fd = sys.stdin.fileno()
            self._old_settings = termios.tcgetattr(self._fd)
            # TCSADRAIN, not tty.setcbreak's default TCSAFLUSH: the default
            # discards any input typed in the instant before this takes
            # effect, which would destroy a keystroke instead of merely
            # mis-echoing it.
            tty.setcbreak(self._fd, termios.TCSADRAIN)
            self._active = True
        except (termios.error, ValueError, OSError):
            self._active = False
        return self

    def poll(self):
        """Drain whatever has been typed since the last poll, without echoing it."""
        if not self._active:
            return
        try:
            while select.select([sys.stdin], [], [], 0)[0]:
                chunk = os.read(self._fd, 1024).decode(errors="ignore")
                if not chunk:
                    break
                self.buffer += chunk
        except (OSError, ValueError):
            pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._active:
            self.poll()
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_settings)
            except (termios.error, OSError):
                pass
        return False


def _stash_typeahead(raw_buffer):
    """Split captured keystrokes into completed lines (queued) and a trailing
    in-progress line (preloaded into the next prompt)."""
    global _typeahead_partial
    if not raw_buffer:
        return
    # A backspace/delete in cbreak mode arrives as a raw control byte rather
    # than editing the buffer in place, so apply it here before splitting.
    cleaned = []
    for ch in raw_buffer:
        if ch in ("\x7f", "\x08"):
            if cleaned:
                cleaned.pop()
        elif ch == "\x03":  # Ctrl-C while streaming: drop what was buffered.
            cleaned = []
        elif ch.isprintable() or ch == "\n":
            cleaned.append(ch)
    text = "".join(cleaned)
    parts = text.split("\n")
    _typeahead_queue.extend(parts[:-1])
    _typeahead_partial += parts[-1]


def _next_prompt_line(prompt_label):
    """Return the next prompt string, replaying any typeahead captured during
    the last response instead of silently discarding or reordering it."""
    global _typeahead_partial
    if _typeahead_queue:
        line = _typeahead_queue.popleft()
        print(f"{prompt_label}{line}")
        return line
    if _typeahead_partial:
        # Preloading readline's editable buffer (set_pre_input_hook +
        # insert_text) would be the ideal UX, but macOS ships Python linked
        # against libedit, where that hook is a silent no-op - the text would
        # vanish with no error. Appending it to input()'s own prompt string
        # instead is fully portable: it prints immediately before the cursor,
        # and whatever the user types next lands right after it.
        pending = _typeahead_partial
        _typeahead_partial = ""
        rest = input(f"{prompt_label}{pending}")
        return pending + rest
    return input(prompt_label)


def has_tts_backend():
    """Return whether this platform has a supported text-to-speech backend."""
    return platform.system() == "Darwin" or has_pyttsx3

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
    if context.current_agent:
        agent_name = AVAILABLE_AGENTS[context.current_agent]['name']
        return f"[{agent_name}] {base_prompt}"
    return base_prompt


# -----------------------------
# Conversation management
# -----------------------------
def trim_conversation(max_messages=80, max_chars=20000):
    """Budget instructions and complete recent turns for the selected model.

    Token counts are approximate; reserve reply space and retain bounded older
    excerpts when possible. Never silently discard an oversized current request.
    """
    if not isinstance(context.assistant_convo, list) or not context.assistant_convo:
        return
    chosen = _selected_model()
    size = MODEL_CONTEXT.get(chosen, DEFAULT_CONTEXT)
    if cloud_models.is_cloud(chosen):
        size = 8192
    try:
        context.assistant_convo = budget_messages(context.assistant_convo, size, max_messages, max_chars)
    except ValueError as exc:
        raise ModelUnavailableError(str(exc)) from exc


def _conversations_dir():
    path = os.path.join(core_config.project_root(), "conversations")
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
    return path


def _derive_conversation_title(convo, max_len=40):
    """Short, filesystem-safe title from the first user message, so a saved
    conversation reads as something recognizable in a list instead of an
    opaque conv_<timestamp> name."""
    first_user = next((m.get('content', '') for m in convo if m.get('role') == 'user'), '').strip()
    if not first_user:
        return None
    if len(first_user) > max_len:
        first_user = first_user[:max_len].rsplit(' ', 1)[0] or first_user[:max_len]
    return sanitize_filename(first_user) or None


def save_conversation(name=None):
    """Save the current context.assistant_convo to a timestamped file. Returns path or None."""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if name:
            safe_name = sanitize_filename(name)
        else:
            safe_name = _derive_conversation_title(context.assistant_convo) or f"conv_{timestamp}"
        fname = f"{safe_name}_{timestamp}.json"
        path = os.path.join(_conversations_dir(), fname)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'conversation': context.assistant_convo}, f, ensure_ascii=False, indent=2)
        return path
    except Exception:
        return None


def list_conversations():
    d = _conversations_dir()
    files = sorted([f for f in os.listdir(d) if f.endswith('.json')], reverse=True)
    return files


def new_conversation(save_current=True, name=None):
    """Start a new conversation. Optionally save the current one first."""
    saved = None
    if save_current and context.assistant_convo and len(context.assistant_convo) > 1:
        saved = save_conversation(name)
    context.assistant_convo = [sys_msgs.assistant_msg]
    return saved


def load_conversation(name_or_index):
    """Load a saved conversation by filename or 1-based index from the conversations dir.
    Returns the path on success, or None on failure.
    """
    try:
        files = list_conversations()
        if not files:
            return None

        # If numeric, treat as 1-based index into the list
        if isinstance(name_or_index, str) and name_or_index.isdigit():
            idx = int(name_or_index) - 1
            if 0 <= idx < len(files):
                fname = files[idx]
            else:
                return None
        else:
            # Exact match or fallback to sanitize
            fname = name_or_index
            if fname not in files:
                # try sanitized and partial matches
                candidates = [f for f in files if sanitize_filename(fname) in f or fname in f]
                if candidates:
                    fname = candidates[0]
                else:
                    return None

        path = os.path.join(_conversations_dir(), fname)
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        conv = data.get('conversation') or data.get('conversation', [])
        if isinstance(conv, list) and conv:
            context.assistant_convo = conv
            return path
    except Exception:
        return None
    return None

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
    if os.path.exists(effect_path):
        if platform.system() == "Windows":
            subprocess.run(["start", "", effect_path], shell=True)
        elif platform.system() == "Darwin":
            # afplay ships with macOS, so it works regardless of PATH quirks
            # in whatever launched this process (e.g. VS Code's Python runner
            # not sourcing a login shell's Homebrew PATH additions).
            subprocess.run(["afplay", effect_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            try:
                subprocess.run(["mpg123", "-q", effect_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except FileNotFoundError:
                print(f"{Fore.YELLOW}Note: mpg123 not available. Audio effects disabled.{Style.RESET_ALL}")

# -------------------------------------
# Utility Functions
# -------------------------------------
from datetime import datetime, timedelta, timezone
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
            if has_trafilatura:
                extracted_text = trafilatura.extract(r.text, include_comments=False, include_tables=False)
            else:
                extracted_text = None
            if extracted_text and len(extracted_text.strip()) > 50:
                # Limit content size for faster processing
                return extracted_text[:1200] if len(extracted_text) > 1200 else extracted_text
            else:
                # Fallback to basic text extraction
                if BeautifulSoup is None:
                    return None
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
def stop_tts():
    """Interrupt the current TTS response without changing audio modes."""
    global stop_voice_flag, active_pyttsx3_engine, active_pyttsx3_thread, active_tts_process
    stop_voice_flag = True
    with tts_process_lock:
        tts_process = active_tts_process
        active_tts_process = None
    if tts_process is not None and tts_process.poll() is None:
        tts_process.terminate()
        try:
            tts_process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            tts_process.kill()
    with pyttsx3_lock:
        engine = active_pyttsx3_engine
        speech_thread = active_pyttsx3_thread
    if has_pyttsx3 and engine is not None:
        try:
            engine.stop()
        except Exception:
            pass
    if (
        has_pyttsx3
        and speech_thread is not None
        and speech_thread is not threading.current_thread()
        and speech_thread.is_alive()
    ):
        speech_thread.join(timeout=0.5)
    if speech_thread is not None and not speech_thread.is_alive():
        with pyttsx3_lock:
            if active_pyttsx3_thread is speech_thread:
                active_pyttsx3_thread = None


def stop_voice(disable_voice=True):
    stop_tts()
    if disable_voice:
        context.voice_mode = False
    if disable_voice:
        print(f"{Fore.RED}Voice stopped. Returning to text mode.{Style.RESET_ALL}")
        play_audio_effect("mic_off")
        if platform.system() == "Windows":
            os.system("taskkill /IM mpg123.exe /F")
        elif platform.system() == "Darwin":
            os.system("pkill -STOP afplay")
            time.sleep(0.5)
            os.system("pkill afplay")
        else:
            os.system("pkill -STOP mpg123")
            time.sleep(0.5)
            os.system("pkill mpg123")

def _is_tts_source_heading(text):
    return bool(re.fullmatch(
        r"\s*(?:#{1,6}\s*)?(?:\*\*)?(?:sources?|references?|citations?|bibliography)"
        r"(?:\*\*)?\s*:?(?:\*\*)?\s*", text, re.IGNORECASE,
    ))


def _clean_tts_text(text):
    # Keep evidence in the transcript, but speak only the answer.
    lines = []
    for line in text.splitlines():
        if _is_tts_source_heading(line):
            break
        lines.append(line)
    text = '\n'.join(lines)
    text = re.sub(r'```.*?(?:```|$)', '', text, flags=re.DOTALL)
    text = re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)', r'\1', text)
    text = re.sub(r'\[(?:\d+(?:\s*[,;–-]\s*\d+)*|source\s+\d+|citation[^\]]*)\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[*_`~#>\[\]\(\)\|]', '', text)
    text = re.sub(r'[\r\n]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _init_pyttsx3_engine():
    engine = pyttsx3.init()
    try:
        rate = engine.getProperty("rate")
        engine.setProperty("rate", max(120, int(rate * 0.95)))
    except Exception:
        pass
    return engine


def _speak_with_pyttsx3(text):
    global active_pyttsx3_engine, active_pyttsx3_thread
    # pyttsx3 shares a driver loop between engine instances.  Locking only
    # around assignment of ``active_pyttsx3_engine`` still allowed concurrent
    # runAndWait calls, which raises "run loop already started".
    with pyttsx3_speech_lock:
        engine = _init_pyttsx3_engine()
        with pyttsx3_lock:
            active_pyttsx3_engine = engine
            active_pyttsx3_thread = threading.current_thread()
        try:
            engine.say(text)
            engine.runAndWait()
        finally:
            try:
                engine.stop()
            except Exception:
                pass
            with pyttsx3_lock:
                if active_pyttsx3_engine is engine:
                    active_pyttsx3_engine = None
                if active_pyttsx3_thread is threading.current_thread():
                    active_pyttsx3_thread = None


def _speak_with_macos_say(text):
    """Use macOS's native speech process, which can be stopped safely."""
    global active_tts_process
    process = subprocess.Popen(["say", "-r", "190", text])
    with tts_process_lock:
        active_tts_process = process
    try:
        process.wait()
    finally:
        with tts_process_lock:
            if active_tts_process is process:
                active_tts_process = None


def _speak_with_system_tts(text):
    if platform.system() == "Darwin":
        _speak_with_macos_say(text)
    else:
        _speak_with_pyttsx3(text)


def is_speaking():
    """Return True while a TTS utterance is actively playing (for UI sync)."""
    with tts_process_lock:
        process = active_tts_process
    if process is not None and process.poll() is None:
        return True
    with pyttsx3_lock:
        return active_pyttsx3_engine is not None


def start_tts_in_background(text):
    """Start text-mode speech without blocking the next terminal prompt."""
    global stop_voice_flag, active_pyttsx3_thread
    if not has_tts_backend() or not context.tts_mode:
        return
    clean_text = _clean_tts_text(text)
    if not clean_text:
        return

    stop_tts()
    stop_voice_flag = False
    speech_thread = threading.Thread(
        target=_speak_with_system_tts,
        args=(clean_text,),
        daemon=True,
        name="gnosis-tts",
    )
    with pyttsx3_lock:
        active_pyttsx3_thread = speech_thread
    speech_thread.start()


async def speak_text(text):
    global stop_voice_flag, active_pyttsx3_engine, active_pyttsx3_thread
    if not has_tts_backend():
        print(f"{Fore.YELLOW}Text-to-speech is unavailable because no supported TTS backend is installed.{Style.RESET_ALL}")
        return
    if not (context.voice_mode or context.tts_mode):
        return
    stop_voice_flag = False
    if active_pyttsx3_engine is not None:
        with pyttsx3_lock:
            try:
                active_pyttsx3_engine.stop()
            except Exception:
                pass
            active_pyttsx3_engine = None
    if active_pyttsx3_thread is not None and active_pyttsx3_thread.is_alive():
        active_pyttsx3_thread.join(timeout=0.5)
        if active_pyttsx3_thread.is_alive():
            active_pyttsx3_thread = None
    clean_text = _clean_tts_text(text)
    if not clean_text:
        return
    try:
        await asyncio.to_thread(_speak_with_system_tts, clean_text)
        return
    except Exception as e:
        if stop_voice_flag:
            # User intentionally interrupted speech; keep TTS enabled.
            return
        error_text = str(e).lower()
        if "run loop already started" in error_text or "loop already started" in error_text:
            # Recoverable pyttsx3 state issue: reset engine and retry once.
            with pyttsx3_lock:
                active_pyttsx3_engine = None
            try:
                await asyncio.to_thread(_speak_with_system_tts, clean_text)
                return
            except Exception as e2:
                print(f"{Fore.RED}pyttsx3 error after retry: {e2}{Style.RESET_ALL}")
                return
        print(f"{Fore.RED}pyttsx3 error: {e}{Style.RESET_ALL}")
        context.tts_mode = False
        return

# -------------------------------------
# Streaming Response Function
# -------------------------------------
def stream_response():
    if ollama is None and not cloud_models.is_cloud(_selected_model()):
        print(f"{Fore.RED}Ollama client is unavailable. Cannot generate response.{Style.RESET_ALL}")
        return ""
    # Ensure conversation is within allowed context window
    trim_conversation()
    print(f"{Fore.CYAN}Generating response...\n{Style.RESET_ALL}")
    complete_response = ""
    chosen_model = _selected_model()
    response_stream = model_chat(model=chosen_model, messages=context.assistant_convo, stream=True,
                                 **thinking_options(chosen_model, context.reasoning_mode or context.deep_think_mode))
    with _TypeaheadCapture() as capture:
        for chunk in response_stream:
            text_chunk = chunk["message"]["content"]
            complete_response += text_chunk
            print(f"{Fore.GREEN}{text_chunk}{Style.RESET_ALL}", end="", flush=True)
            capture.poll()
    _stash_typeahead(capture.buffer)
    print()
    if context.tts_mode and not context.voice_mode:
        start_tts_in_background(complete_response)
    elif context.voice_mode:
        asyncio.run(speak_text(complete_response))
    context.assistant_convo.append({"role": "assistant", "content": complete_response})
    return complete_response


def _selected_model():
    """Return the model selected by the current shared application modes."""
    if context.selected_model:
        return context.selected_model
    if context.unfiltered_mode:
        return MODELS["unfiltered"]
    if context.reasoning_mode:
        return MODELS["search"]
    if context.coding_mode:
        return MODELS["coding"]
    return MODELS["main"]


def chat_response(prompt, on_chunk=None, on_status=None, on_sources=None):
    """Process one chat message for any interface.

    This is the programmatic counterpart to the terminal loop: it owns
    conversation state, context enrichment, mode selection, streaming, and
    agent-memory updates.  ``on_chunk`` receives text as it arrives, making
    it suitable for GUI clients without giving them access to Ollama directly.
    ``on_status`` (optional) receives short human-readable progress strings
    ("Searching the web...", "Verifying facts...") between the user's
    message and the reply - see _emit_status. It's set on the shared
    context for the duration of this call so deeply nested functions
    (search_web, model_directed_web_research, ...) can reach it without
    threading a callback through every signature; cleared afterward so it
    never leaks into an unrelated call. ``on_sources`` (optional) receives
    the raw evidence list whenever web search or Deep Think actually ran -
    an empty list means research was attempted and found nothing, which a
    caller should show distinctly from "no research happened this turn"
    (this function never calls it at all in that case).
    """
    if ollama is None and not cloud_models.is_cloud(_selected_model()):
        raise ModelUnavailableError("Ollama client is unavailable. Please install and configure ollama.")

    prompt = (prompt or "").strip()
    if not prompt:
        return ""

    previous_status_callback = context.status_callback
    context.status_callback = on_status
    try:
        return _chat_response_impl(prompt, on_chunk, on_sources)
    finally:
        context.status_callback = previous_status_callback


def _chat_response_impl(prompt, on_chunk, on_sources=None):
    stop_tts()
    processed_prompt = process_search_tags(prompt)
    research_prompt = _research_prompt_for_followup(processed_prompt)

    # A real cron mutation is reported verbatim, code-generated, with no LLM
    # call for this turn at all - see run_scheduler_agent_step's docstring
    # for why free-form narration of a real system action isn't trusted.
    scheduler_reply = run_scheduler_agent_step(processed_prompt)
    if scheduler_reply is not None:
        context.assistant_convo.append({"role": "user", "content": processed_prompt})
        context.assistant_convo.append({"role": "assistant", "content": scheduler_reply})
        if on_chunk:
            on_chunk(scheduler_reply)
        return scheduler_reply

    # Remove only context explicitly tagged as belonging to an earlier turn.
    context.assistant_convo = [m for m in context.assistant_convo if not m.get('_turn_context')]
    direct = is_direct_chat(processed_prompt) and not context.deep_think_mode
    research_used = context.deep_think_mode or (context.web_search_mode and not direct)
    search_results = []
    if research_used:
        update_user_notes_softly(research_prompt, [])
        search_results = model_directed_web_research(research_prompt)
        if on_sources:
            on_sources(search_results)
        context.assistant_convo.append({
            "role": "system",
            "content": enhance_conversation_with_search(research_prompt, search_results, deep=context.deep_think_mode),
            "_turn_context": True,
        })
    else:
        context_info = [get_datetime_context()]
        user_context = get_relevant_user_context(research_prompt)
        if user_context != "No user profile information available":
            context_info.append(f"User context: {user_context}")
        context.assistant_convo.append({"role": "system", "_turn_context": True, "content": f"[Context: {' | '.join(context_info)}]"})
        if not direct and not requires_current_web_verification(research_prompt):
            _emit_status("Searching saved knowledge...")
            search_results = _knowledge_search_evidence(research_prompt, search_knowledge_base(research_prompt))
            if search_results:
                context.assistant_convo.append({
                    "role": "system", "_turn_context": True,
                    "content": "Saved knowledge is unverified background, not live evidence. Use only passages that answer this request.\n" + enhance_conversation_with_search(research_prompt, search_results),
                })
                if on_sources:
                    on_sources(search_results)

    if not direct:
        _emit_status("Checking whether a local capability would help...")
    tool_action = {"tool": None} if direct else _select_tool_action(research_prompt)
    if tool_action.get("tool"):
        _emit_status(f"Using {tool_action['tool']}...")
        tool_summary = _execute_tool_action(tool_action)
        if tool_summary:
            print(f"{Fore.CYAN}🛠️  Model selected tool: {tool_action['tool']}{Style.RESET_ALL}")
            context.assistant_convo.append({
                "role": "system",
                "content": f"Additional context from a Gnosis capability you chose to use:\n{tool_summary}",
                "_turn_context": True,
            })

    persona_prompt = get_persona_system_prompt()
    if persona_prompt:
        context.assistant_convo.append({"role": "system", "_turn_context": True, "content": persona_prompt})

    if context.voice_mode:
        context.assistant_convo.append({
            "role": "system", "_turn_context": True,
            "content": "This is a live voice conversation. Respond naturally, with concise spoken sentences. Avoid tables, code, and long lists unless the user asks for them. Preserve your active persona and answer the user's actual question.",
        })
    memory_key = context.current_agent or "default"
    memory_context = get_relevant_agent_memory(memory_key, processed_prompt)
    if memory_context:
        context.assistant_convo.append({"role": "system", "_turn_context": True, "content": memory_context})

    turn_focus = (
        "Answer the latest user message below and stay on its immediate topic. "
        "Use earlier turns only to resolve references such as 'that' or 'again'. "
        "Ignore unrelated topics, stale memory, and evidence that does not directly answer it. "
        f"The current topic is: {research_prompt}"
    )
    for message in reversed(context.assistant_convo):
        if message.get("role") == "system" and message.get("_turn_context"):
            message["content"] += f"\n{turn_focus}"
            break
    context.assistant_convo.append({"role": "user", "content": processed_prompt})

    trim_conversation()

    _emit_status("Writing a response...")
    complete_response = ""
    chosen_model = _selected_model()
    thinking_reported = False
    response_stream = model_chat(model=chosen_model, messages=context.assistant_convo, stream=True,
                                 **thinking_options(chosen_model, context.reasoning_mode or context.deep_think_mode))
    try:
        for chunk in response_stream:
            message = chunk.get("message", {})
            if message.get("thinking") and not thinking_reported:
                _emit_status("Thinking...")
                thinking_reported = True
            text_chunk = message.get("content", "")
            if not text_chunk:
                continue
            if on_chunk and not research_used:
                on_chunk(text_chunk)
            complete_response += text_chunk
    except ChatCancelled:
        if complete_response:
            context.assistant_convo.append({"role": "assistant", "content": complete_response, "interrupted": True})
        raise
    finally:
        close = getattr(response_stream, "close", None)
        if close:
            close()

    if research_used and complete_response.strip():
        complete_response = review_draft_topic(processed_prompt, complete_response, search_results)
        if on_chunk:
            on_chunk(complete_response)

    # Stored as the model's own drafted answer, with nothing appended after
    # it - see fact_check_answer's call site below for why.
    context.assistant_convo.append({"role": "assistant", "content": complete_response})
    if search_results:
        # Rides along as an extra dict key - confirmed harmless to pass back
        # into ollama.chat later (it's simply ignored), and it means sources
        # persist through save_conversation/load_conversation for free, with
        # no separate index-keyed structure to keep in sync with trimming.
        context.assistant_convo[-1]["sources"] = search_results

    if research_used and complete_response.strip():
        # The fact-check result used to be appended onto the displayed
        # answer. Two problems with that: it read like a research report
        # bolted onto a normal reply, and (worse) a small local model shown
        # its own past "---\n**Fact-check**\n[Tag] ..." text as prior
        # assistant turns started imitating that format unprompted in later
        # drafted answers (observed live - by the third exchange in a
        # research session, the model's own "answer" text started including
        # a self-generated, hallucinated "**Fact-check**" or "**Correction**"
        # section of its own). It's now persisted as historical/audit data
        # via save_fact_check_record instead of shown to the user at all.
        _emit_status("Verifying facts...")
        fact_check = fact_check_answer(complete_response, search_results, user_prompt=processed_prompt)
        if fact_check:
            save_fact_check_record(processed_prompt, complete_response, fact_check, search_results)

    try:
        from core.autonomous_research import observe_turn
        observe_turn(core_config.project_root(), processed_prompt, complete_response,
                     evidence=search_results, checked=not direct)
    except (OSError, ValueError):
        pass  # Queue persistence must not interrupt a completed chat response.
    analyze_conversation_patterns(processed_prompt, complete_response)
    if complete_response:
        events.publish(
            TASK_COMPLETED, agent_name=context.current_agent or "default",
            user_input=processed_prompt, response=complete_response,
        )
    if context.voice_mode and on_chunk is None:
        asyncio.run(speak_text(complete_response))
    elif context.tts_mode and not context.voice_mode:
        start_tts_in_background(complete_response)
    return complete_response

# -------------------------------------
# Speech Recognition Function
# -------------------------------------
def recognize_speech():
    global stop_voice_flag
    if not has_speech_recognition:
        print(f"{Fore.RED}Speech recognition is unavailable because SpeechRecognition is not installed.{Style.RESET_ALL}")
        return None
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
                context.voice_mode = False
                print(f"{Fore.RED}Voice OFF.{Style.RESET_ALL}")
                return None
            if "web search stop" in speech_text:
                context.web_search_mode = False
                print(f"{Fore.YELLOW}Web search OFF.{Style.RESET_ALL}")
                return ""
            return speech_text
        except:
            return ""

# -------------------------------------
# Model & Web Search Functions
# -------------------------------------
def pull_model():
    pull_all_models()

def search_searx(query):
    """Search using a SearxNG instance."""
    searx_url = os.environ.get("SEARXNG_URL", "https://search.lozdev.com")
    search_endpoint = f"{searx_url.rstrip('/')}/search"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36'
    }
    params = {
        'q': query,
        'format': 'json',
        'language': 'en',
        'pageno': 1
    }
    try:
        resp = requests.get(search_endpoint, params=params, timeout=12, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        extracted_data = []
        for result in data.get('results', [])[:5]:
            url = result.get('url')
            title = result.get('title') or result.get('content') or query
            content = result.get('content') or result.get('excerpt') or ''
            if url and content:
                extracted_data.append({
                    'title': title, 'url': url, 'content': content,
                    'publishedDate': result.get('publishedDate') or result.get('date'),
                })
            elif url:
                page_content = tool_registry.execute("web.fetch", url=url)
                if page_content:
                    if len(page_content) > 2000:
                        page_content = page_content[:2000] + '...'
                    extracted_data.append({
                        'title': title, 'url': url, 'content': page_content,
                        'publishedDate': result.get('publishedDate') or result.get('date'),
                    })
        return extracted_data
    except Exception as e:
        print(f"{Fore.YELLOW}SearxNG search failed: {e}{Style.RESET_ALL}")
        return []


def search_web(query):
    """Web search with intelligent fallback to SearxNG or offline context."""
    print(f"{Fore.CYAN}🧠 Performing web search for: {query}{Style.RESET_ALL}")
    _emit_status(f"Searching the web: {query}")
    results = search_searx(query)
    live_result_count = len(results or [])
    if results:
        results = [dict(result, search_provider="searxng") for result in results]
    else:
        print(f"{Fore.YELLOW}ℹ️ Web search sources unavailable or returned no results. Using offline fallback.{Style.RESET_ALL}")
        results = search_fallback(query)
    events.publish(SEARCH_COMPLETED, query=query, result_count=len(results),
                   live_result_count=live_result_count)
    return results


# Research is intentionally model-directed: web mode does not automatically run a
# fixed set of searches. The planner chooses whether to search, what to search for
# next, and when the available evidence is sufficient. SearxNG is user-operated,
# so there is no artificial query cap; repeated queries terminate the loop.
# "Repeated" also means near-identical, not just an exact match - a planner stuck
# on an unresolved ambiguity (e.g. "the reluctant messenger book") tends to
# rephrase rather than repeat verbatim ("reluctant messenger book title"), which
# an exact case-fold check alone would never catch. See _is_near_duplicate_query.
MAX_RESEARCH_SEARCHES = None
NEAR_DUPLICATE_QUERY_OVERLAP_THRESHOLD = 0.7
MAX_CONSECUTIVE_NEAR_DUPLICATE_QUERIES = 2
# Deep Think is explicitly asked for exhaustive research, so it gets a floor
# (small local planner models otherwise say "answer" after one or two
# searches) and a ceiling (a runaway local model should not search forever).
DEEP_THINK_MIN_SEARCHES = 4
DEEP_THINK_MAX_SEARCHES = 10
DEEP_THINK_ANGLE_SUFFIXES = (
    "recent developments",
    "data and statistics",
    "expert or official analysis",
    "criticism and disagreement",
    "background and history",
)
AUTHORITATIVE_DOMAIN_SUFFIXES = (
    ".gov", ".edu", ".ac.uk", ".int", ".mil", ".nih.gov", ".who.int",
)
HIGH_REPUTATION_DOMAINS = {
    "reuters.com", "apnews.com", "nature.com", "science.org", "arxiv.org",
    "bbc.com", "nytimes.com", "wikipedia.org",
}
EVIDENCE_TAG_RULES = {
    "government_politics": ("senator", "senate", "congress", "election", "president", "governor", "government", "politic"),
    "sports": ("world cup", "fifa", "match", "football", "soccer", "score", "tournament"),
    "science_health": ("health", "medical", "medicine", "study", "research", "science", "disease"),
    "technology": ("software", "ai", "artificial intelligence", "cyber", "computer", "technology"),
    "business_finance": ("stock", "market", "price", "economy", "finance", "company", "ceo"),
    "law_policy": ("law", "court", "legal", "regulation", "policy", "legislation"),
}
TAG_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "is", "it", "of", "on", "or", "the", "to", "what", "who", "with",
    "current", "currently", "latest", "today", "official", "source", "update",
}


def _keyword_tags(text, limit=12):
    """Extract distinctive, stopword-filtered words from text, in order of appearance.

    Shared by web-evidence tagging and Historian's knowledge-base sorting, so
    both derive topics the same way instead of two divergent heuristics.
    """
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9'-]{2,}", (text or "").casefold())
    tags = []
    for word in words:
        if word not in TAG_STOP_WORDS and word not in tags:
            tags.append(word)
        if len(tags) == limit:
            break
    return tags


def requires_current_web_verification(prompt):
    """Return whether answering safely requires live, attributable evidence.

    This is a reliability floor for small local models that sometimes ignore the
    planner protocol. It intentionally does not make web mode search ordinary
    stable questions such as arithmetic or conceptual explanations.
    """
    text = prompt.casefold()
    current_markers = (
        "current", "currently", "latest", "recent", "today", "now", "news",
        "update", "who won", "election", "midterm", "senator", "senate member",
        "president", "governor", "mayor", "prime minister", "ceo", "score",
        "result", "price", "weather", "schedule", "standing", "2026",
    )
    correction_markers = (
        "double check", "verify", "fact check", "are you sure", "that's wrong",
        "that is wrong", "no ", "isn't", "is not", "incorrect", "wrong",
    )
    population_count = bool(
        re.search(r"\bpopulation\b", text)
        and re.search(r"\b(what|how|estimate|size|number|count|current|latest)\b", text)
    ) or bool(re.search(r"\bhow many (?:people|residents) (?:live|are|does|do)\b", text))
    return population_count or any(marker in text for marker in current_markers + correction_markers)


def _planner_history():
    """Give the planner enough context to recognize a correction without feeding it the full chat."""
    recent = []
    for message in context.assistant_convo[-6:]:
        if message.get("role") in {"user", "assistant"}:
            recent.append(f"{message['role']}: {message.get('content', '')[:350]}")
    return "\n".join(recent) or "(No prior conversation.)"


def _inspect_conversation():
    """Return bounded, derived conversation state without exposing prompts or memory."""
    turns = [
        message for message in context.assistant_convo
        if message.get("role") in {"user", "assistant"}
    ]
    user_turns = [message.get("content", "").strip() for message in turns if message.get("role") == "user"]
    latest = user_turns[-1] if user_turns else ""
    topic_prompt = latest
    if latest and re.sub(r"[.!?]+$", "", latest.casefold()) in _FOLLOWUP_RETRY_PHRASES and len(user_turns) > 1:
        topic_prompt = user_turns[-2]
    constraint_prompt = topic_prompt or latest
    requested_count = None
    count_match = re.search(r"\b(?:top|list of|give me)\s+(\d+)\b", constraint_prompt.casefold())
    if count_match:
        requested_count = int(count_match.group(1))
    formats = [
        name for name, marker in (
            ("list", "list"), ("table", "table"), ("code", "code"),
            ("steps", "step"), ("summary", "summar"),
        ) if marker in constraint_prompt.casefold()
    ]
    return {
        "user_turn_count": len(user_turns),
        "recent_user_turns": user_turns[-3:],
        "active_topic": topic_prompt[:500],
        "is_follow_up": bool(latest and topic_prompt.casefold() != latest.casefold()),
        "requested_count": requested_count,
        "requested_formats": formats,
        "has_assistant_reply": bool(turns and turns[-1].get("role") == "assistant"),
    }


def _knowledge_related(topic, limit=5):
    """Return bounded provenance-rich knowledge matches for a topic."""
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 5
    matches = search_knowledge_base(topic)[:limit]
    return [
        {
            "path": filename,
            "excerpt": str(passage)[:1200],
            "provenance": dict(getattr(passage, "metadata", {}) or {}),
        }
        for filename, passage in matches
    ]


def _knowledge_forget(path, confirm=False):
    """Archive a knowledge source before removing it, only after confirmation."""
    if not confirm:
        return {"removed": False, "requires_confirmation": True, "path": path}
    root = os.path.abspath(os.path.join(core_config.project_root(), "knowledge_base"))
    target = os.path.abspath(os.path.join(root, path))
    if not target.startswith(root + os.sep) or not os.path.isfile(target):
        return {"removed": False, "requires_confirmation": False, "path": path, "error": "source not found"}
    from core.knowledge_maintenance import preserve_source
    archive_path = preserve_source(target, core_config.project_root())
    os.unlink(target)
    return {"removed": True, "path": path, "archive_path": os.path.relpath(archive_path, core_config.project_root())}


def _inspect_repository():
    return {
        "basic_audit": audit_repository(),
        "advanced_audit": audit_repository_advanced(),
    }


def _model_status():
    from core import models
    return {
        "selected_model": _selected_model(),
        "available": models.is_available(),
        "context_window": MODEL_CONTEXT.get(_selected_model(), DEFAULT_CONTEXT),
        "modes": {
            "web_search": context.web_search_mode,
            "deep_think": context.deep_think_mode,
            "reasoning": context.reasoning_mode,
            "coding": context.coding_mode,
            "voice": context.voice_mode,
        },
        "recent_metrics": task_completion_stats(window=10),
    }


def _build_task_plan(goal, context=""):
    goal = (goal or "").strip()
    if not goal:
        return {"goal": "", "steps": [], "error": "goal is required"}
    planner = (
        "Create a bounded execution-neutral plan for the user's goal. Return ONLY valid JSON in this shape: "
        '{"goal": "...", "steps": [{"title": "...", "depends_on": [], "done": false}], "next_action": "..."}. '
        "Return at most 8 concrete steps. Do not claim anything was executed, do not persist tasks, and do not "
        "invent missing project facts. Keep the plan specific and concise.\n\n"
        f"Goal: {goal[:1200]}\nContext: {context[:1200]}"
    )
    if ollama is None:
        return {"goal": goal, "steps": [], "next_action": "Clarify the first concrete step.", "error": "model unavailable"}
    try:
        response = model_chat(model=MODELS['fast'], messages=[{"role": "system", "content": planner}])
        parsed = json.loads(response.get("message", {}).get("content", ""))
        if not isinstance(parsed, dict) or not isinstance(parsed.get("steps"), list):
            raise ValueError("planner returned an invalid plan")
        steps = [step for step in parsed["steps"][:8] if isinstance(step, dict) and isinstance(step.get("title"), str)]
        return {
            "goal": goal,
            "steps": [{"title": step["title"][:240], "depends_on": step.get("depends_on", []), "done": bool(step.get("done", False))} for step in steps],
            "next_action": str(parsed.get("next_action") or (steps[0]["title"] if steps else "Clarify the first concrete step."))[:240],
        }
    except (ValueError, TypeError, json.JSONDecodeError, AttributeError):
        return {"goal": goal, "steps": [], "next_action": "Clarify the first concrete step.", "error": "planner returned invalid JSON"}


_FOLLOWUP_RETRY_PHRASES = (
    "try again", "do it again", "answer again", "repeat that", "same question",
    "the same question", "retry", "redo that",
)


def _research_prompt_for_followup(prompt):
    """Anchor a vague retry to the preceding user request for research only."""
    normalized = re.sub(r"[.!?]+$", "", prompt.strip().casefold())
    if normalized not in _FOLLOWUP_RETRY_PHRASES:
        return prompt
    for message in reversed(context.assistant_convo):
        if message.get("role") != "user":
            continue
        previous = (message.get("content") or "").strip()
        if previous:
            return previous
    return prompt


_CORRECTION_MARKERS = ("double check", "verify", "wrong", "no ", "isn't", "is not")


def _resolve_correction_entity(prompt):
    """Ask the model to rewrite a correction ('no, it's the reluctant messenger')
    into one complete, correctly-spelled search query, using the recent
    conversation to fix a typo or expand a fragment - instead of the
    deterministic fallback below searching the user's raw text verbatim.
    Returns None if unavailable or the rewrite doesn't look like a real
    query, so the caller can fall back further.

    Tuning notes from testing this live against all three local models, in
    order of what actually happened:

    1. An earlier version gave the model an explicit "respond UNKNOWN if
       unsure" escape hatch, with detailed instructions to check the
       conversation before general knowledge. Every model reached for
       UNKNOWN far too readily - even trivial cases where the correct
       spelling was already sitting verbatim in the prior message came back
       UNKNOWN, and one model's visible reasoning showed it oscillating for
       dozens of steps before giving up. Replaced with a plain, low-ceremony
       "rewrite this" instruction and no bail-out option, which produces
       usable results far more often.
    2. That plain instruction has its own failure mode: it always returns
       *something*, including outright non-answers to prompts that were
       never really an entity lookup in the first place (e.g. "no, Sinema
       isn't my senator anymore" came back the single word "Yes"), and it
       sometimes wraps the real answer in a full first line of rambling
       (an example response, a restated instruction, markdown) with the
       actual query buried inside or the line trailing into unrelated
       continuation text. `_first_clean_line` below is what absorbs that:
       take the first line only, strip a leading label, discard anything
       that isn't short-and-plausible as an actual query.
    """
    if ollama is None:
        return None
    resolver_prompt = (
        "Rewrite the text below as a short, correctly-spelled, complete web search query. "
        "Use the conversation to fix any typo, fill in an omitted subject, or expand a partial "
        "name/title into its full form. Respond with ONLY the rewritten query text on a single "
        "line - no labels, no explanation, no quotation marks, no markdown.\n\n"
        f"Conversation:\n{_planner_history()}\n\nText to rewrite: {prompt}"
    )
    try:
        response = model_chat(model=MODELS['fast'], messages=[{"role": "system", "content": resolver_prompt}])
        raw = (response.get("message", {}).get("content") or "")
        return _first_clean_line(raw)
    except Exception:
        return None


def _first_clean_line(raw):
    """Extract a usable one-line query from a local model's free-form reply,
    or return None if nothing in it looks like one. See
    _resolve_correction_entity's tuning notes for why this exists: these
    models don't reliably stop at one clean line, so this only trusts the
    first line, and only if it's short enough to plausibly be a query
    rather than a paragraph, example, or restated instruction.
    """
    for line in raw.splitlines():
        line = line.strip().strip('"')
        # Drop a leading label like "Query:" / "Rewritten query:" / "A:".
        line = re.sub(r"^[A-Za-z][A-Za-z '-]{0,30}:\s*", "", line)
        # Drop a stray chat-template token some local models trail instead
        # of stopping cleanly (e.g. "...wood<|/im_start|>").
        line = re.sub(r"<\|.*", "", line).strip()
        if not line:
            continue
        word_count = len(line.split())
        # Too short to be a real query (e.g. "Yes"); too long to be a
        # single search query rather than a sentence/paragraph/example.
        if 3 <= word_count <= 20:
            return line
        return None  # first non-empty line exists but isn't query-shaped
    return None


def _fallback_research_query(prompt, evidence):
    """Use the user's wording if a model fails to emit a usable planner action."""
    query = prompt.strip().strip("@")
    # Corrections such as "no, Sinema isn't my senator" or "no, it's called
    # the reluctant messenger" usually omit or garble the actual subject.
    # Try a dedicated entity-resolution pass first; only fall further back to
    # reusing the last substantive, time-sensitive user question (a much
    # cruder heuristic - it can only ever recover the *previous* topic, not
    # the corrected one) if that resolution isn't available.
    if any(marker in query.casefold() for marker in _CORRECTION_MARKERS):
        resolved = _resolve_correction_entity(prompt)
        if resolved:
            query = resolved
        else:
            for message in reversed(context.assistant_convo[:-1]):
                if message.get("role") != "user":
                    continue
                candidate = message.get("content", "").strip()
                if candidate and requires_current_web_verification(candidate) and not any(
                    marker in candidate.casefold() for marker in _CORRECTION_MARKERS
                ):
                    query = candidate
                    break
    if evidence:
        query += " official source"
    return query


def _parse_result_date(value):
    """Return an ISO timestamp when a search provider exposes a publication date."""
    if not value:
        return None
    text = str(value).strip()
    for candidate in (text, text[:10]):
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).isoformat()
        except ValueError:
            pass
    year_match = re.search(r"\b(19|20)\d{2}\b", text)
    return f"{year_match.group(0)}-01-01T00:00:00+00:00" if year_match else None


def score_web_evidence(result, query):
    """Score a single result's source quality and freshness in isolation.

    This only looks at one result; it can't yet know whether other sources
    corroborate it. apply_corroboration() runs afterward, once the rest of the
    evidence pool is known, and blends that into truthfulness_confidence.
    """
    url = result.get("url", "")
    hostname = (urlparse(url).hostname or "").lower()
    content = result.get("content", "")
    score = 35
    if url.startswith("https://"):
        score += 5
    if hostname.endswith(AUTHORITATIVE_DOMAIN_SUFFIXES):
        score += 35
    elif hostname in HIGH_REPUTATION_DOMAINS or any(hostname.endswith("." + d) for d in HIGH_REPUTATION_DOMAINS):
        score += 25
    elif hostname:
        score += 10
    if len(content) >= 500:
        score += 10
    if result.get("search_provider") == "searxng":
        score += 5
    source_quality = max(0, min(100, score))

    published_at = _parse_result_date(result.get("publishedDate") or result.get("date"))
    recency = 35  # Unknown dates must not masquerade as fresh information.
    if published_at:
        try:
            published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            age_days = max(0, (datetime.now(timezone.utc) - published.astimezone(timezone.utc)).days)
            recency = 100 if age_days <= 7 else 85 if age_days <= 31 else 65 if age_days <= 365 else 40
        except (TypeError, ValueError):
            pass
    return {
        # A source-based placeholder until apply_corroboration() sees the full
        # evidence pool and folds in cross-source agreement.
        "truthfulness_confidence": source_quality,
        "source_quality_confidence": source_quality,
        "recency_confidence": recency,
        "published_at": published_at,
        "scoring_note": "Heuristic source-quality, freshness, and cross-source corroboration; not a verification of every claim.",
        "query": query,
    }


_ENTITY_PHRASE_RE = re.compile(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3}\b")
_DISTINCTIVE_NUMBER_RE = re.compile(r"\b\d[\d,]{1,}(?:\.\d+)?%?\b")


def _extract_fact_tokens(content):
    """Pull coarse, comparable factual tokens (numbers, proper-noun phrases) from text.

    A stand-in for real claim/entity extraction: it lets two sources be compared
    for whether they name the same specific facts, without an NLP pipeline.
    """
    if not content:
        return set()
    text = content[:2000]
    tokens = set()
    for match in _DISTINCTIVE_NUMBER_RE.finditer(text):
        if len(re.sub(r"[^\d]", "", match.group(0))) >= 3:
            tokens.add(match.group(0).strip())
    for match in _ENTITY_PHRASE_RE.finditer(text):
        tokens.add(match.group(0).casefold())
    return tokens


# Evidence sources whose truthfulness_confidence is fixed by construction
# (a direct read from a live, authoritative API) rather than derived from
# corroboration math meant for scraped web pages - see apply_corroboration.
_AUTHORITATIVE_EVIDENCE_PROVIDERS = {"open-meteo", "yahoo-finance", "espn"}


def apply_corroboration(evidence):
    """Blend cross-source agreement into truthfulness_confidence.

    Domain reputation (source_quality_confidence) says a source is likely
    reliable; independent domains reporting the same specific facts says the
    claim itself is more likely true. This is the claim-level signal the
    scoring_note in score_web_evidence flagged as a future stage - it mutates
    each evidence item in place and returns the same list.

    Same-entity check: each item's own search query's fact tokens are
    excluded before comparing. Otherwise two results that are only about a
    *different* book/person that happens to share a title/name with the
    query would "corroborate" each other purely by both mentioning the
    query subject's own name - which every result for that query will do
    regardless of what it actually says, so it carries zero real signal
    that the sources agree on anything. Genuine corroboration still needs
    an *additional* shared fact (an author, a date, a number) beyond the
    query subject itself.
    """
    fact_sets = [
        _extract_fact_tokens(item.get("content", "")) - _extract_fact_tokens(item.get("query", ""))
        for item in evidence
    ]
    hostnames = [
        "" if item.get("search_provider") == "knowledge-base" or
        (item.get("provenance") or {}).get("origin") == "saved-conversation"
        else (urlparse(item.get("url", "")).hostname or "").lower()
        for item in evidence
    ]
    for i, item in enumerate(evidence):
        corroborating = set()
        if fact_sets[i] and hostnames[i]:
            for j, other_tokens in enumerate(fact_sets):
                if j == i or not hostnames[j] or hostnames[j] == hostnames[i]:
                    continue
                if fact_sets[i] & other_tokens:
                    corroborating.add(hostnames[j])
        corroboration_confidence = min(100, 40 + 30 * len(corroborating))
        item["corroboration_confidence"] = corroboration_confidence
        item["corroborating_domains"] = sorted(corroborating)
        if item.get("search_provider") == "knowledge-base" or item.get("search_provider") in _AUTHORITATIVE_EVIDENCE_PROVIDERS:
            # A live API reading's confidence is fixed by design (see
            # _weather_evidence_item/_stock_evidence_item/_soccer_evidence_item),
            # not corroboration-derived - a real, live-reported bug: recomputing
            # it here diluted a correct live soccer result's fixed 90 down to
            # ~60 (0.4*90 + 0.6*40, zero shared fact-tokens with unrelated
            # generic web snippets) once combined with other evidence,
            # letting noisy, unrelated search results outrank a correct
            # answer and produce a confidently wrong final reply.
            continue
        source_quality = item.get("source_quality_confidence", item.get("truthfulness_confidence", 35))
        item["truthfulness_confidence"] = round(0.4 * source_quality + 0.6 * corroboration_confidence)
    return evidence


def persist_evidence_updates(evidence):
    """Write refreshed corroboration/truthfulness scores back to saved evidence files."""
    evidence_dir = os.path.join(core_config.project_root(), "knowledge_base", "web_evidence")
    for item in evidence:
        evidence_id = item.get("id")
        if not evidence_id:
            continue
        item["metadata"] = categorize_web_evidence(item, item.get("query", ""), {
            "truthfulness_confidence": item["truthfulness_confidence"],
            "recency_confidence": item.get("recency_confidence", 35),
        })
        try:
            with open(os.path.join(evidence_dir, f"{evidence_id}.json"), "w", encoding="utf-8") as handle:
                json.dump(item, handle, ensure_ascii=False, indent=2)
        except OSError:
            pass


def categorize_web_evidence(result, query, scores=None):
    """Create explicit, deterministic tags for sorting and Historian workflows."""
    url = result.get("url", "")
    hostname = (urlparse(url).hostname or "").lower()
    corpus = " ".join((query, result.get("title", ""), result.get("content", "")[:1200])).casefold()
    def contains_term(term):
        return re.search(rf"\b{re.escape(term)}\b", corpus) is not None

    categories = [category for category, terms in EVIDENCE_TAG_RULES.items() if any(contains_term(term) for term in terms)]
    if not categories:
        categories = ["general_reference"]

    if hostname.endswith((".gov", ".mil", ".int")):
        source_type = "official"
    elif hostname.endswith((".edu", ".ac.uk")) or hostname in {"arxiv.org", "nature.com", "science.org"}:
        source_type = "academic_research"
    elif hostname in {"reuters.com", "apnews.com", "bbc.com", "nytimes.com"} or any(hostname.endswith("." + domain) for domain in {"reuters.com", "apnews.com", "bbc.com", "nytimes.com"}):
        source_type = "journalism"
    elif hostname.endswith("wikipedia.org"):
        source_type = "reference"
    else:
        source_type = "web_publisher"

    keyword_tags = _keyword_tags(f"{query} {result.get('title', '')}")
    scores = scores or score_web_evidence(result, query)
    time_sensitive = any(category in categories for category in ("government_politics", "sports", "business_finance"))
    return {
        "schema_version": 1,
        "topic_categories": categories,
        "keyword_tags": keyword_tags,
        "source_type": source_type,
        "verification_status": "unverified_source_quality_scored",
        "sanitization_status": "pending_historian_review",
        "revalidation_priority": "high" if time_sensitive else "normal",
        "sort_key": f"{source_type}:{'-'.join(categories)}",
        "quality_band": "high" if scores["truthfulness_confidence"] >= 75 else "medium" if scores["truthfulness_confidence"] >= 55 else "low",
        "freshness_band": "fresh" if scores["recency_confidence"] >= 85 else "aging" if scores["recency_confidence"] >= 65 else "unknown_or_stale",
    }


def save_web_evidence(query, results):
    """Persist raw web evidence plus machine-readable provenance and ranking metadata."""
    evidence_dir = os.path.join(core_config.project_root(), "knowledge_base", "web_evidence")
    os.makedirs(evidence_dir, exist_ok=True)
    saved = []
    captured_at = datetime.now(timezone.utc).isoformat()
    for result in results:
        if is_fallback_result(result) or not result.get("url"):
            continue
        metadata = score_web_evidence(result, query)
        evidence_id = hashlib.sha256(f"{result['url']}|{captured_at}".encode("utf-8")).hexdigest()[:16]
        record = {
            "id": evidence_id,
            "query": query,
            "captured_at": captured_at,
            "title": result.get("title", "Untitled"),
            "url": result["url"],
            "search_provider": result.get("search_provider", "unknown"),
            "content": result.get("content", ""),
            **metadata,
            "metadata": categorize_web_evidence(result, query, metadata),
        }
        try:
            with open(os.path.join(evidence_dir, f"{evidence_id}.json"), "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, indent=2)
            saved.append(record)
        except OSError as error:
            print(f"{Fore.YELLOW}Could not save web evidence: {error}{Style.RESET_ALL}")
    return saved


def save_fact_check_record(user_prompt, answer_text, fact_check_text, evidence):
    """Persist a fact-check result to disk as historical/audit data instead
    of showing it to the user - it used to be appended directly onto the
    displayed answer, which read like a research report rather than a
    normal reply and (per chat_response's docstring) taught the model to
    imitate that formatting in its own later answers. Mirrors
    save_web_evidence's on-disk shape. Returns the saved record, or None if
    there was nothing to save or the write failed.
    """
    if not fact_check_text:
        return None
    fact_check_dir = os.path.join(core_config.project_root(), "knowledge_base", "fact_checks")
    os.makedirs(fact_check_dir, exist_ok=True)
    captured_at = datetime.now(timezone.utc).isoformat()
    record_id = hashlib.sha256(f"{user_prompt}|{captured_at}".encode("utf-8")).hexdigest()[:16]
    record = {
        "id": record_id,
        "query": user_prompt,
        "captured_at": captured_at,
        "answer_text": answer_text,
        "fact_check": fact_check_text,
        "evidence_urls": [item.get("url") for item in (evidence or []) if item.get("url")],
    }
    try:
        with open(os.path.join(fact_check_dir, f"{record_id}.json"), "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
    except OSError as error:
        print(f"{Fore.YELLOW}Could not save fact-check record: {error}{Style.RESET_ALL}")
        return None
    return record


def _emit_status(message):
    """Forward a short, human-readable status update to whichever caller
    registered one via context.status_callback for the current turn (the
    GUI wires this to a status label so the user sees what's happening
    between sending a message and getting a reply). A no-op when nothing is
    listening - e.g. the CLI path, which already prints its own status
    lines straight to the terminal.
    """
    callback = context.status_callback
    if callback:
        try:
            callback(message)
        except ChatCancelled:
            raise
        except Exception:
            pass


def backfill_web_evidence_metadata():
    """Add current taxonomy metadata to legacy evidence records without replacing their evidence."""
    evidence_dir = os.path.join(core_config.project_root(), "knowledge_base", "web_evidence")
    if not os.path.isdir(evidence_dir):
        return 0
    updated = 0
    for filename in os.listdir(evidence_dir):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(evidence_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                record = json.load(handle)
            scores = {
                "truthfulness_confidence": record.get("truthfulness_confidence", 0),
                "recency_confidence": record.get("recency_confidence", 35),
            }
            record["metadata"] = categorize_web_evidence(record, record.get("query", ""), scores)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, indent=2)
            updated += 1
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    return updated


def _research_action(prompt, evidence, searches_used):
    """Ask the model for exactly one research action, using a small JSON protocol."""
    if ollama is None:
        return {"action": "answer"}
    evidence_text = "\n".join(
        f"[{i + 1}] {item['title']} | confidence={item['truthfulness_confidence']} "
        f"(corroborated by {len(item.get('corroborating_domains', []))} other domain(s)) "
        f"freshness={item['recency_confidence']} | {item['url']}\n{item['content'][:500]}"
        for i, item in enumerate(evidence[-8:])
    ) or "(No web evidence collected yet.)"
    planner = (
        "You are a web-research planner. Decide the next single action needed to answer the user's request. "
        "Use web search only when it would materially improve factual accuracy, freshness, or specificity. "
        "A saved knowledge-base note matching a broad topic is not necessarily evidence for the requested fact. "
        "Search again if the collected evidence does not actually answer the latest request; do not treat "
        "a prior conversation's subject as the subject of a new, explicitly named question. "
        "Return ONLY valid JSON: {\"action\": \"search\", \"query\": \"specific query\", \"reason\": \"...\"} "
        "or {\"action\": \"answer\", \"reason\": \"...\"}. Do not search merely because web mode is enabled. "
        "For current officeholders, election or sports results, prices, schedules, news, or a user correction, "
        "you MUST search before answering.\n"
        "If the user's request is correcting a name, title, or spelling from earlier in the conversation, "
        "do not just search their raw correction text verbatim - it may be a fragment or contain a typo. "
        "First resolve it, using the recent conversation and your own knowledge, to the most complete and "
        "correctly-spelled form of the specific person/book/entity you believe they mean, and write the "
        "query for *that* resolved form (e.g. full title plus author, or full name plus a disambiguating "
        "detail) so the search lands on the right entity instead of a similarly-named but different one.\n"
        + ("Deep Think is enabled: investigate multiple angles and seek corroborating or conflicting sources before answering.\n" if context.deep_think_mode else "")
        + f"Searches already used: {searches_used}; no hard limit. Stop when the evidence is sufficient.\n\n"
        f"Recent conversation (may contain unverified claims):\n{_planner_history()}\n\n"
        f"User request: {prompt}\n\nEvidence:\n{evidence_text}"
    )
    def _chat_fn(messages):
        response = model_chat(model=MODELS['fast'], messages=messages)
        return response.get("message", {}).get("content", "")

    action = agent_dialogue.call_agent_json(_chat_fn, planner)
    if isinstance(action, dict):
        if action.get("action") == "search" and isinstance(action.get("query"), str) and action["query"].strip():
            return action
        if action.get("action") == "answer":
            # Honor a genuine, validly-parsed "answer" decision here. The
            # fallback below is for a missing/malformed response, not for a
            # planner that legitimately thinks it has enough evidence -
            # conflating the two meant Deep Think could never stop on its own
            # judgment and instead always fell through to a deterministic
            # fallback query, which then collided with the duplicate-query
            # guard and cut research short after just one or two searches.
            return action
    if context.deep_think_mode or requires_current_web_verification(prompt):
        return {
            "action": "search",
            "query": _fallback_research_query(prompt, evidence),
            "reason": "Required live verification after an invalid planner response.",
        }
    return {"action": "answer", "reason": "The planner did not request a valid additional search."}


# The research-capable tools (web.search, web.fetch, knowledge.search, and
# the live.* lookups) are deliberately excluded from open model selection
# below - they go through _select_tool_actions instead (wired into
# model_directed_web_research), which combines multiple free sources and
# feeds the result through evidence scoring/fact-checking. Offering them
# here too would just be a second, uncoordinated path to the same
# capabilities with none of that pipeline behind it.
_TOOL_ACTION_EXCLUDED_NAMES = {"web.search", "web.fetch", "knowledge.search", "live.weather", "live.stock_quote", "live.soccer_result"}


def _available_tool_actions():
    """SAFE-permission tools eligible for open model selection during an
    ordinary chat turn. Scoped to Permission.SAFE (read-only capabilities;
    see tools/base.py's Permission enum) - this is the first place that
    field is actually enforced rather than just documented, deliberately:
    nothing that mutates state (filesystem writes, cron add/edit/remove,
    sandbox sessions, running shell/tests) should be reachable by a model
    freely deciding what to do on an ordinary chat turn. Those stay
    command-only, as today.
    """
    return [
        tool for tool in tool_registry.list()
        if tool.permission == Permission.SAFE and tool.name not in _TOOL_ACTION_EXCLUDED_NAMES
    ]


def _tool_action_catalog_text(catalog):
    lines = []
    for tool in catalog:
        params = ", ".join(tool.parameters.keys()) or "no arguments"
        lines.append(f"- {tool.name}: {tool.description} (arguments: {params})")
    return "\n".join(lines)


def _select_tool_action(prompt):
    """Ask the model whether one of Gnosis's own SAFE, read-only
    capabilities (repo audit, git status/diff, the crontab listing, the
    knowledge base) would materially help answer this message - using the
    same model-agnostic JSON protocol _research_action already uses for web
    search, not Ollama's native tools= mechanism. Confirmed live before
    building this: yi:6b (this app's model for Unfiltered mode) doesn't
    support tools= at all (Ollama raises "does not support tools"), and even
    a model that accepts the parameter isn't guaranteed to use it correctly
    (qwen2.5-coder:7b took the schema but wrote its tool call out as plain
    JSON text instead of a real structured tool_calls response). A plain
    JSON decision that ordinary code parses works uniformly across every
    local model this app runs, regardless of which one a given mode
    selects.

    Returns {"tool": name, "arguments": {...}} or {"tool": None}. Never
    raises - any missing/unparseable/invalid response is treated as "no
    tool needed," the same fail-safe default as an ordinary reply.

    Deliberately skipped entirely (not just discouraged by the prompt) for
    anything the weather/stock/soccer live-lookup bypasses already own -
    live-tested this before shipping it: telling the model in-prompt "this
    is separate from web search, don't pick anything here for a web-search-
    shaped question" was not reliable enough on yi:6b, which sometimes
    routed a plain "what's the weather today?" to knowledge.search anyway
    despite that instruction. A deterministic code-level skip removes the
    collision entirely instead of hoping a weak model's judgment holds -
    the same lesson _flag_unverified_dollar_figures already learned about
    this model tier.

    Deliberately NOT also gated on requires_current_web_verification: that
    check's word list ("now", "today", "current", ...) is broad by design
    for its own purpose and would wrongly suppress a legitimate local-tool
    question just for containing one of those common words (e.g. "is the
    repo dirty right now?" - a real git.status case, caught by testing
    this live before shipping it).
    """
    if ollama is None:
        return {"tool": None}
    if (
        _looks_like_weather_query(prompt) or _looks_like_stock_query(prompt) or _looks_like_soccer_query(prompt)
        or _looks_like_soccer_standings_query(prompt)
    ):
        return {"tool": None}
    catalog = _available_tool_actions()
    if not catalog:
        return {"tool": None}
    planner = (
        "You are Gnosis. Most user messages need NO special capability - a plain conversational answer is "
        "correct almost every time. Only pick one of the capabilities below in the rare case it would "
        "clearly and specifically help.\n\n"
        "Do NOT pick a capability for: general knowledge questions, casual conversation, jokes, opinions, "
        "or math - those are handled elsewhere, never here.\n\n"
        "ONLY consider a capability when the user is specifically asking about: this codebase/repository's "
        "own files, tests, or code quality; this codebase's git status or uncommitted changes; a task they "
        "scheduled with Gnosis; their current subscriptions (teams/topics/websites/weather they follow); or "
        "something Gnosis may have researched and saved for them before.\n\n"
        f"Capabilities:\n{_tool_action_catalog_text(catalog)}\n\n"
        "Return ONLY valid JSON: {\"tool\": \"<name>\", \"arguments\": {...}, \"reason\": \"one short "
        "sentence on why (or why not)\"} to use one of them, or {\"tool\": null, \"reason\": \"...\"} for "
        "everything else (the default). The reason is logged for later review, not shown to the user - "
        "always include a real one.\n\n"
        f"User message: {prompt}"
    )

    def _chat_fn(messages):
        response = model_chat(model=MODELS['fast'], messages=messages)
        return response.get("message", {}).get("content", "")

    decision = agent_dialogue.call_agent_json(_chat_fn, planner)
    if not isinstance(decision, dict):
        events.publish(TOOL_SELECTION_MADE, prompt=prompt, selected=[], reason="unparseable model response")
        return {"tool": None}
    reason = decision.get("reason") if isinstance(decision.get("reason"), str) else None
    name = decision.get("tool")
    selected_tool = next((tool for tool in catalog if tool.name == name), None)
    if not isinstance(name, str) or selected_tool is None:
        events.publish(TOOL_SELECTION_MADE, prompt=prompt, selected=[], reason=reason)
        return {"tool": None}
    arguments = decision.get("arguments")
    arguments = arguments if isinstance(arguments, dict) else {}
    # A real, reported failure: the model supplied an extra argument the
    # tool doesn't accept at all (e.g. a "location" left over from a
    # different tool it used the turn before) - tool_registry.execute
    # raised a TypeError for the unexpected keyword (caught, so it failed
    # safe, but wasted the turn and fell through to a worse fallback path).
    # Dropping anything outside the tool's declared parameters is a hard,
    # deterministic check code can do perfectly, the same reasoning as the
    # missing-argument check below.
    arguments = {key: value for key, value in arguments.items() if key in selected_tool.parameters}
    # A real, reported failure: the model picked knowledge.search but left
    # "arguments" empty, missing the required "topic" - the call reached
    # tool_registry.execute and raised a TypeError there (caught, so it
    # failed safe, but wasted the turn). Rejecting a call missing a
    # required argument here is a hard, deterministic check code can do
    # perfectly - better than attempting a call already known to fail.
    missing = [param for param in selected_tool.parameters if param not in arguments]
    if missing:
        print(f"{Fore.YELLOW}ℹ️ Model selected '{name}' but didn't supply required argument(s) "
              f"{missing} - treating as no tool selected.{Style.RESET_ALL}")
        events.publish(
            TOOL_SELECTION_MADE, prompt=prompt, selected=[],
            reason=f"{reason or 'no reason given'} (rejected: missing argument(s) {missing})",
        )
        return {"tool": None}
    events.publish(TOOL_SELECTION_MADE, prompt=prompt, selected=[name], reason=reason)
    return {"tool": name, "arguments": arguments}


def _cron_entry_schedule(entry):
    """The 5 cron schedule fields from a parsed crontab entry - a
    cron_list_entries() entry has no separate 'schedule' key, only the full
    shell command_line the schedule is prefixed onto. Extracted so the
    model is given the entry's real time instead of inventing one - a real,
    live-observed gap: the first cut of this summary omitted the schedule
    entirely, and the model filled in specific, plausible-sounding but
    fabricated times ("at 08:00 AM") for tasks whose actual schedule was
    never in its context at all."""
    fields = (entry.get("command_line") or "").split(None, 5)
    return " ".join(fields[:5]) if len(fields) >= 5 else "unknown"


def _summarize_tool_result(name, result):
    """Turn one of the SAFE tools' raw return values into a short, readable
    text blurb for injecting into the model's context. Each tool has its
    own return shape (a pre-formatted string, a list of tuples, a
    (list, error) pair, a (returncode, stdout, stderr) triple) - a small
    per-tool dispatch instead of one generic str(result), which would leak
    Python repr/tuple syntax straight into what the model reads.
    """
    if name in {"repo.audit", "repo.audit_advanced"}:
        return str(result)[:1500]
    if name == "knowledge.search":
        if not result:
            return "No matching entries found in the knowledge base."
        return "\n".join(f"- {filename}: {content[:200].strip()}" for filename, content in result[:5])
    if name == "subscriptions.list":
        if not result:
            return "No subscriptions yet."
        return "\n".join(f"- [{record['type'].capitalize()}] {record['name']}" for record in result)
    if name == "cron.list":
        entries, error = result
        if error:
            return error
        if not entries:
            return "No scheduled tasks."
        return "\n".join(
            f"#{i + 1} {entry.get('description') or '(no description)'} "
            f"(schedule: {_cron_entry_schedule(entry)})"
            for i, entry in enumerate(entries)
        )
    if name in {"git.status", "git.diff"}:
        returncode, stdout, stderr = result
        if returncode != 0:
            return f"git command failed: {(stderr or '').strip()[:500]}"
        return stdout.strip()[:1500] or "(clean - no output)"
    return str(result)[:1500]


def _confirm_cron_schedule_with_user(entries):
    """Ask the user to confirm (or correct) their schedule instead of
    trusting a small local model's plain-English translation of raw cron
    syntax - live-tested and found unreliable before this existed: a real
    "0 2 * * *" (every day at 2 AM) got narrated back as "the 1st, 3rd, 5th
    of each month... at 2 AM." Rather than trying to make that translation
    perfect, this shows the user the real cron expression for each task
    (untranslated, so there's nothing to get wrong) and lets them say it's
    right or state the correct time in their own words - the same blocking
    clarify-question mechanism _research_action's planner already uses.

    Returns the user's free-text answer, or None if there was nothing to
    ask or they gave an empty reply.
    """
    if not entries:
        return None
    lines = [
        f"- {entry.get('description') or '(no description)'}: {_cron_entry_schedule(entry)}"
        for entry in entries
    ]
    question = (
        "Here is your current scheduled-task list, in raw cron syntax (minute hour day-of-month month "
        "day-of-week):\n" + "\n".join(lines) +
        "\n\nIs this correct? If any of these should run at a different time, tell me which one and the "
        "correct time - otherwise just confirm it looks right."
    )
    answers = agent_dialogue.ask_user_question([{"question": question, "options": None}])
    return (answers.get(question) or "").strip() or None


def _execute_tool_action(action):
    """Run a _select_tool_action decision and return a short evidence-style
    summary of the result, or None if no tool was selected or it failed.
    Failures are swallowed, not raised - a bad tool choice or a runtime
    error (e.g. a malformed regex the model supplied as knowledge.search's
    topic) should never break the chat turn, just mean no extra context
    gets added this time.

    cron.list gets one extra step: see _confirm_cron_schedule_with_user for
    why its result isn't just handed straight to the answering model like
    every other tool's.
    """
    name = action.get("tool")
    if not name:
        return None
    try:
        result = tool_registry.execute(name, **action.get("arguments", {}))
    except Exception as error:
        print(f"{Fore.YELLOW}ℹ️ Tool '{name}' selected by the model failed: {error}{Style.RESET_ALL}")
        events.publish(
            TOOL_EXECUTION_COMPLETED, tool=name, arguments=action.get("arguments", {}),
            success=False, error=str(error),
        )
        return None
    events.publish(TOOL_EXECUTION_COMPLETED, tool=name, arguments=action.get("arguments", {}), success=True, error=None)
    summary = f"[{name}] {_summarize_tool_result(name, result)}"
    if name == "cron.list":
        # The real schedule data above must stay in the summary, not be
        # replaced by the confirmation - a real, live-tested regression:
        # returning only "the user said it's correct" left the answering
        # model with no actual task data at all, and it hallucinated a
        # completely fictional task list to answer with anyway.
        entries, error = result
        if not error and entries:
            confirmation = _confirm_cron_schedule_with_user(entries)
            if confirmation:
                summary += f"\nThe user reviewed this schedule and said: {confirmation}"
    return summary


def _deep_think_research_plan(prompt):
    """Ask the model for several distinct research angles up front.

    A single small local model asked to search-or-answer one step at a time
    tends to settle for "answer" after one or two queries. Planning several
    non-overlapping angles before the adaptive loop starts guarantees breadth
    instead of leaving it to that model's turn-by-turn judgment.
    """
    if ollama is None:
        return []
    planner = (
        "Plan thorough web research on the user's request. Produce 4 to 5 distinct, "
        "non-overlapping search queries that together cover different angles: "
        "background or definition, the most recent developments, data or statistics, "
        "expert or official analysis, and any notable controversy or disagreement. "
        "Skip an angle if it plainly does not apply to the request. "
        "Return ONLY a JSON array of query strings, e.g. [\"query one\", \"query two\"].\n\n"
        f"User request: {prompt}"
    )
    try:
        response = model_chat(model=MODELS['fast'], messages=[{"role": "system", "content": planner}])
        content = response.get("message", {}).get("content", "")
        match = re.search(r"\[.*\]", content, re.DOTALL)
        queries = json.loads(match.group(0) if match else content)
        if isinstance(queries, list):
            return [q.strip() for q in queries if isinstance(q, str) and q.strip()][:5]
    except (ValueError, TypeError, json.JSONDecodeError, AttributeError):
        pass
    return []


def _query_words(query):
    return {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 3}


def _search_text_matches_prompt(prompt, search_text):
    """Return whether a generated search stays connected to the user request."""
    return candidate_matches_request(prompt, search_text)


def _is_near_duplicate_query(query, previous_queries):
    """True if `query` shares enough significant (>3 character) words with
    any already-tried query to count as a rephrasing rather than a genuinely
    new angle - Jaccard word overlap over
    NEAR_DUPLICATE_QUERY_OVERLAP_THRESHOLD. Catches a planner stuck
    rephrasing the same unresolved reference ("the reluctant messenger
    book" -> "reluctant messenger book title") that an exact case-fold
    match alone would miss - see TODO.md Phase 6."""
    words = _query_words(query)
    if not words:
        return False
    for previous in previous_queries:
        other_words = _query_words(previous)
        if not other_words:
            continue
        overlap = len(words & other_words) / len(words | other_words)
        if overlap >= NEAR_DUPLICATE_QUERY_OVERLAP_THRESHOLD:
            return True
    return False


def _deep_think_forced_query(prompt, index):
    """Build a fresh, angle-distinct query to keep Deep Think below its search floor.

    Reusing the same fallback query text would hit the repeated-query guard
    and end the loop early, so each forced continuation targets a different
    angle instead.
    """
    base = _fallback_research_query(prompt, evidence=[])
    angle = DEEP_THINK_ANGLE_SUFFIXES[index % len(DEEP_THINK_ANGLE_SUFFIXES)]
    return f"{base} {angle}"


WEATHER_QUERY_KEYWORDS = (
    "weather", "temperature", "forecast", "how hot", "how cold", "how warm",
    "is it raining", "is it snowing", "wind chill",
)

_WMO_WEATHER_DESCRIPTIONS = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    56: "light freezing drizzle", 57: "dense freezing drizzle",
    61: "light rain", 63: "moderate rain", 65: "heavy rain",
    66: "light freezing rain", 67: "heavy freezing rain",
    71: "light snow", 73: "moderate snow", 75: "heavy snow", 77: "snow grains",
    80: "light rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    85: "light snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with light hail", 99: "thunderstorm with heavy hail",
}

_WEATHER_QUERY_LEAD_PHRASES = (
    "what's the weather like in", "what's the weather in", "what is the weather like in",
    "what is the weather in", "how's the weather in", "how is the weather in",
    "is it raining in", "is it snowing in", "how hot is it in", "how cold is it in", "how warm is it in",
    "weather in", "weather for", "weather at", "temperature in", "forecast for", "forecast in",
)


def _looks_like_weather_query(prompt):
    lowered = prompt.lower()
    return any(keyword in lowered for keyword in WEATHER_QUERY_KEYWORDS)


_WEATHER_QUERY_TRAILING_FILLER = re.compile(
    r"\s*(right now|outside|at the moment|currently|today|now)\s*[?.!]*$", re.IGNORECASE
)


def _weather_location_query(prompt):
    """Best-effort location text for the geocoder - strip common
    weather-question phrasing (leading and trailing), keep the rest
    verbatim. Open-Meteo's geocoder already tolerates extra words
    reasonably well, so this only needs to avoid obviously wrong input,
    not parse perfectly.

    Found live while testing this fix: leaving a trailing "right now" in
    place ("Camdenton, MO right now") made the geocoder return zero
    matches, silently falling back to the exact noisy search path this was
    built to avoid - a real bug in the fix itself, not a hypothetical."""
    lowered = prompt.lower()
    location = prompt.strip(" ?.!")
    for phrase in _WEATHER_QUERY_LEAD_PHRASES:
        if phrase in lowered:
            location = prompt[lowered.index(phrase) + len(phrase):].strip(" ?.!")
            break
    return _WEATHER_QUERY_TRAILING_FILLER.sub("", location).strip(" ?.!,")


def fetch_current_weather(location_query):
    """A single, unambiguous live reading from Open-Meteo (free, keyless
    geocoding + forecast APIs).

    Built because generic web search snippets for weather sites
    (AccuWeather etc.) are hourly-forecast tables with several different
    temperatures for different hours and no explicit "current"/"now" label
    - a model synthesizing an answer from one of those snippets has no
    principled way to tell which number is actually current. That is the
    root cause of a real, reported bug ("weather is a total hit or miss,
    wrong temp"): which of several plausible-looking numbers
    `summarize_text`'s 3-sentence window happened to keep depends on
    sentence-splitting luck, not on which one is right. Confirmed live
    against a real SearxNG search for "weather in Camdenton, MO" before
    writing this - the top AccuWeather snippet was
    "1 PM 82°. rain drop 49% · 2 PM 83°. rain drop 20% · 3 PM 84°." with no
    indication of which hour was "now."

    Returns None on any failure (network, no geocoding match, unexpected
    response shape) so callers can fall back to ordinary web search -
    wttr.in was tried first and rejected because it was returning
    "weather data source not available" (a live, real failure, not a
    hypothetical) when this was written; Open-Meteo's own geocoding +
    forecast APIs need no key and were verified live to work.
    """
    try:
        geocode = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location_query, "count": 1}, timeout=8,
        )
        geocode.raise_for_status()
        matches = geocode.json().get("results") or []
        if not matches:
            return None
        place = matches[0]

        forecast = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"], "longitude": place["longitude"],
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "timezone": "auto",
            }, timeout=8,
        )
        forecast.raise_for_status()
        current = forecast.json()["current"]

        place_name = ", ".join(
            part for part in (place.get("name"), place.get("admin1"), place.get("country")) if part
        )
        return {
            "place": place_name,
            "temp_f": current["temperature_2m"],
            "feels_like_f": current["apparent_temperature"],
            "humidity": current["relative_humidity_2m"],
            "wind_mph": current["wind_speed_10m"],
            "description": _WMO_WEATHER_DESCRIPTIONS.get(current["weather_code"], "unknown conditions"),
            "observed_at": current["time"],
        }
    except (requests.RequestException, KeyError, IndexError, ValueError, TypeError):
        return None


def _weather_evidence_item(prompt, location=None):
    """A real-time, single-source evidence item for the specific case a
    noisy generic web search snippet cannot reliably answer: what the
    current temperature/conditions actually are right now. Deliberately
    not persisted through save_web_evidence/knowledge_base/web_evidence -
    that store is for stable, citable web content, and a live sensor-style
    reading is stale within the hour; polluting it would misinform anyone
    (e.g. Historian) who later reads that file expecting durable evidence.
    Returns None if this isn't a weather query or the live lookup fails,
    so the caller falls back to ordinary research unchanged.

    `location`, when given, skips regex detection/extraction entirely and
    looks up that location directly - used by the live.weather tool, whose
    argument comes from the model (with full conversation context), not
    from parsing the raw prompt text. See _select_tool_actions's docstring
    for why: regex phrasing coverage for "what's the weather" turned into
    an unwinnable game of whack-a-mole, the same lesson learned the hard
    way for stock and soccer queries before this existed.
    """
    if location is None:
        if not _looks_like_weather_query(prompt):
            return None
        location = _weather_location_query(prompt)
    weather = fetch_current_weather(location)
    if not weather:
        return None
    content = (
        f"Live current conditions for {weather['place']}, observed at {weather['observed_at']} "
        f"(local time) - a single real-time reading, not a multi-hour forecast table: "
        f"{weather['temp_f']}°F, feels like {weather['feels_like_f']}°F, "
        f"{weather['description']}, humidity {weather['humidity']}%, wind {weather['wind_mph']} mph."
    )
    return {
        "id": hashlib.sha256(f"open-meteo|{weather['place']}|{weather['observed_at']}".encode("utf-8")).hexdigest()[:16],
        "query": prompt,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "title": f"Live weather - {weather['place']}",
        "url": "https://open-meteo.com/",
        "search_provider": "open-meteo",
        "content": content,
        "truthfulness_confidence": 90,
        "recency_confidence": 100,
        "corroborating_domains": [],
    }


STOCK_QUERY_KEYWORDS = (
    "stock price", "share price", "stock quote", "share quote", "stock trading at",
    "shares trading at", "stock worth", "shares worth", "stock currently at",
    "price of", "price for",
)

_STOCK_TICKER_PATTERN = re.compile(r"\(([A-Z]{1,5}(?:\.[A-Z])?)\)|\$([A-Z]{1,5})\b")

_STOCK_QUERY_LEAD_PHRASES = (
    "what's the current stock price of", "whats the current stock price of", "what is the current stock price of",
    "what's the stock price of", "whats the stock price of", "what is the stock price of",
    "what's the current share price of", "whats the current share price of", "what is the current share price of",
    "what's the current price for", "whats the current price for", "what is the current price for",
    "what's the current price of", "whats the current price of", "what is the current price of",
    "what's the price for", "whats the price for", "what is the price for",
    "what's the price of", "whats the price of", "what is the price of",
    "current stock price of", "current share price of", "current price for", "current price of",
    "stock price of", "share price of", "price of", "price for",
    "how much is",
)

_STOCK_QUERY_TRAILING_FILLER = re.compile(
    r"(?:\s*(?:stock price|share price|stock quote|share quote|stock trading at|shares trading at|"
    r"trading at|stock|shares|share|price|quote|worth|on nasdaq|on nyse|on amex|right now|today|currently|now))+"
    r"[?.!,]*$",
    re.IGNORECASE,
)

# _STOCK_QUERY_LEAD_PHRASES only covers the "[question words] + price-phrase
# + of/for + SUBJECT" shape ("what is the stock price of MSFT"). The equally
# common "[question words] + SUBJECT + price-phrase" shape ("what is MSFT
# stock price?") has no "of"/"for" for those phrases to match on, so the
# leading question words were never stripped and the resolved "subject" came
# out as "what is MSFT" - a real, reported bug. This is stripped first,
# unconditionally, so both shapes reduce to the same remaining text before
# the lead-phrase/trailing-filler logic below runs.
_STOCK_QUERY_GENERIC_PREAMBLE = re.compile(
    r"^(?:what'?s|what is|whats|how much is|tell me|please tell me)\s+(?:the\s+)?(?:current\s+)?",
    re.IGNORECASE,
)


def _looks_like_stock_query(prompt):
    return (
        any(keyword in prompt.lower() for keyword in STOCK_QUERY_KEYWORDS)
        or bool(_STOCK_TICKER_PATTERN.search(prompt))
    )


def _stock_query_subject(prompt):
    """Best-effort ticker or company name for a stock-price question - an
    explicit ticker (parenthesized like "(MSFT)" or cashtagged like "$MSFT")
    wins outright and skips name resolution entirely. Otherwise strips a
    generic leading question preamble, then common lead/trailing price
    phrasing, the same approach _weather_location_query uses, and leaves the
    rest for _resolve_stock_symbol to look up by name.
    """
    match = _STOCK_TICKER_PATTERN.search(prompt)
    if match:
        return (match.group(1) or match.group(2)).upper(), True
    working = _STOCK_QUERY_GENERIC_PREAMBLE.sub("", prompt.strip(" ?.!"), count=1).strip(" ?.!")
    lowered = working.lower()
    subject = working
    for phrase in _STOCK_QUERY_LEAD_PHRASES:
        if phrase in lowered:
            subject = working[lowered.index(phrase) + len(phrase):].strip(" ?.!")
            break
    subject = _STOCK_QUERY_TRAILING_FILLER.sub("", subject).strip(" ?.!,")
    return subject, False


_YAHOO_FINANCE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36"
}
# Yahoo's unofficial, keyless endpoints occasionally return an empty result
# for a query that succeeds moments later - confirmed live while testing this
# fix: a search for "MSFT" (an exact, valid ticker) came back with zero
# quotes once, then succeeded on the next four consecutive attempts with no
# code change at all. There's no distinguishing HTTP status for this - it's
# a 200 with an empty list - so one short retry absorbs that flakiness
# instead of falling all the way back to the noisy generic-search path over
# a transient hiccup.
_YAHOO_FINANCE_RETRY_ATTEMPTS = 2
_YAHOO_FINANCE_RETRY_DELAY_SECONDS = 0.6


def _resolve_stock_symbol(company_name):
    """Look up a ticker symbol by company name via Yahoo Finance's keyless
    search endpoint. Returns (symbol, display_name) or None. Unlike
    Open-Meteo's geocoder there's no dedicated free name->symbol API in
    wide use, but this endpoint is the same one yfinance and similar
    libraries rely on and was verified live while writing this fix.
    """
    last_error, last_count = None, 0
    for attempt in range(_YAHOO_FINANCE_RETRY_ATTEMPTS):
        try:
            resp = requests.get(
                "https://query1.finance.yahoo.com/v1/finance/search",
                params={"q": company_name, "quotesCount": 5, "newsCount": 0},
                headers=_YAHOO_FINANCE_HEADERS, timeout=8,
            )
            resp.raise_for_status()
            quotes = resp.json().get("quotes", [])
            for quote in quotes:
                if quote.get("quoteType") in {"EQUITY", "ETF"} and quote.get("symbol"):
                    return quote["symbol"], quote.get("shortname") or quote.get("longname") or quote["symbol"]
            last_error, last_count = None, len(quotes)
        except (requests.RequestException, ValueError, KeyError) as error:
            last_error = error
        if attempt + 1 < _YAHOO_FINANCE_RETRY_ATTEMPTS:
            time.sleep(_YAHOO_FINANCE_RETRY_DELAY_SECONDS)
    if last_error is not None:
        print(f"{Fore.YELLOW}ℹ️ Yahoo Finance symbol search for '{company_name}' failed: {last_error}. "
              f"Falling back to generic search.{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}ℹ️ Yahoo Finance symbol search for '{company_name}' returned no equity/ETF match "
              f"(got {last_count} result(s)). Falling back to generic search.{Style.RESET_ALL}")
    return None


def _fetch_stock_quote(symbol):
    """A single, unambiguous live quote from Yahoo Finance's keyless chart
    endpoint - built for the same reason fetch_current_weather bypasses
    generic search: Yahoo/Google/stockanalysis stock pages render their
    price client-side with JS, so a plain scrape of those pages only ever
    reaches the static meta description ("Get real-time stock quotes...")
    with no number in it at all. Confirmed live: every evidence item saved
    for a real "current stock price of Microsoft" search had zero digits
    in its content, and the model filled the gap by inventing a number and
    citing a source that never stated it.

    Stooq's CSV endpoint was tried first and rejected - it now gates
    requests behind a JS proof-of-work challenge, so a plain scrape gets a
    "verify your browser" stub instead of data.

    Returns None on any failure so the caller falls back to ordinary
    search.
    """
    last_error, had_no_price = None, False
    for attempt in range(_YAHOO_FINANCE_RETRY_ATTEMPTS):
        try:
            resp = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                params={"interval": "1d", "range": "1d"},
                headers=_YAHOO_FINANCE_HEADERS, timeout=8,
            )
            resp.raise_for_status()
            meta = resp.json()["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice")
            if price is None:
                last_error, had_no_price = None, True
            else:
                return {
                    "symbol": meta.get("symbol", symbol),
                    "name": meta.get("longName") or meta.get("shortName") or meta.get("symbol", symbol),
                    "price": price,
                    "currency": meta.get("currency", ""),
                    "previous_close": meta.get("chartPreviousClose"),
                    "day_high": meta.get("regularMarketDayHigh"),
                    "day_low": meta.get("regularMarketDayLow"),
                    "exchange": meta.get("fullExchangeName", meta.get("exchangeName", "")),
                    "observed_at": datetime.fromtimestamp(meta["regularMarketTime"], tz=timezone.utc).isoformat()
                    if meta.get("regularMarketTime") else None,
                }
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, OSError) as error:
            last_error = error
        if attempt + 1 < _YAHOO_FINANCE_RETRY_ATTEMPTS:
            time.sleep(_YAHOO_FINANCE_RETRY_DELAY_SECONDS)
    if last_error is not None:
        print(f"{Fore.YELLOW}ℹ️ Yahoo Finance chart lookup for '{symbol}' failed: {last_error}. "
              f"Falling back to generic search.{Style.RESET_ALL}")
    elif had_no_price:
        print(f"{Fore.YELLOW}ℹ️ Yahoo Finance chart lookup for '{symbol}' had no regularMarketPrice in the "
              f"response. Falling back to generic search.{Style.RESET_ALL}")
    return None


def _stock_evidence_item(prompt, subject=None):
    """A real-time, single-source evidence item for a stock-price question -
    the same fix as _weather_evidence_item for the same underlying problem.
    See _fetch_stock_quote's docstring for the live evidence that generic
    web search cannot answer this reliably. Returns None if this isn't a
    recognized stock query or the live lookup fails, so the caller falls
    back to ordinary research unchanged.

    `subject`, when given, skips regex detection/extraction entirely and
    resolves that company/ticker directly - see _weather_evidence_item's
    `location` parameter for why (same fix, same reason, live.stock_quote
    instead of live.weather).
    """
    is_ticker = False
    if subject is None:
        if not _looks_like_stock_query(prompt):
            return None
        subject, is_ticker = _stock_query_subject(prompt)
    if not subject:
        print(f"{Fore.YELLOW}ℹ️ '{prompt}' looked like a stock query but no company name/ticker could be "
              f"extracted from it. Falling back to generic search.{Style.RESET_ALL}")
        return None
    if is_ticker:
        symbol, display_name = subject, subject
    else:
        print(f"{Fore.CYAN}📈 Resolving ticker symbol for: {subject}{Style.RESET_ALL}")
        _emit_status(f"Looking up ticker symbol for {subject}...")
        resolved = _resolve_stock_symbol(subject)
        if not resolved:
            return None
        symbol, display_name = resolved
    quote = _fetch_stock_quote(symbol)
    if not quote:
        return None
    content = (
        f"Live quote for {display_name} ({quote['symbol']}) on {quote['exchange']}, "
        f"as of {quote['observed_at']}: {quote['price']} {quote['currency']} "
        f"(previous close {quote['previous_close']} {quote['currency']}, "
        f"day range {quote['day_low']}-{quote['day_high']} {quote['currency']})."
    )
    return {
        "id": hashlib.sha256(f"yahoo-finance|{quote['symbol']}|{quote['observed_at']}".encode("utf-8")).hexdigest()[:16],
        "query": prompt,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "title": f"Live stock quote - {quote['symbol']}",
        "url": f"https://finance.yahoo.com/quote/{quote['symbol']}",
        "search_provider": "yahoo-finance",
        "content": content,
        "truthfulness_confidence": 90,
        "recency_confidence": 100,
        "corroborating_domains": [],
    }


SOCCER_QUERY_KEYWORDS = (
    "final score", "match score", "game score", "score of", "result of",
    "premier league score", "champions league score", "europa league score",
    "premier league result",
)
_SOCCER_TRAILING_KEYWORDS = ("score", "result", "fixture", "fixtures")
_SOCCER_WIN_LOSE_PATTERN = re.compile(r"\bdid\s+(.+?)\s+(?:win|lose|draw|beat)\b", re.IGNORECASE)
_SOCCER_HOW_DID_PATTERN = re.compile(r"\bhow\s+did\s+(.+?)\s+(?:do|get on|get along|play|go)\b", re.IGNORECASE)
# Separate from _SOCCER_HOW_DID_PATTERN because "how was/is X's last match"
# doesn't have a "do/play/go" verb to anchor on - a real, reported miss:
# "how was man utd last match?" matched nothing, fell through with zero
# evidence at all, and got answered with a fully invented score and date.
#
# The leading "(?:the\s+)?(?:last\s+|next\s+|recent\s+)?" (before the
# capture group, in addition to the one after it) matters: English puts
# that modifier BEFORE the subject in "how was the last man united match"
# just as often as after it in "how was man united's last match". Without
# it, the lazy capture group swallowed "the last" as if it were part of
# the team name ("the last man united"), team resolution then found
# nothing for that garbled name, and the query fell through to zero
# evidence again - a second real, reported miss on the very fix meant to
# prevent this class of bug.
_SOCCER_HOW_WAS_PATTERN = re.compile(
    r"\bhow\s+(?:was|is|did)\s+(?:the\s+)?(?:last\s+|next\s+|recent\s+)?(.+?)(?:'s)?\s+"
    r"(?:last\s+|next\s+|recent\s+)?(?:match|game|fixture)\b",
    re.IGNORECASE,
)
_SOCCER_WHAT_HAPPENED_PATTERN = re.compile(
    r"\bwhat\s+happened\s+(?:in|to|with)\s+(?:the\s+)?(?:last\s+|recent\s+)?(.+?)(?:'s)?\s+"
    r"(?:last\s+|recent\s+)?(?:match|game|fixture)\b",
    re.IGNORECASE,
)
# "what was the last fixture for X?" (subject after "for/of") and "what was
# X's last fixture?" (subject before, possessive) - a real, reported miss:
# neither _SOCCER_HOW_WAS_PATTERN ("how was") nor _SOCCER_WHAT_HAPPENED_PATTERN
# ("what happened") covers "what was ... fixture", and the query fell
# through with zero evidence, producing a fully invented opponent, score,
# and even starting lineup.
_SOCCER_WHAT_FIXTURE_FOR_PATTERN = re.compile(
    r"\bwhat\s+(?:was|is|were|are)\s+(?:the\s+)?(?:last\s+|next\s+|recent\s+)?(?:fixture|match|game)s?\s+"
    r"(?:for|of)\s+(.+)",
    re.IGNORECASE,
)
# Same leading-modifier fix as _SOCCER_HOW_WAS_PATTERN above, for the same reason.
_SOCCER_WHAT_FIXTURE_POSSESSIVE_PATTERN = re.compile(
    r"\bwhat\s+(?:was|is|were|are)\s+(?:the\s+)?(?:last\s+|next\s+|recent\s+)?(.+?)(?:'s)?\s+"
    r"(?:last\s+|next\s+|recent\s+)?(?:fixture|match|game)\b",
    re.IGNORECASE,
)
# Covers both "when is/are/do/does X play/match" (future - next match) and
# "when was/were X's last match" (past - last match): a real, reported miss
# on "when was the last Manchester United Match?" - only present/future
# tense verbs were accepted, so a past-tense "when was" question matched
# nothing and fell through with zero evidence. Named _WHEN_ rather than
# _NEXT_MATCH_ now that it covers both tenses. Same leading-modifier fix as
# _SOCCER_HOW_WAS_PATTERN above and for the same reason ("the last
# Manchester United match" puts "last" before the subject).
_SOCCER_WHEN_SEARCH_PATTERN = re.compile(
    r"\bwhen\s+(?:do|does|is|are|was|were)\s+(?:the\s+)?(?:last\s+|next\s+|recent\s+)?.+?\s+"
    r"(?:last\s+|next\s+|recent\s+)?(?:play(?:ing)?|match|game|fixture)s?\b",
    re.IGNORECASE,
)
_SOCCER_WHEN_CAPTURE_PATTERN = re.compile(
    r"\bwhen\s+(?:do|does|is|are|was|were)\s+(?:the\s+)?(?:last\s+|next\s+|recent\s+)?(.+?)(?:'s)?\s+"
    r"(?:last\s+|next\s+|recent\s+)?(?:play(?:ing)?|match|game|fixture)s?\b",
    re.IGNORECASE,
)
# "who does/do/is/are X play(ing) next" - a real, live-observed miss: this
# phrasing (asking for the OPPONENT rather than a time) matched none of the
# "when ..." patterns above, so the query fell through to the model-driven
# selector with no free bypass, and the model both mis-parsed and then
# wrongly refused it as "outside scope" - fully hallucinating a fixture.
# Same leading-modifier fix as _SOCCER_HOW_WAS_PATTERN above and for the
# same reason.
_SOCCER_WHO_PLAY_PATTERN = re.compile(
    r"\bwho\s+(?:do|does|is|are)\s+(?:the\s+)?(?:last\s+|next\s+|recent\s+)?(.+?)(?:'s)?\s+"
    r"(?:last\s+|next\s+|recent\s+)?play(?:ing)?\b",
    re.IGNORECASE,
)
_SOCCER_SCORE_OF_PATTERN = re.compile(r"\b(?:score|result)\s+(?:of|for)\s+(?:the\s+)?(.+)", re.IGNORECASE)
_SOCCER_QUERY_TRAILING_FILLER = re.compile(
    r"(?:\s*(?:final score|match score|game score|next match|next game|last match|last game|"
    r"score|result|game|match|fixture|next|today|tonight|this week|right now))+"
    r"[?.!,]*$",
    re.IGNORECASE,
)
# UEFA club competitions checked alongside a team's own domestic league so a
# fixture in continental competition (Champions League, Europa League) is
# found even though the query resolved the team through its domestic league.
_SOCCER_UEFA_LEAGUE_SLUGS = ("uefa.champions", "uefa.europa")

# A table/standings question ("where do they stand in the league?",
# "premier league table") is a different information need from every
# pattern above - none of them are meant to match it, and none do today.
# Deliberately its own detector rather than folded into
# _looks_like_soccer_query: _fetch_soccer_team_matches only ever pulls a
# team's own schedule (last/next/live fixture) from ESPN, never table
# position, points, or record, so a standings question can never be
# answered by that data no matter how well the team name resolves. See
# _soccer_standings_evidence_item for what this is actually used for -
# stating that gap explicitly instead of leaving the question ungrounded.
_SOCCER_STANDINGS_KEYWORDS = ("standings", "league table", "table position", "league position")
_SOCCER_STAND_PATTERN = re.compile(
    r"\bstand(?:s|ing)?\s+in\s+the\s+(?:table|standings|\S+\s+league|league)\b", re.IGNORECASE,
)


def _looks_like_soccer_standings_query(prompt):
    lowered = prompt.lower()
    return any(keyword in lowered for keyword in _SOCCER_STANDINGS_KEYWORDS) or bool(_SOCCER_STAND_PATTERN.search(prompt))


def _looks_like_soccer_query(prompt):
    lowered = prompt.lower()
    return (
        any(keyword in lowered for keyword in SOCCER_QUERY_KEYWORDS)
        or any(lowered.rstrip("?.! ").endswith(keyword) for keyword in _SOCCER_TRAILING_KEYWORDS)
        or bool(_SOCCER_WIN_LOSE_PATTERN.search(prompt))
        or bool(_SOCCER_HOW_DID_PATTERN.search(prompt))
        or bool(_SOCCER_HOW_WAS_PATTERN.search(prompt))
        or bool(_SOCCER_WHAT_HAPPENED_PATTERN.search(prompt))
        or bool(_SOCCER_WHAT_FIXTURE_FOR_PATTERN.search(prompt))
        or bool(_SOCCER_WHAT_FIXTURE_POSSESSIVE_PATTERN.search(prompt))
        or bool(_SOCCER_WHEN_SEARCH_PATTERN.search(prompt))
        or bool(_SOCCER_WHO_PLAY_PATTERN.search(prompt))
    )


def _clean_soccer_subject(text):
    text = text.strip(" ?.!'")
    text = _SOCCER_QUERY_TRAILING_FILLER.sub("", text).strip(" ?.!,'")
    text = re.sub(r"'s$", "", text).strip()
    return text


def _soccer_query_subject(prompt):
    """Best-effort team name for a soccer-result question. Tries each
    sentence-shape pattern ("did X win", "how did X do", "when do X play",
    "score of X") in turn, then falls back to trailing-filler stripping on
    the whole prompt for the bare "X score"/"X result" shape - the same
    two-direction problem _stock_query_subject solves for "stock price of
    X" vs "X stock price", solved the same way here.
    """
    # Ordered most-specific-first: _SOCCER_WHAT_FIXTURE_POSSESSIVE_PATTERN is
    # deliberately last - it's the most permissive shape ("what was ... X
    # game/match/fixture") and would otherwise intercept sentences the more
    # specific patterns above it should handle first (a real regression
    # caught by testing this before shipping it: it grabbed "the score of
    # the Man United" whole instead of letting _SOCCER_SCORE_OF_PATTERN
    # handle "what was the score of the Man United game?").
    for pattern in (
        _SOCCER_WIN_LOSE_PATTERN, _SOCCER_HOW_DID_PATTERN, _SOCCER_HOW_WAS_PATTERN,
        _SOCCER_WHAT_HAPPENED_PATTERN, _SOCCER_WHAT_FIXTURE_FOR_PATTERN,
        _SOCCER_WHEN_CAPTURE_PATTERN, _SOCCER_WHO_PLAY_PATTERN, _SOCCER_SCORE_OF_PATTERN,
        _SOCCER_WHAT_FIXTURE_POSSESSIVE_PATTERN,
    ):
        match = pattern.search(prompt)
        if match:
            return _clean_soccer_subject(match.group(1))
    return _clean_soccer_subject(prompt)


def _resolve_soccer_team(team_name):
    """Look up an ESPN soccer team by name via ESPN's keyless site-search
    endpoint. Returns (team_id, display_name, league_slug) or None. The
    same shape as _resolve_stock_symbol: a free search endpoint stands in
    for a proper name->id lookup, filtered to soccer team results only.
    """
    try:
        resp = requests.get(
            "https://site.api.espn.com/apis/search/v2",
            params={"query": team_name, "limit": 10}, timeout=8,
        )
        resp.raise_for_status()
        for group in resp.json().get("results", []):
            if group.get("type") != "team":
                continue
            for item in group.get("contents", []):
                if item.get("sport") != "soccer" or item.get("type") != "team":
                    continue
                match = re.search(r"t:(\d+)", item.get("uid", ""))
                league_slug = item.get("defaultLeagueSlug")
                if match and league_slug:
                    return match.group(1), item.get("displayName", team_name), league_slug
        return None
    except (requests.RequestException, ValueError, KeyError):
        return None


def _soccer_score_display(competitor, state):
    """A competitor's score, or None for a not-yet-played ('pre') fixture -
    ESPN represents an unplayed match's score inconsistently (a real 0 or a
    scoreless dict, both meaningless before kickoff), so this only trusts a
    score once the match has actually started or finished."""
    if state not in {"in", "post"}:
        return None
    score = competitor.get("score")
    return score.get("displayValue") if isinstance(score, dict) else score


def _parse_soccer_event(event, default_competition):
    """One ESPN event dict (from either the schedule endpoint's `events`
    list or the team-summary endpoint's `nextEvent` list - same shape) into
    (state, match) - state is ESPN's "pre"/"in"/"post", match is the dict
    _fetch_soccer_team_matches assembles into evidence text. (None, None)
    if the event is missing a field this code depends on."""
    try:
        competition = event["competitions"][0]
        state = competition["status"]["type"]["state"]
        competitors = competition["competitors"]
        home = next(c for c in competitors if c.get("homeAway") == "home")
        away = next(c for c in competitors if c.get("homeAway") == "away")
        match = {
            "date": event.get("date"),
            "competition": event.get("league", {}).get("name", default_competition),
            "status_description": competition["status"]["type"].get("description", ""),
            "home_name": home["team"]["displayName"],
            "away_name": away["team"]["displayName"],
            "home_score": _soccer_score_display(home, state),
            "away_score": _soccer_score_display(away, state),
        }
        return state, match
    except (KeyError, IndexError, StopIteration, TypeError):
        return None, None


def _fetch_next_scheduled_match(team_id, league_slugs):
    """The team's next fixture from ESPN's team-summary endpoint's
    `nextEvent` field - a second, separate ESPN endpoint from the schedule
    one _fetch_soccer_team_matches otherwise relies on.

    A real, reported bug, confirmed live: the schedule endpoint
    (.../teams/{id}/schedule) returned exactly one event for Manchester
    United - the most recent PAST match - and zero future fixtures, even
    though a real next fixture existed and was already on the calendar
    (visible immediately via this second endpoint's `nextEvent`). The
    grounding pipeline was correctly telling the model "no next match
    found" - genuinely correct given the data _fetch_soccer_team_matches
    was looking at - but that data was incomplete, not the model
    fabricating over real evidence like the earlier UNKNOWN-instruction
    truncation bug. This fills that specific gap from a second real ESPN
    source rather than guessing.
    """
    for slug in league_slugs:
        try:
            resp = requests.get(
                f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams/{team_id}",
                timeout=8,
            )
            resp.raise_for_status()
            next_events = resp.json().get("team", {}).get("nextEvent") or []
        except (requests.RequestException, ValueError, KeyError):
            continue
        for event in next_events:
            state, match = _parse_soccer_event(event, slug)
            if state == "pre":
                return match
    return None


def _fetch_soccer_team_matches(team_id, home_league_slug):
    """A team's most recent result and next fixture from ESPN's keyless
    schedule endpoint - built for the same reason _fetch_stock_quote
    bypasses generic search: a live score page renders client-side with
    JS, so a plain scrape of it has no score in it at all. Checks the
    team's home league plus the UEFA club competitions so a Champions
    League/Europa League fixture is found even though the team was
    resolved through its domestic league.

    Returns {"last_match": ..., "next_match": ..., "live_match": ...}
    (each a dict or None), or None if every league's schedule call failed.
    """
    league_slugs = [home_league_slug] + [s for s in _SOCCER_UEFA_LEAGUE_SLUGS if s != home_league_slug]
    events, any_success = [], False
    for slug in league_slugs:
        try:
            resp = requests.get(
                f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams/{team_id}/schedule",
                timeout=8,
            )
            resp.raise_for_status()
            events.extend(resp.json().get("events", []))
            any_success = True
        except (requests.RequestException, ValueError, KeyError):
            continue
    if not any_success:
        return None

    last_match, next_match, live_match = None, None, None
    for event in sorted(events, key=lambda e: e.get("date", "")):
        state, match = _parse_soccer_event(event, home_league_slug)
        if state is None:
            continue
        if state == "post":
            last_match = match  # events are date-sorted, so the last one seen is the most recent
        elif state == "in":
            live_match = match
        elif state == "pre" and next_match is None:
            next_match = match
    if next_match is None:
        next_match = _fetch_next_scheduled_match(team_id, league_slugs)
    return {"last_match": last_match, "next_match": next_match, "live_match": live_match}


def _soccer_outcome_sentence(home_name, away_name, home_score, away_score):
    """An explicit winner/loser/draw sentence, alongside the raw "home
    NN-NN away" line - a real, live-observed bug: given a scoreline like
    "Hull City 2-0 Manchester United", the small answering model
    misattributed the result and told the user Manchester United had WON
    2-0 - inverting both the winner and the home/away scores. A bare
    scoreline leaves that inference to the model; stating the outcome in
    words removes it. Returns None if the scores aren't parseable as
    integers."""
    try:
        home_n, away_n = int(home_score), int(away_score)
    except (TypeError, ValueError):
        return None
    if home_n > away_n:
        return f"{home_name} won {home_n}-{away_n} against {away_name}."
    if away_n > home_n:
        return f"{away_name} won {away_n}-{home_n} against {home_name}."
    return f"{home_name} and {away_name} drew {home_n}-{away_n}."


def _unresolved_soccer_subject_evidence(prompt, reason):
    """An explicit, stated evidence item for a message that looks like a
    live soccer/match question (_looks_like_soccer_query matched) but names
    no team this code can resolve to real data. `reason` is a short,
    specific description of what failed (no team text found at all, vs. a
    team name that didn't resolve against ESPN) - logged in `content` so
    it's visible in the model's own context, not just to a developer
    reading the code.

    Returned instead of None so the caller (_soccer_evidence_item) treats
    this the same as a successful lookup: it stops the live-lookup bypass
    chain right here with real evidence, rather than falling through to a
    generic web search with no team-specific grounding at all. See the
    call site above for the real, reported failure this fixes."""
    content = (
        f"No live match data was retrieved ({reason}). Do not guess, assume, or invent any team, opponent, "
        "score, date, or league standing to answer this question. State plainly that you don't have this "
        "information and ask the user to name the team."
    )
    return {
        "id": hashlib.sha256(f"soccer-unresolved|{prompt}|{reason}".encode("utf-8")).hexdigest()[:16],
        "query": prompt,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "title": "No team identified for this question",
        "url": "",
        "search_provider": "soccer-unresolved",
        "content": content,
        "truthfulness_confidence": 90,
        "recency_confidence": 100,
        "corroborating_domains": [],
    }


# Abbreviation -> IANA zone, for the handful of US zone names a person is
# likely to type into user_details.log's free-text `timezone` field. "mst"
# maps to America/Phoenix (Arizona's non-DST MST) rather than the Mountain
# zone's seasonal America/Denver - see _user_timezone's docstring for why
# that's the right call for THIS specific, single-user deployment.
_TIMEZONE_ABBREVIATIONS = {
    "utc": "UTC", "gmt": "UTC",
    "est": "America/New_York", "edt": "America/New_York",
    "cst": "America/Chicago", "cdt": "America/Chicago",
    "mst": "America/Phoenix",
    "mdt": "America/Denver",
    "pst": "America/Los_Angeles", "pdt": "America/Los_Angeles",
}


def _user_timezone():
    """The user's configured local timezone (user_details.log's free-text
    `timezone` field, via load_user_profile), resolved to a pytz zone - or
    None if the field is empty or doesn't match a recognized abbreviation
    or IANA name.

    Deliberately no guessing beyond an exact, listed match: an
    unrecognized value returns None so callers state a time in UTC
    explicitly instead of silently mislabeling it with a wrong zone - the
    same "state the gap, don't fabricate" reasoning as
    _unresolved_soccer_subject_evidence above.

    Gnosis is built for one person, not a multi-tenant service (this
    user's own framing: "multi agent, single user") - load_user_profile()
    reads a single shared profile file, not a per-request user id, so this
    helper is correct as-is; it would need real per-user zone storage
    instead of one shared profile file if that ever changed.
    """
    raw = (load_user_profile().get("timezone") or "").strip()
    if not raw:
        return None
    token = raw.split("(")[0].strip().lower()
    zone_name = _TIMEZONE_ABBREVIATIONS.get(token)
    if zone_name:
        return pytz.timezone(zone_name)
    try:
        return pytz.timezone(raw)
    except pytz.UnknownTimeZoneError:
        return None


def _format_match_datetime(iso_date):
    """Format an ESPN match `date` (UTC ISO8601) for display, converted to
    the user's configured local timezone when known (_user_timezone()) and
    always explicitly labeled with the zone it's in - UTC when no local
    zone is configured, never a bare, ambiguous timestamp. Converting here,
    once, deterministically, is the point: a small local model asked to do
    timezone math itself is exactly the kind of thing that gets silently
    guessed at instead of computed - see this module's other "state it
    explicitly, don't leave it for the model to fill in" fixes for the same
    reasoning applied elsewhere in soccer evidence."""
    if not iso_date:
        return iso_date
    try:
        when = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    except ValueError:
        return iso_date
    zone = _user_timezone()
    if zone is None:
        return when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return when.astimezone(zone).strftime("%Y-%m-%d %H:%M %Z")


def _soccer_evidence_item(prompt, team_name=None, resolved_team=None):
    """A real-time, single-source evidence item for a soccer-result
    question - the same fix as _weather_evidence_item/_stock_evidence_item
    for the same underlying problem. See _fetch_soccer_team_matches'
    docstring for the live evidence generic web search cannot answer this
    reliably. Returns None if this isn't a recognized soccer query or the
    live lookup fails, so the caller falls back to ordinary research
    unchanged.

    `team_name`, when given, skips regex detection/extraction entirely and
    resolves that team directly - see _weather_evidence_item's `location`
    parameter for why (same fix, same reason, live.soccer_result instead
    of live.weather).

    `resolved_team`, when given, is an already-resolved `(team_id,
    display_name, league_slug)` - the exact shape _resolve_soccer_team
    returns - and skips that ESPN name-search call entirely, going straight
    to the schedule fetch. For a subscribed team (core/subscriptions.py),
    the id/league were already resolved once at subscribe time; re-running
    a live name search on every single message would be both slower and a
    second chance for that search to fail or match the wrong team.
    """
    if resolved_team is not None:
        team_id, display_name, league_slug = resolved_team
    else:
        subject = team_name
        if subject is None:
            if not _looks_like_soccer_query(prompt):
                return None
            subject = _soccer_query_subject(prompt)
        if not subject:
            # This message is soccer-shaped (_looks_like_soccer_query said
            # so) but no team name could be extracted from it at all - a
            # real, reported failure: the old code returned None here,
            # silently, and the caller treated that identically to "not a
            # soccer question," falling through to a generic web search
            # with no team-specific evidence. The model then filled the gap
            # itself, fabricating a fixture wholesale rather than saying it
            # didn't know which team was being asked about. State the gap
            # instead of hiding it - same fix, same reasoning, as the
            # explicit "Next match: UNKNOWN" text below for a resolved team
            # with no scheduled fixture.
            return _unresolved_soccer_subject_evidence(prompt, reason="no team name found in this message")
        resolved = _resolve_soccer_team(subject)
        if not resolved:
            return _unresolved_soccer_subject_evidence(
                prompt, reason=f'"{subject}" did not match any team in ESPN\'s data',
            )
        team_id, display_name, league_slug = resolved
    matches = _fetch_soccer_team_matches(team_id, league_slug)
    if not matches or not any(matches.values()):
        return None

    parts = [f"{display_name}."]

    def _describe(label, match, include_score):
        home_score, away_score = match["home_score"], match["away_score"]
        piece = f"{label}: {match['home_name']}"
        has_score = include_score and home_score is not None and away_score is not None
        if has_score:
            piece += f" {home_score}-{away_score}"
        piece += (
            f" {match['away_name']} ({match['competition']}, {match['status_description']}) "
            f"on {_format_match_datetime(match['date'])}."
        )
        parts.append(piece)
        if has_score:
            outcome = _soccer_outcome_sentence(match["home_name"], match["away_name"], home_score, away_score)
            if outcome:
                parts.append(outcome)

    if matches["live_match"]:
        _describe("Live now", matches["live_match"], include_score=True)
    if matches["last_match"]:
        _describe("Last result", matches["last_match"], include_score=True)
    else:
        parts.append("Last result: no recent match found in the available data.")
    if matches["next_match"]:
        _describe("Next match", matches["next_match"], include_score=False)
    else:
        # A real, reported bug: when this was silently omitted instead of
        # stated, the model - asked "who do they play next?" with only a
        # "Last result" line to work from - relabeled that past match as
        # the upcoming one instead of saying it didn't know. A short,
        # explicit "no data" line wasn't enough on its own either - tested
        # live and the model still restated the last match as the next one
        # despite it. This more forceful, repetitive version (spelling out
        # that the last result is a PAST match, not the next one, and that
        # saying "unknown" is the required answer) is what actually landed,
        # confirmed live before shipping it - the same "needed a stronger
        # prompt to actually land" lesson [Unverified title] and [Wrong
        # entity] already required in fact_check_answer.
        parts.append(
            "Next match: UNKNOWN - no upcoming fixture is scheduled in the available data. If asked what "
            "team plays next or when the next match is, you must say this information is not currently "
            "available. The 'Last result' above is a PAST match that has already happened - it is NOT the "
            "next match, even though it is the only match listed."
        )

    content = " ".join(parts)
    return {
        "id": hashlib.sha256(f"espn-soccer|{team_id}|{content}".encode("utf-8")).hexdigest()[:16],
        "query": prompt,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "title": f"Live soccer results - {display_name}",
        "url": f"https://www.espn.com/soccer/team/_/id/{team_id}",
        "search_provider": "espn",
        "content": content,
        "truthfulness_confidence": 90,
        "recency_confidence": 100,
        "corroborating_domains": [],
    }


def _live_weather_lookup(location):
    """Tool-facing wrapper for live.weather - see _weather_evidence_item's
    `location` parameter docstring for why this bypasses regex entirely."""
    return _weather_evidence_item(location, location=location)


def _live_stock_lookup(company_or_ticker):
    """Tool-facing wrapper for live.stock_quote - see _stock_evidence_item's
    `subject` parameter docstring for why this bypasses regex entirely."""
    return _stock_evidence_item(company_or_ticker, subject=company_or_ticker)


def _live_soccer_lookup(team):
    """Tool-facing wrapper for live.soccer_result - see
    _soccer_evidence_item's `team_name` parameter docstring for why this
    bypasses regex entirely."""
    return _soccer_evidence_item(team, team_name=team)


def _soccer_standings_evidence_item(prompt):
    """An explicit 'not available' evidence item for a league standings/
    table question. Gnosis has no live standings data source at all -
    _fetch_soccer_team_matches only pulls a team's own schedule, never
    table position, points, or record - so this can't be answered by
    resolving a team better or searching harder; the capability itself
    doesn't exist yet. Returns None if prompt isn't standings-shaped.

    A real, reported failure: "where do they stand in the premier league?"
    matched none of the soccer-query detectors, reached the model with
    zero evidence, and got answered with a fully invented league position,
    point total, and goal record. State the gap explicitly - same fix,
    same reasoning as _unresolved_soccer_subject_evidence - instead of
    pretending to have data this code doesn't fetch."""
    if not _looks_like_soccer_standings_query(prompt):
        return None
    return {
        "id": hashlib.sha256(f"soccer-standings-unavailable|{prompt}".encode("utf-8")).hexdigest()[:16],
        "query": prompt,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "title": "League standings not available",
        "url": "",
        "search_provider": "soccer-standings-unavailable",
        "content": (
            "Gnosis has no live league standings/table data (position, points, goal record) for any team. "
            "Do not guess, estimate, or invent a league position, point total, or record. State plainly that "
            "this information isn't available."
        ),
        "truthfulness_confidence": 90,
        "recency_confidence": 100,
        "corroborating_domains": [],
    }


def _try_live_lookup_bypasses(query_text):
    """Try each live-lookup bypass in turn against query_text, printing/
    emitting status and returning the first evidence item found, or None if
    none matched. Shared by model_directed_web_research's direct attempt
    against the raw prompt and its retry against a resolved follow-up."""
    weather_item = _weather_evidence_item(query_text)
    if weather_item:
        print(f"{Fore.CYAN}🌤️  Live weather lookup for: {query_text}{Style.RESET_ALL}")
        _emit_status("Checking live weather...")
        return weather_item
    stock_item = _stock_evidence_item(query_text)
    if stock_item:
        print(f"{Fore.CYAN}📈 Live stock quote lookup for: {query_text}{Style.RESET_ALL}")
        _emit_status("Checking live stock quote...")
        return stock_item
    soccer_item = _soccer_evidence_item(query_text)
    if soccer_item:
        print(f"{Fore.CYAN}⚽ Live soccer result lookup for: {query_text}{Style.RESET_ALL}")
        _emit_status("Checking live match result...")
        return soccer_item
    standings_item = _soccer_standings_evidence_item(query_text)
    if standings_item:
        print(f"{Fore.CYAN}⚽ Soccer standings query (no data source) for: {query_text}{Style.RESET_ALL}")
        _emit_status("Checking league standings...")
        return standings_item
    return None


def _matching_subscription(prompt):
    """The first subscription (core/subscriptions.py) whose name or any
    keyword appears in prompt, or None. First-match-wins, no ranking - fine
    for a handful of subscriptions; would need real ranking if that ever
    stops being true."""
    lowered = prompt.lower()
    for subscription in subscriptions.list_subscriptions():
        candidates = [subscription.get("name", "")] + subscription.get("metadata", {}).get("keywords", [])
        if any(candidate and candidate.lower() in lowered for candidate in candidates):
            return subscription
    return None


def _subscribed_team_lookup(subscription, prompt):
    metadata = subscription.get("metadata", {})
    if metadata.get('sport', 'soccer') != 'soccer' or re.search(r'\b(?:schedule|fixtures|next\s+(?:five|5))\b', prompt, re.IGNORECASE):
        from core import sports
        return sports.schedule_evidence(subscription, _format_match_datetime)
    team_id, league_slug = metadata.get("team_id"), metadata.get("league_slug")
    if not team_id or not league_slug:
        return []
    item = _soccer_evidence_item(
        subscription["name"], resolved_team=(team_id, subscription["name"], league_slug),
    )
    return [item] if item else []


def _subscribed_topic_lookup(subscription, prompt):
    try:
        results = tool_registry.execute("web.search", query=f"{subscription['name']} {prompt}")
    except Exception:
        return []
    return save_web_evidence(prompt, results or [])


def _subscribed_website_lookup(subscription, prompt):
    url = subscription.get("metadata", {}).get("url")
    if not url:
        return []
    text = fetch_page_content(url)
    if not text:
        return []
    return [{
        "id": hashlib.sha256(f"subscribed-website|{url}|{text[:200]}".encode("utf-8")).hexdigest()[:16],
        "query": prompt,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "title": subscription["name"],
        "url": url,
        "search_provider": "subscribed-website",
        "content": text[:1500],
        "truthfulness_confidence": 85,
        "recency_confidence": 80,
        "corroborating_domains": [],
    }]


def _subscribed_weather_lookup(subscription, prompt):
    location = subscription.get("metadata", {}).get("location")
    if not location:
        return []
    item = _weather_evidence_item(prompt, location=location)
    return [item] if item else []


_SUBSCRIPTION_HANDLERS = {
    "team": _subscribed_team_lookup,
    "topic": _subscribed_topic_lookup,
    "website": _subscribed_website_lookup,
    "weather": _subscribed_weather_lookup,
}


def get_subscription_dashboard_evidence(subscription):
    """Fetch source data without changing chat history or its status callback."""
    kind = subscription.get('type')
    if kind == 'team':
        from core import sports
        return sports.schedule_evidence(subscription, _format_match_datetime)
    if kind == 'topic':
        # Use the search provider directly; chat's search wrapper emits status
        # into the active turn and archives results, neither belongs here.
        return search_searx(f"{subscription['name']} latest news")
    handler = _SUBSCRIPTION_HANDLERS.get(kind)
    return handler(subscription, '') if handler else []


def _subscription_bypass(prompt):
    """Evidence for prompt from a user-declared subscription, or [] if none
    matches - see core/subscriptions.py's module docstring for why this
    exists: skip inferring the subject from raw prompt text entirely for
    anything the user already told Gnosis they follow."""
    subscription = _matching_subscription(prompt)
    if not subscription:
        return []
    handler = _SUBSCRIPTION_HANDLERS.get(subscription["type"])
    if not handler:
        return []
    from core.result_cache import subscription_cache
    key = json.dumps([subscription, prompt.casefold().strip()], sort_keys=True)
    force = bool(re.search(r"\b(refresh|verify|wrong|incorrect)\b|double check", prompt, re.I))
    evidence = None if force else subscription_cache.get(key)
    if evidence is None:
        evidence = handler(subscription, prompt)
        ttl = {"weather": 120, "team": 60, "topic": 300, "website": 300}.get(subscription["type"], 60)
        subscription_cache.put(key, evidence, ttl)
    if evidence:
        print(f"{Fore.CYAN}🔔 Subscribed {subscription['type']} lookup: {subscription['name']}{Style.RESET_ALL}")
        _emit_status(f"Checking your {subscription['type']} subscription: {subscription['name']}...")
    return evidence


def add_team_subscription(name):
    """GUI-facing: resolve name against ESPN once, then persist the
    resolved (team_id, league_slug) - see _soccer_evidence_item's
    `resolved_team` docstring for why that avoids a repeated live name
    search on every message about this team. Raises ValueError (with a
    message fit to show the user directly) if the team can't be resolved."""
    resolved = _resolve_soccer_team(name)
    if not resolved:
        raise ValueError(f"Could not find a soccer team named \"{name}\".")
    team_id, display_name, league_slug = resolved
    return subscriptions.add_subscription(
        "team", display_name,
        metadata={"team_id": team_id, "league_slug": league_slug, "sport": "soccer"},
    )


def add_sports_team_subscription(league_key, team_id):
    """Save a team chosen from the specified league's verified directory."""
    from core import sports
    team = next((item for item in sports.list_teams(league_key) if item['id'] == str(team_id)), None)
    if team is None:
        raise ValueError('Choose a team from the loaded league list.')
    return subscriptions.add_subscription('team', team['name'], sports.team_metadata(league_key, team))


def add_topic_subscription(name, keywords=None, category=None):
    """GUI-facing: no live resolution needed - a topic is just a name (and
    optional alias keywords) matched against future prompts."""
    metadata = {"keywords": keywords or []}
    if category is not None:
        from core.interest_catalog import CATEGORIES
        if category not in CATEGORIES:
            raise ValueError("Choose a valid interest category")
        metadata["category"] = category
    return subscriptions.add_subscription("topic", name, metadata=metadata)


def add_website_subscription(name, url, keywords=None, category=None):
    """GUI-facing: verify the URL is actually fetchable before saving it -
    the same "we know it works" bar add_team_subscription holds a team
    name to. Raises ValueError (with a message fit to show the user
    directly) if the URL can't be fetched."""
    if not fetch_page_content(url):
        raise ValueError(f"Could not fetch {url} - check the URL and try again.")
    metadata = {"url": url, "keywords": keywords or []}
    if category is not None:
        from core.interest_catalog import CATEGORIES
        if category not in CATEGORIES:
            raise ValueError("Choose a valid interest category")
        metadata["category"] = category
    return subscriptions.add_subscription("website", name, metadata=metadata)


def add_weather_subscription(location):
    """GUI-facing: resolve location against Open-Meteo's geocoder once, and
    persist the NORMALIZED place name it returns (e.g. "tucson" ->
    "Tucson, Arizona, United States"), not the user's raw text - so every
    future _subscribed_weather_lookup call geocodes the same unambiguous
    string instead of re-resolving arbitrary user phrasing each time.
    Raises ValueError (with a message fit to show the user directly) if
    nothing geocodes."""
    weather = fetch_current_weather(location)
    if not weather:
        raise ValueError(f"Could not find a location matching \"{location}\".")
    return subscriptions.add_subscription("weather", weather["place"], metadata={"location": weather["place"]})


def add_interest_subscription(name, category, keywords=None, url=None):
    """Follow any named subject, optionally resolving a website source."""
    from core.interest_catalog import CATEGORIES
    if category not in CATEGORIES or category == "weather":
        raise ValueError("Choose an interest category; use the location picker for weather")
    name = (name or "").strip()
    if not name:
        raise ValueError("Enter an interest name")
    keywords = [word.strip() for word in (keywords or []) if word.strip()]
    if url:
        url = url.strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Enter a complete http:// or https:// website URL")
        return add_website_subscription(name, url, keywords=keywords, category=category)
    return add_topic_subscription(name, keywords=keywords, category=category)


_RESEARCH_TOOL_NAMES = ("knowledge.search", "web.search", "live.weather", "live.stock_quote", "live.soccer_result")


def _research_tool_catalog():
    catalog_by_name = {tool.name: tool for tool in tool_registry.list() if tool.name in _RESEARCH_TOOL_NAMES}
    return [catalog_by_name[name] for name in _RESEARCH_TOOL_NAMES if name in catalog_by_name]


def _select_tool_actions(prompt):
    """Ask the model which of the research tools (the knowledge base, web
    search, and the live weather/stock/soccer lookups) would help answer
    this message - and, unlike _select_tool_action, explicitly invites
    selecting SEVERAL at once (e.g. knowledge.search to check prior
    research AND web.search for anything not already known, or a live.*
    tool for extra corroboration alongside web.search) rather than jumping
    at the first one that matches, since all of these are free and
    combining sources gives a fuller, better-corroborated answer.

    Replaces regex-based intent detection as the PRIMARY mechanism for this
    class of question - _try_live_lookup_bypasses (the old regex path) is
    still tried first as a free, zero-latency fast path, but this is what
    runs when it finds nothing. Natural language has far more phrasings
    than any hand-written pattern set can keep up with: four separate real,
    reported regex bugs were found and fixed in this exact area (missing
    "X stock price" word order, "the last fixture for X" phrasing, "the
    last man united match" modifier-before-subject order, "when was" past
    tense) before this replaced regex as the primary path. Recent
    conversation history is included so a follow-up naming no subject of
    its own ("what was the last fixture?") can still be resolved from
    context, the same way a person reading the conversation would.

    Returns a list of {"tool": name, "arguments": {...}} (possibly empty).
    Never raises - any missing/unparseable/invalid response yields [].
    """
    if ollama is None:
        return []
    catalog = _research_tool_catalog()
    if not catalog:
        return []
    planner = (
        "You have these research tools available. Decide which of them, if any, would help answer the "
        "user's LATEST message - you may select MORE THAN ONE if combining sources would give a fuller or "
        "better-corroborated answer (e.g. knowledge.search to check prior research AND web.search for "
        "anything not already known, or a live.* tool alongside web.search for extra corroboration). Do "
        "not pick any tool for a question that doesn't need current, external, or previously-researched "
        "information (general knowledge, opinions, casual conversation, math).\n\n"
        "Use the recent conversation to resolve a follow-up that doesn't name its own subject (e.g. "
        "\"what was the last fixture?\" after a conversation about Manchester United means "
        "team=\"Manchester United\"). If you cannot tell which specific subject (team, company, place) "
        "the user means even after checking the conversation, do not guess one - select no tool for that "
        "capability. An honest \"I don't know\" is a fine answer; a tool call built on a guessed argument "
        "is not.\n\n"
        f"Tools:\n{_tool_action_catalog_text(catalog)}\n\n"
        "Return ONLY valid JSON: {\"tools\": [{\"tool\": \"<name>\", \"arguments\": {...}}, ...], "
        "\"reason\": \"one short sentence on why (or why none apply)\"} - an empty tools list if none apply. "
        "The reason is logged for later review, not shown to the user - always include a real one, even "
        "for an empty list (e.g. \"casual conversation, no tool needed\" or \"no team named, even in the "
        "recent conversation\").\n\n"
        f"Recent conversation:\n{_planner_history()}\n\nLatest message: {prompt}"
    )

    def _chat_fn(messages):
        response = model_chat(model=MODELS['fast'], messages=messages)
        return response.get("message", {}).get("content", "")

    decision = agent_dialogue.call_agent_json(_chat_fn, planner)
    if not isinstance(decision, dict):
        events.publish(TOOL_SELECTION_MADE, prompt=prompt, selected=[], reason="unparseable model response")
        return []
    reason = decision.get("reason") if isinstance(decision.get("reason"), str) else None
    raw_tools = decision.get("tools")
    if not isinstance(raw_tools, list):
        events.publish(TOOL_SELECTION_MADE, prompt=prompt, selected=[], reason=reason or "no 'tools' list in response")
        return []
    valid_by_name = {tool.name: tool for tool in catalog}
    selected, seen_names = [], set()
    for entry in raw_tools:
        if not isinstance(entry, dict):
            continue
        name = entry.get("tool")
        tool = valid_by_name.get(name)
        if tool is None or name in seen_names:
            continue
        arguments = entry.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}
        # Real, reported failure: the model supplied live.soccer_result with
        # both "team" and a "location" left over from a live.weather call it
        # made the turn before - tool_registry.execute raised a TypeError for
        # the unexpected keyword (caught, so it failed safe, but wasted the
        # turn and fell through to a worse fallback path). Dropping anything
        # outside the tool's declared parameters is a hard, deterministic
        # check code can do perfectly.
        arguments = {key: value for key, value in arguments.items() if key in tool.parameters}
        missing = [param for param in tool.parameters if param not in arguments]
        if missing:
            print(f"{Fore.YELLOW}ℹ️ Model selected '{name}' but didn't supply required argument(s) "
                  f"{missing} - skipping it.{Style.RESET_ALL}")
            continue
        if name == "web.search" and not _search_text_matches_prompt(prompt, arguments.get("query", "")):
            signals = relevance_signals(prompt, arguments.get("query", ""))
            reason = (
                f"rejected off-topic web query; overlap={signals['overlap']}; "
                f"introduced={signals['introduced']}"
            )
            print(f"{Fore.YELLOW}ℹ️ Ignoring an off-topic web search for '{arguments.get('query')}'.{Style.RESET_ALL}")
            continue
        seen_names.add(name)
        selected.append({"tool": name, "arguments": arguments})
    events.publish(TOOL_SELECTION_MADE, prompt=prompt, selected=[a["tool"] for a in selected], reason=reason)
    return selected


def _knowledge_search_evidence(query, results):
    """Normalize passages while retaining provenance. Saved research remains
    unverified background; local ownership does not establish truth or freshness.
    """
    evidence = []
    for filename, content in (results or [])[:5]:
        provenance = getattr(content, "metadata", {})
        if provenance:
            from core.knowledge_retrieval import terms, supports_population_count
            requested = set(terms(query))
            overlap = requested & set(terms(content))
            if requested and len(overlap) / len(requested) < 0.6 and not (provenance.get("semantic_similarity") or 0) >= 0.65:
                continue
            if "usa" in requested and "usa" not in terms(content):
                continue
            if "population" in requested and not supports_population_count(content, requested):
                continue
        evidence.append({
            "id": hashlib.sha256(f"knowledge-base|{filename}|{provenance.get('offset', 0)}|{query}".encode("utf-8")).hexdigest()[:16],
            "query": query,
            "captured_at": getattr(content, "metadata", {}).get("captured_at"),
            "title": f"Knowledge base - {filename}",
            "url": f"knowledge_base://{filename}",
            "search_provider": "knowledge-base",
            "content": content[:2000],
            "truthfulness_confidence": 40,
            "recency_confidence": 0,
            "provenance": getattr(content, "metadata", {}),
            "verification_status": "unverified",
            "corroborating_domains": [],
        })
    return evidence


def _execute_research_tool_action(action, query_for_record):
    """Execute one _select_tool_actions selection and return a list of
    evidence-dicts (0 or more - most tools yield one, web.search can yield
    several), or [] on any failure. Each tool's raw result has a different
    shape; normalized here to the shared evidence-dict shape so downstream
    corroboration scoring and fact-checking don't need to know which
    tool(s) actually produced the grounding.
    """
    name = action.get("tool")
    arguments = action.get("arguments", {})
    try:
        result = tool_registry.execute(name, **arguments)
    except Exception as error:
        print(f"{Fore.YELLOW}ℹ️ Tool '{name}' selected by the model failed: {error}{Style.RESET_ALL}")
        events.publish(TOOL_EXECUTION_COMPLETED, tool=name, arguments=arguments, success=False, error=str(error), evidence_count=0)
        return []

    evidence = []
    if name == "live.weather" and result:
        print(f"{Fore.CYAN}🌤️  Live weather lookup (model-selected): {arguments.get('location')}{Style.RESET_ALL}")
        _emit_status("Checking live weather...")
        evidence = [result]
    elif name == "live.stock_quote" and result:
        print(f"{Fore.CYAN}📈 Live stock quote lookup (model-selected): {arguments.get('company_or_ticker')}{Style.RESET_ALL}")
        _emit_status("Checking live stock quote...")
        evidence = [result]
    elif name == "live.soccer_result" and result:
        print(f"{Fore.CYAN}⚽ Live soccer result lookup (model-selected): {arguments.get('team')}{Style.RESET_ALL}")
        _emit_status("Checking live match result...")
        evidence = [result]
    elif name == "web.search":
        print(f"{Fore.CYAN}🔍 Web search (model-selected): {arguments.get('query')}{Style.RESET_ALL}")
        _emit_status(f"Searching the web: {arguments.get('query')}")
        results = [item for item in (result or []) if not is_fallback_result(item)][:5]
        evidence = save_web_evidence(query_for_record, results)
    elif name == "knowledge.search":
        print(f"{Fore.CYAN}📚 Knowledge base search (model-selected): {arguments.get('topic')}{Style.RESET_ALL}")
        _emit_status("Checking the knowledge base...")
        evidence = _knowledge_search_evidence(query_for_record, result)

    events.publish(
        TOOL_EXECUTION_COMPLETED, tool=name, arguments=arguments,
        success=bool(evidence), error=None, evidence_count=len(evidence),
    )
    return evidence


def model_directed_web_research(prompt):
    """Collect evidence through successive, model-chosen searches and rank it.

    Deep Think additionally seeds a multi-angle plan up front and enforces a
    minimum search count, since breadth should not depend on a small local
    planner model choosing on its own to keep researching. Standard mode
    short-circuits to a single live reading for a weather, stock-price, or
    soccer-result query instead - see _weather_evidence_item,
    _stock_evidence_item, and _soccer_evidence_item for why generic search
    evidence is unreliable for these specific question shapes, and Deep
    Think keeps its existing multi-source behavior since forcing it down to
    one reading would defeat that mode's whole purpose.

    Standard mode seeds evidence via _select_tool_actions before the
    refinement loop below runs - symmetric with how Deep Think seeds via
    _deep_think_research_plan - so a follow-up naming no subject of its own
    ("what was the last fixture?") still resolves from conversation context,
    and multiple free sources (knowledge base, web search, a live.* lookup)
    can combine into one answer instead of stopping at the first hit. See
    _select_tool_actions's docstring for why this replaced regex as the
    primary mechanism here. Local-only selections continue through the
    refinement loop, and current facts require external evidence.
    """
    if not context.deep_think_mode:
        subscription_evidence = _subscription_bypass(prompt)
        if subscription_evidence:
            return subscription_evidence
        item = _try_live_lookup_bypasses(prompt)
        if item:
            return [item]
    elif _looks_like_weather_query(prompt) or _looks_like_stock_query(prompt) or _looks_like_soccer_query(prompt):
        print(f"{Fore.YELLOW}ℹ️ Deep Think mode is on, so the live weather/stock/soccer lookup is skipped for: "
              f"{prompt} (falling back to multi-source research).{Style.RESET_ALL}")

    _emit_status("Researching...")
    evidence, seen_queries = [], set()
    search_number = 0

    if context.deep_think_mode:
        plan_queries = _deep_think_research_plan(prompt) or [_fallback_research_query(prompt, evidence)]
        for query in plan_queries:
            query_key = query.casefold()
            if query_key in seen_queries:
                continue
            seen_queries.add(query_key)
            print(f"{Fore.CYAN}🔍 Deep Think angle {search_number + 1}: {query}{Style.RESET_ALL}")
            _emit_status(f"Researching angle {search_number + 1}: {query}")
            results = [item for item in tool_registry.execute("web.search", query=query) if not is_fallback_result(item)][:5]
            evidence.extend(save_web_evidence(query, results))
            apply_corroboration(evidence)
            search_number += 1
    else:
        actions = _select_tool_actions(prompt)
        for action in actions:
            evidence.extend(_execute_research_tool_action(action, prompt))
        if requires_current_web_verification(prompt):
            # Saved notes cannot satisfy live verification or become citations
            # for a current answer when web search is unavailable.
            evidence = [item for item in evidence if item.get('search_provider') != 'knowledge-base']
        external_evidence = [item for item in evidence if item.get('search_provider') != 'knowledge-base']
        if external_evidence:
            # Preserve authoritative live lookups and selected web results.
            # Local-only hits still need the refinement loop: finding a saved
            # note about a country does not establish its population today.
            apply_corroboration(evidence)
            persist_evidence_updates(evidence)
            return sorted(evidence, key=lambda item: (item["truthfulness_confidence"], item["recency_confidence"]), reverse=True)

    near_duplicate_streak = 0
    while True:
        if context.deep_think_mode and search_number >= DEEP_THINK_MAX_SEARCHES:
            break
        action = _research_action(prompt, evidence, search_number)
        verification_required = context.deep_think_mode or requires_current_web_verification(prompt)
        forced_continuation = False
        if action.get("action") == "search" and verification_required and not evidence:
            # Keep the subject anchored to the user's request. This prevents a
            # chatty planner from searching a side remark (for example, a joke)
            # instead of the current officeholder or result being verified.
            action["query"] = _fallback_research_query(prompt, evidence)
        # A time-sensitive answer needs at least one source, even if the model
        # answered prematurely. If the first results have no strong source, try
        # one official-source refinement before allowing an answer.
        if action.get("action") != "search" and verification_required:
            if not evidence:
                action = {"action": "search", "query": _fallback_research_query(prompt, evidence)}
            elif context.deep_think_mode and search_number < DEEP_THINK_MIN_SEARCHES:
                # Deliberately exempt from the near-duplicate check below: this
                # rotates through a fixed set of distinct angle suffixes on the
                # same base query by construction, so it looks like a repeat
                # word-overlap-wise without actually being an unresolved planner
                # stuck rephrasing the same failed query.
                action = {"action": "search", "query": _deep_think_forced_query(prompt, search_number)}
                forced_continuation = True
            elif search_number == 1 and (
                max(item["truthfulness_confidence"] for item in evidence) < 75
                or len({urlparse(item["url"]).hostname for item in evidence}) < 2
            ):
                action = {"action": "search", "query": _fallback_research_query(prompt, evidence)}
        if action.get("action") != "search":
            break
        query = action["query"].strip()
        query_key = query.casefold()
        if query_key in seen_queries:
            break
        if not forced_continuation:
            if _is_near_duplicate_query(query, seen_queries):
                near_duplicate_streak += 1
                if near_duplicate_streak >= MAX_CONSECUTIVE_NEAR_DUPLICATE_QUERIES:
                    break
            else:
                near_duplicate_streak = 0
        seen_queries.add(query_key)
        print(f"{Fore.CYAN}🔍 Research search {search_number + 1}: {query}{Style.RESET_ALL}")
        _emit_status(f"Searching: {query}")
        results = [item for item in tool_registry.execute("web.search", query=query) if not is_fallback_result(item)][:5]
        evidence.extend(save_web_evidence(query, results))
        apply_corroboration(evidence)
        search_number += 1
    persist_evidence_updates(evidence)
    return sorted(evidence, key=lambda item: (item["truthfulness_confidence"], item["recency_confidence"]), reverse=True)


def is_fallback_result(result):
    """Detect synthetic fallback results that should not be treated as real web search hits."""
    return isinstance(result, dict) and result.get("url") == "system://intelligent-fallback"


def check_search_services(timeout=8):
    """Check whether SearxNG is reachable and usable.

    Returns a dict with a boolean flag: {'searxng': bool}
    """
    status = {'searxng': False}
    try:
        searx_url = os.environ.get('SEARXNG_URL', 'https://search.lozdev.com').rstrip('/')
        search_endpoint = f"{searx_url}/search"
        headers = {'User-Agent': 'Gnosis/1.0'}
        resp = requests.get(search_endpoint, params={'q': 'healthcheck', 'format': 'json'}, timeout=timeout, headers=headers)
        if resp.ok:
            # basic validation: JSON with 'results' key or at least parsable
            try:
                _ = resp.json()
                status['searxng'] = True
            except Exception:
                status['searxng'] = False
        else:
            status['searxng'] = False
    except Exception:
        status['searxng'] = False

    return status

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
        results = tool_registry.execute("web.search", query=query)
        if not results:
            retries += 1
            continue
        context_snippets = []
        for result in results:
            summary = summarize_text(result["content"])
            context_snippets.append(f"{result['title']}: {summary}")
        accumulated_context += "\n\n".join(context_snippets) + "\n\n"
        context.assistant_convo.append({"role": "system", "content": f"Here is some info:\n{accumulated_context}"})
        # Trim before sending to the model to avoid oversized context
        try:
            trim_conversation()
        except Exception:
            pass
        if context.unfiltered_mode:
            model_key = "unfiltered"
        elif context.reasoning_mode:
            model_key = "search"
        else:
            model_key = "main"
        response = model_chat(model=MODELS[model_key], messages=context.assistant_convo)
        context.assistant_convo.append({"role": "assistant", "content": response["message"]["content"]})
        if not needs_more_search(response["message"]["content"]):
            return response["message"]["content"]
        query = refine_query(response["message"]["content"])
        retries += 1
    return response["message"]["content"]

# Note: generate_smart_queries function removed - no longer needed with optimized search

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
            
            # Get only top 2 real results instead of 6
            results = [r for r in (tool_registry.execute("web.search", query=query) or []) if not is_fallback_result(r)][:2]
            
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
    profile_path = os.path.join(core_config.project_root(), "user_details.log")
    profile = {
        'name': 'User',
        'persona': 'neutral',
        'preferences': [],
        'interests': [],
        'location': '',
        'home_address': '',
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
    profile_path = os.path.join(core_config.project_root(), "user_details.log")
    try:
        with open(profile_path, "w", encoding="utf-8") as f:
            f.write("# User Profile - Edit this file to customize your AI assistant\n")
            f.write("# Lines starting with # are comments\n\n")
            f.write(f"name: {profile.get('name', 'User')}\n")
            f.write(f"location: {profile.get('location', '')}\n")
            f.write(f"home_address: {profile.get('home_address', '')}\n")
            f.write(f"timezone: {profile.get('timezone', '')}\n")
            f.write(f"persona: {profile.get('persona', 'neutral')}\n")
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
    
    if profile['persona']:
        context_parts.append(f"Persona: {profile['persona']}")

    if profile['preferences']:
        context_parts.append(f"Preferences: {', '.join(profile['preferences'])}")
    
    if profile['interests']:
        context_parts.append(f"Interests: {', '.join(profile['interests'])}")
    
    if profile['recent_explorations']:
        context_parts.append(f"Recently explored: {', '.join(profile['recent_explorations'])}")
    
    if profile['notes']:
        context_parts.append(f"Additional notes: {profile['notes']}")
    
    return "; ".join(context_parts) if context_parts else "No user profile information available"


def _profile_field_is_relevant(field_text, prompt):
    """A profile field is relevant to a prompt if any of its significant
    (>3 character) words appears in the prompt, case-insensitively. A
    keyword-overlap heuristic rather than a model judgment call on purpose
    - this decides what context to show the model, so it can't itself call
    the model to decide. Known limitation: a query that clearly implies a
    topic without naming it (e.g. "what's the weather like today" implying
    the user's stored location) won't match - accepted rather than solved
    here, see TODO.md Phase 4."""
    prompt_words = set(re.findall(r"[a-z0-9]+", prompt.lower()))
    field_words = [w for w in re.findall(r"[a-z0-9]+", field_text.lower()) if len(w) > 3]
    return any(word in prompt_words for word in field_words)


def get_relevant_user_context(prompt):
    """Like get_user_context(), but the topic-specific fields
    (preferences/interests/recent_explorations/notes) are only included
    when they share a keyword with `prompt` - identity fields (name,
    persona, location) are always included since they describe who to
    address and how, not what the conversation is about. Fixes forcing
    unrelated profile context (e.g. an unrelated interest like "meditation"
    or "software development") into every reply regardless of what was
    actually asked - see TODO.md Phase 4."""
    profile = load_user_profile()
    context_parts = []

    if profile['name'] != 'User':
        context_parts.append(f"User's name: {profile['name']}")

    if profile['location']:
        context_parts.append(f"Location: {profile['location']}")

    if profile['persona']:
        context_parts.append(f"Persona: {profile['persona']}")

    relevant_preferences = [p for p in profile['preferences'] if _profile_field_is_relevant(p, prompt)]
    if relevant_preferences:
        context_parts.append(f"Preferences: {', '.join(relevant_preferences)}")

    relevant_interests = [i for i in profile['interests'] if _profile_field_is_relevant(i, prompt)]
    if relevant_interests:
        context_parts.append(f"Interests: {', '.join(relevant_interests)}")

    relevant_explorations = [e for e in profile['recent_explorations'] if _profile_field_is_relevant(e, prompt)]
    if relevant_explorations:
        context_parts.append(f"Recently explored: {', '.join(relevant_explorations)}")

    if profile['notes'] and _profile_field_is_relevant(profile['notes'], prompt):
        context_parts.append(f"Additional notes: {profile['notes']}")

    return "; ".join(context_parts) if context_parts else "No user profile information available"


def get_persona_system_prompt():
    profile = load_user_profile()
    persona = profile.get('persona', '').strip()
    if not persona or persona.lower() == 'neutral':
        return None

    persona_tags = [p.strip() for p in re.split(r'[,&]|and\b', persona) if p.strip()]
    if not persona_tags:
        return None

    if len(persona_tags) == 1:
        return f"Respond in a {persona_tags[0]} style and tone. Follow this persona preference closely."
    return f"Respond using the following combined persona styles: {', '.join(persona_tags)}. Match the tone, word choice, and mood to these tags precisely."


def get_supported_personas():
    return ['neutral', 'happy', 'sad', 'angry', 'dark', 'cheery', 'calm', 'professional', 'empathetic', 'direct']


def normalize_persona_values(persona):
    if not persona:
        return []
    persona = persona.lower().strip()
    persona = persona.replace(' and ', ', ')
    values = [part.strip() for part in persona.split(',') if part.strip()]
    return values


def set_user_persona(persona):
    persona_values = normalize_persona_values(persona)
    supported = get_supported_personas()
    invalid = [value for value in persona_values if value not in supported]
    if not persona_values or invalid:
        return False, supported

    normalized = ', '.join(persona_values)
    profile = load_user_profile()
    profile['persona'] = normalized
    save_user_profile(profile)
    return True, profile


def format_persona_transition(old_persona, new_persona):
    old_normal = old_persona.strip().lower() if old_persona else 'neutral'
    new_normal = new_persona.strip().lower() if new_persona else 'neutral'
    if old_normal == new_normal:
        return f"🎭 {new_normal.title()} is already on stage. The chat continues with the same vibe."
    if old_normal in ['', 'neutral']:
        return f"✨ {new_normal.title()} just slid into the chat like a guest star. Neutral took a bow and exited stage left."
    return f"🎬 {old_normal.title()} exits stage left, and {new_normal.title()} takes the spotlight. Enjoy the new vibe!"


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
    profile_path = os.path.join(core_config.project_root(), "user_details.log")
    if not os.path.exists(profile_path):
        default_profile = {
            'name': 'User',
            'persona': 'neutral',
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

# Live-lookup and explicit-gap evidence items are short, already-curated
# single-source blobs - often built specifically to carry a "you must say
# X" instruction (e.g. _soccer_evidence_item's "Next match: UNKNOWN... you
# must say this information is not currently available"). A real, reported
# bug: summarize_text's blind first-N-sentences cut silently dropped that
# instruction every time in standard mode - 2 sentences kept the team name
# and the last result, but never reached the "UNKNOWN" sentence that came
# after them, so the model answered as if it had never been told the fact
# was unknown, because it genuinely never saw that sentence (confirmed via
# a saved fact-check record: evidence correctly said "no scheduled next
# match", the displayed answer confidently invented one anyway). Generic
# multi-source web search content is the opposite case - long, noisy,
# unstructured - and still benefits from trimming, so this is scoped to
# just the search_provider values that mean "one curated, already-short
# item," not applied to every evidence item uniformly.
_UNSUMMARIZED_EVIDENCE_PROVIDERS = {
    "open-meteo", "yahoo-finance", "espn", "soccer-unresolved", "soccer-standings-unavailable",
}


def _evidence_display_text(result, max_sentences):
    content = result.get("content", "No content available")
    if result.get("search_provider") in _UNSUMMARIZED_EVIDENCE_PROVIDERS:
        return content
    return summarize_text(content, max_sentences=max_sentences)


def enhance_conversation_with_search(query, search_results, deep=False):
    """
    Use search results to create conversational flow with multiple perspectives
    """
    user_context = get_relevant_user_context(query)
    datetime_context = get_datetime_context()
    
    # Analyze the query for potential social concerns
    concerning_keywords = [
        'hate', 'violence', 'illegal', 'harmful', 'dangerous', 'exploit', 
        'scam', 'fraud', 'weapon', 'drug', 'suicide', 'self-harm',
        'bomb', 'terror', 'kill', 'murder', 'abuse', 'trafficking'
    ]
    
    is_concerning = any(keyword in query.lower() for keyword in concerning_keywords)
    
    # Create search context summary. Deep Think gathers evidence across several
    # research angles, so it needs far more of that evidence in the final
    # synthesis than the quick standard-mode answer does.
    evidence_limit = 12 if deep else 3
    summary_sentences = 3 if deep else 2
    if search_results:
        try:
            context_summary = "\n".join([
                f"Evidence {i+1} (confidence {result.get('truthfulness_confidence', 'n/a')}/100, "
                f"corroborated by {len(result.get('corroborating_domains', []))} other domain(s); "
                f"freshness {result.get('recency_confidence', 'n/a')}/100): "
                f"{_evidence_display_text(result, summary_sentences)}\n"
                f"Source: {result.get('url', 'unknown')}; captured: {result.get('captured_at') or 'unknown'}; "
                f"origin: {(result.get('provenance') or {}).get('origin') or result.get('search_provider', 'unknown')}; "
                f"verification: {result.get('verification_status', 'not independently verified')}"
                for i, result in enumerate(search_results[:evidence_limit])
                if result and 'content' in result
            ])
            if not context_summary:
                context_summary = "Search results found but no readable content available."
        except Exception as e:
            context_summary = f"Error processing search results: {str(e)}"
    else:
        context_summary = "No additional web context found."
    
    if deep:
        return f"""
        {datetime_context}
        The user asked: "{query}"

        Research evidence (confidence blends source reputation with how many
        independent domains corroborate the same facts; it is a heuristic, not
        verified fact-checking):
        {context_summary}

        Produce a Deep Think research brief. Work only from the evidence shown;
        do not repeat unverified claims from prior chat messages. Use these exact
        sections: Direct answer; Evidence and source assessment; Analysis;
        Alternative explanations or disagreements; Confidence and limitations;
        Sources. Cite source URLs beside material factual claims, and note next
        to each one whether it is corroborated by multiple independent domains
        or resting on a single source. Separate facts from your inferences,
        state what additional evidence would change the conclusion, and say
        "insufficient evidence" rather than guessing.
        """

    # Build the standard research prompt
    if is_concerning:
        conversation_prompt = f"""
        {datetime_context}
        User context: {user_context}
        
        The user asked about: "{query}"
        
        Retrieved evidence (saved knowledge is unverified background; source scores blend reputation with
        cross-source corroboration; it is a heuristic, not verified fact-checking):
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
        
        Retrieved evidence (saved knowledge is unverified background; source scores blend reputation with how
        many independent domains corroborate the same facts; it is a
        heuristic, not verified fact-checking):
        {context_summary}

        Answer from the evidence above, not from prior assistant messages or
        unstated background knowledge. Answer the latest question directly;
        ignore evidence about a different topic. For numerical facts, include
        the estimate's date and distinguish estimates from census counts when
        the evidence provides them. For a current or disputed fact, do not
        guess: if the evidence does not establish it, say so plainly, and do
        not invent names, dates, results, officeholders, quotes, prices, or
        source details. If no relevant evidence is available, explain briefly
        that you couldn't verify the requested fact; do not describe unrelated
        retrieved notes as the answer.

        Write like you're answering a person directly, not drafting a report:
        one to three sentences for a simple factual question, no restating
        the question, no citing a URL inline, and no closing disclaimer
        telling them to "check an official source", "verify with a
        financial advisor", or that things "may change" - only mention
        uncertainty when the evidence genuinely conflicts or is too thin to
        answer confidently. End the answer right after the actual answer,
        the same way a person would in conversation, not with a reflexive
        caveat sentence. Do not add unrelated user-profile observations.
        """
    
    return conversation_prompt


def review_draft_topic(user_prompt, draft, evidence=None):
    """Review a research draft for topic drift and requested-format failures."""
    if ollama is None or not (draft or "").strip():
        return draft
    evidence_text = "\n".join(
        f"- {item.get('title', 'Source')}: {item.get('content', '')[:500]}"
        for item in (evidence or [])[:5]
    ) or "(No evidence attached.)"
    review_prompt = (
        "You are the final response editor. Judge only the user's latest request. "
        "Return ONLY valid JSON in exactly this shape: "
        '{"on_topic": true|false, "format_satisfied": true|false, "reason": "short", "revised_answer": "..."}. '
        "Mark on_topic false if the draft changes subjects, follows unrelated evidence, or answers a different "
        "question. Mark format_satisfied false if it ignores an explicit count, list, table, or other requested "
        "format. If either is false, rewrite the answer to address the latest request directly. Do not invent "
        "facts, sources, titles, or details. If the request asks for recommendations, fulfill it directly rather "
        "than discussing whether an external source has an official list. If the draft passes, return it unchanged.\n\n"
        f"Latest user request:\n{user_prompt[:1000]}\n\n"
        f"Relevant evidence:\n{evidence_text}\n\n"
        f"Draft answer:\n{draft[:5000]}"
    )
    try:
        response = model_chat(model=MODELS['fast'], messages=[{"role": "system", "content": review_prompt}])
        parsed = json.loads(response.get("message", {}).get("content", ""))
        if not isinstance(parsed, dict):
            return draft
        on_topic = parsed.get("on_topic") is True
        format_satisfied = parsed.get("format_satisfied") is True
        revised = parsed.get("revised_answer")
        if on_topic and format_satisfied:
            return draft
        if isinstance(revised, str) and revised.strip():
            return revised.strip()
    except (ValueError, TypeError, json.JSONDecodeError, AttributeError):
        pass
    return draft


def _verify_evidence(answer_text, evidence, user_prompt=""):
    """Return fact-check findings plus bounded source provenance for tool callers."""
    findings = fact_check_answer(answer_text, evidence, user_prompt=user_prompt)
    return {
        "answer_text": answer_text,
        "user_prompt": user_prompt,
        "findings": findings,
        "has_findings": bool(findings),
        "evidence_count": len(evidence or []),
        "source_urls": [item.get("url") for item in (evidence or []) if item.get("url")],
    }


def fact_check_answer(answer_text, evidence, user_prompt=""):
    """Run an independent second pass that labels each claim in a drafted answer.

    The synthesis prompt above already asks the answering model to self-report
    confidence, but it's grading its own work. This spawns a separate pass with
    a Fact Checker persona that only sees the evidence and the finished answer,
    so it can catch claims that were stated more confidently than the evidence
    supports.

    `user_prompt` is what closes a real gap: corroboration used to mean only
    "do 2+ independent-domain sources agree with each other", with no check
    that they agree about the thing the user actually asked about. Two
    sources can agree with each other while both being about a same-titled
    but different book, or a same-named but different person - that used to
    get labeled [Corroborated] anyway. [Wrong entity] exists specifically for
    that case: source agreement doesn't count as corroboration if the sources
    agree about the wrong subject.

    [Unverified title] closes a related gap (Phase 6's titles/authors
    sanity check): a book/media recommendation naming a specific title or
    author that appears nowhere in the evidence at all has no source behind
    it - it may be an invented title or a misattributed author, not just a
    claim with weak support ([Unverified] already covers ordinary
    unsupported claims; this tag is specifically for named works/authors so
    that case is easy to spot rather than blending into the general bucket).
    Needed a stronger prompt than the first attempt to actually land: the
    model initially kept mislabeling a zero-source fabricated title as
    [Single source] (there is a real difference between "one source" and
    "zero sources," and the first prompt wording didn't make the model
    treat that difference as decisive) - verified live, not just in a unit
    test, since this is a model-judgment call like [Wrong entity] was.

    Unverified dollar figures (fabricated prices, in particular - see
    _fetch_stock_quote's docstring for the live evidence that motivated
    this) are deliberately NOT handled by asking this same LLM pass to add
    an [Unverified figure] tag the way [Unverified title] handles invented
    titles: tried that first, and live-tested it against the exact
    fabricated-price case that motivated this fix - the model tagged the
    identical "$308.67" figure both [Corroborated] and [Unverified figure]
    in adjacent bullets of the same response. "Does this exact digit
    sequence appear in this text" is a check code can do perfectly and a
    6B instruct model provably cannot, so _flag_unverified_dollar_figures
    below does it deterministically instead, and its output is appended
    after this LLM pass rather than folded into its prompt.
    """
    if ollama is None or not (answer_text or "").strip():
        return ""
    if not evidence:
        # No evidence at all - usually a live-lookup-shaped query (soccer/
        # weather/stock) whose tool selection failed or was wrongly
        # refused. The LLM checker pass below and the two evidence-diffing
        # flags after it all need real evidence to compare against, so
        # none of them can run here - see
        # _flag_unsupported_live_lookup_claim's docstring for the one
        # check that still can.
        return _flag_unsupported_live_lookup_claim(answer_text, user_prompt)
    evidence_lines = "\n".join(
        f"[{i + 1}] {item.get('url', 'unknown')} - corroborated by "
        f"{len(item.get('corroborating_domains', []))} other independent domain(s): "
        f"{item.get('content', '')[:300]}"
        for i, item in enumerate(evidence[:10])
    )
    checker_prompt = (
        "You are a Fact Checker. Below is the user's request, a drafted answer, and the web evidence "
        "it was based on. List each material factual claim in the answer as one short bullet line, and "
        "label it with exactly one tag:\n"
        "[Corroborated] if 2+ independent-domain sources support it AND those sources are clearly about "
        "the same person/book/entity the user actually asked about;\n"
        "[Wrong entity] if the sources agree with each other but are clearly about a different "
        "person/book/entity than the one the user asked about (e.g. a same-titled but different book, "
        "a same-named but different person) - source agreement does not count as corroboration if the "
        "sources agree about the wrong subject;\n"
        "[Single source] if only one source supports it;\n"
        "[Contradicted] if the evidence disagrees with it;\n"
        "[Unverified title] if the claim names a specific book, film, song, or other titled work (or "
        "its author) and that exact title does NOT appear anywhere in the evidence above, even if the "
        "answer is recommending or comparing it to a work that does appear in the evidence - check the "
        "title string itself against the evidence text, zero sources means [Unverified title], never "
        "[Single source] or [Corroborated];\n"
        "or [Unverified] if no evidence supports it and it does not name a specific titled work.\n"
        "Be terse - do not repeat the whole answer or add a preamble. If there are no checkable factual "
        "claims, respond with exactly: No factual claims to check.\n\n"
        f"User's request: {(user_prompt or '')[:500]}\n\n"
        f"Evidence:\n{evidence_lines}\n\nDrafted answer:\n{answer_text[:3000]}"
    )
    try:
        response = model_chat(model=MODELS['fast'], messages=[{"role": "system", "content": checker_prompt}])
        result = (response.get("message", {}).get("content") or "").strip()
        if not result or result.lower().startswith("no factual claims"):
            result = ""
    except Exception:
        result = ""
    figure_flags = _flag_unverified_dollar_figures(answer_text, evidence)
    next_match_flags = _flag_fabricated_next_match_claim(answer_text, evidence)
    all_flags = figure_flags + next_match_flags
    if all_flags:
        result = "\n".join(filter(None, [result, *all_flags]))
    return result


_ANSWER_DOLLAR_FIGURE_PATTERN = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")
_EVIDENCE_NUMBER_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _flag_unverified_dollar_figures(answer_text, evidence):
    """Deterministically flag a dollar figure stated in the answer that
    appears in none of the evidence content. See fact_check_answer's
    docstring for why this is plain code rather than another LLM
    instruction: exact substring matching is not something the local model
    can be trusted to get right on this task.

    Evidence is scanned for bare numbers, not just dollar-prefixed ones -
    a live quote (_stock_evidence_item) writes "487.31 USD", no "$" - and a
    whole-dollar answer figure is accepted if it's the rounded form of an
    evidence number (a model saying "$487" when evidence says "487.31" is
    reformatting a real figure, not fabricating one). Found both gaps by
    testing this function against its own live evidence output before
    shipping it, not just the original bug report.

    Scoped narrowly to dollar amounts (not percentages, dates, or other
    numbers) because that is the specific fabrication this was built to
    catch and it keeps false positives rare rather than routine.
    """
    evidence_text = " ".join(item.get("content", "") for item in evidence)
    evidence_numbers = {
        match.replace(",", "").strip()
        for match in _EVIDENCE_NUMBER_PATTERN.findall(evidence_text)
    }
    evidence_values = set()
    for number in evidence_numbers:
        try:
            evidence_values.add(round(float(number)))
        except ValueError:
            pass

    def is_supported(normalized):
        if normalized in evidence_numbers:
            return True
        if "." in normalized:
            return False
        try:
            return int(normalized) in evidence_values
        except ValueError:
            return False

    flagged = []
    seen = set()
    for match in _ANSWER_DOLLAR_FIGURE_PATTERN.findall(answer_text or ""):
        normalized = match.replace("$", "").replace(",", "").strip()
        if is_supported(normalized) or normalized in seen:
            continue
        seen.add(normalized)
        flagged.append(f"[Unverified figure] {match.strip()} does not appear in any evidence source and may be fabricated.")
    return flagged


# The exact marker string _soccer_evidence_item writes when
# _fetch_soccer_team_matches found no upcoming fixture - see
# _flag_fabricated_next_match_claim.
_NEXT_MATCH_UNKNOWN_MARKER = "Next match: UNKNOWN"
_NEXT_MATCH_CLAIM_PHRASES = (
    "next match", "next game", "next fixture", "play next", "next scheduled",
    "upcoming match", "upcoming fixture", "upcoming game",
)
_DATE_LIKE_PATTERN = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
    re.IGNORECASE,
)


def _flag_fabricated_next_match_claim(answer_text, evidence):
    """Deterministically flag an answer that states a specific "next match"
    date/opponent when the evidence explicitly found none
    (_soccer_evidence_item marks this UNKNOWN, not silence, precisely so
    there's something unambiguous to check against here).

    Live-tested and confirmed necessary, not just theoretical: even a
    forceful in-evidence instruction ("this is a PAST match, NOT the next
    one - you must say this information is not currently available") was
    not reliably followed in the real chat pipeline - the model fabricated
    an entirely new date instead of just relabeling the old one. Exact
    marker/phrase/date-pattern presence is a check code can do perfectly;
    a small local model respecting a negative instruction embedded in its
    own context is not - the same lesson _flag_unverified_dollar_figures
    already learned about this model tier, applied to a different failure
    shape.
    """
    if not any(_NEXT_MATCH_UNKNOWN_MARKER in item.get("content", "") for item in evidence):
        return []
    lowered = (answer_text or "").lower()
    if not any(phrase in lowered for phrase in _NEXT_MATCH_CLAIM_PHRASES):
        return []
    if not _DATE_LIKE_PATTERN.search(answer_text or ""):
        return []
    return [
        "[Unverified] The evidence found no scheduled next match (explicitly marked unknown), but the "
        "answer states one - treat any next-match date/opponent above as unconfirmed/possibly fabricated.",
    ]


_SCORE_LIKE_PATTERN = re.compile(r"\b\d{1,2}\s*-\s*\d{1,2}\b")


def _flag_unsupported_live_lookup_claim(answer_text, user_prompt):
    """Deterministically flag a specific-sounding claim (a date, a score, or
    a dollar figure) in the answer to a weather/stock/soccer-shaped
    question when fact_check_answer was given literally zero evidence to
    check it against.

    Covers a gap _flag_fabricated_next_match_claim and
    _flag_unverified_dollar_figures both leave open: both compare a claim
    against evidence that exists, but fact_check_answer never even reaches
    them when evidence is empty - which is exactly the case for a
    live-lookup query whose tool selection failed or was wrongly refused,
    rather than one that ran and came back empty-handed. Real, live-
    reported case: asked "who does Man United play next" right after
    live.soccer_result's tool call was wrongly refused as "outside scope",
    the model invented an opponent and date (Southampton, September 5,
    2026) from nothing at all. With zero evidence there's also nothing for
    an LLM checker pass to compare against, so this is the only check left
    that can catch it - "does this answer sound this specific about a live
    fact and did we retrieve any live fact at all" is something code can
    tell perfectly, the same lesson the other two flags already apply to a
    different failure shape.

    Also in scope: a prompt matching a user subscription (core/
    subscriptions.py) - the same "supposed to be grounded in a live source,
    zero evidence means nothing backs this claim" logic applies whether the
    live source was a regex-detected weather/stock/soccer shape or a
    subscribed team/topic/website whose handler failed or found nothing.
    """
    if not (
        _looks_like_soccer_query(user_prompt) or _looks_like_weather_query(user_prompt)
        or _looks_like_stock_query(user_prompt) or _matching_subscription(user_prompt)
    ):
        return ""
    answer_text = answer_text or ""
    has_specific_claim = (
        bool(_DATE_LIKE_PATTERN.search(answer_text))
        or bool(_SCORE_LIKE_PATTERN.search(answer_text))
        or bool(_ANSWER_DOLLAR_FIGURE_PATTERN.search(answer_text))
    )
    if not has_specific_claim:
        return ""
    return (
        "[Unverified] No live data was actually retrieved for this question - the tool lookup failed or "
        "was skipped - so any specific date, score, or figure in the answer above is unconfirmed and may "
        "be entirely fabricated."
    )

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
    },
    'scheduler': {
        'name': 'Cron Scheduler',
        'description': 'Freely creates, edits, lists, and removes real scheduled (cron) tasks from natural-language requests',
        'knowledge_path': 'agent_knowledge/cron_scheduler',
        'persona': (
            'You are the Cron Scheduler agent. You manage the user\'s real system cron tasks - recurring jobs '
            'that run on a schedule even when no one is chatting with you. You have full, standing permission '
            'to add, edit, and remove tasks whenever the user\'s request clearly calls for it - you never need '
            'to ask "should I go ahead?" once you understand what they want. '
            'Important: you are only ever shown to the user for two things - asking what you still need to '
            'know, or plain conversation about scheduling. The moment a request has enough information (a '
            'clear schedule AND clear content), a separate step builds or edits or removes the real task '
            'automatically and shows the user an exact, code-generated confirmation - your own reply is '
            'skipped entirely for that turn, on purpose, because a task is real system state and its '
            'confirmation must be exactly accurate, not paraphrased. So: never describe a task as already '
            'created, edited, or removed - by the time you would say so, either it genuinely happened (and '
            'the user already saw the real confirmation, not from you) or you don\'t yet have enough '
            'information and should be asking, not claiming. Never invent or describe a shell script, bash '
            'command, or any other implementation detail - a task can only ever do one of three things: run '
            'a saved prompt through the assistant, run one of the built-in features (historian, '
            'historian_preview, news), or sound a real audible-plus-visual alarm (a system sound and a '
            'notification banner) with a short message - there is no script behind any of these, and if '
            'asked to schedule a raw shell command you refuse and explain why. Use the alarm option whenever '
            'the user wants to actually be alerted, woken up, or notified with sound (an alarm clock, a '
            'timer, "remind me" in the sense of interrupting them) rather than just receive generated text; '
            'use a prompt when they want the assistant to produce fresh written content each time instead. '
            'When information is missing, ask exactly what\'s missing in one direct question rather than '
            'guessing or filling in a plausible-sounding default. When asked to change or remove a task and '
            'more than one existing task could plausibly match, name the candidates and ask which one rather '
            'than guessing. You are talking with the person who owns this machine and its crontab - be direct '
            'and concrete, not overly cautious about the concept of scheduling itself.'
        )
    }
}

def get_agent_knowledge(agent_name):
    """Load knowledge base content for a specific agent"""
    if agent_name not in AVAILABLE_AGENTS:
        return ""
    
    agent_path = os.path.join(core_config.project_root(), AVAILABLE_AGENTS[agent_name]['knowledge_path'])
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
                    except OSError:
                        pass
    
    return "\n".join(knowledge_content) if knowledge_content else "No specialized knowledge base found."

# -------------------------------------
# Agent Memory System
# -------------------------------------
def load_agent_memory(agent_name):
    """Load conversation memory for a specific agent"""
    if not agent_name:
        return []
    
    memory_path = os.path.join(core_config.project_root(), "agent_memory")
    if not os.path.exists(memory_path):
        os.makedirs(memory_path)
    
    memory_file = os.path.join(memory_path, f"{agent_name}_memory.json")
    
    if os.path.exists(memory_file):
        try:
            with open(memory_file, 'r', encoding='utf-8') as f:
                memory_data = json.load(f)
                return memory_data.get('conversations', [])
        except (OSError, json.JSONDecodeError):
            pass

    return []

def save_agent_memory(agent_name, conversation_summary):
    """Save important conversation points for agent memory"""
    if not agent_name or not conversation_summary:
        return

    memory_path = os.path.join(core_config.project_root(), "agent_memory")
    if not os.path.exists(memory_path):
        os.makedirs(memory_path)

    memory_file = os.path.join(memory_path, f"{agent_name}_memory.json")

    # Load existing memory
    memory_data = {'conversations': []}
    if os.path.exists(memory_file):
        try:
            with open(memory_file, 'r', encoding='utf-8') as f:
                memory_data = json.load(f)
        except (OSError, json.JSONDecodeError):
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
    entries = memory_data['conversations']
    pinned = [entry for entry in entries if entry.get('pinned')][-20:]
    remaining = 20 - len(pinned)
    recent = [entry for entry in entries if not entry.get('pinned')][-remaining:] if remaining else []
    memory_data['conversations'] = sorted(pinned + recent, key=lambda entry: entry.get('date', ''))

    # Save updated memory
    try:
        with open(memory_file, 'w', encoding='utf-8') as f:
            json.dump(memory_data, f, indent=2, ensure_ascii=False)
        events.publish(MEMORY_CREATED, agent_name=agent_name)
    except OSError as e:
        print(f"{Fore.YELLOW}⚠️  Failed to save agent memory for {agent_name}: {e}{Style.RESET_ALL}")

def update_agent_memory(agent_name, entry_date, *, summary=None, pinned=None, forget=False):
    """Edit a user-selected memory entry without changing other stored entries."""
    if not re.fullmatch(r"[a-z_]+", agent_name or ""):
        raise ValueError("Invalid agent memory name")
    path = os.path.join(core_config.project_root(), "agent_memory", f"{agent_name}_memory.json")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    entries = data.get("conversations", [])
    entry = next((item for item in entries if item.get("date") == entry_date), None)
    if entry is None:
        raise ValueError("This memory entry has changed or was removed. Reopen memory controls.")
    if forget:
        entries.remove(entry)
    else:
        if summary is not None:
            summary = summary.strip()
            if not summary:
                raise ValueError("Memory text cannot be empty")
            entry["summary"] = summary[:4000]
            entry["topics"] = extract_topics_from_summary(entry["summary"])
        if pinned is not None:
            entry["pinned"] = bool(pinned)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    os.replace(temporary, path)
    return entry

def extract_topics_from_summary(summary):
    """Extract key topics from conversation summary for memory indexing"""
    # Simple keyword extraction - could be enhanced with NLP
    common_words = {
        'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by',
        'is', 'was', 'are', 'were', 'a', 'an',
        # save_agent_memory's stored summaries always start "User: ...
        # Response: ..." - strip those labels too, or they end up as
        # spurious "topics" every memory entry shares, causing unrelated
        # future prompts to falsely match old memories.
        'user', 'response',
    }
    words = [word.strip('.,!?:') for word in summary.lower().split()]
    topics = [word for word in words if len(word) > 3 and word not in common_words]
    return list(set(topics))[:10]  # Return up to 10 unique topics

def get_relevant_agent_memory(agent_name, current_topic):
    """Get relevant past conversations for current context"""
    memory = load_agent_memory(agent_name)
    if not memory:
        return ""
    
    # Simple relevance matching - could be enhanced
    relevant_conversations = []
    current_words = set(current_topic.lower().split())
    
    for conv in memory:  # Pinned entries survive the normal recent-memory window.
        topics = conv.get('topics', [])
        if conv.get("pinned") or any(topic in current_words for topic in topics):
            relevant_conversations.append(conv)
    
    if relevant_conversations:
        context = "\n=== Relevant Past Conversations ===\nHistorical conversation notes are unverified memory, not independent factual evidence. Follow the current user request.\n"
        selected = sorted(relevant_conversations, key=lambda conv: (bool(conv.get('pinned')), conv.get('date', '')), reverse=True)[:3]
        for conv in reversed(selected):
            # summary is already bounded at write time (save_agent_memory /
            # _on_task_completed) - re-truncating here ate into it a second
            # time, usually cutting the actual response fragment down to
            # near-nothing mid-word.
            context += f"Date: {conv['date'][:10]} - {conv['summary']}\n"
        return context
    
    return ""

def switch_agent(agent_name):
    """Switch to a specialized agent persona"""
    
    if agent_name is None or agent_name == 'default':
        context.current_agent = None
        return "Switched to default mode."
    
    if agent_name not in AVAILABLE_AGENTS:
        available = ', '.join(AVAILABLE_AGENTS.keys())
        return f"Unknown agent '{agent_name}'. Available agents: {available}"
    
    context.current_agent = agent_name
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
    
    context.assistant_convo.append({"role": "system", "content": persona_prompt})
    
    return f"✨ Switched to {agent_info['name']} agent.\n{agent_info['description']}\n\nHow can I assist you from this specialized perspective?"

def setup_multi_agent_collaboration(agent_names):
    """Setup collaboration between multiple agents"""
    
    valid_agents = []
    for agent_name in agent_names:
        if agent_name in AVAILABLE_AGENTS:
            valid_agents.append(agent_name)
    
    if not valid_agents:
        return "No valid agents specified for collaboration."
    
    # Set primary agent as current
    context.current_agent = valid_agents[0]
    
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

Respond as a collaborative team of specialized agents, with {AVAILABLE_AGENTS[context.current_agent]['name']} taking the lead.
"""
    
    context.assistant_convo.append({"role": "system", "content": collaboration_prompt})
    
    agent_names_formatted = [AVAILABLE_AGENTS[name]['name'] for name in valid_agents]
    return f"🤝 Collaborative mode activated!\n\nActive agents: {', '.join(agent_names_formatted)}\nLead agent: {AVAILABLE_AGENTS[context.current_agent]['name']}\n\nHow can our team assist you?"

def job_command(args=None):
    """Handle the /job command with support for multi-agent collaboration"""
    if not args:
        # Show available agents
        result = "🤖 Available Agent Personas:\n\n"
        for key, agent in AVAILABLE_AGENTS.items():
            status = " (ACTIVE)" if context.current_agent == key else ""
            result += f"**{key}**: {agent['name']}{status}\n"
            result += f"   └─ {agent['description']}\n\n"
        
        result += f"Current agent: {AVAILABLE_AGENTS[context.current_agent]['name'] if context.current_agent else 'Default mode'}\n"
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
    """Returns True on a real write, False on failure - a caller that
    reports "saved" back to the user (e.g. ResearchTopicSkill) needs this
    to be honest rather than assuming success just because no exception
    reached it."""
    kb_path = os.path.join(core_config.project_root(), "knowledge_base")
    if not os.path.exists(kb_path):
        os.makedirs(kb_path)
    safe_filename = sanitize_filename(filename)
    file_path = os.path.join(kb_path, safe_filename)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        return False
    events.publish(KNOWLEDGE_UPDATED, filename=safe_filename)
    return True

def record_learning_path(topic, resources):
    tutor_path = os.path.join(core_config.project_root(), "tutor_paths")
    if not os.path.exists(tutor_path):
        os.makedirs(tutor_path)
    safe_filename = sanitize_filename(topic) + ".txt"
    file_path = os.path.join(tutor_path, safe_filename)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(resources))
    except OSError as e:
        print(f"{Fore.YELLOW}⚠️  Failed to save learning path for {topic!r}: {e}{Style.RESET_ALL}")

def load_learning_paths():
    tutor_path = os.path.join(core_config.project_root(), "tutor_paths")
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
            except OSError:
                pass
    return paths

learning_paths = load_learning_paths()

def search_knowledge_base(topic):
    from core.knowledge_retrieval import search
    return search(os.path.join(core_config.project_root(), "knowledge_base"), topic)

# -------------------------------------
# Self-Improvement Workflow
# -------------------------------------

def audit_repository():
    root = core_config.project_root()
    total_files = 0
    total_dirs = 0
    total_lines = 0
    ext_counts = {}
    todos = []
    large_files = []
    tests_present = False

    for dirpath, dirnames, filenames in os.walk(root):
        if '.git' in dirnames:
            dirnames.remove('.git')
        if 'venv' in dirnames:
            dirnames.remove('venv')
        if '__pycache__' in dirnames:
            dirnames.remove('__pycache__')

        total_dirs += len(dirnames)
        for filename in filenames:
            if filename.startswith('.'):
                continue
            path = os.path.join(dirpath, filename)
            total_files += 1
            ext = os.path.splitext(filename)[1].lower() or '<noext>'
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            try:
                if path.endswith('.py'):
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()
                    total_lines += len(lines)
                    for idx, line in enumerate(lines, start=1):
                        if any(marker in line for marker in ['TODO', 'FIXME', 'HACK']):
                            todos.append(f"{path}:{idx}: {line.strip()}")
                if os.path.getsize(path) > 200_000:
                    large_files.append((os.path.getsize(path), path))
            except Exception:
                pass

        if os.path.basename(dirpath).lower() in ('tests', 'test'):
            tests_present = True

    ext_summary = '\n'.join([f"  {ext}: {count}" for ext, count in sorted(ext_counts.items(), key=lambda item: (-item[1], item[0]))[:20]])
    todo_summary = '\n'.join(todos[:20]) if todos else '  No TODO/FIXME comments found.'
    large_summary = '\n'.join([f"  {size // 1024} KB - {path}" for size, path in sorted(large_files, reverse=True)[:10]])
    if not large_summary:
        large_summary = '  No large files detected.'

    return "\n".join([
        f"Repository root: {root}",
        f"Total directories: {total_dirs}",
        f"Total files: {total_files}",
        f"Total Python lines: {total_lines}",
        "Top file types:",
        ext_summary,
        "Large files:",
        large_summary,
        "TODO/FIXME findings:",
        todo_summary,
        f"Tests folder present: {'Yes' if tests_present else 'No'}"
    ])


def audit_repository_advanced():
    """A second, higher-level audit pass: README quality, test-suite
    presence (file counts, not measured coverage percentage - that needs
    running the tests under a coverage tool, a separate and heavier concern),
    CI config detection, and docs health. Complements audit_repository()'s
    file/line/TODO stats rather than replacing them."""
    root = core_config.project_root()

    readme_path = None
    for candidate in ("README.md", "README.rst", "README.txt", "readme.md", "readme.txt"):
        full = os.path.join(root, candidate)
        if os.path.isfile(full):
            readme_path = full
            break
    if readme_path is None:
        readme_report = "No README found."
    else:
        with open(readme_path, "r", encoding="utf-8", errors="ignore") as f:
            readme_text = f.read()
        word_count = len(readme_text.split())
        sections = [s for s in ("install", "usage", "setup", "getting started") if s in readme_text.lower()]
        readme_report = (
            f"{os.path.basename(readme_path)}: {word_count} words, "
            f"sections found: {', '.join(sections) if sections else 'none'}"
            + (" - thin, consider expanding" if word_count < 100 else "")
        )

    test_files, source_files = [], []
    for dirpath, dirnames, filenames in os.walk(root):
        if '.git' in dirnames:
            dirnames.remove('.git')
        if 'venv' in dirnames:
            dirnames.remove('venv')
        if '__pycache__' in dirnames:
            dirnames.remove('__pycache__')
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            if filename.startswith("test_") or filename.endswith("_test.py"):
                test_files.append(os.path.join(dirpath, filename))
            else:
                source_files.append(os.path.join(dirpath, filename))
    coverage_config = any(
        os.path.isfile(os.path.join(root, name)) for name in (".coveragerc", "pyproject.toml", "setup.cfg")
    )
    test_report = (
        f"{len(test_files)} test file(s) found for {len(source_files)} non-test .py file(s)"
        f"{' (coverage config present)' if coverage_config else ' (no coverage config found)'}"
    )

    ci_candidates = {
        "GitHub Actions": os.path.join(root, ".github", "workflows"),
        "GitLab CI": os.path.join(root, ".gitlab-ci.yml"),
        "CircleCI": os.path.join(root, ".circleci", "config.yml"),
        "Travis CI": os.path.join(root, ".travis.yml"),
        "Jenkins": os.path.join(root, "Jenkinsfile"),
        "Azure Pipelines": os.path.join(root, "azure-pipelines.yml"),
    }
    ci_found = []
    for name, path in ci_candidates.items():
        if os.path.isdir(path):
            workflow_files = [f for f in os.listdir(path) if f.endswith((".yml", ".yaml"))]
            if workflow_files:
                ci_found.append(f"{name} ({len(workflow_files)} workflow file(s))")
        elif os.path.isfile(path):
            ci_found.append(name)
    ci_report = ", ".join(ci_found) if ci_found else "No CI configuration found."

    docs_dir = os.path.join(root, "docs")
    if not os.path.isdir(docs_dir):
        docs_report = "No docs/ directory found."
    else:
        doc_files = [f for f in os.listdir(docs_dir) if f.endswith(".md")]
        empty_docs = [f for f in doc_files if os.path.getsize(os.path.join(docs_dir, f)) == 0]
        docs_report = f"{len(doc_files)} doc file(s) in docs/"
        if empty_docs:
            docs_report += f", {len(empty_docs)} empty: {', '.join(empty_docs)}"

    return "\n".join([
        f"Repository root: {root}",
        "README quality:",
        f"  {readme_report}",
        "Test suite presence:",
        f"  {test_report}",
        "CI configuration:",
        f"  {ci_report}",
        "Docs health:",
        f"  {docs_report}",
    ])


def load_todo_list(root):
    todo_path = os.path.join(root, "TODO.md")
    if not os.path.exists(todo_path):
        return None
    try:
        with open(todo_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read().strip()
        return content if content else None
    except Exception:
        return None


_SELFIMPROVE_MAX_TARGET_BYTES = 80_000
# Defense-in-depth alongside the size cap above: even if webagent.py were ever
# split into smaller files, the pipeline must never pick itself (or this
# module) as an edit target.
_SELFIMPROVE_DENYLIST = {"webagent.py", "webagent_gui.py", "nightly.py", "core/knowledge_maintenance.py", "core/autonomous_research.py", "scripts/install_nightly.py"}
_SELFIMPROVE_REPORTS_DIRNAME = "selfimprove_reports"
_SELFIMPROVE_STATE_FILENAME = ".last_run.json"


def _selfimprove_root():
    return core_config.project_root()


def _git(*args):
    """Run a git command in the repo root. Returns (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(["git", *args], cwd=_selfimprove_root(), capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 1, "", "git not available"


def _is_worktree_clean():
    code, out, _ = tool_registry.execute("git.status")
    return code == 0 and not out.strip()


def _dirty_paths():
    code, out, _ = tool_registry.execute("git.status")
    if code != 0:
        return []
    paths = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        # porcelain format: "XY path" (or "XY path -> path" for renames)
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            paths.append(parts[1].split(" -> ")[-1].strip())
    return paths


def _git_tracked_files():
    code, out, _ = _git("ls-files")
    if code != 0:
        return set()
    return set(out.splitlines())


def _selfimprove_reports_dir():
    reports_dir = os.path.join(_selfimprove_root(), "knowledge_base", _SELFIMPROVE_REPORTS_DIRNAME)
    os.makedirs(reports_dir, exist_ok=True)
    return reports_dir


def _load_selfimprove_state():
    state_path = os.path.join(_selfimprove_reports_dir(), _SELFIMPROVE_STATE_FILENAME)
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_selfimprove_state(touched_paths):
    state_path = os.path.join(_selfimprove_reports_dir(), _SELFIMPROVE_STATE_FILENAME)
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump({"touched_paths": touched_paths, "recorded_at": datetime.now().isoformat()}, f, indent=2)
    except Exception:
        pass


def _write_selfimprove_report(status, body):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(_selfimprove_reports_dir(), f"selfimprove_{timestamp}.md")
    content = f"# Self-improve run — {status}\n\n{body}\n"
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        pass
    return content


def _selfimprove_coding_chat(system_prompt, user_prompt):
    if ollama is None:
        return None
    try:
        response = model_chat(model=MODELS['coding'], messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        return response.get('message', {}).get('content', '').strip()
    except Exception:
        return None


def _select_self_improve_candidate(audit_text, todo_text):
    system_prompt = (
        "You are an autonomous self-improvement assistant for a Python repository. "
        "Given a repository audit (and optionally a TODO list for context), propose exactly ONE "
        "small, concretely scoped improvement to a single existing Python file. "
        "Respond with ONLY a JSON object, no other text, in the form: "
        '{"target_file": "relative/path.py", "issue": "what is wrong", "proposed_fix_summary": "what you would change"}'
    )
    user_prompt = f"Repository audit:\n\n{audit_text}\n"
    if todo_text:
        user_prompt += f"\nProject TODO list (optional context, not a hard restriction):\n\n{todo_text}\n"
    raw = _selfimprove_coding_chat(system_prompt, user_prompt)
    if not raw:
        return None, "the coding model was unavailable or returned nothing"

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None, "could not find a JSON object in the model's response"
    try:
        candidate = json.loads(match.group(0))
    except Exception as e:
        return None, f"the model's JSON was invalid: {e}"

    target_file = candidate.get("target_file", "").strip().lstrip("/")
    if not target_file:
        return None, "the model did not name a target file"
    if os.path.basename(target_file) in _SELFIMPROVE_DENYLIST:
        return None, f"'{target_file}' is on the self-improve denylist (it implements this pipeline)"
    if not target_file.endswith(".py"):
        return None, f"'{target_file}' is not a Python file"
    if target_file not in _git_tracked_files():
        return None, f"'{target_file}' is not an existing, git-tracked file"
    abs_path = os.path.join(_selfimprove_root(), target_file)
    try:
        size = os.path.getsize(abs_path)
    except OSError:
        return None, f"'{target_file}' could not be read"
    if size > _SELFIMPROVE_MAX_TARGET_BYTES:
        return None, f"'{target_file}' is {size} bytes, over the {_SELFIMPROVE_MAX_TARGET_BYTES}-byte self-improve cap"

    candidate["target_file"] = target_file
    return candidate, None


_SELFIMPROVE_FILE_BLOCK_RE = re.compile(r"^###\s+(\S+)\s*$", re.MULTILINE)


def _parse_single_file_block(raw, expected_path):
    """Parse a `### {relpath}` + fenced code block from a model response,
    where the header matches expected_path.
    Returns the block's content, or None."""
    if not raw:
        return None
    match = None
    for candidate_match in _SELFIMPROVE_FILE_BLOCK_RE.finditer(raw):
        if candidate_match.group(1) == expected_path:
            match = candidate_match
            break
    if not match:
        return None
    after_header = raw[match.end():]
    fence_start = after_header.find("```")
    if fence_start == -1:
        return None
    after_fence = after_header[fence_start + 3:]
    # Skip an optional language tag right after the opening fence.
    newline_idx = after_fence.find("\n")
    if newline_idx != -1 and after_fence[:newline_idx].strip().isalpha():
        after_fence = after_fence[newline_idx + 1:]
    fence_end = after_fence.find("```")
    if fence_end == -1:
        return None
    return after_fence[:fence_end]


def _generate_file_fix(target_file, current_content, issue):
    system_prompt = (
        "You are fixing one issue in one Python file. You will be given the file's full current "
        "content and the issue to fix. Respond with the file's COMPLETE new content (the whole "
        "file, not a diff or a snippet) formatted as:\n\n"
        f"### {target_file}\n```python\n<full new file content>\n```\n\n"
        "Output nothing else - no explanation before or after."
    )
    user_prompt = f"Issue to fix:\n{issue}\n\nCurrent content of {target_file}:\n\n{current_content}"
    raw = _selfimprove_coding_chat(system_prompt, user_prompt)
    new_content = _parse_single_file_block(raw, target_file)
    if new_content is None:
        return None, "could not parse a valid file replacement from the model's response"

    original_lines = current_content.count("\n") + 1
    new_lines = new_content.count("\n") + 1
    if new_lines < original_lines * 0.5:
        return None, (
            f"the model's replacement looks truncated ({new_lines} lines vs. {original_lines} original) "
            "and was discarded"
        )
    return new_content, None


def _module_name_for_path(target_file):
    return os.path.splitext(os.path.basename(target_file))[0]


def _test_path_for_module(module_name):
    return os.path.join("tests", f"test_{module_name}.py")


def _generate_test_for_fix(target_file, new_content, issue):
    module_name = _module_name_for_path(target_file)
    test_rel_path = _test_path_for_module(module_name)
    test_abs_path = os.path.join(_selfimprove_root(), test_rel_path)
    existing_test = None
    if os.path.exists(test_abs_path):
        try:
            with open(test_abs_path, "r", encoding="utf-8") as f:
                existing_test = f.read()
        except Exception:
            existing_test = None

    system_prompt = (
        "You are writing a Python unittest test for a fix that was just applied to one file. "
        f"You will be given the fixed file's new content ({target_file}, importable as module "
        f"'{module_name}') and the issue it fixes. Respond with ONE complete test file's content "
        "(using Python's unittest, importing from the module by name) formatted as:\n\n"
        f"### {test_rel_path}\n```python\n<full test file content>\n```\n\n"
        "The test file MUST contain at least one real assertion (assertEqual/assertTrue/etc., not "
        "just `assert True`) that exercises something imported from the fixed module. "
        "Output nothing else - no explanation before or after."
    )
    user_prompt = f"Issue that was fixed:\n{issue}\n\nNew content of {target_file}:\n\n{new_content}"
    if existing_test:
        user_prompt += f"\n\nExisting test file to extend/update ({test_rel_path}):\n\n{existing_test}"
        system_prompt += f" An existing test file at {test_rel_path} is provided - update it, don't discard its other tests."

    raw = _selfimprove_coding_chat(system_prompt, user_prompt)
    test_content = _parse_single_file_block(raw, test_rel_path)
    if test_content is None:
        return None, None, "could not parse a valid test file from the model's response"

    if not _test_has_real_assertion(test_content, module_name):
        return None, None, "the generated test has no real assertion referencing the fixed module"

    return test_rel_path, test_content, None


def _test_has_real_assertion(test_content, module_name):
    try:
        tree = ast.parse(test_content)
    except SyntaxError:
        return False

    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module_name:
            imported_names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module_name:
                    imported_names.add(alias.asname or alias.name)

    if not imported_names:
        return False

    names_used_in_asserts = set()
    for node in ast.walk(tree):
        is_assert_call = (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr.startswith("assert")
            and node.func.attr != "assertTrue"
        ) or isinstance(node, ast.Assert)
        if not is_assert_call:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                names_used_in_asserts.add(sub.id)
            elif isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
                names_used_in_asserts.add(sub.value.id)

    return bool(imported_names & names_used_in_asserts)


def _run_self_improve_tests(cwd=None):
    """`cwd` defaults to the live repo (_selfimprove_root()) for the
    registered test.run tool's sake; run_self_improve_cycle passes its
    sandbox Workspace's path instead, so this never runs against the live
    checkout during a candidate fix attempt."""
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
    try:
        proc = subprocess.run(cmd, cwd=cwd or _selfimprove_root(), capture_output=True, text=True)
    except Exception as e:
        events.publish(TEST_FAILED, reason=str(e))
        return False, f"could not run the test suite: {e}"

    match = re.search(r"Ran (\d+) tests?", proc.stderr)
    ran = int(match.group(1)) if match else 0
    output = (proc.stdout + "\n" + proc.stderr).strip()
    if proc.returncode != 0:
        events.publish(TEST_FAILED, reason="test suite failed")
        return False, f"test suite failed:\n{output}"
    if ran == 0:
        events.publish(TEST_FAILED, reason="vacuous pass (0 tests collected)")
        return False, f"test suite reported 0 tests collected (vacuous pass):\n{output}"
    events.publish(TEST_PASSED, tests_ran=ran)
    return True, output


def run_self_improve_cycle(dry_run=False):
    """Analyze the repo, propose and apply one small fix with a test, validate
    it, and either leave it staged for human review or revert it. Never
    commits. Returns (success: bool, report_text: str).

    `dry_run=True` runs every step identically - candidate selection, fix
    generation, writing, compiling, testing - but stops short of
    `workspace.merge_back()` on the success path, reporting the verified
    diff instead of ever touching the live repo. This only became a real,
    honest answer to "what does a preview show" once the sandbox existed
    to build and test the fix somewhere real without the live repo being
    at risk while doing it - see TODO.md Phase 6's rollback-preview item.

    Note the returned `success` is always True - it means "the cycle ran to
    completion without crashing," not "a fix was applied" (a correctly
    skipped or reverted run is still a successful *cycle*). The real,
    structured outcome - whether the fix itself worked - is recorded
    separately as a Phase 5 Experience via the local _record() helper below,
    since this boolean was never expressive enough to carry that."""
    def _record(goal, tools_used, success, result, plan=""):
        record_experience(build_experience(
            goal=goal, plan=plan, tools_used=tools_used, result=result,
            success=success, agent="self-improve",
        ))

    if not _is_worktree_clean():
        dirty = _dirty_paths()
        last_state = _load_selfimprove_state()
        last_touched = set(last_state.get("touched_paths", [])) if last_state else set()
        if last_touched and set(dirty) <= last_touched:
            report = _write_selfimprove_report(
                "blocked",
                f"Skipped: last run's change is still uncommitted and awaiting review:\n" + "\n".join(dirty),
            )
        else:
            report = _write_selfimprove_report(
                "blocked",
                "Skipped: the working tree has unrelated uncommitted changes:\n" + "\n".join(dirty),
            )
        _record("Run a self-improve cycle", ["git.status"], None, report)
        return True, report

    audit_text = tool_registry.execute("repo.audit")
    todo_text = load_todo_list(_selfimprove_root())

    candidate, reason = _select_self_improve_candidate(audit_text, todo_text)
    if candidate is None:
        report = _write_selfimprove_report("no candidate", f"No change made: {reason}.")
        _record("Find a self-improvement candidate", ["repo.audit"], None, report)
        return True, report

    target_file = candidate["target_file"]
    issue = candidate.get("issue", "")
    goal = f"Fix {target_file}: {issue}"

    if is_stuck_goal(goal, agent="self-improve"):
        report = _write_selfimprove_report(
            "no candidate",
            f"No change made: '{goal}' has failed repeatedly in recent cycles - skipping it "
            "rather than retrying the same goal again unchanged. See /learning for details.",
        )
        _record("Find a self-improvement candidate", ["repo.audit"], None, report)
        return True, report

    try:
        workspace_cm = Workspace(_selfimprove_root())
        workspace = workspace_cm.__enter__()
    except RuntimeError as e:
        report = _write_selfimprove_report("error", f"Could not create a sandbox workspace: {e}")
        _record(goal, ["repo.audit"], False, report)
        return True, report

    try:
        # Everything below reads/writes/compiles/tests inside `workspace.path`,
        # an isolated git worktree - never the live checkout. On any failure
        # path there is nothing to revert: the live repo was never touched,
        # and the workspace is destroyed on __exit__ regardless. The live repo
        # is only ever written to below, via workspace.merge_back(), on the
        # one path that actually keeps a change.
        abs_target = os.path.join(workspace.path, target_file)
        try:
            with open(abs_target, "r", encoding="utf-8") as f:
                current_content = f.read()
        except Exception as e:
            report = _write_selfimprove_report("error", f"Could not read candidate target '{target_file}': {e}")
            _record(goal, ["repo.audit"], False, report)
            return True, report

        new_content, reason = _generate_file_fix(target_file, current_content, issue)
        if new_content is None:
            report = _write_selfimprove_report(
                "no fix", f"Candidate: {target_file} - {issue}\n\nNo change made: {reason}."
            )
            _record(goal, ["repo.audit"], False, report)
            return True, report

        test_rel_path, test_content, reason = _generate_test_for_fix(target_file, new_content, issue)
        if test_content is None:
            report = _write_selfimprove_report(
                "no test", f"Candidate: {target_file} - {issue}\n\nNo change made: {reason}."
            )
            _record(goal, ["repo.audit"], False, report)
            return True, report

        test_abs_path = os.path.join(workspace.path, test_rel_path)

        try:
            with open(abs_target, "w", encoding="utf-8") as f:
                f.write(new_content)
            os.makedirs(os.path.dirname(test_abs_path), exist_ok=True)
            with open(test_abs_path, "w", encoding="utf-8") as f:
                f.write(test_content)
        except Exception as e:
            report = _write_selfimprove_report("error", f"Failed writing changes for '{target_file}': {e}")
            _record(goal, ["repo.audit"], False, report)
            return True, report

        compile_errors = []
        for path in (abs_target, test_abs_path):
            try:
                import py_compile
                py_compile.compile(path, doraise=True)
            except Exception as e:
                compile_errors.append(f"{path}: {e}")

        if compile_errors:
            _, diff, _ = workspace.run("git", "diff")
            report = _write_selfimprove_report(
                "reverted",
                f"Candidate: {target_file} - {issue}\n\nReverted: compile errors:\n"
                + "\n".join(compile_errors) + f"\n\nAttempted diff:\n{diff}",
            )
            _record(goal, ["repo.audit", "git.diff"], False, report)
            return True, report

        tests_passed, test_output = _run_self_improve_tests(cwd=workspace.path)
        if not tests_passed:
            _, diff, _ = workspace.run("git", "diff")
            report = _write_selfimprove_report(
                "reverted",
                f"Candidate: {target_file} - {issue}\n\nReverted: {test_output}\n\nAttempted diff:\n{diff}",
            )
            _record(goal, ["repo.audit", "test.run", "git.diff"], False, report)
            return True, report

        plan = candidate.get('proposed_fix_summary', '')
        _, diff, _ = workspace.run("git", "diff")
        # Phase 11: a real diff a human is actually about to look at (kept
        # or previewed, never a reverted/discarded one nobody will read) -
        # informational only, see reviewers/__init__.py's stance.
        reviews = run_review_panel(diff, _selfimprove_coding_chat)
        recommendation = summarize_reviews(reviews.values(), tests_passed=True)
        review_section = (
            "\n--- Engineering team review (informational only) ---\n"
            f"Security: {reviews['security']}\n"
            f"Performance: {reviews['performance']}\n"
            f"Documentation: {reviews['documentation']}\n"
            f"Release Manager: {recommendation}\n"
        )

        if dry_run:
            report = _write_selfimprove_report(
                "dry run",
                f"Candidate: {target_file}\nIssue: {issue}\nFix: {plan}\n\n"
                f"Test output:\n{test_output}\n\n"
                "Dry run - the live repo was never touched. Preview of what would be applied:\n"
                f"{diff}{review_section}",
            )
            _record(goal, ["repo.audit", "test.run"], True, report, plan=plan)
            return True, report

        workspace.merge_back([target_file, test_rel_path])
        _save_selfimprove_state([target_file, test_rel_path])
        report = _write_selfimprove_report(
            "applied",
            f"Candidate: {target_file}\nIssue: {issue}\nFix: {plan}\n\n"
            f"Test output:\n{test_output}\n\n"
            f"Changed files (uncommitted, staged for review): {target_file}, {test_rel_path}\n"
            f"Review with `git diff` and commit manually if it looks good.{review_section}",
        )
        _record(goal, ["repo.audit", "test.run"], True, report, plan=plan)
        return True, report
    finally:
        workspace_cm.__exit__(None, None, None)


def perform_self_improve(dry_run=False):
    label = "dry run" if dry_run else "workflow"
    print(f"{Fore.CYAN}🚀 Starting /selfimprove {label}...{Style.RESET_ALL}")
    success, report = run_self_improve_cycle(dry_run=dry_run)
    color = Fore.GREEN if success else Fore.RED
    print(f"{color}{report}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}/selfimprove {label} complete.{Style.RESET_ALL}")

# -------------------------------------
# Overnight Autonomous Learning (Phase 16)
# -------------------------------------
_OVERNIGHT_REPORTS_DIRNAME = "overnight_reports"


def _overnight_reports_dir():
    reports_dir = os.path.join(_selfimprove_root(), "knowledge_base", _OVERNIGHT_REPORTS_DIRNAME)
    os.makedirs(reports_dir, exist_ok=True)
    return reports_dir


def _next_overnight_run_number():
    existing = [f for f in os.listdir(_overnight_reports_dir()) if f.startswith("overnight_") and f.endswith(".md")]
    return len(existing) + 1


def _write_overnight_report(run_number, content):
    report_path = os.path.join(
        _overnight_reports_dir(), f"overnight_{run_number:04d}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
    )
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        pass
    return content


def _overnight_performance_line(label, performance):
    if performance["attempted"] == 0:
        return f"{label}: no attempts recorded yet."
    return f"{label}: {performance['attempted']} attempted, {performance['success_rate']:.0%} succeeded recently."


def _historian_summary_text(stats):
    """Short plain-text summary of a historian() result, for embedding in
    the overnight report - historian() itself already prints a fuller
    breakdown line by line for an interactive run; this mirrors the same
    numbers rather than introducing a second, divergent set."""
    kb, convo, memory = stats["knowledge_base"], stats["conversations"], stats["agent_memory"]
    return (
        f"Knowledge base: {kb['files_sorted']} file(s) sorted, {kb['duplicates_removed']} duplicate(s) removed, "
        f"{kb['web_evidence_duplicates_removed']} stale web-evidence capture(s) removed.\n"
        f"Conversations: {convo['conversations_merged']} merged into knowledge_base "
        f"({convo['exchanges_saved']} exchange(s)), {convo['skipped_empty']} empty file(s) discarded.\n"
        f"Agent memory: {memory['agents_cleaned']} agent file(s) cleaned, "
        f"{memory['duplicates_removed']} duplicate entr{'y' if memory['duplicates_removed'] == 1 else 'ies'} removed."
    )


def run_overnight_cycle():
    from nightly import cycle_lock
    try:
        with cycle_lock(core_config.project_root()):
            return _run_overnight_cycle_unlocked()
    except BlockingIOError:
        return "Another overnight cycle is already running."


def _run_overnight_cycle_unlocked():
    """Knowledge maintenance runs independently of engineering outcomes."""
    from core.knowledge_maintenance import maintain_knowledge, atomic_json
    run_number = _next_overnight_run_number()
    sections, errors = [], []

    def stage(label, action):
        try:
            output = action()
            sections.append(f"{label}:\n{output}")
        except Exception as error:
            errors.append(label)
            sections.append(f"{label}:\nERROR {type(error).__name__}: {error}")

    # Build usable retrieval data even if the optional model or legacy cleanup fails.
    stage("Knowledge consolidation", lambda: json.dumps(maintain_knowledge(core_config.project_root()), indent=2))
    stage("Historian cleanup", lambda: _historian_summary_text(historian(dry_run=False)))
    def research():
        from core.autonomous_research import run_research
        result = run_research(core_config.project_root())
        if result.get("errors"):
            raise RuntimeError(json.dumps(result))
        return json.dumps(result)
    stage("Gap-driven research", research)
    def study():
        from core.knowledge_maintenance import learn_from_sources
        maintain_knowledge(core_config.project_root())
        result = learn_from_sources(core_config.project_root())
        if any(item.get("kind") == "execution" for item in result.get("failures", [])):
            raise RuntimeError(json.dumps(result))
        return json.dumps(result)
    stage("Source-backed learning", study)
    stage("Retrieval refresh", lambda: json.dumps(maintain_knowledge(core_config.project_root()), indent=2))
    stage("Self-improve", lambda: run_self_improve_cycle()[1])
    stage("Tool generation", lambda: run_tool_generation_cycle(
        _selfimprove_coding_chat, _selfimprove_root(),
        [(tool.name, tool.description) for tool in tool_registry.list()], agent="self-improve"))
    stage("Learning reflection", lambda: json.dumps(consolidated_lessons(), ensure_ascii=False))
    report = (f"☀️ GOOD MORNING — Overnight Learning Run #{run_number}\n\n"
              + "\n\n".join(sections)
              + "\n\nStatus: " + ("partial failure: " + ", ".join(errors) if errors else "completed")
              + "\nKnowledge is consolidated for retrieval; model weights are unchanged. "
                "Review code changes and tool proposals before using them. "
                "To chat, relaunch `python3 webagent.py`.\n")
    _write_overnight_report(run_number, report)
    atomic_json(os.path.join(core_config.project_root(), "knowledge_state", "overnight_status.json"),
                {"finished_at": datetime.now().isoformat(), "errors": errors, "run": run_number})
    return report


def perform_overnight_cycle():
    print(f"{Fore.CYAN}🌙 Starting the overnight learning cycle...{Style.RESET_ALL}")
    report = run_overnight_cycle()
    print(f"{Fore.GREEN}{report}{Style.RESET_ALL}")

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
    tool_registry.execute("knowledge.write", filename=f"wiki_{sanitize_filename(query)}.txt", content=full_wiki)
    prompt = (
        f"You are a knowledgeable assistant. Based on the following Wikipedia information:\n\n"
        f"{full_wiki}\n\n"
        f"Please answer the following query: {query}"
    )
    context.assistant_convo.append({"role": "user", "content": prompt})
    chosen_model = MODELS["search"] if context.reasoning_mode else MODELS["main"]
    response = model_chat(model=chosen_model, messages=context.assistant_convo)
    final_text = response["message"]["content"]
    context.assistant_convo.append({"role": "assistant", "content": final_text})
    print(f"{Fore.GREEN}{final_text}{Style.RESET_ALL}\n")
    if context.voice_mode or context.tts_mode:
        asyncio.run(speak_text(final_text))

# -------------------------------------
# Historian Integration (/historian)
# -------------------------------------
_HISTORIAN_UNSORTED_DIRS = {"web_evidence", "overnight_reports", "selfimprove_reports", ".historian_staging"}
# General English filler, well beyond TAG_STOP_WORDS's narrow query-tag list -
# needed because Historian tags free-form personal chat text, not search queries.
_GENERAL_STOPWORDS = {
    "user", "response", "which", "under", "that", "this", "these", "those", "being", "about",
    "would", "could", "should", "their", "there", "they're", "you're", "don't", "doesnt", "doesn't",
    "isn't", "wasn't", "aren't", "let's", "here's", "it's", "i'm", "we're", "into", "than",
    "then", "them", "your", "have", "been", "were", "when", "where", "some", "such", "also",
    "each", "more", "most", "very", "just", "over", "only", "same", "does", "did",
    "you", "yours", "me", "my", "mine", "we", "us", "our", "ours", "he", "she", "his", "her",
    "hers", "will", "shall", "can", "may", "might", "must", "not", "yes", "than", "here",
    "all", "any", "both", "few", "other", "own", "too", "up", "down", "off", "again", "once",
    "if", "because", "until", "while", "above", "below", "between", "through", "during",
    "before", "after", "but", "nor", "yet", "hello", "hey", "thanks", "please", "okay", "yeah",
    "sorry", "get", "got", "like", "know", "think", "want", "need", "make", "made", "look",
    "looking", "find", "find", "give", "tell", "say", "said", "going", "lets",
}


def _historian_topic_bucket(text):
    """Derive a folder-safe topic bucket from text.

    Picks the longest word among the first few surviving keyword candidates,
    after filtering general filler - the longest of several early candidates
    tends to be the actual topic noun ("watermelon") rather than a short verb
    or pronoun that slipped past the narrower query-tag stopword list.
    """
    tags = [tag for tag in _keyword_tags(text, limit=20) if tag not in _GENERAL_STOPWORDS and not tag.isdigit()]
    return sanitize_filename(max(tags[:6], key=len)) if tags else "general"


_HISTORIAN_CLASSIFY_CHUNK = 10
_HISTORIAN_CLASSIFY_ATTEMPTS = 2


def _historian_classify_topics(titles, label="items"):
    """Batch-classify short topic titles into a small, reused set of category names.

    A per-file keyword pick (_historian_topic_bucket) mostly yields one bucket
    per file, since unrelated questions rarely share their single most
    distinctive word. Classifying a whole batch in one call lets the model
    reuse a category across genuinely related items (several crime/demographics
    questions, several Python questions) - real "group by topic" instead of
    "label by keyword". Returns a list the same length as `titles`; any item
    the model didn't classify comes back as None so the caller falls back to
    the keyword heuristic for just that item.

    Uses the coding model rather than whatever chat mode is active: in testing,
    the small general-chat model ignored the list and echoed it back, while the
    coding model reliably returned a matching-length JSON array. Even so, a
    small local model asked for an exact-length array occasionally miscounts,
    so chunks are kept small and get one retry before giving up. This is the
    slowest part of a Historian run (one local-model call per chunk), so it
    prints progress per chunk rather than going quiet until it's done.
    """
    if ollama is None or not titles:
        return [None] * len(titles)
    classify_model = MODELS.get("coding", _selected_model())
    results = [None] * len(titles)
    total_chunks = (len(titles) + _HISTORIAN_CLASSIFY_CHUNK - 1) // _HISTORIAN_CLASSIFY_CHUNK
    for chunk_num, start in enumerate(range(0, len(titles), _HISTORIAN_CLASSIFY_CHUNK), start=1):
        chunk = titles[start:start + _HISTORIAN_CLASSIFY_CHUNK]
        print(
            f"{Fore.CYAN}  Historian: classifying {label} - batch {chunk_num}/{total_chunks} "
            f"({len(chunk)} item(s)){Style.RESET_ALL}"
        )
        listing = "\n".join(f"{i + 1}. {title[:80]}" for i, title in enumerate(chunk))
        planner = (
            "Group these items into a small set of broad topic categories, reusing the same "
            "category for every related item instead of inventing a new one-off category per item. "
            f"Use no more than {max(3, len(chunk) // 3)} distinct categories for this list. "
            "Category names: lowercase, 1-3 words, underscore-separated, no punctuation. "
            "Return ONLY a JSON array of category strings, one per item, in the same order, "
            f"with exactly {len(chunk)} elements - the array length must equal the number of items.\n\n"
            f"Items:\n{listing}"
        )
        for attempt in range(_HISTORIAN_CLASSIFY_ATTEMPTS):
            try:
                response = model_chat(model=classify_model, messages=[{"role": "system", "content": planner}])
                content = response.get("message", {}).get("content", "")
                match = re.search(r"\[.*\]", content, re.DOTALL)
                categories = json.loads(match.group(0) if match else content)
                if isinstance(categories, list) and len(categories) == len(chunk):
                    for i, category in enumerate(categories):
                        if isinstance(category, str) and category.strip():
                            results[start + i] = sanitize_filename(
                                re.sub(r"[\s-]+", "_", category.strip().lower())
                            )
                    break
                if attempt == 0:
                    print(f"{Fore.YELLOW}    Retrying batch {chunk_num} (unexpected response length)...{Style.RESET_ALL}")
            except Exception:
                if attempt == 0:
                    print(f"{Fore.YELLOW}    Retrying batch {chunk_num} (couldn't parse response)...{Style.RESET_ALL}")
    return results


def _historian_unique_destination(dest_dir, filename):
    """Return a non-colliding path in dest_dir for filename, adding a numeric suffix on collision."""
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(dest_dir, filename)
    n = 1
    while os.path.exists(candidate):
        candidate = os.path.join(dest_dir, f"{base}_{n}{ext}")
        n += 1
    return candidate


def _historian_ensure_bucket_dir(path):
    """Create a topic bucket directory, tolerating a same-named flat file already at that path.

    A bucket name (from either the classifier or the keyword heuristic) can
    collide with an existing top-level knowledge_base filename, e.g. a file
    literally named "help" and a bucket also named "help" - os.makedirs raises
    FileExistsError in that case even with exist_ok=True, since exist_ok only
    tolerates an existing *directory*.
    """
    candidate, n = path, 1
    while os.path.exists(candidate) and not os.path.isdir(candidate):
        candidate = f"{path}_{n}"
        n += 1
    os.makedirs(candidate, exist_ok=True)
    return candidate


def historian_clean_knowledge_base(dry_run=False):
    """Dedupe and topic-sort the flat knowledge_base dump, and dedupe stale web_evidence captures.

    Only files sitting directly in knowledge_base/ get sorted into a topic
    subfolder; files already filed away are left alone so repeat runs are
    cheap and idempotent. Exact-duplicate content anywhere in the tree
    (including already-sorted files) is deduped by hash, keeping the oldest.
    """
    kb_path = os.path.join(core_config.project_root(), "knowledge_base")
    stats = {"duplicates_removed": 0, "files_sorted": 0, "buckets": {}, "web_evidence_duplicates_removed": 0}
    if not os.path.isdir(kb_path):
        return stats

    print(f"{Fore.CYAN}  Historian: scanning knowledge_base for duplicate content...{Style.RESET_ALL}")
    hash_to_paths = {}
    for root, dirs, files in os.walk(kb_path):
        dirs[:] = [d for d in dirs if d not in _HISTORIAN_UNSORTED_DIRS and not d.startswith(".") and not os.path.islink(os.path.join(root, d))]
        for name in files:
            path = os.path.join(root, name)
            if name.startswith(".") or os.path.islink(path):
                continue
            try:
                with open(path, "rb") as handle:
                    digest = hashlib.sha256(handle.read()).hexdigest()
            except OSError:
                continue
            hash_to_paths.setdefault(digest, []).append(path)

    for paths in hash_to_paths.values():
        if len(paths) < 2:
            continue
        paths.sort(key=os.path.getmtime)
        for stale in paths[1:]:
            stats["duplicates_removed"] += 1
            if not dry_run:
                try:
                    from core.knowledge_maintenance import preserve_source
                    preserve_source(stale, core_config.project_root())
                    os.remove(stale)
                except OSError:
                    pass
    print(
        f"{Fore.GREEN}  Historian: {stats['duplicates_removed']} duplicate file(s) "
        f"{'found (preview only)' if dry_run else 'removed'}{Style.RESET_ALL}"
    )

    top_level_files = [name for name in os.listdir(kb_path) if not name.startswith(".") and not os.path.islink(os.path.join(kb_path, name)) and os.path.isfile(os.path.join(kb_path, name))]
    file_entries = []
    for name in top_level_files:
        path = os.path.join(kb_path, name)
        if not os.path.exists(path):
            continue  # removed above as a duplicate
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                content = handle.read()
        except OSError:
            continue
        file_entries.append((name, path, content))

    if file_entries:
        print(f"{Fore.CYAN}  Historian: sorting {len(file_entries)} unfiled knowledge_base entr"
              f"{'y' if len(file_entries) == 1 else 'ies'} into topics...{Style.RESET_ALL}")
    classified = _historian_classify_topics(
        [name.replace("_", " ") + " " + content[:1000] for name, _, content in file_entries], label="knowledge_base files"
    )
    assignments = []
    for (name, path, content), category in zip(file_entries, classified):
        bucket = category or _historian_topic_bucket(f"{name} {content[:300]}")
        stats["buckets"][bucket] = stats["buckets"].get(bucket, 0) + 1
        stats["files_sorted"] += 1
        filename = name if os.path.splitext(name)[1] else f"{sanitize_filename(name)}.txt"
        assignments.append((path, bucket, filename))

    if not dry_run and assignments:
        # Each move is atomic; an interrupted run leaves remaining sources in
        # their original locations for the next pass, never stranded in staging.
        for path, bucket, filename in assignments:
            dest_dir = _historian_ensure_bucket_dir(os.path.join(kb_path, bucket))
            os.replace(path, _historian_unique_destination(dest_dir, filename))
    if file_entries:
        print(
            f"{Fore.GREEN}  Historian: {'would sort' if dry_run else 'sorted'} {stats['files_sorted']} "
            f"file(s) into {len(stats['buckets'])} topic bucket(s){Style.RESET_ALL}"
        )

    print(f"{Fore.CYAN}  Historian: checking web_evidence for duplicate captures...{Style.RESET_ALL}")
    evidence_dir = os.path.join(kb_path, "web_evidence")
    if os.path.isdir(evidence_dir):
        by_url = {}
        for filename in os.listdir(evidence_dir):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(evidence_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    record = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            url = record.get("url")
            content = record.get("content")
            if url and isinstance(content, str):
                key = (url, hashlib.sha256(content.encode("utf-8")).hexdigest())
                by_url.setdefault(key, []).append((record.get("captured_at", ""), path))
        for entries in by_url.values():
            if len(entries) < 2:
                continue
            entries.sort(key=lambda entry: entry[0])
            for _, stale_path in entries[:-1]:
                stats["web_evidence_duplicates_removed"] += 1
                if not dry_run:
                    try:
                        from core.knowledge_maintenance import preserve_source
                        preserve_source(stale_path, core_config.project_root())
                        os.remove(stale_path)
                    except OSError:
                        pass
    print(
        f"{Fore.GREEN}  Historian: {stats['web_evidence_duplicates_removed']} stale web-evidence capture(s) "
        f"{'found (preview only)' if dry_run else 'removed'}{Style.RESET_ALL}"
    )

    return stats


def _historian_conversation_pairs(messages):
    """Extract ordered (user, assistant) exchange pairs from a raw message list, skipping system noise."""
    pairs = []
    pending_user = None
    for message in messages:
        content = (message.get("content") or "").strip()
        if not content:
            continue
        if message.get("role") == "user":
            pending_user = content
        elif message.get("role") == "assistant" and pending_user is not None:
            pairs.append((pending_user, content))
            pending_user = None
    return pairs


def historian_merge_conversations(dry_run=False):
    """Fold saved conversation transcripts into topic-sorted knowledge_base entries, then remove the originals.

    Only conversations already persisted to disk (via save_conversation /
    new_conversation) are touched - the live in-memory conversation is left
    alone until the user explicitly saves it or starts a new one. A source
    file is only deleted after its merged write succeeds, so a disk error
    can't lose the conversation.
    """
    kb_path = os.path.join(core_config.project_root(), "knowledge_base")
    convo_dir = _conversations_dir()
    stats = {"conversations_merged": 0, "exchanges_saved": 0, "skipped_empty": 0}
    if not os.path.isdir(convo_dir):
        return stats

    print(f"{Fore.CYAN}  Historian: scanning saved conversations...{Style.RESET_ALL}")
    entries = []
    for filename in sorted(os.listdir(convo_dir)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(convo_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue

        pairs = _historian_conversation_pairs(data.get("conversation") or [])
        if not pairs:
            stats["skipped_empty"] += 1
            if not dry_run:
                try:
                    from core.knowledge_maintenance import preserve_source
                    preserve_source(path, core_config.project_root())
                    os.remove(path)
                except OSError:
                    pass
            continue
        entries.append((filename, pairs))

    if entries:
        print(f"{Fore.CYAN}  Historian: merging {len(entries)} saved conversation(s) into knowledge_base"
              f"{' (preview)' if dry_run else ''}...{Style.RESET_ALL}")
    titles = [pairs[0][0][:60].strip() for _, pairs in entries]
    classified = _historian_classify_topics(titles, label="conversations")

    for (filename, pairs), title, category in zip(entries, titles, classified):
        bucket = category or _historian_topic_bucket(title)
        body = "\n\n".join(
            f"## Exchange {i + 1}\n**User**: {user}\n\n**Assistant**: {assistant}"
            for i, (user, assistant) in enumerate(pairs)
        )
        merged_content = f"# Conversation: {title}\n\n**Merged from**: {filename}\n\n{body}\n"
        stats["conversations_merged"] += 1
        stats["exchanges_saved"] += len(pairs)
        if dry_run:
            continue

        path = os.path.join(convo_dir, filename)
        dest_dir = _historian_ensure_bucket_dir(os.path.join(kb_path, bucket))
        dest_filename = f"conversation_{sanitize_filename(os.path.splitext(filename)[0])}.md"
        dest_path = _historian_unique_destination(dest_dir, dest_filename)
        try:
            with open(dest_path, "w", encoding="utf-8") as handle:
                handle.write(merged_content)
        except OSError:
            continue  # leave the source in place if the merge write failed
        try:
            from core.knowledge_maintenance import preserve_source
            preserve_source(path, core_config.project_root())
            os.remove(path)
        except OSError:
            pass

    print(
        f"{Fore.GREEN}  Historian: {stats['conversations_merged']} conversation(s) "
        f"{'would be merged' if dry_run else 'merged'} ({stats['exchanges_saved']} exchange(s)), "
        f"{stats['skipped_empty']} empty file(s) discarded{Style.RESET_ALL}"
    )
    return stats


def _clean_memory_topics(summary):
    """Re-derive memory topics, stripping the 'User:'/'Response:' prefixes that polluted the old extractor."""
    text = re.sub(r"\b(user|response)\s*:", " ", summary, flags=re.IGNORECASE)
    return [tag for tag in _keyword_tags(text, limit=20) if tag not in _GENERAL_STOPWORDS][:10]


def historian_clean_agent_memory(dry_run=False):
    """Dedupe, re-tag, and chronologically sort each agent's stored memory file."""
    memory_path = os.path.join(core_config.project_root(), "agent_memory")
    stats = {"agents_cleaned": 0, "duplicates_removed": 0, "entries_retagged": 0}
    if not os.path.isdir(memory_path):
        return stats

    print(f"{Fore.CYAN}  Historian: cleaning agent_memory...{Style.RESET_ALL}")
    for filename in os.listdir(memory_path):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(memory_path, filename)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                memory_data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        conversations = memory_data.get("conversations", [])
        if not isinstance(conversations, list):
            continue

        seen_summaries, deduped = set(), []
        for entry in conversations:
            summary = entry.get("summary", "")
            if summary in seen_summaries:
                stats["duplicates_removed"] += 1
                continue
            seen_summaries.add(summary)
            entry["topics"] = _clean_memory_topics(summary)
            stats["entries_retagged"] += 1
            deduped.append(entry)
        deduped.sort(key=lambda entry: entry.get("date", ""))

        removed_here = len(conversations) - len(deduped)
        print(
            f"{Fore.GREEN}    {filename}: {len(deduped)} entr{'y' if len(deduped) == 1 else 'ies'} kept, "
            f"{removed_here} duplicate{'' if removed_here == 1 else 's'} "
            f"{'found (preview only)' if dry_run else 'removed'}{Style.RESET_ALL}"
        )
        stats["agents_cleaned"] += 1
        if dry_run:
            continue
        memory_data["conversations"] = deduped
        try:
            from core.knowledge_maintenance import preserve_source
            preserve_source(path, core_config.project_root())
            from core.knowledge_maintenance import atomic_json
            atomic_json(path, memory_data)
        except OSError:
            pass

    return stats


def historian(dry_run=False):
    """Clean, categorize, and consolidate everything the assistant has stored.

    Three passes: dedupe/topic-sort knowledge_base, merge saved conversation
    transcripts into knowledge_base (removing the merged originals), and
    dedupe/re-tag agent_memory. Pass dry_run=True to preview counts without
    changing anything on disk - the terminal command exposes this as
    "/historian preview".
    """
    running_label = "Historian preview run" if dry_run else "Historian run"
    print(f"{Fore.CYAN}{running_label} starting - this can take a while if it needs to classify a lot of "
          f"unsorted content.{Style.RESET_ALL}")

    print(f"{Fore.CYAN}[1/3] Knowledge base{Style.RESET_ALL}")
    kb_stats = historian_clean_knowledge_base(dry_run=dry_run)

    print(f"{Fore.CYAN}[2/3] Conversations{Style.RESET_ALL}")
    convo_stats = historian_merge_conversations(dry_run=dry_run)

    print(f"{Fore.CYAN}[3/3] Agent memory{Style.RESET_ALL}")
    memory_stats = historian_clean_agent_memory(dry_run=dry_run)

    label = "Historian Preview (dry run - nothing changed)" if dry_run else "Historian Summary"
    print(f"{Fore.CYAN}{label}:{Style.RESET_ALL}")
    print(
        f"{Fore.GREEN}Knowledge base: {kb_stats['files_sorted']} file(s) sorted, "
        f"{kb_stats['duplicates_removed']} duplicate(s) removed, "
        f"{kb_stats['web_evidence_duplicates_removed']} stale web-evidence capture(s) removed{Style.RESET_ALL}"
    )
    for bucket, count in sorted(kb_stats["buckets"].items(), key=lambda kv: -kv[1]):
        print(f"{Fore.GREEN}  {bucket}: {count} entr{'y' if count == 1 else 'ies'}{Style.RESET_ALL}")
    print(
        f"{Fore.GREEN}Conversations: {convo_stats['conversations_merged']} merged into knowledge_base "
        f"({convo_stats['exchanges_saved']} exchange(s)), "
        f"{convo_stats['skipped_empty']} empty file(s) discarded{Style.RESET_ALL}"
    )
    print(
        f"{Fore.GREEN}Agent memory: {memory_stats['agents_cleaned']} agent file(s) cleaned, "
        f"{memory_stats['duplicates_removed']} duplicate entr"
        f"{'y' if memory_stats['duplicates_removed'] == 1 else 'ies'} removed{Style.RESET_ALL}"
    )
    return {"knowledge_base": kb_stats, "conversations": convo_stats, "agent_memory": memory_stats}

# -------------------------------------
# Cron Task Management (/cron, Scheduler agent)
# -------------------------------------
# Gnosis-managed tasks only ever run a saved prompt through the assistant or
# one of these named features - never an arbitrary shell command. This is a
# deliberate limit: the model (via /job scheduler) can create and delete real
# entries in the user's system crontab, so what a task is allowed to *do* is
# fixed in code, not left to whatever the model decides at the time.
CRON_FEATURE_ACTIONS = {"historian", "historian_preview", "news", "selfimprove", "overnight"}
_CRON_MARKER_RE = re.compile(r"^#\s*gnosis:([0-9a-f]{8})\s*(.*)$")
_CRON_FIELD_RE = re.compile(r"^[\d*/,\-]+$")
# A curated, always-present macOS system sound - not user- or model-selectable,
# so an "alarm" task can never be turned into "play an arbitrary audio file".
_CRON_ALARM_SOUND = "/System/Library/Sounds/Glass.aiff"


_ALARM_MAX_SECONDS = 600  # safety ceiling: stop ringing on its own if truly nobody dismisses it
_ALARM_REPLAY_SECONDS = 4  # how often the sound replays while the dialog is still up


def _trigger_alarm(message, max_seconds=_ALARM_MAX_SECONDS):
    """Ring an alarm - repeating sound plus a blocking, dismissible dialog - until the user hits OK.

    Returns (success, detail). A blocking `display dialog` (not the passive
    `display notification` this started as) is what makes "goes off until
    dismissed" possible at all: a notification banner auto-dismisses on its
    own and can't be waited on. The dialog also gets a `giving up after`
    ceiling as a safety net, in case no GUI session ever picks it up (a real,
    separate risk from cron - see docs/cron.md) - without it, an alarm nobody
    can see would otherwise loop and hold a process open forever. While the
    dialog is still open, the sound is replayed every few seconds so the
    alarm is actually audible for as long as it's unacknowledged, not just
    once at the start.

    This is the building block for pomodoro-style timers later: a real
    pomodoro would just be two of these back to back (work duration, then
    break duration), reusing this exact ringing behavior for each edge.
    """
    message = (message or "Alarm").strip() or "Alarm"
    script = (
        f'display dialog {json.dumps(message)} with title "Gnosis Alarm" '
        f'buttons {{"Dismiss"}} default button "Dismiss" giving up after {int(max_seconds)}'
    )
    try:
        dialog = subprocess.Popen(["osascript", "-e", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError:
        dialog = None

    played_any = False
    start = time.monotonic()
    while True:
        try:
            subprocess.run(["afplay", _CRON_ALARM_SOUND], timeout=15, capture_output=True)
            played_any = True
        except (OSError, subprocess.TimeoutExpired):
            pass
        if dialog is None:
            break  # osascript unavailable at all - one sound pass is all we can do
        if dialog.poll() is not None:
            break  # dismissed, or its own "giving up after" ceiling fired
        if time.monotonic() - start >= max_seconds:
            break
        time.sleep(_ALARM_REPLAY_SECONDS)

    if dialog is None:
        return played_any, "played a sound once, but couldn't show a dismissible alert (osascript unavailable)"

    if dialog.poll() is None:
        # Our own max_seconds elapsed before the dialog's ceiling did (or it never bound to a session) - stop waiting.
        dialog.terminate()
        try:
            dialog.wait(timeout=5)
        except subprocess.TimeoutExpired:
            dialog.kill()
        return played_any, "rang until the safety timeout - no dismissal was detected (check GUI/notification permissions)"

    stdout, _ = dialog.communicate()
    gave_up = "gave up:true" in (stdout or "")
    if gave_up:
        return played_any, "rang until its own timeout - no dismissal was detected (check GUI/notification permissions)"
    return True, "rang until the user dismissed it"


def _cron_dir():
    path = os.path.join(core_config.project_root(), "cron")
    os.makedirs(path, exist_ok=True)
    return path


def _cron_tasks_path():
    return os.path.join(_cron_dir(), "tasks.json")


def _cron_logs_dir():
    path = os.path.join(_cron_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def _cron_backups_dir():
    path = os.path.join(_cron_dir(), "backups")
    os.makedirs(path, exist_ok=True)
    return path


def _load_cron_tasks():
    path = _cron_tasks_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cron_tasks(tasks):
    """Returns True/False. Callers deliberately don't fold this into their
    own (success, error) return contract - the real crontab write is the
    mutation that matters and is already checked separately; this is
    best-effort bookkeeping (schedule/description/last_run) that shouldn't
    be reported to the user as "your cron job failed" when it didn't. Still
    printed, not silently swallowed - a real, live crontab entry existing
    with no matching Gnosis record is a genuinely confusing state to debug
    blind."""
    try:
        with open(_cron_tasks_path(), "w", encoding="utf-8") as handle:
            json.dump(tasks, handle, indent=2, ensure_ascii=False)
        return True
    except OSError as e:
        print(f"{Fore.YELLOW}⚠️  Failed to save cron task metadata: {e}{Style.RESET_ALL}")
        return False


def _read_crontab():
    """Return the current user's crontab text, "" if empty/unset, or None if `crontab` isn't available."""
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except OSError:
        return None
    if result.returncode != 0:
        return ""  # most commonly "no crontab for <user>" - not a real error
    return result.stdout


def _write_crontab(text):
    """Back up the existing crontab, then replace it with `text`. Returns True on success."""
    current = _read_crontab()
    if current:
        backup_path = os.path.join(_cron_backups_dir(), f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.crontab")
        try:
            with open(backup_path, "w", encoding="utf-8") as handle:
                handle.write(current)
        except OSError:
            pass
    try:
        result = subprocess.run(["crontab", "-"], input=text, text=True, capture_output=True)
    except OSError:
        return False
    return result.returncode == 0


def _cron_marker_line(task_id, description):
    return f"# gnosis:{task_id} {description}".rstrip()


def _cron_shell_command(task_id):
    """Build the shell command a crontab line runs to execute one Gnosis task headlessly."""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(project_dir, "venv", "bin", "python")
    python_exe = venv_python if os.path.isfile(venv_python) else sys.executable
    script_path = os.path.abspath(__file__)
    log_path = os.path.join(_cron_logs_dir(), f"{task_id}.log")
    return (
        f"cd {shlex.quote(project_dir)} && {shlex.quote(python_exe)} {shlex.quote(script_path)} "
        f"--cron-task {task_id} >> {shlex.quote(log_path)} 2>&1"
    )


def _parse_crontab_entries(text):
    """Split crontab text into addressable entries: (lines, entries).

    A `# gnosis:<id> <description>` comment immediately followed by its
    schedule+command line is one "gnosis" entry (both lines removed as a
    unit). Any other schedule+command line is a "foreign" entry (one line).
    Blank lines and unrelated comments are left alone and are not
    individually addressable - only real schedule lines are "entries".
    """
    lines = (text or "").splitlines()
    entries = []
    pending = None  # (task_id, description, marker_line_index)
    for i, line in enumerate(lines):
        stripped = line.strip()
        marker_match = _CRON_MARKER_RE.match(stripped) if stripped.startswith("#") else None
        if marker_match:
            pending = (marker_match.group(1), marker_match.group(2).strip(), i)
            continue
        is_schedule_line = (
            bool(stripped) and not stripped.startswith("#") and len(stripped.split(None, 5)) >= 6
        )
        if is_schedule_line:
            if pending:
                task_id, description, marker_index = pending
                entries.append({
                    "kind": "gnosis", "task_id": task_id, "description": description,
                    "line_indices": [marker_index, i], "command_line": line,
                })
            else:
                entries.append({
                    "kind": "foreign", "task_id": None, "description": None,
                    "line_indices": [i], "command_line": line,
                })
        pending = None
    return lines, entries


_ALARM_DAY_NUMBERS = {
    "sunday": 0, "sun": 0,
    "monday": 1, "mon": 1,
    "tuesday": 2, "tues": 2, "tue": 2,
    "wednesday": 3, "wed": 3,
    "thursday": 4, "thurs": 4, "thu": 4,
    "friday": 5, "fri": 5,
    "saturday": 6, "sat": 6,
}
_ALARM_DAY_NAME_PATTERN = "|".join(sorted((re.escape(name) for name in _ALARM_DAY_NUMBERS), key=len, reverse=True))
_ALARM_DURATION_RE = re.compile(
    r"^\s*(?:in|for)?\s*(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)\s*$", re.IGNORECASE
)
_ALARM_TIME_RE = re.compile(r"\b(\d{1,2})(?::([0-5]\d))?\s*(am|pm)?\b", re.IGNORECASE)
_ALARM_ONE_TIME = r"\d{1,2}(?::[0-5]\d)?\s*(?:am|pm)?"
_ALARM_TIME_RANGE_RE = re.compile(
    rf"\bbetween\s+({_ALARM_ONE_TIME})\s+and\s+({_ALARM_ONE_TIME})\b"
    rf"|\b({_ALARM_ONE_TIME})\s*(?:-|to|through|until|till)\s*({_ALARM_ONE_TIME})\b",
    re.IGNORECASE,
)


def _parse_alarm_day_pattern(lowered):
    """Return (cron_weekday_field, error). No day phrase at all defaults to '*' (every day)."""
    if re.search(r"\bweekdays?\b", lowered):
        return "1-5", None
    if re.search(r"\bweekends?\b", lowered):
        return "6,0", None
    if re.search(r"\bevery\s*day\b|\bdaily\b", lowered):
        return "*", None

    range_match = re.search(
        rf"\b({_ALARM_DAY_NAME_PATTERN})\s*(?:through|to|-)\s*({_ALARM_DAY_NAME_PATTERN})\b", lowered
    )
    if range_match:
        start = _ALARM_DAY_NUMBERS[range_match.group(1)]
        end = _ALARM_DAY_NUMBERS[range_match.group(2)]
        if end < start:
            return None, "A day range that wraps past Saturday isn't supported yet - list the days individually instead."
        return f"{start}-{end}", None

    day_names_found = re.findall(rf"\b({_ALARM_DAY_NAME_PATTERN})\b", lowered)
    if day_names_found:
        numbers = sorted({_ALARM_DAY_NUMBERS[name] for name in day_names_found})
        return ",".join(str(n) for n in numbers), None

    return "*", None


def _parse_alarm_clock_time(lowered):
    """Return (hour, minute, error) in 24-hour form. Requires am/pm for any ambiguous 1-12 hour."""
    if re.search(r"\bnoon\b", lowered):
        return 12, 0, None
    if re.search(r"\bmidnight\b", lowered):
        return 0, 0, None
    match = _ALARM_TIME_RE.search(lowered)
    if not match:
        return None, None, "No specific time was given - say something like '3am' or '15:00'."
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = match.group(3)
    if meridiem:
        if not (1 <= hour <= 12):
            return None, None, f"'{hour}{meridiem}' isn't a valid hour - use 1-12 with am/pm."
        meridiem = meridiem.lower()
        hour = (0 if hour == 12 else hour) if meridiem == "am" else (12 if hour == 12 else hour + 12)
        return hour, minute, None
    if not (0 <= hour <= 23):
        return None, None, f"'{hour}' isn't a valid hour."
    if 1 <= hour <= 12:
        return None, None, f"'{hour}:{minute:02d}' is ambiguous - add am/pm, or use 24-hour time like '15:00'."
    return hour, minute, None


def parse_alarm_time(description):
    """Parse a natural-language alarm/timer time phrase into cron fields.

    Returns (schedule_fields, one_shot, error) - schedule_fields is None on
    error. Two shapes are recognized:

    - A relative duration ("in 12 minutes", "12 mins", "2 hours") becomes a
      one-shot alarm at now() + that duration, expressed as a specific
      minute/hour/day-of-month/month with weekday left as "*". Cron has no
      year field, so a specific day+month doesn't uniquely identify a single
      instant on its own - one_shot=True is what actually guarantees it only
      fires once, by removing itself right after (see run_cron_task_now).
    - An absolute clock time, optionally with a day-of-week pattern ("3am
      Monday through Friday", "every day at 9pm", "weekends at 10am", "every
      Monday at 7:30am"), becomes a recurring schedule. No day pattern at all
      means it recurs daily.
    - An hour range ("8am - 5pm Monday-Friday", "between 8am and 5pm") means
      fire once per hour across that range, not once at the start time - cron
      already expresses "every hour, hours 8 through 17" directly as a
      bare hour range, so this maps onto the exact same mechanism as a single
      time, just with "H1-H2" instead of "H" in the hour field. If the start
      and end times don't share the same minute (e.g. "8:15am to 5:45pm"),
      the start time's minute is used for every firing - an approximation,
      not an attempt to also range the minute field.

    Deliberately has no LLM fallback - this is meant to be a fast,
    dependency-free building block that cron (or anything else) can call
    directly, not a conversational feature in its own right. A caller that
    wants to handle a phrasing this can't parse is free to fall back to its
    own model call (see _cron_agent_plan for that pattern), using the error
    text this returns as the reason it's asking.
    """
    if not description or not description.strip():
        return None, False, "No time was given for the alarm."
    text = description.strip()

    duration_match = _ALARM_DURATION_RE.match(text)
    if duration_match:
        amount, unit = int(duration_match.group(1)), duration_match.group(2).lower()
        if amount <= 0:
            return None, False, "The duration must be a positive number."
        if unit.startswith("sec"):
            if amount < 60:
                return None, False, "Cron can't schedule less than a minute out - try at least 1 minute."
            delta = timedelta(seconds=amount)
        elif unit.startswith("min"):
            delta = timedelta(minutes=amount)
        elif unit.startswith(("hour", "hr")):
            delta = timedelta(hours=amount)
        else:
            delta = timedelta(days=amount)
        target = datetime.now() + delta
        schedule_fields = [str(target.minute), str(target.hour), str(target.day), str(target.month), "*"]
        return schedule_fields, True, None

    lowered = text.lower()
    weekday_field, day_error = _parse_alarm_day_pattern(lowered)
    if day_error:
        return None, False, day_error

    range_match = _ALARM_TIME_RANGE_RE.search(lowered)
    if range_match:
        start_text = range_match.group(1) or range_match.group(3)
        end_text = range_match.group(2) or range_match.group(4)
        start_hour, start_minute, start_error = _parse_alarm_clock_time(start_text)
        if start_error:
            return None, False, start_error
        end_hour, _end_minute, end_error = _parse_alarm_clock_time(end_text)
        if end_error:
            return None, False, end_error
        if end_hour < start_hour:
            return None, False, "An hour range that wraps past midnight isn't supported yet."
        return [str(start_minute), f"{start_hour}-{end_hour}", "*", "*", weekday_field], False, None

    hour, minute, time_error = _parse_alarm_clock_time(lowered)
    if time_error:
        return None, False, time_error

    return [str(minute), str(hour), "*", "*", weekday_field], False, None


def set_alarm(description, message=None, label=None):
    """Create a real alarm/timer cron task from a natural-language time description.

    The single reusable entry point cron (or anything else) can call to set
    up an alarm or timer: parse_alarm_time does the time parsing, cron_add
    does the actual scheduling - exactly the same underlying mechanism as any
    other cron task, just with action_type="alarm" (see _trigger_alarm).
    Returns (task_id, error) - exactly one is None, same convention as
    cron_add.
    """
    schedule_fields, one_shot, error = parse_alarm_time(description)
    if error:
        return None, error
    alert_text = (message or description).strip()
    if not alert_text:
        return None, "No alert message was given."
    task_label = label or (f"Timer: {alert_text[:60]}" if one_shot else f"Alarm: {alert_text[:60]}")
    return tool_registry.execute(
        "cron.add", schedule_fields=schedule_fields, action_type="alarm", action_payload=alert_text,
        description=task_label, one_shot=one_shot,
    )


def _validate_cron_task(schedule_fields, action_type, action_payload):
    """Shared validation for cron_add and cron_edit. Returns an error message, or None if valid."""
    schedule_fields = list(schedule_fields)
    if len(schedule_fields) != 5:
        return "A cron schedule needs exactly 5 fields (minute hour day-of-month month day-of-week)."
    if not all(_CRON_FIELD_RE.match(field) for field in schedule_fields):
        return "Cron schedule fields may only contain digits, *, /, ',', and '-'."
    if action_type == "feature":
        if action_payload not in CRON_FEATURE_ACTIONS:
            return f"Unknown feature '{action_payload}'. Known features: {', '.join(sorted(CRON_FEATURE_ACTIONS))}."
    elif action_type == "prompt":
        if not action_payload or not action_payload.strip():
            return "A prompt task needs non-empty prompt text."
    elif action_type == "alarm":
        if not action_payload or not action_payload.strip():
            return "An alarm task needs non-empty alert text."
    else:
        return "action_type must be 'prompt', 'feature', or 'alarm'."
    return None


def cron_add(schedule_fields, action_type, action_payload, description=None, one_shot=False):
    """Create a new Gnosis-managed cron task. Returns (task_id, error_message) - exactly one is None.

    one_shot=True marks a task (typically a short relative timer, e.g. "in 12
    minutes") to remove itself after it fires once - see run_cron_task_now.
    """
    schedule_fields = list(schedule_fields)
    error = _validate_cron_task(schedule_fields, action_type, action_payload)
    if error:
        return None, error

    current = _read_crontab()
    if current is None:
        return None, "The `crontab` command isn't available on this system."

    task_id = uuid.uuid4().hex[:8]
    schedule_str = " ".join(schedule_fields)
    label = (description or (action_payload if action_type == "feature" else action_payload))[:80]

    new_lines = ([current.rstrip("\n")] if current.strip() else []) + [
        _cron_marker_line(task_id, label),
        f"{schedule_str} {_cron_shell_command(task_id)}",
    ]
    if not _write_crontab("\n".join(new_lines) + "\n"):
        return None, "Failed to write the new crontab."

    tasks = _load_cron_tasks()
    tasks[task_id] = {
        "schedule": schedule_str,
        "action_type": action_type,
        "action_payload": action_payload,
        "description": label,
        "one_shot": bool(one_shot),
        "created_at": datetime.now().isoformat(),
        "last_run": None,
        "last_status": None,
    }
    _save_cron_tasks(tasks)
    return task_id, None


def cron_edit(task_id, schedule_fields=None, action_type=None, action_payload=None, description=None, one_shot=None):
    """Update an existing Gnosis-managed task in place, keeping its id and its position in the crontab.

    Any argument left as None keeps that task's current value - callers only
    need to pass what's actually changing. Returns (success, error_message).
    """
    tasks = _load_cron_tasks()
    task = tasks.get(task_id)
    if not task:
        return False, f"No cron task with id {task_id}."

    new_schedule_fields = list(schedule_fields) if schedule_fields else task["schedule"].split()
    new_action_type = action_type or task["action_type"]
    new_action_payload = action_payload if action_payload is not None else task["action_payload"]
    new_description = (description or task["description"])[:80]

    error = _validate_cron_task(new_schedule_fields, new_action_type, new_action_payload)
    if error:
        return False, error

    current = _read_crontab()
    if current is None:
        return False, "The `crontab` command isn't available on this system."
    lines, entries = _parse_crontab_entries(current)
    entry = next((e for e in entries if e.get("task_id") == task_id), None)
    if entry is None:
        return False, f"Task {task_id} is in the manifest but its crontab entry is missing."

    marker_index, command_index = entry["line_indices"]
    new_schedule_str = " ".join(new_schedule_fields)
    # The shell command itself only ever references this task_id (see
    # _cron_shell_command) - what it actually runs comes from the manifest,
    # so only the leading schedule fields on this line need to change.
    existing_fields = entry["command_line"].split(None, 5)
    command_part = existing_fields[5] if len(existing_fields) >= 6 else _cron_shell_command(task_id)
    lines[marker_index] = _cron_marker_line(task_id, new_description)
    lines[command_index] = f"{new_schedule_str} {command_part}"

    if not _write_crontab("\n".join(lines) + "\n"):
        return False, "Failed to write the updated crontab."

    task.update({
        "schedule": new_schedule_str,
        "action_type": new_action_type,
        "action_payload": new_action_payload,
        "description": new_description,
        "one_shot": bool(one_shot) if one_shot is not None else task.get("one_shot", False),
        "updated_at": datetime.now().isoformat(),
    })
    tasks[task_id] = task
    _save_cron_tasks(tasks)
    return True, None


def cron_list_entries():
    """Return (entries, error_message) - the parsed, addressable crontab entries."""
    current = _read_crontab()
    if current is None:
        return [], "The `crontab` command isn't available on this system."
    _, entries = _parse_crontab_entries(current)
    return entries, None


def cron_remove(index):
    """Remove the entry at 1-based `index` (as numbered by cron_list_entries). Returns (success, entry_or_error)."""
    current = _read_crontab()
    if current is None:
        return False, "The `crontab` command isn't available on this system."
    lines, entries = _parse_crontab_entries(current)
    if not (1 <= index <= len(entries)):
        return False, f"No entry #{index}."
    entry = entries[index - 1]
    remove_set = set(entry["line_indices"])
    remaining = [line for i, line in enumerate(lines) if i not in remove_set]
    new_text = ("\n".join(remaining) + "\n") if remaining else ""
    if not _write_crontab(new_text):
        return False, "Failed to write the updated crontab."
    if entry["kind"] == "gnosis":
        tasks = _load_cron_tasks()
        tasks.pop(entry["task_id"], None)
        _save_cron_tasks(tasks)
    return True, entry


def _execute_cron_task(task):
    """Run one task's action right now. Returns (success, output_text). Never runs a raw shell command."""
    action_type = task.get("action_type")
    action_payload = task.get("action_payload")
    try:
        if action_type == "prompt":
            return True, chat_response(action_payload)
        if action_type == "alarm":
            ok, detail = _trigger_alarm(action_payload)
            return ok, f"Alarm ({detail}): {action_payload}"
        if action_type == "feature" and action_payload == "historian":
            return True, json.dumps(historian(dry_run=False), indent=2)
        if action_type == "feature" and action_payload == "historian_preview":
            return True, json.dumps(historian(dry_run=True), indent=2)
        if action_type == "feature" and action_payload == "news":
            items = news_command()
            return True, json.dumps(items, indent=2) if items else "(no news items returned)"
        if action_type == "feature" and action_payload == "selfimprove":
            return run_self_improve_cycle()
        if action_type == "feature" and action_payload == "overnight":
            report = run_overnight_cycle()
            return "Status: partial failure:" not in report, report
        return False, f"Unknown action: {action_type}:{action_payload}"
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"


def run_cron_task_now(task_id):
    """Run a Gnosis cron task immediately, log it, and update its manifest entry. Returns (success, output)."""
    tasks = _load_cron_tasks()
    task = tasks.get(task_id)
    if not task:
        return False, f"No cron task with id {task_id}."
    success, output = _execute_cron_task(task)
    task["last_run"] = datetime.now().isoformat()
    task["last_status"] = "success" if success else "error"
    tasks[task_id] = task
    _save_cron_tasks(tasks)
    try:
        with open(os.path.join(_cron_logs_dir(), f"{task_id}.log"), "a", encoding="utf-8") as handle:
            handle.write(f"--- {task['last_run']} ({task['last_status']}) ---\n{output}\n\n")
    except OSError:
        pass

    if task.get("one_shot"):
        # A one-shot timer (e.g. "in 12 minutes") only ever fires once, whether
        # triggered by real cron or run manually via /cron run - remove it
        # from both the crontab and the manifest right after it runs.
        entries, list_error = tool_registry.execute("cron.list")
        if not list_error:
            match_index = next((i for i, e in enumerate(entries, start=1) if e.get("task_id") == task_id), None)
            if match_index is not None:
                tool_registry.execute("cron.remove", index=match_index)

    return success, output


def print_cron_list():
    """Print every addressable crontab entry, numbered for /cron remove and /cron run."""
    entries, error = tool_registry.execute("cron.list")
    if error:
        print(f"{Fore.RED}{error}{Style.RESET_ALL}")
        return entries
    if not entries:
        print(f"{Fore.YELLOW}No cron entries found.{Style.RESET_ALL}")
        return entries
    tasks = _load_cron_tasks()
    for i, entry in enumerate(entries, start=1):
        if entry["kind"] == "gnosis":
            task = tasks.get(entry["task_id"], {})
            last_run = task.get("last_run") or "never"
            status = task.get("last_status") or "n/a"
            print(
                f"{Fore.GREEN}[{i}] (gnosis:{entry['task_id']}) {task.get('schedule', '?')} -> "
                f"{task.get('action_type', '?')}:{task.get('action_payload', '?')} - {entry['description']} "
                f"| last run: {last_run} ({status}){Style.RESET_ALL}"
            )
        else:
            print(f"{Fore.CYAN}[{i}] (external) {entry['command_line'].strip()}{Style.RESET_ALL}")
    return entries


def _cron_agent_plan(prompt):
    """Ask the model for the single cron action implied by the user's message and recent conversation.

    Only called while the Scheduler agent is active. The model never touches
    the crontab directly - it returns a small JSON directive that cron_add /
    cron_edit / cron_remove / cron_list_entries validate before anything real
    happens.

    Includes recent conversation history (_planner_history, already used by
    the web-research planner) so a request can be built up across turns: if
    the user's first message is missing a schedule or content, the model is
    told to return "none" and let its normal reply ask what's missing: the
    next call then sees both the original request and the answer together
    and can build the complete task, rather than needing everything in one
    message.

    Uses the coding model rather than whatever chat mode is active, same as
    Historian's topic classifier: in testing, the general-chat model got
    anchored on an existing task's schedule/description instead of the
    user's actual request (asked for 7am news, got back the existing task's
    8:30am and wrong feature), while the coding model got it exactly right.
    """
    if ollama is None:
        return {"action": "none"}
    classify_model = MODELS.get("coding", _selected_model())
    tasks = _load_cron_tasks()
    tasks_listing = "\n".join(
        f"- id={task_id}: schedule='{task['schedule']}' -> {task['action_type']}:{task['action_payload']} "
        f"({task['description']})"
        for task_id, task in tasks.items()
    ) or "(no scheduled tasks yet)"
    planner = (
        "You are the planning step for the Cron Scheduler agent. Decide the single scheduling action implied "
        "by the conversation below, or take no action if the user is just asking a question, chatting, or "
        "hasn't yet given you enough to build or edit a complete task. "
        "Return ONLY valid JSON, matching exactly one of these shapes:\n"
        '{"action": "add", "schedule": "min hour day month weekday", "type": "prompt", '
        '"payload": "<the exact prompt text to run each time>", "description": "<short label>"}\n'
        '{"action": "add", "schedule": "min hour day month weekday", "type": "feature", '
        f'"payload": "<one of: {", ".join(sorted(CRON_FEATURE_ACTIONS))}>", "description": "<short label>"}}\n'
        '{"action": "add", "time_description": "<the user\'s time phrase, e.g. \'3am Monday through Friday\' or '
        '\'in 12 minutes\', verbatim or close to it>", "type": "alarm", '
        '"payload": "<short alert message to show/announce>", "description": "<short label>"}\n'
        '{"action": "edit", "task_id": "<an id from the list below>", "schedule": "<optional, omit if unchanged>", '
        '"type": "<optional>", "payload": "<optional>", "description": "<optional>"}\n'
        '{"action": "remove", "task_id": "<an id from the list below>"}\n'
        '{"action": "list"}\n'
        '{"action": "none"}\n'
        "Use standard 5-field cron syntax for a \"schedule\" field (minute hour day-of-month month day-of-week; "
        "use * for any field, and comma/dash/slash for ranges or steps - e.g. '*/2' or '8-18/2' for 'every 2 "
        "hours', not just a bare range). An alarm \"add\" is different: give \"time_description\" - the user's "
        "own time phrasing, not a cron schedule you compute yourself - a separate deterministic parser turns "
        "it into the actual schedule, since it's more reliable at exact times than guessing cron fields "
        "yourself. Only use \"remove\" or \"edit\" with a task_id that appears in the list below - never invent "
        "one. A task can only do one of three things: run a saved prompt through the assistant (type "
        f"\"prompt\"), run one of the named built-in features ({', '.join(sorted(CRON_FEATURE_ACTIONS))}, type "
        "\"feature\"), or sound an audible+visual alarm with a short message (type \"alarm\") - it can never "
        "run a shell command. Use \"alarm\" when the user wants to be actively alerted/woken/reminded with "
        "sound and a notification (an alarm clock, a timer, \"alert me\", \"wake me up\"); use \"prompt\" when "
        "they want the assistant to generate fresh text each time (a summary, a briefing, an answer). "
        "If the user's request is missing a clear schedule/time or clear content/feature/alarm-message - even after "
        "checking the conversation history below for an earlier part of the same request - return "
        "{\"action\": \"none\"}; a separate reply will ask them what's missing, and their answer will arrive "
        "as a later message in this same conversation.\n\n"
        f"Existing scheduled tasks:\n{tasks_listing}\n\n"
        f"Recent conversation:\n{_planner_history()}\n\nLatest user message: {prompt}"
    )
    try:
        response = model_chat(model=classify_model, messages=[{"role": "system", "content": planner}])
        content = response.get("message", {}).get("content", "")
        match = re.search(r"\{.*\}", content, re.DOTALL)
        action = json.loads(match.group(0) if match else content)
        return action if isinstance(action, dict) else {"action": "none"}
    except (ValueError, TypeError, json.JSONDecodeError, AttributeError):
        return {"action": "none"}


def _describe_cron_action(action_type, action_payload):
    """Human-phrase what a task's action_type/action_payload actually does, for confirmation messages."""
    if action_type == "alarm":
        return f"sound an alarm: {action_payload!r}"
    if action_type == "prompt":
        return f"run this prompt through the assistant: {action_payload!r}"
    if action_type == "feature":
        return f"run the {action_payload} feature"
    return f"{action_type}: {action_payload!r}"


def _cron_agent_execute(action):
    """Execute a validated directive from _cron_agent_plan.

    Returns (acted, message). `acted` is True for every real action attempt
    (add/edit/remove/list, whether it succeeded or failed) - in that case
    `message` is the literal, final reply to show the user, built entirely
    from real data returned by cron_add/cron_edit/cron_remove/
    _load_cron_tasks. It is never handed to the model to paraphrase: in
    testing, asked to describe a real, correctly-created task, the model
    instead invented a fictional bash script and false claims about how it
    worked, ignoring the plain grounding fact it was given. Only the "none"
    case (acted=False, message=None) lets normal chat generation happen -
    there's nothing real to report, so there's nothing for the model to get
    wrong.
    """
    kind = action.get("action")
    if kind == "add" and action.get("type") == "alarm":
        task_id, error = set_alarm(
            str(action.get("time_description", "")).strip(),
            message=str(action.get("payload", "")).strip(),
            label=action.get("description"),
        )
        if error:
            return True, f"I couldn't set that alarm: {error}"
        task = _load_cron_tasks().get(task_id, {})
        kind_word = "timer" if task.get("one_shot") else "alarm"
        return True, (
            f"Done - I've set a {kind_word}: **{task.get('description', '')}** "
            f"(task `{task_id}`, cron schedule `{task.get('schedule', '?')}`). "
            f"It will sound an alarm: {task.get('action_payload', '')!r}. "
            f"Check `/cron list` any time to see it."
        )
    if kind == "add":
        schedule_fields = str(action.get("schedule", "")).split()
        task_id, error = tool_registry.execute(
            "cron.add", schedule_fields=schedule_fields, action_type=action.get("type"),
            action_payload=str(action.get("payload", "")).strip(), description=action.get("description"),
        )
        if error:
            return True, f"I couldn't create that task: {error}"
        return True, (
            f"Done - I've scheduled **{action.get('description') or task_id}** "
            f"(task `{task_id}`, cron schedule `{' '.join(schedule_fields)}`). "
            f"Each time it runs, it will {_describe_cron_action(action.get('type'), action.get('payload'))}. "
            f"Check `/cron list` any time to see it."
        )
    if kind == "edit":
        task_id = action.get("task_id")
        schedule = action.get("schedule")
        ok, error = tool_registry.execute(
            "cron.edit",
            task_id=task_id,
            schedule_fields=str(schedule).split() if schedule else None,
            action_type=action.get("type"),
            action_payload=(str(action.get("payload")).strip() if action.get("payload") is not None else None),
            description=action.get("description"),
        )
        if not ok:
            return True, f"I couldn't update that task: {error}"
        updated = _load_cron_tasks().get(task_id, {})
        return True, (
            f"Done - I've updated task `{task_id}`: **{updated.get('description', '')}** "
            f"(cron schedule `{updated.get('schedule', '?')}`). Each time it runs, it will "
            f"{_describe_cron_action(updated.get('action_type'), updated.get('action_payload'))}."
        )
    if kind == "remove":
        task_id = action.get("task_id")
        entries, error = tool_registry.execute("cron.list")
        if error:
            return True, f"I couldn't remove that: {error}"
        match_index = next((i for i, e in enumerate(entries, start=1) if e.get("task_id") == task_id), None)
        if match_index is None:
            return True, f"I couldn't find a scheduled task with id {task_id} to remove."
        ok, result = tool_registry.execute("cron.remove", index=match_index)
        return (True, f"Done - I've removed task `{task_id}`.") if ok else (True, f"I couldn't remove that: {result}")
    if kind == "list":
        tasks = _load_cron_tasks()
        if not tasks:
            return True, "You don't have any scheduled tasks yet."
        listing = "\n".join(
            f"- `{task_id}`: `{task['schedule']}` -> {task['action_type']}: {task['action_payload']!r} "
            f"({task['description']})"
            for task_id, task in tasks.items()
        )
        return True, f"Here's what's currently scheduled:\n{listing}"
    return False, None


def run_scheduler_agent_step(prompt):
    """If the Scheduler agent is active, plan and (if warranted) execute one cron action.

    Returns the final, literal reply to show the user for this turn - the
    caller should show it directly and skip the normal LLM completion
    entirely - or None if no real action was taken, meaning normal chat
    generation should proceed as usual (e.g. the model is asking a
    clarifying question, or just chatting).
    """
    if context.current_agent != "scheduler":
        return None
    action = _cron_agent_plan(prompt)
    acted, message = _cron_agent_execute(action)
    return message if acted else None


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
    context.assistant_convo.append({"role": "user", "content": prompt})
    chosen_model = MODELS["coding"]
    response = model_chat(model=chosen_model, messages=context.assistant_convo)
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
    if yt_dlp is None:
        print(f"{Fore.RED}yt-dlp is not installed, so YouTube downloads are unavailable.{Style.RESET_ALL}")
        return
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
    if context.current_agent:  # Don't suggest if already using an agent
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
    if not agent_name or agent_name not in AVAILABLE_AGENTS or not should_save_to_knowledge_base(user_input, response):
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
    agent_path = os.path.join(core_config.project_root(), AVAILABLE_AGENTS[agent_name]['knowledge_path'])
    if not os.path.exists(agent_path):
        os.makedirs(agent_path)
    
    insight_path = os.path.join(agent_path, insight_filename)
    try:
        with open(insight_path, 'w', encoding='utf-8') as f:
            f.write(insight_content)
        print(f"{Fore.GREEN}💾 Saved insight to {agent_name} knowledge base{Style.RESET_ALL}")
    except OSError as e:
        print(f"{Fore.YELLOW}⚠️  Failed to save insight to {agent_name} knowledge base: {e}{Style.RESET_ALL}")

# -------------------------------------
# MAIN INTERACTION LOOP
# -------------------------------------
# -------------------------------------
# Command handlers (registered with core.command_router.CommandRouter below)
# -------------------------------------
# Each handler receives the raw, un-lowered prompt string and is responsible
# for parsing its own arguments out of it - exactly how these bodies always
# worked back when they lived inline in main()'s if/elif chain. The only
# thing that changed in this extraction is *how* main() decides which one to
# call; what each one actually does is untouched.

def _cmd_reason(prompt):
    context.reasoning_mode = not context.reasoning_mode
    if context.reasoning_mode:
        context.unfiltered_mode = False
        context.coding_mode = False
    which_model = "search" if context.reasoning_mode else ("unfiltered" if context.unfiltered_mode else ("coding" if context.coding_mode else "main"))
    print(f"{Fore.YELLOW}Reasoning mode {'ON' if context.reasoning_mode else 'OFF'}. Using model: {MODELS[which_model]}")


def _cmd_deepthink(prompt):
    context.deep_think_mode = not context.deep_think_mode
    if context.deep_think_mode:
        context.web_search_mode = True
    print(f"{Fore.YELLOW}Deep Think {'ON' if context.deep_think_mode else 'OFF'}. "
          f"Web research is {'ON' if context.web_search_mode else 'OFF'}.{Style.RESET_ALL}")


def _cmd_reindexevidence(prompt):
    updated = backfill_web_evidence_metadata()
    print(f"{Fore.GREEN}Tagged metadata on {updated} web evidence records.{Style.RESET_ALL}")


def _cmd_password(prompt):
    parts = prompt.split(maxsplit=1)
    args = parts[1] if len(parts) > 1 else None
    password_command(args)


def _cmd_job(prompt):
    parts = prompt.split(maxsplit=1)
    args = parts[1] if len(parts) > 1 else None
    result = job_command(args)
    print(f"{Fore.CYAN}{result}{Style.RESET_ALL}")


def _cmd_unfiltered(prompt):
    context.unfiltered_mode = not context.unfiltered_mode
    if context.unfiltered_mode:
        context.reasoning_mode = False
        context.coding_mode = False
    which_model = "unfiltered" if context.unfiltered_mode else ("search" if context.reasoning_mode else ("coding" if context.coding_mode else "main"))
    print(f"{Fore.YELLOW}Unfiltered mode {'ON' if context.unfiltered_mode else 'OFF'}. Using model: {MODELS[which_model]}")


def _cmd_coding(prompt):
    context.coding_mode = not context.coding_mode
    if context.coding_mode:
        context.reasoning_mode = False
        context.unfiltered_mode = False
    which_model = "coding" if context.coding_mode else ("search" if context.reasoning_mode else ("unfiltered" if context.unfiltered_mode else "main"))
    print(f"{Fore.YELLOW}Coding mode {'ON' if context.coding_mode else 'OFF'}. Using model: {MODELS[which_model]}")


def _cmd_tts(prompt):
    if not has_tts_backend():
        print(
            f"{Fore.RED}TTS is unavailable because pyttsx3 is not installed in "
            f"{sys.executable}.{Style.RESET_ALL}"
        )
        print("Install project dependencies with: ./venv/bin/python -m pip install -r requirements.txt")
        return
    context.tts_mode = not context.tts_mode
    print(f"{Fore.YELLOW}TTS mode {'ON' if context.tts_mode else 'OFF'}.")


def _cmd_websearch(prompt):
    context.web_search_mode = not context.web_search_mode
    print(f"{Fore.YELLOW}Web search {'ON (model decides per message)' if context.web_search_mode else 'OFF'}.")
    if context.web_search_mode:
        print(f"{Fore.CYAN}Checking search service availability...{Style.RESET_ALL}")
        svc = check_search_services()
        parts = []
        if svc.get('searxng'):
            parts.append('SearxNG: UP')
        else:
            parts.append('SearxNG: DOWN')
        parts.append('Fallback: offline contextual search available')
        print(f"{Fore.GREEN}{' | '.join(parts)}{Style.RESET_ALL}")


def _cmd_historian(prompt):
    historian(dry_run=prompt.lower() != "/historian")


def _cmd_cron_help(prompt):
    print(f"{Fore.CYAN}/cron list{Style.RESET_ALL} - show every crontab entry, numbered")
    print(f"{Fore.CYAN}/cron add <min> <hour> <day> <month> <weekday> prompt: <text>{Style.RESET_ALL} - "
          f"run a prompt through the assistant on a schedule")
    print(f"{Fore.CYAN}/cron add <min> <hour> <day> <month> <weekday> feature: "
          f"<{'|'.join(sorted(CRON_FEATURE_ACTIONS))}>{Style.RESET_ALL} - run a built-in feature on a schedule")
    print(f"{Fore.CYAN}/cron add <min> <hour> <day> <month> <weekday> alarm: <message>{Style.RESET_ALL} - "
          f"sound an audible + visual alarm on a schedule")
    print(f"{Fore.CYAN}/cron edit <n> <min> <hour> <day> <month> <weekday> prompt|feature|alarm: <text>"
          f"{Style.RESET_ALL} - change a Gnosis-managed entry #n in place")
    print(f"{Fore.CYAN}/cron alarm <time description> message: <text>{Style.RESET_ALL} - set an alarm/timer "
          f"from natural time phrasing, e.g. '/cron alarm 3am Monday through Friday message: Take medication' "
          f"or '/cron alarm in 12 minutes message: Tea is ready'")
    print(f"{Fore.CYAN}/cron remove <n>{Style.RESET_ALL} - remove entry #n from /cron list (asks to confirm)")
    print(f"{Fore.CYAN}/cron run <n>{Style.RESET_ALL} - run a Gnosis-managed entry #n right now")
    print(f"{Fore.YELLOW}Tip: /job scheduler lets you manage tasks conversationally instead.{Style.RESET_ALL}")


def _cmd_cron_list(prompt):
    print_cron_list()


def _cmd_cron_alarm(prompt):
    rest = prompt[len("/cron alarm "):]
    marker = " message:"
    idx = rest.lower().find(marker)
    if idx == -1:
        print(f"{Fore.RED}Usage: /cron alarm <time description> message: <text> - e.g. "
              f"'/cron alarm 3am Monday through Friday message: Take medication'{Style.RESET_ALL}")
        return
    time_description = rest[:idx].strip()
    alert_message = rest[idx + len(marker):].strip()
    if not time_description or not alert_message:
        print(f"{Fore.RED}Both a time description and a message are required.{Style.RESET_ALL}")
        return
    task_id, error = set_alarm(time_description, message=alert_message)
    if error:
        print(f"{Fore.RED}{error}{Style.RESET_ALL}")
    else:
        task = _load_cron_tasks().get(task_id, {})
        kind_word = "timer" if task.get("one_shot") else "alarm"
        print(f"{Fore.GREEN}Set {kind_word} `{task_id}`: cron schedule `{task.get('schedule', '?')}`, "
              f"message: {alert_message!r}{Style.RESET_ALL}")


def _cmd_cron_add(prompt):
    rest = prompt.split(None, 2)
    tail_tokens = rest[2].split(None, 5) if len(rest) > 2 else []
    if len(tail_tokens) < 6:
        print(f"{Fore.RED}Usage: /cron add <min> <hour> <day> <month> <weekday> prompt|feature|alarm: <text>"
              f"{Style.RESET_ALL}")
        return
    schedule_fields, action_text = tail_tokens[:5], tail_tokens[5]
    if action_text.lower().startswith("prompt:"):
        action_type, action_payload = "prompt", action_text.split(":", 1)[1].strip()
    elif action_text.lower().startswith("feature:"):
        action_type, action_payload = "feature", action_text.split(":", 1)[1].strip().lower()
    elif action_text.lower().startswith("alarm:"):
        action_type, action_payload = "alarm", action_text.split(":", 1)[1].strip()
    else:
        print(f"{Fore.RED}Action must start with 'prompt:', 'feature:', or 'alarm:'.{Style.RESET_ALL}")
        return
    task_id, error = tool_registry.execute(
        "cron.add", schedule_fields=schedule_fields, action_type=action_type, action_payload=action_payload,
    )
    if error:
        print(f"{Fore.RED}{error}{Style.RESET_ALL}")
    else:
        print(f"{Fore.GREEN}Created cron task {task_id}: {' '.join(schedule_fields)} -> "
              f"{action_type}:{action_payload}{Style.RESET_ALL}")


def _cmd_cron_edit(prompt):
    rest = prompt.split(None, 3)
    if len(rest) < 4 or not rest[2].isdigit():
        print(f"{Fore.RED}Usage: /cron edit <n> <min> <hour> <day> <month> <weekday> prompt|feature|alarm: <text>"
              f"{Style.RESET_ALL}")
        return
    entries, error = tool_registry.execute("cron.list")
    if error:
        print(f"{Fore.RED}{error}{Style.RESET_ALL}")
        return
    index = int(rest[2])
    if not (1 <= index <= len(entries)):
        print(f"{Fore.RED}No entry #{index}.{Style.RESET_ALL}")
        return
    if entries[index - 1]["kind"] != "gnosis":
        print(f"{Fore.RED}Entry #{index} isn't Gnosis-managed, so it can't be edited this way.{Style.RESET_ALL}")
        return
    tail_tokens = rest[3].split(None, 5)
    if len(tail_tokens) < 6:
        print(f"{Fore.RED}Usage: /cron edit <n> <min> <hour> <day> <month> <weekday> prompt|feature|alarm: <text>"
              f"{Style.RESET_ALL}")
        return
    schedule_fields, action_text = tail_tokens[:5], tail_tokens[5]
    if action_text.lower().startswith("prompt:"):
        action_type, action_payload = "prompt", action_text.split(":", 1)[1].strip()
    elif action_text.lower().startswith("feature:"):
        action_type, action_payload = "feature", action_text.split(":", 1)[1].strip().lower()
    elif action_text.lower().startswith("alarm:"):
        action_type, action_payload = "alarm", action_text.split(":", 1)[1].strip()
    else:
        print(f"{Fore.RED}Action must start with 'prompt:', 'feature:', or 'alarm:'.{Style.RESET_ALL}")
        return
    task_id = entries[index - 1]["task_id"]
    ok, error = tool_registry.execute(
        "cron.edit", task_id=task_id, schedule_fields=schedule_fields, action_type=action_type, action_payload=action_payload,
    )
    if ok:
        print(f"{Fore.GREEN}Updated cron task {task_id}: {' '.join(schedule_fields)} -> "
              f"{action_type}:{action_payload}{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}{error}{Style.RESET_ALL}")


def _cmd_cron_remove(prompt):
    parts = prompt.split()
    if len(parts) != 3 or not parts[2].isdigit():
        print(f"{Fore.RED}Usage: /cron remove <n> (see /cron list for numbers){Style.RESET_ALL}")
        return
    entries = print_cron_list()
    index = int(parts[2])
    if not (1 <= index <= len(entries)):
        print(f"{Fore.RED}No entry #{index}.{Style.RESET_ALL}")
        return
    confirm = _next_prompt_line(f"{Fore.YELLOW}Remove entry #{index} shown above? [y/N] {Style.RESET_ALL}")
    if confirm.strip().lower() not in ("y", "yes"):
        print(f"{Fore.YELLOW}Cancelled.{Style.RESET_ALL}")
        return
    ok, result = tool_registry.execute("cron.remove", index=index)
    print(f"{Fore.GREEN}Removed entry #{index}.{Style.RESET_ALL}" if ok else f"{Fore.RED}{result}{Style.RESET_ALL}")


def _cmd_cron_run(prompt):
    parts = prompt.split()
    if len(parts) != 3 or not parts[2].isdigit():
        print(f"{Fore.RED}Usage: /cron run <n> (see /cron list for numbers){Style.RESET_ALL}")
        return
    entries, error = tool_registry.execute("cron.list")
    if error:
        print(f"{Fore.RED}{error}{Style.RESET_ALL}")
        return
    index = int(parts[2])
    if not (1 <= index <= len(entries)):
        print(f"{Fore.RED}No entry #{index}.{Style.RESET_ALL}")
        return
    entry = entries[index - 1]
    if entry["kind"] != "gnosis":
        print(f"{Fore.RED}Entry #{index} isn't Gnosis-managed, so it can't be run this way.{Style.RESET_ALL}")
        return
    print(f"{Fore.CYAN}Running task {entry['task_id']} now...{Style.RESET_ALL}")
    success, output = tool_registry.execute("cron.run", task_id=entry["task_id"])
    print(f"{Fore.GREEN if success else Fore.RED}{output}{Style.RESET_ALL}")


def _cmd_askwiki(prompt):
    parts = prompt.split(maxsplit=1)
    if len(parts) < 2:
        print(f"{Fore.RED}Please provide a query for /askwiki.{Style.RESET_ALL}")
        return
    wiki_query = parts[1]
    ask_wiki(wiki_query)


def _cmd_tutor(prompt):
    parts = prompt.split(maxsplit=1)
    if len(parts) < 2:
        print(f"{Fore.RED}Please provide a topic for /tutor.{Style.RESET_ALL}")
        return
    topic = parts[1]
    tutor(topic)


def _cmd_showpath(prompt):
    parts = prompt.split(maxsplit=1)
    topic = parts[1] if len(parts) > 1 else None
    show_learning_path(topic)


def _cmd_delpath(prompt):
    parts = prompt.split(maxsplit=1)
    if len(parts) < 2:
        print(f"{Fore.RED}Please provide a topic for /delpath.{Style.RESET_ALL}")
        return
    topic = parts[1]
    delete_learning_path(topic)


def _cmd_news(prompt):
    parts = prompt.split(maxsplit=1)
    args = parts[1] if len(parts) > 1 else None
    news_command(args)


def _cmd_ytdl(prompt):
    parts = prompt.split(maxsplit=1)
    url = parts[1] if len(parts) > 1 else None
    ytdl_command(url)


def _cmd_profile(prompt):
    parts = prompt.split(maxsplit=2)
    if len(parts) == 1:
        # Show current profile
        profile = load_user_profile()
        print(f"{Fore.CYAN}Current User Profile:{Style.RESET_ALL}")
        print(f"Name: {profile['name']}")
        print(f"Location: {profile['location']}")
        print(f"Persona: {profile.get('persona', 'neutral')}")
        print(f"Preferences: {', '.join(profile['preferences'])}")
        print(f"Interests: {', '.join(profile['interests'])}")
        print(f"Recent Explorations: {', '.join(profile['recent_explorations'])}")
        print(f"Notes: {profile['notes']}")
        print(f"{Fore.YELLOW}Use '/profile persona <value>' to set a persona, or edit user_details.log directly.{Style.RESET_ALL}")
    elif len(parts) >= 3 and parts[1].lower() == 'persona':
        profile = load_user_profile()
        old_persona = profile.get('persona', 'neutral')
        success, result = set_user_persona(parts[2])
        if not success:
            print(f"{Fore.RED}Unsupported persona. Supported values: {', '.join(result)}{Style.RESET_ALL}")
        else:
            transition_text = format_persona_transition(old_persona, result['persona'])
            print(f"{Fore.GREEN}{transition_text}{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}Usage: /profile persona <neutral|happy|sad|angry|dark|cheery|calm|professional|empathetic|direct>{Style.RESET_ALL}")


def _cmd_persona(prompt):
    parts = prompt.split(maxsplit=1)
    if len(parts) == 2:
        profile = load_user_profile()
        old_persona = profile.get('persona', 'neutral')
        success, result = set_user_persona(parts[1])
        if not success:
            print(f"{Fore.RED}Unsupported persona. Supported values: {', '.join(result)}{Style.RESET_ALL}")
        else:
            transition_text = format_persona_transition(old_persona, result['persona'])
            print(f"{Fore.GREEN}{transition_text}{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}Usage: /persona <neutral|happy|sad|angry|dark|cheery|calm|professional|empathetic|direct>{Style.RESET_ALL}")


def _cmd_selfimprove(prompt):
    perform_self_improve(dry_run=prompt.lower() != "/selfimprove")


def _cmd_learning(prompt):
    """Phase 6's Learning Engine, made visible: a real report over
    self-improve's recorded Experiences (Phase 5) - recent success rate,
    detected failure patterns, and consolidated lessons. Purely
    informational; nothing here gates or alters future self-improve runs."""
    performance = evaluate_recent_performance(agent="self-improve")
    print(f"\n{Fore.CYAN}📊 Learning report - self-improve{Style.RESET_ALL}")
    if performance["attempted"] == 0:
        print("No self-improve attempts recorded yet.")
    else:
        rate = performance["success_rate"]
        print(
            f"Recent attempts: {performance['attempted']} ({performance['succeeded']} succeeded, "
            f"{rate:.0%} success rate); {performance['not_attempted']} run(s) skipped without "
            "attempting a fix."
        )

    findings = critique_recent_failures(agent="self-improve")
    if findings:
        print(f"\n{Fore.YELLOW}Patterns in recent failures:{Style.RESET_ALL}")
        for finding in findings:
            print(f"  - {finding['summary']}")

    lessons = consolidated_lessons(agent="self-improve")
    if lessons:
        print(f"\n{Fore.GREEN}Recent lessons:{Style.RESET_ALL}")
        for lesson, count in lessons[:5]:
            suffix = f" (x{count})" if count > 1 else ""
            print(f"  - {lesson}{suffix}")


def _cmd_generate(prompt):
    """Phase 9's tool-generation pipeline, on demand: looks at Phase 6's
    critic findings for a real, recurring capability gap and, if one
    exists, designs, generates, and sandboxes-tests a new Skill to address
    it. Always just a proposal under gnosis_workspace/proposals/ for human
    review - never registers anything automatically, no matter the
    outcome."""
    print(f"{Fore.CYAN}🔧 Looking for a capability gap to generate a tool for...{Style.RESET_ALL}")
    available_tools = [(tool.name, tool.description) for tool in tool_registry.list()]
    report = run_tool_generation_cycle(
        _selfimprove_coding_chat, _selfimprove_root(), available_tools, agent="self-improve",
    )
    print(f"{Fore.GREEN}{report}{Style.RESET_ALL}")


def _cmd_report(prompt):
    """Phase 13's observability report: real metrics computed over what
    Phase 5/6/12 already record, not a browser dashboard - see
    observability/__init__.py for what's deliberately not in this report
    and why."""
    print(f"\n{Fore.CYAN}📈 Observability report{Style.RESET_ALL}")
    from observability.model_metrics import recent_calls
    print(f"\n{Fore.YELLOW}Recent Ollama calls (this session, up to 100):{Style.RESET_ALL}")
    for call in list(recent_calls)[-5:]:
        first = call.get('first_content_seconds')
        first_text = f", first text {first:.2f}s" if first is not None else ''
        speed = call.get('tokens_per_second')
        speed_text = f", {speed:.1f} tokens/s" if speed is not None else ''
        print(f"  {call['model']}: {call['elapsed_seconds']:.2f}s{first_text}{speed_text}")
    if not recent_calls:
        print("  No calls recorded yet.")

    completion = task_completion_stats()
    print(f"\n{Fore.YELLOW}Task completion (chat turns with an active persona):{Style.RESET_ALL}")
    if completion["total_completed"] == 0:
        print("  None recorded yet.")
    else:
        print(f"  {completion['total_completed']} total")
        for agent_name, count in completion["by_agent"].items():
            print(f"    {agent_name}: {count}")

    search = search_quality_stats()
    print(f"\n{Fore.YELLOW}Search quality:{Style.RESET_ALL}")
    if search["total_searches"] == 0:
        print("  No searches recorded yet.")
    else:
        print(
            f"  {search['total_searches']} searches, {search['zero_result_searches']} returned "
            f"nothing ({search['zero_result_rate']:.0%}), average {search['avg_result_count']:.1f} results"
        )

    tools = tool_usage_stats()
    print(f"\n{Fore.YELLOW}Tool usage:{Style.RESET_ALL}")
    if not tools:
        print("  No recorded self-improve/tool-generator activity yet.")
    else:
        for name, stats in sorted(tools.items(), key=lambda item: -item[1]["used"]):
            rate = f"{stats['success_rate']:.0%}" if stats["success_rate"] is not None else "n/a"
            print(f"  {name}: used {stats['used']}x, {rate} in a successful outcome")

    files = self_improve_target_file_stats()
    print(f"\n{Fore.YELLOW}Self-improve: files changed over time:{Style.RESET_ALL}")
    if not files:
        print("  No recorded self-improve attempts yet.")
    else:
        for target_file, stats in sorted(files.items(), key=lambda item: -item[1]["attempts"]):
            print(f"  {target_file}: {stats['attempts']} attempt(s), {stats['succeeded']} succeeded")

    for agent_name, label in (("self-improve", "Self-improve"), ("tool-generator", "Tool generation")):
        performance = evaluate_recent_performance(agent=agent_name)
        print(f"\n{Fore.YELLOW}{label} performance:{Style.RESET_ALL}")
        if performance["attempted"] == 0:
            print("  No attempts recorded yet.")
        else:
            print(f"  {performance['attempted']} attempted, {performance['success_rate']:.0%} succeeded")


def _cmd_overnight(prompt):
    """Manual trigger for Phase 16's overnight cycle - the same thing the
    real `feature: overnight` cron entry runs unattended, available here
    on demand so it can be run (and tested) without waiting for the
    schedule."""
    perform_overnight_cycle()


def _cmd_help(prompt):
    print("\nCommands:")
    print("/archives [topic] - Search knowledge base for [topic]")
    print("/askwiki [query] - Query Wikipedia and interpret the information")
    print("/new - Save current conversation and start a new one")
    print("/conversations - List saved conversations")
    print("/loadconv <filename|index> - Load a saved conversation by name or list index")
    print("/clear - Reset conversation")
    print("/coding - Toggle coding mode (nous-hermes2:10.7b)")
    print("/cron - Show cron help (add/edit/list/remove/run scheduled tasks; see docs/cron.md)")
    print("/cron list - List every crontab entry, numbered")
    print("/cron add <min> <hour> <day> <month> <weekday> prompt|feature|alarm: <text> - Schedule a task")
    print("/cron edit <n> <min> <hour> <day> <month> <weekday> prompt|feature|alarm: <text> - Change entry #n in place")
    print("/cron alarm <time description> message: <text> - Set an alarm/timer from natural time phrasing")
    print("/cron remove <n> - Remove crontab entry #n (asks to confirm)")
    print("/cron run <n> - Run a Gnosis-managed crontab entry #n right now")
    print("/delpath [topic] - Delete the learning path for the given topic")
    print("/exit - Save and exit")
    print("/historian - Dedupe/sort knowledge_base, merge saved conversations into it, clean agent_memory")
    print("/historian preview - Same as /historian but only reports what would change")
    print("/help - Show help")
    print("/job [agent] - Switch to specialized agent persona (research, philosophy, space, ethics, creative, scheduler, ...)")
    print("/news - Fetch latest news headlines")
    print("/password [-N] - Generate N (default 5) complex passwords, each 20 characters")
    print("/profile - Show current user profile")
    print("/profile persona <value> - Set a profile persona tone")
    print("/persona <value> - Shortcut to set persona tone")
    print("/deepthink - Toggle evidence-led, structured web research")
    print("/reason - Toggle reasoning mode (deepseek-r1:14b)")
    print("/reindexevidence - Add or refresh sortable metadata on saved web evidence")
    print("/showpath [topic] - Show the learning path for the given topic")
    print("/tarot - Perform a single-deck Tree of Life Tarot reading")
    print("/tutor [topic] - Create a learning path for the given topic")
    print("/tts - Toggle TTS mode (read responses aloud)")
    print("/unfiltered - Toggle unfiltered mode (r1-1776:70b)")
    print("/selfimprove - Propose, apply, test, and validate one small repo fix (reverts on failure, never auto-commits)")
    print("/selfimprove preview (or --dry-run) - Same as above, but never touches the live repo - reports the verified diff instead")
    print("/learning - Report recent self-improve success rate, failure patterns, and lessons learned")
    print("/generate - Design, generate, and sandbox-test a new tool for a recurring capability gap (proposal only, never auto-registered)")
    print("/report - Observability report: task completion, search quality, tool usage, self-improve/tool-generation performance")
    print("/overnight - Run the overnight learning cycle now (self-improve + tool generation + a combined report) - same as the nightly cron trigger")
    print("/voice - Toggle voice mode (for live input)")
    print("/websearch - Toggle web search (ON by default; the model decides per message whether to search)")
    print("/ytdl <url> - Download YouTube video in highest quality to ~/Downloads")
    print("\n💡 Pro Tip: Use @keyword@ tags in any message to search for current info!")
    print("   Example: 'When are @midterm elections@ happening?'")


def _cmd_exit(prompt):
    print(f"{Fore.MAGENTA}Exiting...")
    exit()


def _cmd_clear(prompt):
    context.assistant_convo = [sys_msgs.assistant_msg]
    print(f"{Fore.YELLOW}Conversation reset.")


def _cmd_new(prompt):
    path = new_conversation(save_current=True)
    if path:
        print(f"{Fore.GREEN}Saved previous conversation to: {path}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}Started a new conversation.{Style.RESET_ALL}")


def _cmd_conversations(prompt):
    files = list_conversations()
    if not files:
        print(f"{Fore.YELLOW}No saved conversations found.{Style.RESET_ALL}")
    else:
        print(f"{Fore.CYAN}Saved conversations:{Style.RESET_ALL}")
        for f in files:
            print(f" - {f}")


def _cmd_loadconv(prompt):
    parts = prompt.split(maxsplit=1)
    if len(parts) < 2:
        files = list_conversations()
        if not files:
            print(f"{Fore.YELLOW}No saved conversations available.{Style.RESET_ALL}")
        else:
            print(f"{Fore.CYAN}Saved conversations (use `/loadconv <index>`):{Style.RESET_ALL}")
            for i, f in enumerate(files, start=1):
                print(f" {i}. {f}")
        return
    arg = parts[1]
    loaded = load_conversation(arg)
    if loaded:
        print(f"{Fore.GREEN}Loaded conversation from: {loaded}{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}Could not load conversation: {arg}{Style.RESET_ALL}")


def _cmd_voice(prompt):
    context.voice_mode = not context.voice_mode
    if context.voice_mode:
        play_audio_effect("mic_on")
    print(f"{Fore.YELLOW}Voice {'ON' if context.voice_mode else 'OFF'}.")


def _cmd_stopvoice(prompt):
    stop_voice()
    print(f"{Fore.RED}Voice stopped.")


def _cmd_archives(prompt):
    parts = prompt.split(maxsplit=1)
    if len(parts) < 2:
        return
    topic = parts[1]
    found = tool_registry.execute("knowledge.search", topic=topic)
    if found:
        for fname, text in found:
            print(f"\nFound in {fname}:\n{text}\n")
    else:
        print(f"{Fore.RED}No results found for '{topic}' in knowledge base.")


def _cmd_tarot(prompt):
    from tarot import tarot_reading
    tarot_reading()


def _cmd_createpath(prompt):
    parts = prompt.split(maxsplit=2)
    if len(parts) < 3:
        print(f"{Fore.RED}Please provide a topic and resources for /createpath.{Style.RESET_ALL}")
        return
    topic = parts[1]
    resources = parts[2].split(",")
    create_learning_path(topic, resources)


def _build_command_router():
    router = CommandRouter()
    router.register("/reason", _cmd_reason)
    router.register("/deepthink", _cmd_deepthink)
    router.register("/reindexevidence", _cmd_reindexevidence)
    router.register_prefix("/password", _cmd_password)
    router.register_prefix("/job", _cmd_job)
    router.register("/unfiltered", _cmd_unfiltered)
    router.register("/coding", _cmd_coding)
    router.register("/tts", _cmd_tts)
    router.register("/websearch", _cmd_websearch)
    router.register(("/historian", "/historian preview", "/historian --dry-run"), _cmd_historian)
    router.register(("/cron", "/cron help"), _cmd_cron_help)
    router.register("/cron list", _cmd_cron_list)
    router.register_prefix("/cron alarm ", _cmd_cron_alarm)
    router.register_prefix("/cron add", _cmd_cron_add)
    router.register_prefix("/cron edit", _cmd_cron_edit)
    router.register_prefix("/cron remove", _cmd_cron_remove)
    router.register_prefix("/cron run", _cmd_cron_run)
    router.register_prefix("/askwiki", _cmd_askwiki)
    router.register_prefix("/tutor", _cmd_tutor)
    router.register_prefix("/showpath", _cmd_showpath)
    router.register_prefix("/delpath", _cmd_delpath)
    router.register_prefix("/news", _cmd_news)
    router.register_prefix("/ytdl", _cmd_ytdl)
    router.register_prefix("/profile", _cmd_profile)
    router.register_prefix("/persona", _cmd_persona)
    router.register(("/selfimprove", "/selfimprove preview", "/selfimprove --dry-run"), _cmd_selfimprove)
    router.register("/learning", _cmd_learning)
    router.register("/generate", _cmd_generate)
    router.register("/report", _cmd_report)
    router.register("/overnight", _cmd_overnight)
    router.register("/help", _cmd_help)
    router.register("/exit", _cmd_exit)
    router.register("/clear", _cmd_clear)
    router.register("/new", _cmd_new)
    router.register("/conversations", _cmd_conversations)
    # Bug fix (found during this extraction): originally nested inside an
    # outer `if prompt.lower() in [...]:` gate that only matched the bare
    # "/loadconv" with no argument - "/loadconv myfile" could never reach
    # its own handler and always fell through to the unrecognized-command
    # catch-all. Registering it as its own prefix fixes that.
    router.register_prefix("/loadconv", _cmd_loadconv)
    router.register("/voice", _cmd_voice)
    router.register("/stopvoice", _cmd_stopvoice)
    router.register_prefix("/archives", _cmd_archives)
    router.register("/tarot", _cmd_tarot)
    router.register_prefix("/createpath", _cmd_createpath)
    return router


_COMMAND_ROUTER = _build_command_router()


def _register_tools():
    """Register every capability Gnosis has as a Tool, binding each one to
    its real webagent.py implementation. Internal callers now reach these
    through tool_registry.execute(...) rather than calling the function
    directly - see TODO.md Phase 2's caller-migration entry."""
    tool_registry.register(WebSearchTool(search_web))
    tool_registry.register(WebFetchTool(fetch_page_content))
    tool_registry.register(KnowledgeSearchTool(search_knowledge_base))
    tool_registry.register(KnowledgeWriteTool(record_to_knowledge_base))
    tool_registry.register(SubscriptionsListTool(subscriptions.list_subscriptions))
    tool_registry.register(LiveWeatherTool(_live_weather_lookup))
    tool_registry.register(LiveStockQuoteTool(_live_stock_lookup))
    tool_registry.register(LiveSoccerResultTool(_live_soccer_lookup))
    tool_registry.register(CronListTool(cron_list_entries))
    tool_registry.register(CronAddTool(cron_add))
    tool_registry.register(CronEditTool(cron_edit))
    tool_registry.register(CronRemoveTool(cron_remove))
    tool_registry.register(CronRunTool(run_cron_task_now))
    tool_registry.register(GitStatusTool(_git))
    tool_registry.register(GitDiffTool(_git))
    tool_registry.register(TestRunTool(_run_self_improve_tests))
    tool_registry.register(RepoAuditTool(audit_repository))
    tool_registry.register(RepoAuditAdvancedTool(audit_repository_advanced))
    tool_registry.register(ShellSandboxedRunTool(
        lambda command_name, workspace_id=None: run_sandboxed_command(
            command_name, repo_root=_selfimprove_root(), workspace_id=workspace_id,
        )
    ))
    tool_registry.register(SandboxOpenTool(lambda: open_session(_selfimprove_root())))
    tool_registry.register(SandboxCloseTool(close_session))
    tool_registry.register(FilesystemReadTool(read_file))
    tool_registry.register(FilesystemWriteTool(write_file))
    tool_registry.register(DesignListProjectsTool(penpot.list_projects))
    tool_registry.register(DesignCreateProjectTool(penpot.create_project))
    tool_registry.register(DesignListFilesTool(penpot.list_files))
    tool_registry.register(DesignCreateFileTool(penpot.create_file))
    tool_registry.register(DesignGetFileTool(penpot.get_file))
    tool_registry.register(DesignAddBoardTool(penpot.add_board))
    tool_registry.register(DesignAddShapeTool(penpot.add_shape))
    tool_registry.register(ConversationInspectTool(_inspect_conversation))
    tool_registry.register(EvidenceVerifyTool(_verify_evidence))
    tool_registry.register(KnowledgeRelatedTool(_knowledge_related))
    tool_registry.register(KnowledgeForgetTool(_knowledge_forget))
    tool_registry.register(RepoInspectTool(_inspect_repository))
    tool_registry.register(ModelStatusTool(_model_status))
    tool_registry.register(TaskPlanTool(_build_task_plan))


def _register_skills():
    """Register every Skill Gnosis has. Must run after _register_tools() -
    SkillRegistry.register() validates each skill's required_tools against
    tool_registry at registration time."""
    skill_registry.register(ResearchTopicSkill())
    skill_registry.register(ConversationRecoverSkill())
    skill_registry.register(ResearchVerifySkill())
    skill_registry.register(KnowledgeMaintainSkill())
    skill_registry.register(RepositoryChangeReviewSkill())


def _on_task_completed(agent_name, user_input, response):
    """Phase 12: the one real multi-subscriber case - replaces what used
    to be two duplicated direct-call chains (chat_response and
    _handle_unmatched_prompt) with a single event and a single handler."""
    # Ellipsis only when real truncation happened - it used to be unconditional,
    # which made every short exchange read as cut off even when nothing was cut.
    user_part = user_input[:100] + ("..." if len(user_input) > 100 else "")
    response_part = response[:200] + ("..." if len(response) > 200 else "")
    save_agent_memory(agent_name, f"User: {user_part} Response: {response_part}")
    if should_save_to_knowledge_base(user_input, response):
        save_conversation_insights(agent_name, user_input, response)


def _register_event_subscribers():
    """Every event this codebase actually publishes gets the same generic
    activity-log subscriber (core/activity_log.py) - Phase 12's own job is
    making sure a published event lands somewhere real, not computing
    anything from it yet (that's Phase 13). TASK_COMPLETED additionally
    gets the domain-specific handler above."""
    for event_name in (SEARCH_COMPLETED, TASK_COMPLETED, SKILL_CREATED,
                        KNOWLEDGE_UPDATED, MEMORY_CREATED, TEST_PASSED, TEST_FAILED,
                        TOOL_SELECTION_MADE, TOOL_EXECUTION_COMPLETED, APP_STARTED):
        events.subscribe(event_name, lambda event_name=event_name, **payload: record_activity(event_name, **payload))
    events.subscribe(TASK_COMPLETED, _on_task_completed)


_register_tools()
_register_skills()
_register_event_subscribers()
events.publish(
    APP_STARTED, main_model=MODELS.get("main"), coding_model=MODELS.get("coding"),
    search_model=MODELS.get("search"), tool_count=len(tool_registry.list()), skill_count=len(skill_registry.list()),
)


def _read_next_prompt():
    print()
    if not context.voice_mode:
        play_audio_effect("response_end")
    if context.voice_mode:
        return recognize_speech()
    return _next_prompt_line(f"{Fore.BLUE}{get_fun_prompt()}{Style.RESET_ALL}")


def _before_dispatch(prompt):
    # A submitted message means the user is ready to move on; interrupt
    # any background TTS before processing it.
    stop_tts()


def _handle_unmatched_prompt(prompt):
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
        return

    context.assistant_convo = [m for m in context.assistant_convo if not m.get('_turn_context')]
    direct = is_direct_chat(prompt) and not context.deep_think_mode

    # Web search is planned by the model, one targeted query at a time.
    if context.deep_think_mode or (context.web_search_mode and not direct):
        update_user_notes_softly(prompt, [])
        print(f"{Fore.CYAN}🧭 Letting the model plan web research...{Style.RESET_ALL}\n")
        evidence = model_directed_web_research(prompt)
        context.assistant_convo.append({"role": "system", "_turn_context": True, "content": enhance_conversation_with_search(prompt, evidence, deep=context.deep_think_mode)})
        tool_action = _select_tool_action(prompt)
        if tool_action.get("tool"):
            tool_summary = _execute_tool_action(tool_action)
            if tool_summary:
                print(f"{Fore.CYAN}🛠️  Model selected tool: {tool_action['tool']}{Style.RESET_ALL}")
                context.assistant_convo.append({
                    "role": "system", "_turn_context": True,
                    "content": f"Additional context from a Gnosis capability you chose to use:\n{tool_summary}",
                })
        persona_prompt = get_persona_system_prompt()
        if persona_prompt:
            context.assistant_convo.append({"role": "system", "_turn_context": True, "content": persona_prompt})
        context.assistant_convo.append({"role": "user", "content": prompt})
        response = stream_response()
        if response and response.strip():
            # Persisted as historical/audit data, not shown to the user or
            # appended to context.assistant_convo - see chat_response's
            # identical fix and its docstring note for why (a small local
            # model shown its own past "--- Fact-check ---" text starts
            # imitating that format in its own later drafted answers).
            fact_check = fact_check_answer(response, evidence, user_prompt=prompt)
            if fact_check:
                save_fact_check_record(prompt, response, fact_check, evidence)
        return

    # Standard conversation
    # Process @keyword@ search tags first
    processed_prompt = process_search_tags(prompt)

    # A real cron mutation is reported verbatim, code-generated, with no
    # LLM call for this turn at all - see run_scheduler_agent_step's
    # docstring for why free-form narration of a real system action isn't
    # trusted.
    scheduler_reply = run_scheduler_agent_step(processed_prompt)
    if scheduler_reply is not None:
        context.assistant_convo.append({"role": "user", "content": processed_prompt})
        context.assistant_convo.append({"role": "assistant", "content": scheduler_reply})
        print(f"{Fore.GREEN}{scheduler_reply}{Style.RESET_ALL}")
        return

    # Add contextual information for better responses
    context_info = []
    context_info.append(get_datetime_context())
    user_context = get_relevant_user_context(processed_prompt)
    if user_context != "No user profile information available":
        context_info.append(f"User context: {user_context}")

    # Add context as system message before user prompt
    if context_info:
        context_message = " | ".join(context_info)
        context.assistant_convo.append({"role": "system", "_turn_context": True, "content": f"[Context: {context_message}]"})

    tool_action = {"tool": None} if direct else _select_tool_action(processed_prompt)
    if tool_action.get("tool"):
        tool_summary = _execute_tool_action(tool_action)
        if tool_summary:
            print(f"{Fore.CYAN}🛠️  Model selected tool: {tool_action['tool']}{Style.RESET_ALL}")
            context.assistant_convo.append({
                "role": "system", "_turn_context": True,
                "content": f"Additional context from a Gnosis capability you chose to use:\n{tool_summary}",
            })

    persona_prompt = get_persona_system_prompt()
    if persona_prompt:
        context.assistant_convo.append({"role": "system", "_turn_context": True, "content": persona_prompt})

    context.assistant_convo.append({"role": "user", "content": processed_prompt})

    # Context-aware agent suggestions
    suggested_agent = suggest_agent_for_context(processed_prompt)
    if suggested_agent and suggested_agent != context.current_agent:
        agent_name = AVAILABLE_AGENTS[suggested_agent]['name']
        print(f"{Fore.YELLOW}💡 This looks like a job for the {agent_name}! Switch with `/job {suggested_agent}`?{Style.RESET_ALL}")

    # Advanced conversation pattern analysis
    analyze_conversation_patterns(processed_prompt)

    response = stream_response()

    if context.current_agent and response:
        events.publish(
            TASK_COMPLETED, agent_name=context.current_agent,
            user_input=processed_prompt, response=response,
        )


def main():

    # Initialize agent to default mode on startup
    context.current_agent = None

    # Create default user profile if it doesn't exist
    create_default_user_profile()

    pull_model()

    if context.web_search_mode:
        print(f"{Fore.YELLOW}Web search is ON by default — the model decides per message whether to search.{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Checking search service availability...{Style.RESET_ALL}")
        svc = check_search_services()
        parts = ['SearxNG: UP' if svc.get('searxng') else 'SearxNG: DOWN']
        parts.append('Fallback: offline contextual search available')
        print(f"{Fore.GREEN}{' | '.join(parts)}{Style.RESET_ALL}")

    orchestrator = Orchestrator(
        read_input=_read_next_prompt,
        before_dispatch=_before_dispatch,
        router=_COMMAND_ROUTER,
        on_unmatched=_handle_unmatched_prompt,
    )
    orchestrator.run_forever()

def _run_headless_cron_task(task_id):
    """Entry point for `python webagent.py --cron-task <id>`, invoked by an actual crontab line."""
    create_default_user_profile()
    success, output = tool_registry.execute("cron.run", task_id=task_id)
    print(output)
    return 0 if success else 1


if __name__ == "__main__":
    if "--cron-task" in sys.argv:
        _flag_index = sys.argv.index("--cron-task")
        _task_id = sys.argv[_flag_index + 1] if _flag_index + 1 < len(sys.argv) else None
        if not _task_id:
            print("Usage: webagent.py --cron-task <task_id>", file=sys.stderr)
            sys.exit(1)
        sys.exit(_run_headless_cron_task(_task_id))
    main()
