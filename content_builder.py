"""LinkedIn/Blog Posts Builder - a pane for generating marketing copy for
LOZDEV (Skylar's website-building-and-hosting business) with Ollama.

Split the same way as worklog.py: plain-Python storage/prompt-building logic
up top (no Qt imports, unit-testable on its own) with
LinkedInBlogBuilderWidget's Qt layer below it as a thin UI over that state.
The business profile and generated-post history live in one JSON file under
core_config.path("content_builder") - same lazy-mkdir-on-write-only
discipline as core/activity_log.py and worklog.py: a read must never create
the directory.

First-draft output from a small local model tends to read generic - the
helper functionality here (content angle, hook style, audience, CTA, a
phrases-to-avoid list, writing-sample voice matching, regenerate-with-a-
different-angle, and a separate polish pass) exists specifically to push
back on that, on top of just letting Ollama free-write from a topic string.
"""
import json
import os
import uuid
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from core import config as core_config
from core.models import MODELS, chat as model_chat

TEXT_MUTED = "#797986"
ACCENT = "#7c5cff"
WARNING_COLOR = "#f5a524"
DANGER_COLOR = "#e5484d"

# LinkedIn hard-caps posts at 3000 characters; only the first ~210 show
# before the "see more" truncation, so that's where the hook has to land.
LINKEDIN_MAX_CHARS = 3000
LINKEDIN_HOOK_CHARS = 210

DEFAULT_BUSINESS_PROFILE = (
    "LOZDEV is a website design, development, and hosting business. It builds "
    "fast, modern websites for small businesses and solo entrepreneurs, then "
    "hosts and maintains them so clients never have to think about the "
    "technical side. Voice: approachable, plain-spoken, confident - explain "
    "technical value in terms of business outcomes (more customers, less "
    "downtime, one less thing to worry about), not jargon."
)

DEFAULT_AUDIENCE = (
    "Small business owners and solo entrepreneurs who don't have a website "
    "yet, or have an old one that no longer represents them. Not deeply "
    "technical - they care about results (more customers, less hassle), not "
    "how the tech works."
)

DEFAULT_CTA = "Book a free consultation with LOZDEV to see what a new site could do for your business."

DEFAULT_AVOID_PHRASES = "\n".join((
    "unlock", "unleash", "game-changer", "dive into", "delve into",
    "in today's fast-paced world", "in the ever-evolving landscape",
    "look no further", "elevate your", "take it to the next level",
    "at the end of the day", "it's important to note that", "in conclusion",
    "revolutionize", "seamless", "leverage", "synergy", "paradigm shift",
    "cutting-edge", "robust solution", "unlock your potential",
))

TONES = ("Professional", "Casual", "Enthusiastic", "Educational")

POST_TYPES = {
    "linkedin": {
        "label": "LinkedIn Post",
        "instructions": (
            f"Write a LinkedIn post. LinkedIn hard-caps posts at "
            f"{LINKEDIN_MAX_CHARS} characters - the finished post, including "
            f"hashtags, must stay under that limit; aim for 900-1500 "
            f"characters for typical engagement. Only the first "
            f"{LINKEDIN_HOOK_CHARS} characters show before the \"see more\" "
            f"cutoff, so the opening line must hook on its own without "
            f"needing the rest of the post - don't summarize the whole post "
            f"in that first line, create curiosity or tension instead. Use "
            f"short paragraphs and line breaks for readability. End with "
            f"3-5 relevant hashtags."
        ),
    },
    "blog": {
        "label": "Blog Post",
        "instructions": (
            "Write a blog post draft (500-800 words) with a title, a short "
            "intro, 2-4 subheadings, and a concluding call to action. Write "
            "it ready to publish on a company blog - skimmable, no filler."
        ),
    },
}

GENERAL_QUALITY_INSTRUCTIONS = (
    "Be concrete and specific throughout - real-sounding details or "
    "clearly-illustrative examples beat vague generalities like \"we help "
    "businesses grow\" or \"quality service.\" Vary sentence length. Avoid "
    "rhetorical questions as a crutch and empty transition phrases."
)

SEO_INSTRUCTIONS = {
    "linkedin": (
        "SEO/discoverability: work the target keyword or phrase naturally "
        "into the opening line and at least once more in the body - it "
        "affects what LinkedIn's search and feed algorithm surfaces the "
        "post for. Never stuff it in unnaturally, and prefer it in plain "
        "text over only in a hashtag."
    ),
    "blog": (
        "SEO: before the body, output two lines - "
        "\"SEO Title: \" (50-60 characters, includes the target keyword "
        "near the front) and \"Meta Description: \" (150-160 characters, "
        "includes the keyword, written to earn the click from a search "
        "results page). Work the keyword into the post title, the first "
        "100 words, and at least one subheading, and use it naturally a "
        "few more times through the body - never keyword-stuff. End with "
        "a line \"Suggested tags: \" listing 3-5 related secondary "
        "keywords/phrases."
    ),
}

# label -> instruction fragment. "" (the first entry in each) means "no
# extra steering" so the combo box always has a neutral default.
CONTENT_ANGLES = {
    "Let the topic decide": "",
    "Educational tip": (
        "Teach one specific, practical tip related to the topic - something "
        "the reader can act on today. No generic advice."
    ),
    "Common mistake": (
        "Center the post on one specific, common mistake business owners "
        "make related to the topic, what it costs them, and what to do "
        "instead."
    ),
    "Client win / case study": (
        "Frame the post around a real or realistic (anonymized) before/after "
        "result for a client related to the topic - concrete outcomes, not "
        "vague praise."
    ),
    "Behind the scenes": (
        "Give a behind-the-scenes look at how LOZDEV actually does the work "
        "related to the topic - the process, a tool, or a decision and why "
        "it was made."
    ),
    "Industry trend / hot take": (
        "Share a clear, specific opinion or reaction to a trend related to "
        "the topic. Take an actual stance - don't hedge."
    ),
    "Direct offer / promo": (
        "Lead with the value to the reader, then make a direct, "
        "low-pressure offer related to the topic."
    ),
    "Personal story": (
        "Tell a short, specific personal or founder story related to the "
        "topic, then connect it to the point being made."
    ),
}

HOOK_STYLES = {
    "Let the model choose": "",
    "Question": (
        "Open with a direct, specific question the target audience actually "
        "asks themselves."
    ),
    "Bold statement": (
        "Open with a bold, specific claim or opinion - something a reader "
        "could disagree with."
    ),
    "Number / scale": (
        "Open by naming a concrete number, timeframe, or scale (e.g. "
        "\"3 weeks,\" \"half your visitors\") - only something LOZDEV can "
        "stand behind. Never invent a statistic or cite a made-up source."
    ),
    "Story / scene": (
        "Open with a one- or two-sentence scene or anecdote, then connect "
        "it to the topic."
    ),
    "Contrarian": "Open by pushing back on a common but wrong assumption related to the topic.",
}


# ----------------------------------------------------------------------
# Storage - business profile/voice settings + generated post history
# ----------------------------------------------------------------------
def _data_path():
    return os.path.join(core_config.path("content_builder"), "content_builder.json")


def _defaults():
    return {
        "business_profile": DEFAULT_BUSINESS_PROFILE,
        "target_audience": DEFAULT_AUDIENCE,
        "default_cta": DEFAULT_CTA,
        "avoid_phrases": DEFAULT_AVOID_PHRASES,
        "style_examples": "",
        "history": [],
    }


def load_data():
    path = _data_path()
    if not os.path.isfile(path):
        return _defaults()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return _defaults()
    if not isinstance(data, dict):
        return _defaults()
    for key, value in _defaults().items():
        data.setdefault(key, value)
    return data


def save_data(data):
    path = _data_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _clean_phrase_list(text):
    parts = []
    for chunk in text.replace(",", "\n").split("\n"):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


def build_messages(*, business_profile, post_type, topic, tone, notes="", seo_keyword="",
                    audience="", cta="", angle="", hook_style="", avoid_phrases="",
                    style_examples="", avoid_repeating=""):
    type_info = POST_TYPES[post_type]
    parts = [
        "You are a marketing copywriter for the following business:",
        "",
        business_profile.strip(),
        "",
        type_info["instructions"],
        GENERAL_QUALITY_INSTRUCTIONS,
        f"Tone: {tone}.",
    ]
    if audience:
        parts.append(
            f"Target audience: {audience}. Write directly to them - their "
            f"situation, their problem, their words."
        )
    angle_instruction = CONTENT_ANGLES.get(angle, "")
    if angle_instruction:
        parts.append(angle_instruction)
    hook_instruction = HOOK_STYLES.get(hook_style, "")
    if hook_instruction:
        parts.append(hook_instruction)
    if cta:
        parts.append(f"Work this call to action in naturally, at the end: {cta}")
    phrases = _clean_phrase_list(avoid_phrases) if avoid_phrases else []
    if phrases:
        parts.append(
            "Never use these overused phrases or close variants of them: "
            f"{', '.join(phrases)}. Write like a specific person who runs "
            "this business, not a generic corporate AI voice."
        )
    if style_examples.strip():
        parts.append(
            "Match the voice, sentence rhythm, and level of formality of "
            "these past posts (don't reuse their content, just the voice):"
            f"\n---\n{style_examples.strip()}\n---"
        )
    if seo_keyword:
        parts.append(SEO_INSTRUCTIONS[post_type])
        parts.append(f"Target keyword/phrase: {seo_keyword}")
    parts.append("Write only the finished post - no preamble, no explanation, no markdown code fences.")
    system = "\n\n".join(parts)

    user = f"Topic: {topic}"
    if notes:
        user += f"\n\nAdditional notes/points to include:\n{notes}"
    if avoid_repeating.strip():
        user += (
            "\n\nA previous draft already used this angle and these words - "
            "write something meaningfully different this time (a different "
            "hook, different structure, different phrasing), not a light "
            f"rewrite:\n---\n{avoid_repeating.strip()}\n---"
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_polish_messages(business_profile, post_type, current_text, avoid_phrases=""):
    """A second-pass "editor" prompt: tighten what's already there instead of
    writing a fresh draft - a separate, smaller lever than regenerating."""
    type_info = POST_TYPES[post_type]
    system = (
        f"You are an editor tightening a {type_info['label']} for the "
        f"following business:\n\n{business_profile.strip()}\n\n"
        "Cut filler and cliche AI-marketing phrasing, tighten the wording, "
        "and make it sound like a specific person wrote it. Keep the "
        "meaning, structure, length, and any hashtags/tags intact. Return "
        "only the revised post, nothing else."
    )
    phrases = _clean_phrase_list(avoid_phrases) if avoid_phrases else []
    if phrases:
        system += f"\n\nNever use: {', '.join(phrases)}."
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": current_text},
    ]


def list_available_models():
    """Local Ollama models to offer in the model picker, in the order the
    daemon reports them, falling back to the curated MODELS registry if the
    daemon can't be reached. The import is local (not at module load time)
    so tests can monkeypatch core.models.ollama and have it take effect."""
    from core.models import ollama as ollama_client
    fallback = list(dict.fromkeys(MODELS.values()))
    if ollama_client is None:
        return fallback
    try:
        response = ollama_client.list()
        raw_models = response.get("models", []) if isinstance(response, dict) else getattr(response, "models", [])
        names = []
        for m in raw_models:
            name = m.get("model") if isinstance(m, dict) else getattr(m, "model", None)
            if name:
                names.append(name)
        return names or fallback
    except Exception:
        return fallback


def add_history_entry(post_type, topic, tone, content):
    data = load_data()
    entry = {
        "id": uuid.uuid4().hex[:8],
        "post_type": post_type,
        "topic": topic,
        "tone": tone,
        "content": content,
        "created_at": datetime.now().isoformat(),
    }
    data["history"].insert(0, entry)
    save_data(data)
    return entry


def delete_history_entry(entry_id):
    data = load_data()
    data["history"] = [e for e in data["history"] if e["id"] != entry_id]
    save_data(data)


# ----------------------------------------------------------------------
# Qt layer
# ----------------------------------------------------------------------
class _GenerateWorker(QThread):
    """Runs core.models.chat() off the GUI thread so Generate never freezes
    the window - same shape as ResponseWorker/CycleWorker in webagent_gui.py.
    """
    result_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, model, messages):
        super().__init__()
        self.model = model
        self.messages = messages

    def run(self):
        try:
            response = model_chat(model=self.model, messages=self.messages, stream=False)
            self.result_ready.emit(response["message"]["content"])
        except Exception as e:
            self.error_occurred.emit(str(e))


class LinkedInBlogBuilderWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = load_data()
        self._available_models = list_available_models()
        self._worker = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(15, 15, 15, 15)
        outer.setSpacing(10)

        title = QLabel("📝 LinkedIn/Blog Builder")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        self.linkedin_tab = self._build_generator_tab("linkedin")
        self.blog_tab = self._build_generator_tab("blog")
        self.history_tab = self._build_history_tab()
        self.profile_tab = self._build_profile_tab()
        self.tabs.addTab(self.linkedin_tab, "LinkedIn Post")
        self.tabs.addTab(self.blog_tab, "Blog Post")
        self.tabs.addTab(self.history_tab, "History")
        self.tabs.addTab(self.profile_tab, "Business Profile")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._refresh_history()

    def _on_tab_changed(self, index):
        if self.tabs.widget(index) is self.history_tab:
            self._refresh_history()

    def save_now(self):
        """No-op: every write (profile edits, history saves) is flushed to
        disk immediately, same as worklog.py."""
        pass

    # ------------------------------------------------------------------
    # Generator tabs (LinkedIn / Blog share the same layout)
    # ------------------------------------------------------------------
    def _build_generator_tab(self, post_type):
        page = QWidget()
        page.post_type = post_type
        outer = QVBoxLayout(page)

        page.topic_input = QLineEdit()
        page.topic_input.setPlaceholderText("e.g. why small businesses need managed hosting")

        page.angle_combo = QComboBox()
        page.angle_combo.addItems(list(CONTENT_ANGLES.keys()))

        page.audience_input = QLineEdit()
        page.audience_input.setPlaceholderText(self._data["target_audience"] or "(set a default in Business Profile)")

        page.tone_combo = QComboBox()
        page.tone_combo.addItems(TONES)

        page.hook_combo = QComboBox()
        page.hook_combo.addItems(list(HOOK_STYLES.keys()))

        page.cta_input = QLineEdit()
        page.cta_input.setPlaceholderText(self._data["default_cta"] or "(set a default in Business Profile)")

        page.seo_input = QLineEdit()
        page.seo_input.setPlaceholderText("e.g. small business website hosting")

        page.model_combo = QComboBox()
        page.model_combo.addItems(self._available_models)
        default_model = MODELS.get("main")
        if default_model in self._available_models:
            page.model_combo.setCurrentText(default_model)

        form = QFormLayout()
        form.addRow("Topic:", page.topic_input)
        form.addRow("Angle:", page.angle_combo)
        form.addRow("Audience:", page.audience_input)
        form.addRow("Tone:", page.tone_combo)
        form.addRow("Opening hook:", page.hook_combo)
        form.addRow("Call to action:", page.cta_input)
        form.addRow("SEO keyword (optional):", page.seo_input)
        form.addRow("Model:", page.model_combo)
        outer.addLayout(form)

        outer.addWidget(QLabel("Notes / key points to include (optional):"))
        page.notes_input = QTextEdit()
        page.notes_input.setFixedHeight(60)
        outer.addWidget(page.notes_input)

        button_row = QHBoxLayout()
        page.generate_button = QPushButton(f"Generate {POST_TYPES[post_type]['label']}")
        page.generate_button.setStyleSheet(f"background-color: {ACCENT}; font-weight: bold;")
        button_row.addWidget(page.generate_button)
        page.regenerate_button = QPushButton("↻ Regenerate")
        page.regenerate_button.setToolTip(
            "Fresh take on the same inputs - the model is told to avoid repeating the current draft."
        )
        page.regenerate_button.setEnabled(False)
        button_row.addWidget(page.regenerate_button)
        page.polish_button = QPushButton("✨ Polish")
        page.polish_button.setToolTip(
            "Tighten the current draft and cut AI-sounding filler, without rewriting it from scratch."
        )
        page.polish_button.setEnabled(False)
        button_row.addWidget(page.polish_button)
        button_row.addStretch()
        page.copy_button = QPushButton("Copy")
        button_row.addWidget(page.copy_button)
        page.save_button = QPushButton("Save to History")
        button_row.addWidget(page.save_button)
        outer.addLayout(button_row)

        page.output = QTextEdit()
        page.output.setPlaceholderText("Generated post will appear here - feel free to edit before copying.")
        outer.addWidget(page.output, 1)

        page.counter_label = QLabel("")
        page.counter_label.setStyleSheet(f"color: {TEXT_MUTED};")
        outer.addWidget(page.counter_label)

        page.status_label = QLabel("")
        page.status_label.setStyleSheet(f"color: {TEXT_MUTED};")
        outer.addWidget(page.status_label)

        page.output.textChanged.connect(lambda: self._on_output_changed(page))
        self._on_output_changed(page)

        page.generate_button.clicked.connect(lambda: self._generate(page, regenerate=False))
        page.regenerate_button.clicked.connect(lambda: self._generate(page, regenerate=True))
        page.polish_button.clicked.connect(lambda: self._polish(page))
        page.copy_button.clicked.connect(lambda: self._copy_to_clipboard(page.output))
        page.save_button.clicked.connect(lambda: self._save_to_history(page))
        return page

    def _on_output_changed(self, page):
        has_text = bool(page.output.toPlainText().strip())
        page.regenerate_button.setEnabled(has_text)
        page.polish_button.setEnabled(has_text)
        self._update_counter(page.post_type, page.output, page.counter_label)

    def _update_counter(self, post_type, output, counter_label):
        text = output.toPlainText()
        if post_type == "linkedin":
            chars = len(text)
            if chars > LINKEDIN_MAX_CHARS:
                color = DANGER_COLOR
            elif chars > LINKEDIN_MAX_CHARS * 0.9:
                color = WARNING_COLOR
            else:
                color = TEXT_MUTED
            counter_label.setText(f"{chars} / {LINKEDIN_MAX_CHARS} characters "
                                   f"(first {LINKEDIN_HOOK_CHARS} shown before \"see more\")")
            counter_label.setStyleSheet(f"color: {color};")
        else:
            words = len(text.split())
            counter_label.setText(f"{words} words (target 500-800)")
            counter_label.setStyleSheet(f"color: {TEXT_MUTED};")

    def _generate(self, page, regenerate=False):
        topic = page.topic_input.text().strip()
        if not topic:
            QMessageBox.warning(self, "Missing topic", "Enter a topic before generating.")
            return
        avoid_repeating = page.output.toPlainText().strip() if regenerate else ""
        audience = page.audience_input.text().strip() or self._data["target_audience"]
        cta = page.cta_input.text().strip() or self._data["default_cta"]
        messages = build_messages(
            business_profile=self._data["business_profile"],
            post_type=page.post_type,
            topic=topic,
            tone=page.tone_combo.currentText(),
            notes=page.notes_input.toPlainText().strip(),
            seo_keyword=page.seo_input.text().strip(),
            audience=audience,
            cta=cta,
            angle=page.angle_combo.currentText(),
            hook_style=page.hook_combo.currentText(),
            avoid_phrases=self._data["avoid_phrases"],
            style_examples=self._data["style_examples"],
            avoid_repeating=avoid_repeating,
        )
        model = page.model_combo.currentText() or MODELS["main"]
        self._run_worker(page, messages, model, "Regenerating..." if regenerate else "Generating...")

    def _polish(self, page):
        current = page.output.toPlainText().strip()
        if not current:
            return
        messages = build_polish_messages(
            self._data["business_profile"], page.post_type, current, self._data["avoid_phrases"],
        )
        model = page.model_combo.currentText() or MODELS["main"]
        self._run_worker(page, messages, model, "Polishing...")

    def _run_worker(self, page, messages, model, status_text):
        page.generate_button.setEnabled(False)
        page.regenerate_button.setEnabled(False)
        page.polish_button.setEnabled(False)
        page.status_label.setText(status_text)
        self._worker = _GenerateWorker(model, messages)
        self._worker.result_ready.connect(lambda text: self._on_generated(page, text))
        self._worker.error_occurred.connect(lambda err: self._on_generate_error(page, err))
        self._worker.start()

    def _on_generated(self, page, text):
        page.output.setPlainText(text.strip())  # textChanged re-enables regenerate/polish
        page.generate_button.setEnabled(True)
        page.status_label.setText("Done.")

    def _on_generate_error(self, page, err):
        page.generate_button.setEnabled(True)
        has_text = bool(page.output.toPlainText().strip())
        page.regenerate_button.setEnabled(has_text)
        page.polish_button.setEnabled(has_text)
        page.status_label.setText("")
        QMessageBox.critical(self, "Generation failed", err)

    def _copy_to_clipboard(self, output):
        text = output.toPlainText()
        if text:
            QApplication.clipboard().setText(text)

    def _save_to_history(self, page):
        text = page.output.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Nothing to save", "Generate (or write) a post first.")
            return
        add_history_entry(page.post_type, page.topic_input.text().strip(), page.tone_combo.currentText(), text)
        self._data = load_data()
        page.status_label.setText("Saved to history.")
        self._refresh_history()

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    def _build_history_tab(self):
        page = QWidget()
        outer = QHBoxLayout(page)

        self.history_list = QListWidget()
        self.history_list.setFixedWidth(260)
        self.history_list.currentItemChanged.connect(self._on_history_selected)
        outer.addWidget(self.history_list)

        right = QVBoxLayout()
        self.history_output = QTextEdit()
        self.history_output.setReadOnly(True)
        right.addWidget(self.history_output, 1)

        button_row = QHBoxLayout()
        copy_button = QPushButton("Copy")
        copy_button.clicked.connect(lambda: self._copy_to_clipboard(self.history_output))
        button_row.addWidget(copy_button)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self._delete_selected_history)
        button_row.addWidget(delete_button)
        button_row.addStretch()
        right.addLayout(button_row)
        outer.addLayout(right, 1)

        return page

    def _refresh_history(self):
        self._data = load_data()
        self.history_list.clear()
        for entry in self._data["history"]:
            label = f"[{POST_TYPES[entry['post_type']]['label']}] {entry['topic'] or '(untitled)'}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, entry["id"])
            self.history_list.addItem(item)
        self.history_output.clear()

    def _on_history_selected(self, current, previous):
        if current is None:
            self.history_output.clear()
            return
        entry_id = current.data(Qt.ItemDataRole.UserRole)
        entry = next((e for e in self._data["history"] if e["id"] == entry_id), None)
        self.history_output.setPlainText(entry["content"] if entry else "")

    def _delete_selected_history(self):
        current = self.history_list.currentItem()
        if current is None:
            return
        delete_history_entry(current.data(Qt.ItemDataRole.UserRole))
        self._refresh_history()

    # ------------------------------------------------------------------
    # Business profile / voice settings
    # ------------------------------------------------------------------
    def _build_profile_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        content_layout.addWidget(QLabel(
            "Business profile - sent as context for every post generated below:"
        ))
        self.profile_input = QTextEdit()
        self.profile_input.setPlainText(self._data["business_profile"])
        self.profile_input.setFixedHeight(100)
        content_layout.addWidget(self.profile_input)

        content_layout.addWidget(QLabel("Target audience (default - each post can override it):"))
        self.audience_input = QTextEdit()
        self.audience_input.setPlainText(self._data["target_audience"])
        self.audience_input.setFixedHeight(60)
        content_layout.addWidget(self.audience_input)

        content_layout.addWidget(QLabel("Default call to action (each post can override it):"))
        self.cta_input = QLineEdit()
        self.cta_input.setText(self._data["default_cta"])
        content_layout.addWidget(self.cta_input)

        content_layout.addWidget(QLabel("Phrases to avoid - one per line (overused AI-marketing filler):"))
        self.avoid_phrases_input = QTextEdit()
        self.avoid_phrases_input.setPlainText(self._data["avoid_phrases"])
        self.avoid_phrases_input.setFixedHeight(90)
        content_layout.addWidget(self.avoid_phrases_input)

        content_layout.addWidget(QLabel(
            "Writing samples (optional) - paste 1-3 posts you like the voice of; "
            "the model matches their style without copying their content:"
        ))
        self.style_examples_input = QTextEdit()
        self.style_examples_input.setPlainText(self._data["style_examples"])
        self.style_examples_input.setFixedHeight(140)
        content_layout.addWidget(self.style_examples_input)

        content_layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        save_button = QPushButton("Save Business Profile")
        save_button.clicked.connect(self._save_profile)
        outer.addWidget(save_button)
        return page

    def _save_profile(self):
        profile = self.profile_input.toPlainText().strip()
        if not profile:
            QMessageBox.warning(self, "Empty profile", "The business profile can't be empty.")
            return
        self._data["business_profile"] = profile
        self._data["target_audience"] = self.audience_input.toPlainText().strip()
        self._data["default_cta"] = self.cta_input.text().strip()
        self._data["avoid_phrases"] = self.avoid_phrases_input.toPlainText().strip()
        self._data["style_examples"] = self.style_examples_input.toPlainText().strip()
        save_data(self._data)
        self._refresh_placeholders()
        QMessageBox.information(self, "Saved", "Business profile saved.")

    def _refresh_placeholders(self):
        for page in (self.linkedin_tab, self.blog_tab):
            page.audience_input.setPlaceholderText(self._data["target_audience"] or "(set a default in Business Profile)")
            page.cta_input.setPlaceholderText(self._data["default_cta"] or "(set a default in Business Profile)")
