import random
import time
from colorama import Fore, Style
# Add necessary imports
import asyncio
from webagent import ollama, assistant_convo, speak_text, unfiltered_mode, reasoning_mode, MODELS, voice_mode, tts_mode

MAJOR_ARCANA = [
    "0. The Fool", "I. The Magician", "II. The High Priestess", "III. The Empress",
    "IV. The Emperor", "V. The Hierophant", "VI. The Lovers", "VII. The Chariot",
    "VIII. Strength", "IX. The Hermit", "X. Wheel of Fortune", "XI. Justice",
    "XII. The Hanged Man", "XIII. Death", "XIV. Temperance", "XV. The Devil",
    "XVI. The Tower", "XVII. The Star", "XVIII. The Moon", "XIX. The Sun",
    "XX. Judgement", "XXI. The World"
]

MINOR_ARCANA = [
    "Ace of Wands", "Two of Wands", "Three of Wands", "Four of Wands", "Five of Wands",
    "Six of Wands", "Seven of Wands", "Eight of Wands", "Nine of Wands", "Ten of Wands",
    "Page of Wands", "Knight of Wands", "Queen of Wands", "King of Wands",
    "Ace of Cups", "Two of Cups", "Three of Cups", "Four of Cups", "Five of Cups",
    "Six of Cups", "Seven of Cups", "Eight of Cups", "Nine of Cups", "Ten of Cups",
    "Page of Cups", "Knight of Cups", "Queen of Cups", "King of Cups",
    "Ace of Swords", "Two of Swords", "Three of Swords", "Four of Swords", "Five of Swords",
    "Six of Swords", "Seven of Swords", "Eight of Swords", "Nine of Swords", "Ten of Swords",
    "Page of Swords", "Knight of Swords", "Queen of Swords", "King of Swords",
    "Ace of Pentacles", "Two of Pentacles", "Three of Pentacles", "Four of Pentacles", "Five of Pentacles",
    "Six of Pentacles", "Seven of Pentacles", "Eight of Pentacles", "Nine of Pentacles", "Ten of Pentacles",
    "Page of Pentacles", "Knight of Pentacles", "Queen of Pentacles", "King of Pentacles"
]

SEPHIROTH = [
    "1. Kether (Crown) - Divine Consciousness",
    "2. Chokmah (Wisdom) - Creative Spark",
    "3. Binah (Understanding) - Form & Limitation",
    "4. Chesed (Mercy) - Expansion & Generosity",
    "5. Geburah (Strength) - Power & Discipline",
    "6. Tiphareth (Beauty) - Harmony & Balance",
    "7. Netzach (Victory) - Emotion & Desire",
    "8. Hod (Glory) - Intellect & Analysis",
    "9. Yesod (Foundation) - Subconscious & Dreams",
    "10. Malkuth (Kingdom) - Manifestation & Reality"
]

DRAW_MESSAGES = [
    "The spirits whisper secrets of fate...",
    "A cosmic giggle echoes through the ether...",
    "Destiny has shuffled the deck just for you...",
    "Reality quivers as the card reveals itself...",
    "A hush falls as the veil of mystery parts...",
    "The spirits seem amused by this selection...",
    "The card glows with hidden possibilities...",
    "The cosmic forces lean in, eager to reveal...",
    "A soft chime rings in the astral plane...",
    "The energies converge, guiding this revelation...",
]

def random_draw_msg():
    return random.choice(DRAW_MESSAGES)

def tarot_reading():
    print(f"{Fore.MAGENTA}The mystic energies align... What question do you seek guidance on?")
    question = input(f"{Fore.YELLOW}Your question: ")
    print(f"{Fore.CYAN}\nDrawing from a single 78-card deck. Minor Arcana fill the 10 Sephiroth; Majors become path cards...\n")

    deck = MAJOR_ARCANA + MINOR_ARCANA
    used = set()
    seph_cards = [None] * 10  # Slots for Sephiroth (Minor Arcana)
    path_cards = []
    minors_filled = 0

    while minors_filled < 10:
        card = random.choice(deck)
        if card in used:
            continue
        used.add(card)

        print(f"{Fore.YELLOW}**Drew card**: {Fore.WHITE}{card}")
        print(f"{Fore.CYAN}{random_draw_msg()}\n")
        time.sleep(1.0)

        if card in MAJOR_ARCANA:
            path_cards.append(card)
        else:
            seph_cards[minors_filled] = card
            minors_filled += 1

    # Format final reading
    reading_text = f"**Question**: {question}\n\n**Sephiroth (Minors):**\n"
    for idx, s in enumerate(SEPHIROTH):
        reading_text += f"{s}: {seph_cards[idx]}\n"

    reading_text += "\n**Paths (Majors) in the order drawn:**\n"
    if path_cards:
        for i, c in enumerate(path_cards, start=1):
            reading_text += f"Path #{i}: {c}\n"
    else:
        reading_text += "None drawn.\n"

    print(f"{Fore.BLUE}\n--- Final Tree of Life Layout ---\n{reading_text}\n")

    decision = input(f"{Fore.MAGENTA}Would you like me to interpret these cards? (yes/no) ➜ ").strip().lower()
    if decision not in ["y", "yes"]:
        print(f"{Fore.YELLOW}Alright, the reading stands on its own. Farewell!")
        return

    # Interpretation via AI model
    if unfiltered_mode:
        chosen_model = MODELS["unfiltered"]
    elif reasoning_mode:
        chosen_model = MODELS["search"]
    else:
        chosen_model = MODELS["main"]

    interpret_prompt = (
        f"You are a Tarot sage. The question is: {question}\n\n"
        f"Here is the final Tree of Life reading, with 10 minor arcana assigned to the Sephiroth in the order they appeared, "
        f"and any major arcana placed as path cards:\n\n{reading_text}\n"
        f"Please provide a cohesive, mystical interpretation of how these cards might answer the question."
    )

    assistant_convo.append({"role": "user", "content": interpret_prompt})

    print(f"{Fore.CYAN}Generating interpretation from the model {chosen_model}...\n")
    response_stream = ollama.chat(model=chosen_model, messages=assistant_convo, stream=True)

    final_text = ""
    for chunk in response_stream:
        text_chunk = chunk["message"]["content"]
        final_text += text_chunk
        print(f"{Fore.GREEN}{text_chunk}", end="", flush=True)

    print()
    assistant_convo.append({"role": "assistant", "content": final_text})
    print(f"\n{Fore.MAGENTA}--- End of Interpretation ---\n")

    if voice_mode or tts_mode:
        asyncio.run(speak_text(final_text))