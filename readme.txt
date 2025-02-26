Got it! Here’s the README.txt without emojis, ready to be saved in VS Code as README.txt.

README.txt

# Voice-Enabled AI Chatbot with Web Search & Text-to-Speech

This is a voice-controlled chatbot that integrates web search using DuckDuckGo, speech recognition, and text-to-speech (TTS) with Edge TTS.

---

## Installation Instructions

### 1. Install Python
Ensure you have **Python 3.9+** installed. You can check by running:
```sh
python --version

If you don’t have Python installed, download it from:
https://www.python.org/downloads/

2. Install Dependencies

Use pip to install all required packages:

pip install -r requirements.txt

If you run into pyaudio issues, install it manually:
	•	Windows:

pip install pipwin
pipwin install pyaudio


	•	Mac/Linux:

brew install portaudio
pip install pyaudio

3. Running the Chatbot

Start the chatbot by running:

python main.py

Once started, the chatbot supports both text and voice input.

Voice Commands & Features
	•	Start Voice Mode: /voice
	•	Stop Voice Mode: Say "voice stop", "mute yourself", "stop talking", "stop speaking", "end voice mode", or "voice mode"
	•	Enable Web Search: /websearch
	•	Disable Web Search: Say "web search stop"
	•	Manually Scrape a URL: /scrape [url]

How Web Search Works
	•	When web search mode is ON, the assistant will:
	1.	Search DuckDuckGo for relevant results.
	2.	Scrape and summarize the top pages.
	3.	Use the extracted info to generate a response.
	•	If results are incomplete, the assistant may retry with a refined search (up to 5 times).

Troubleshooting

Audio Issues
	•	Ensure your microphone is working.
	•	Try installing pyaudio manually (see step 2).

Web Search Not Working
	•	Ensure you have an active internet connection.
	•	Run:

pip install duckduckgo-search requests trafilatura beautifulsoup4



TTS Not Speaking
	•	Try changing the TTS voice in speak_text() inside main.py.

Upcoming Features
	•	Auto-refining searches if the first attempt doesn’t return useful data
	•	More voices for TTS
	•	Voice-based settings toggles

Created by flyser3
Last Updated: 2/25/2025