Voice-Enabled AI Chatbot with Web Search, Wikipedia Integration & Text-to-Speech

This AI chatbot supports voice input, real-time web search via DuckDuckGo, Wikipedia scraping, AI-powered reasoning, and text-to-speech (TTS). It is designed for research, automation, and interactive conversations.

Installation Instructions

1. Install Python 3.9+

Check if Python is installed:

python --version

If not, download it from:
Python Official Site

2. Install Dependencies

Use pip to install the required libraries:

pip install -r requirements.txt

If you encounter issues with PyAudio, install it manually:

Windows

pip install pipwin  
pipwin install pyaudio  

Mac/Linux

brew install portaudio  
pip install pyaudio  

3. Running the Chatbot

Start the chatbot with:

python main.py

Once running, it supports both text and voice input.

Command Reference

Command	Description
/voice	Enables voice mode
“voice stop”	Disables voice mode
/tts	Enables text-to-speech mode
/websearch	Enables web search
“web search stop”	Disables web search
/askwiki [query]	Searches Wikipedia and generates a response
/tarot	Generates a Tree of Life Tarot reading with AI interpretation
/reason	Uses DeepSeek for advanced reasoning
/unfiltered	Uses r1-1776 for unrestricted AI responses
/historian	Organizes and cleans the knowledge base
/archives [topic]	Searches the stored knowledge base
/clear	Resets the conversation
/exit	Exits the program

Web Search Overview
	1.	Queries DuckDuckGo for the most relevant results.
	2.	Scrapes and summarizes key webpages.
	3.	Uses AI to generate a response based on the retrieved information.
	4.	If necessary, retries with a refined search (up to five times).

When web search mode is enabled, all user prompts will attempt to retrieve the most accurate information available online.

Wikipedia Integration (/askwiki)
	1.	Breaks down the query into relevant topics.
	2.	Finds Wikipedia pages that match those topics.
	3.	Extracts and summarizes key details.
	4.	Saves useful content in the knowledge base.
	5.	Uses AI to generate a response based on the extracted information.

If Wikipedia does not provide sufficient data, the assistant will automatically switch to web search.

Tarot Reading (/tarot)
	1.	Draws ten Minor Arcana cards for the Sephiroth positions.
	2.	Places Major Arcana cards onto the Paths if drawn.
	3.	Displays the full reading with mystical messages.
	4.	AI interprets the spread and provides insights.
	5.	If TTS mode is enabled, responses will be read in a distinct voice.

Historian Mode (/historian)
	1.	Removes duplicate entries from the knowledge base.
	2.	Categorizes data into topics such as “Technology,” “History,” “Science,” etc.
	3.	Improves searchability for archived information.
	4.	Automatically suggests topics when searching the archives.

This mode helps organize previously stored responses for easier access.

Upcoming Mirroring Bot

A planned feature for automated decision-making and AI-driven trading analysis. The mirroring bot will:
	•	Analyze market trends and trading signals.
	•	Automate decision-making using AI pattern recognition.
	•	Integrate with financial data for market predictions.
	•	Operate as a standalone or assistant-driven system.

This feature is currently in development and will be available in future updates.

Troubleshooting

Audio Issues
	•	Verify that your microphone is working.
	•	Manually install PyAudio (see installation steps).

Web Search Not Working?
	•	Ensure you have an active internet connection.
	•	Reinstall dependencies:

pip install duckduckgo-search requests trafilatura beautifulsoup4



TTS Not Working?
	•	Ensure TTS mode is enabled (/tts).
	•	Modify the voice settings in speak_text() inside main.py.

Upcoming Features
	•	AI-driven automated trading and market mirroring.
	•	Improved Wikipedia integration with better filtering and parsing.
	•	More advanced voice control for enabling/disabling settings.
	•	Additional voices for TTS and Tarot readings.
	•	AI-powered research assistant mode for structured topic analysis.

About This Project

Developed by Flyser3
Last Updated: 02/26/2025

This chatbot is designed for automation, research, and AI-enhanced conversations. It continues to evolve with new features and improvements based on real-world usage.
