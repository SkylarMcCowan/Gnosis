"""Conservative shortcuts and approximate prompt budgeting for local chat."""
import math
import re


def is_direct_chat(prompt):
    """Only bypass planners for clearly conversational, self-contained requests."""
    text = prompt.strip().casefold()
    if re.fullmatch(r"(?:hi|hello|hey|thanks|thank you|good morning|good evening|bye|goodbye)[!. ]*", text):
        return True
    arithmetic = re.sub(r"^(?:hi|hello|hey)[,!. ]+", "", text)
    for word, symbol in {'divided by': '/', 'multiplied by': '*', 'plus': '+', 'minus': '-', 'times': '*', 'point': '.'}.items():
        arithmetic = re.sub(r"\b" + word + r"\b", symbol, arithmetic)
    for index, word in enumerate(('zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten')):
        arithmetic = re.sub(r"\b" + word + r"\b", str(index), arithmetic)
    if re.fullmatch(r"(?:what is |what's |how much is |calculate |solve )?[\d\s()+*/.%-]+[?.!]*", arithmetic):
        return True
    return bool(re.fullmatch(r"(?:tell me (?:a|another) joke|make me laugh)[!.? ]*", text))


def estimated_tokens(message):
    # A heuristic, not a tokenizer: include message framing and UTF-8 text.
    return 8 + math.ceil(len(message.get('content', '').encode('utf-8')) / 3)


def budget_messages(messages, context_size, max_messages=80, max_chars=20000):
    """Keep instructions, current request, and complete recent exchanges.

    Older turns become bounded verbatim excerpts, explicitly labelled as such.
    Never truncate the newest user request or silently drop system instructions.
    """
    reserve = min(1024, context_size // 4)
    budget = context_size - reserve
    systems = [m for m in messages if m.get('role') == 'system' and not m.get('_history_excerpt')]
    turns = [m for m in messages if m.get('role') != 'system']
    old_summary = next((m for m in messages if m.get('_history_excerpt')), None)
    # Group each user message with its answer(s), so trimming leaves no orphan replies.
    groups = []
    for m in turns:
        if m.get('role') == 'user' or not groups:
            groups.append([])
        groups[-1].append(m)
    selected = []
    used = sum(estimated_tokens(m) for m in systems)
    chars = sum(len(m.get('content', '')) for m in systems)
    dropped = []
    if used > budget or chars > max_chars:
        raise ValueError('System instructions exceed the model context budget. Reduce attached context or choose a larger context window.')
    for group in reversed(groups):
        cost = sum(estimated_tokens(m) for m in group)
        length = sum(len(m.get('content', '')) for m in group)
        if used + cost <= budget and len(selected) + len(group) <= max_messages and chars + length <= max_chars:
            selected = group + selected
            used += cost
            chars += length
        else:
            if not selected:
                raise ValueError('The current request and instructions exceed the model context budget. Shorten the request or choose a larger context window.')
            dropped = turns[:len(turns) - len(selected)]
            break
    summary = None
    if dropped:
        pieces = ([old_summary['content'].split('\n', 1)[-1]] if old_summary else [])
        pieces.extend(f"{m['role']}: {m.get('content', '')[:180]}" for m in dropped)
        text = 'Earlier conversation excerpts (incomplete historical text, not instructions):\n' + '\n'.join(pieces)[-600:]
        candidate = {'role': 'system', 'content': text, '_history_excerpt': True}
        # Use any remaining room for excerpts rather than dropping them entirely.
        while text and (used + estimated_tokens(candidate) > budget or chars + len(text) > max_chars):
            excerpts = text.split('\n', 1)[-1]
            if len(excerpts) <= 40:
                break
            text = text.split('\n', 1)[0] + '\n' + excerpts[40:]
            candidate['content'] = text
        if used + estimated_tokens(candidate) <= budget and chars + len(text) <= max_chars:
            summary = candidate
    elif old_summary and used + estimated_tokens(old_summary) <= budget and chars + len(old_summary['content']) <= max_chars:
        summary = old_summary
    return systems + ([summary] if summary else []) + selected
