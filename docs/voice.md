# Voice chat

Open Voice settings from the voice panel and choose a Reply voice. Click **Preview voice** to hear a short sample at the selected speed before saving. Click **Stop preview** to interrupt it; closing the settings also stops playback.

- Aria, Jenny, Guy, and Sonia are online neural voices. They need internet and send the spoken reply text to Microsoft through edge-tts. No API key is required.
- Samantha and the other system voices run locally. New sessions default to Samantha on macOS at 175 words per minute; saved voice and speed preferences are preserved.

Install dependencies with `./venv/bin/python -m pip install -r requirements.txt`.
Neural playback uses afplay on macOS and requires mpv on other platforms.

Voice chat still speaks only the answer, skipping source sections, numbered citations, URLs, and fenced code. Interrupt and End cancel pending synthesis and playback. If online synthesis fails, select a local voice in settings.
