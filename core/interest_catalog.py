"""Interest categories shared by subscriptions and the welcome dashboard."""
CATEGORIES = {
    'sports': 'Sports', 'news': 'News', 'entertainment': 'Entertainment',
    'weather': 'Weather', 'technology': 'Technology', 'science': 'Science & nature',
    'business': 'Business & finance', 'health': 'Health & wellbeing',
    'travel': 'Travel & food', 'spirituality': 'Spirituality', 'other': 'Other interests',
}

CATALOG = {
    'News': [
        {'name': 'BBC News', 'type': 'website', 'url': 'https://www.bbc.com/news'},
        {'name': 'Reuters', 'type': 'website', 'url': 'https://www.reuters.com'},
        {'name': 'Associated Press', 'type': 'website', 'url': 'https://apnews.com'},
        {'name': 'NPR', 'type': 'website', 'url': 'https://www.npr.org'},
        {'name': 'World news', 'type': 'topic'}, {'name': 'Politics', 'type': 'topic'},
    ],
    'Sports': [{'name': name, 'type': 'team'} for name in
               ('Manchester United', 'Arsenal', 'Real Madrid', 'Barcelona', 'Bayern Munich')] +
              [{'name': 'Formula 1', 'type': 'topic', 'keywords': ['F1']},
               {'name': 'Tennis', 'type': 'topic'}],
    'Entertainment': [
        {'name': 'IMDb', 'type': 'website', 'url': 'https://www.imdb.com'},
        {'name': 'Rotten Tomatoes', 'type': 'website', 'url': 'https://www.rottentomatoes.com'},
        {'name': 'Variety', 'type': 'website', 'url': 'https://variety.com'},
        *[{'name': name, 'type': 'topic'} for name in ('Movies', 'Television', 'Music', 'Gaming', 'Books')],
    ],
    'Technology': [{'name': 'Hacker News', 'type': 'website', 'url': 'https://news.ycombinator.com'},
                   *[{'name': name, 'type': 'topic'} for name in ('Artificial intelligence', 'Cybersecurity', 'Open source')]],
    'Science & nature': [{'name': name, 'type': 'topic'} for name in ('Space exploration', 'Climate science', 'Wildlife')],
    'Business & finance': [{'name': name, 'type': 'topic'} for name in ('Economy', 'Personal finance', 'Small business')],
    'Health & wellbeing': [{'name': name, 'type': 'topic'} for name in ('Fitness', 'Nutrition', 'Mental wellbeing')],
    'Travel & food': [{'name': name, 'type': 'topic'} for name in ('Travel', 'Cooking', 'Gardening')],
    'Spirituality': [
        {'name': 'Tricycle (Buddhist Review)', 'type': 'website', 'url': 'https://tricycle.org'},
        {'name': 'On Being', 'type': 'website', 'url': 'https://onbeing.org'},
        {'name': 'Center for Action and Contemplation', 'type': 'website', 'url': 'https://cac.org'},
    ],
    'Other interests': [{'name': 'Wikipedia Current Events', 'type': 'website', 'url': 'https://en.wikipedia.org/wiki/Portal:Current_events'}],
}
for label, items in CATALOG.items():
    key = next(key for key, value in CATEGORIES.items() if value == label)
    for item in items:
        item['category'] = key


def category_for(record):
    """Infer legacy categories without modifying saved subscription records."""
    if record.get('type') == 'team':
        return 'sports'
    if record.get('type') == 'weather':
        return 'weather'
    explicit = (record.get('metadata') or {}).get('category')
    if explicit in CATEGORIES:
        return explicit
    name = str(record.get('name', '')).casefold()
    for items in CATALOG.values():
        for item in items:
            if item['name'].casefold() == name and item['type'] == record.get('type'):
                return item['category']
    return 'other'
