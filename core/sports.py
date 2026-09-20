"""ESPN team directories and schedules for saved sports subscriptions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import time

import requests

LEAGUES = {
    'premier_league': ('Soccer · Premier League', 'soccer', 'eng.1'),
    'la_liga': ('Soccer · La Liga', 'soccer', 'esp.1'),
    'bundesliga': ('Soccer · Bundesliga', 'soccer', 'ger.1'),
    'serie_a': ('Soccer · Serie A', 'soccer', 'ita.1'),
    'ligue_1': ('Soccer · Ligue 1', 'soccer', 'fra.1'),
    'mls': ('Soccer · MLS', 'soccer', 'usa.1'),
    'nba': ('Basketball · NBA', 'basketball', 'nba'),
    'wnba': ('Basketball · WNBA', 'basketball', 'wnba'),
    'nfl': ('Football · NFL', 'football', 'nfl'),
    'mlb': ('Baseball · MLB', 'baseball', 'mlb'),
    'nhl': ('Hockey · NHL', 'hockey', 'nhl'),
}
BASE_URL = 'https://site.api.espn.com/apis/site/v2/sports'
LEAGUE_NAMES = {value[2]: value[0].split(' · ', 1)[1] for value in LEAGUES.values()}
LEAGUE_NAMES.update({'eng.fa': 'FA Cup', 'eng.league_cup': 'League Cup',
                     'uefa.champions': 'Champions League', 'uefa.europa': 'Europa League'})
_team_cache = {}


def _get(path, params=None):
    response = requests.get(f'{BASE_URL}/{path}', params=params, timeout=8)
    response.raise_for_status()
    return response.json()


def list_teams(league_key):
    label, sport, league = LEAGUES[league_key]
    cached = _team_cache.get(league_key)
    if cached and time.monotonic() - cached[0] < 900:
        return [dict(team) for team in cached[1]]
    data = _get(f'{sport}/{league}/teams', {'limit': 1000})
    teams = {}
    for sports in data.get('sports', []):
        for competition in sports.get('leagues', []):
            for entry in competition.get('teams', []):
                team = entry.get('team', {})
                if team.get('id') and team.get('displayName'):
                    teams[str(team['id'])] = {'id': str(team['id']), 'name': team['displayName'],
                                               'abbreviation': team.get('abbreviation', '')}
    result = sorted(teams.values(), key=lambda team: team['name'].casefold())
    if not result:
        raise ValueError(f'No teams are available for {label} right now.')
    _team_cache[league_key] = (time.monotonic(), result)
    return [dict(team) for team in result]


def team_metadata(league_key, team):
    label, sport, league = LEAGUES[league_key]
    keywords = []
    if team['name'].casefold() == 'manchester united':
        keywords = ['Man United', 'Man Utd', 'ManU', 'MUFC']
    return {'sport': sport, 'league_slug': league, 'league_name': label.split(' · ', 1)[1],
            'team_id': str(team['id']), 'keywords': keywords}


def _parse_date(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (AttributeError, ValueError, TypeError):
        return None


def parse_event(event, team_id, league):
    try:
        competition = event['competitions'][0]
        status = (competition.get('status') or event.get('status') or {}).get('type', {})
        competitors = competition['competitors']
        home = next(c for c in competitors if c.get('homeAway') == 'home')
        away = next(c for c in competitors if c.get('homeAway') == 'away')
        if str(team_id) not in {str(home['team']['id']), str(away['team']['id'])}:
            return None
        state = status.get('state')
        date = event.get('date') or competition.get('date')
        if state not in {'pre', 'in', 'post'} or not _parse_date(date):
            return None
        def score(competitor):
            if state == 'pre':
                return None
            value = competitor.get('score')
            return value.get('displayValue') if isinstance(value, dict) else value
        return {'id': str(event.get('id') or f"{date}|{home['team']['id']}|{away['team']['id']}"),
                'date': date, 'state': state, 'status': status.get('description', ''),
                'league': event.get('league', {}).get('name') or league,
                'home': home['team']['displayName'], 'away': away['team']['displayName'],
                'home_score': score(home), 'away_score': score(away),
                'time_tbd': competition.get('timeValid') is False or competition.get('dateValid') is False}
    except (KeyError, IndexError, TypeError, StopIteration):
        return None


def fetch_schedule(metadata, now=None):
    sport = metadata.get('sport', 'soccer')
    league, team_id = metadata.get('league_slug'), str(metadata.get('team_id', ''))
    allowed = {(entry[1], entry[2]) for entry in LEAGUES.values()}
    if (sport, league) not in allowed or not team_id.isdigit():
        return None
    leagues = [league]
    if sport == 'soccer':
        leagues += ['uefa.champions', 'uefa.europa']
        if league == 'eng.1':
            leagues += ['eng.fa', 'eng.league_cup']
    jobs = [(slug, None) for slug in leagues]
    if sport == 'soccer':
        jobs += [(slug, {'fixture': 'true'}) for slug in leagues]
    def fetch(job):
        slug, params = job
        try:
            return slug, _get(f'{sport}/{slug}/teams/{team_id}/schedule', params)
        except (requests.RequestException, ValueError):
            return slug, None
    events, success = {}, False
    with ThreadPoolExecutor(max_workers=4) as pool:
        for slug, data in pool.map(fetch, jobs):
            if data is None:
                continue
            success = True
            for event in data.get('events', []):
                match = parse_event(event, team_id, LEAGUE_NAMES.get(slug, slug))
                if match:
                    events[match['id']] = match
    now = now or datetime.now(timezone.utc)
    upcoming = [e for e in events.values() if e['state'] == 'pre' and _parse_date(e['date']) >= now
                and not any(word in e['status'].casefold() for word in ('postponed', 'cancel'))]
    if not upcoming:
        # A team's summary sometimes carries a next event absent from schedules.
        try:
            data = _get(f'{sport}/{league}/teams/{team_id}')
            success = True
            for event in data.get('team', {}).get('nextEvent') or []:
                match = parse_event(event, team_id, LEAGUE_NAMES.get(league, league))
                if match and match['state'] == 'pre' and _parse_date(match['date']) >= now and not any(
                    word in match['status'].casefold() for word in ('postponed', 'cancel')
                ):
                    upcoming.append(match)
        except (requests.RequestException, ValueError):
            pass
    if not success:
        return None
    sort_key = lambda e: _parse_date(e['date'])
    completed = sorted((e for e in events.values() if e['state'] == 'post' and not any(
        word in e['status'].casefold() for word in ('cancel', 'postponed')
    )), key=sort_key)
    return {'upcoming': sorted(upcoming, key=sort_key)[:5],
            'last_result': completed[-1] if completed else None,
            'live': sorted((e for e in events.values() if e['state'] == 'in'), key=sort_key),
            'league': metadata.get('league_name', LEAGUE_NAMES.get(league, league))}


def schedule_evidence(subscription, format_date):
    metadata = subscription.get('metadata', {})
    schedule = fetch_schedule(metadata)
    if schedule is None:
        return []
    sport = metadata.get('sport', 'soccer')
    league, team_id = metadata['league_slug'], metadata['team_id']
    lines = [f"{subscription['name']} — {schedule['league']}."]
    def describe(event):
        when = format_date(event['date'])
        if event['time_tbd']:
            when = f"{when.split(' ')[0]} · Time TBD"
        matchup = f"{event['away']} at {event['home']}"
        if event['home_score'] is not None and event['away_score'] is not None:
            matchup = f"{event['home']} {event['home_score']}–{event['away_score']} {event['away']}"
        return f"{matchup} · {when} · {event['league']} · {event['status']}"
    if schedule['last_result']:
        lines.append('Last result: ' + describe(schedule['last_result']))
    for event in schedule['live']:
        lines.append('Live now: ' + describe(event))
    if schedule['upcoming']:
        lines.append('Upcoming fixtures:')
        lines.extend(describe(event) for event in schedule['upcoming'])
    else:
        lines.append('Next match: no upcoming fixture available from this source.')
    content = '\n'.join(lines)
    if not schedule['upcoming']:
        content += '\nNext match: UNKNOWN. Do not invent a date or opponent.'
    web_sport = 'soccer' if sport == 'soccer' else league
    return [{'id': hashlib.sha256(f"sports|{sport}|{league}|{team_id}".encode()).hexdigest()[:16],
             'title': f"{subscription['name']} schedule", 'content': content,
             'url': f'https://www.espn.com/{web_sport}/team/_/id/{team_id}',
             'captured_at': datetime.now(timezone.utc).isoformat(), 'search_provider': 'espn',
             'truthfulness_confidence': 90, 'recency_confidence': 100,
             'sports_schedule': {'league': schedule['league'], 'lines': lines[1:]},
             'corroborating_domains': []}]
