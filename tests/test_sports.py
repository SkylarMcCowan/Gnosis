"""Schedules must keep sports separate, preserve dates, and never score unplayed games."""
from datetime import datetime, timezone
import requests
import pytest

from core import sports, subscriptions
import webagent


def event(key='next', state='pre', date='2030-01-02T18:00Z', team_id='360', opponent='Arsenal', score='0'):
    return {'id': key, 'date': date, 'competitions': [{'status': {'type': {'state': state, 'description': 'Scheduled' if state == 'pre' else 'Final'}},
        'competitors': [{'homeAway': 'home', 'team': {'id': team_id, 'displayName': 'Manchester United'}, 'score': score},
                        {'homeAway': 'away', 'team': {'id': '42', 'displayName': opponent}, 'score': {'displayValue': '1'}}]}]}


def test_unplayed_games_do_not_get_a_zero_zero_score():
    match = sports.parse_event(event(), '360', 'Premier League')
    assert match['home_score'] is None
    assert match['away_score'] is None
    match = sports.parse_event(event(state='post', score={'displayValue': '3'}), '360', 'Premier League')
    assert (match['home_score'], match['away_score']) == ('3', '1')
    assert sports.parse_event(event(team_id='123'), '360', 'Premier League') is None


def test_schedule_merges_future_query_and_cup_fixtures_and_deduplicates(monkeypatch):
    calls = []
    def get(path, params=None):
        calls.append((path, params))
        if not path.endswith('/schedule'):
            return {}
        if '/eng.1/' in path:
            if params:
                return {'events': [event(), event('later', date='2030-01-04T18:00Z')]}
            return {'events': [event('last', 'post', '2029-12-31T18:00Z', score='2')]}
        if '/eng.fa/' in path:
            return {'events': [event('cup', date='2030-01-03T18:00Z'), event()]}
        return {'events': []}
    monkeypatch.setattr(sports, '_get', get)
    schedule = sports.fetch_schedule({'team_id': '360', 'league_slug': 'eng.1'}, datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert [e['id'] for e in schedule['upcoming']] == ['next', 'cup', 'later']
    assert schedule['last_result']['id'] == 'last'
    assert any(params == {'fixture': 'true'} for path, params in calls)
    assert any(e['league'] == 'FA Cup' for e in schedule['upcoming'])


def test_missing_future_schedule_uses_next_event_and_preserves_tbd(monkeypatch):
    upcoming = event()
    upcoming['competitions'][0]['timeValid'] = False
    monkeypatch.setattr(sports, '_get', lambda path, params=None: {'events': []} if path.endswith('/schedule') else {'team': {'nextEvent': [upcoming]}})
    schedule = sports.fetch_schedule({'sport': 'basketball', 'league_slug': 'nba', 'team_id': '360'}, datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert schedule['upcoming'][0]['time_tbd']


def test_postponed_and_stale_unplayed_games_are_not_upcoming(monkeypatch):
    postponed = event('postponed')
    postponed['competitions'][0]['status']['type']['description'] = 'Postponed'
    monkeypatch.setattr(sports, '_get', lambda *args: {'events': [postponed, event('stale', date='2020-01-01T18:00Z')]})
    schedule = sports.fetch_schedule({'sport': 'football', 'league_slug': 'nfl', 'team_id': '360'})
    assert schedule['upcoming'] == []


def test_failed_schedule_is_not_presented_as_no_fixtures(monkeypatch):
    def broken(*args):
        raise requests.ConnectionError('offline')
    monkeypatch.setattr(sports, '_get', broken)
    assert sports.fetch_schedule({'sport': 'hockey', 'league_slug': 'nhl', 'team_id': '5'}) is None


def test_team_directory_is_cached_and_saved_with_sport(monkeypatch):
    calls = []
    monkeypatch.setattr(sports, '_team_cache', {})
    def directory(*args):
        calls.append(args)
        return {'sports': [{'leagues': [{'teams': [{'team': {'id': '13', 'displayName': 'Los Angeles Lakers'}}]}]}]}
    monkeypatch.setattr(sports, '_get', directory)
    first = sports.list_teams('nba')
    first[0]['name'] = 'Modified by caller'
    record = webagent.add_sports_team_subscription('nba', '13')
    assert len(calls) == 1
    assert record['name'] == 'Los Angeles Lakers'
    assert record['metadata']['sport'] == 'basketball'
    assert record['metadata']['league_slug'] == 'nba'
    with pytest.raises(ValueError, match='Choose a team'):
        webagent.add_sports_team_subscription('nba', '999')


def test_manu_aliases_match_saved_team(monkeypatch):
    metadata = sports.team_metadata('premier_league', {'id': '360', 'name': 'Manchester United'})
    record = subscriptions.add_subscription('team', 'Manchester United', metadata)
    assert webagent._matching_subscription('When do manu play next?')['id'] == record['id']


def test_schedule_evidence_keeps_full_fixture_list_and_tbd(monkeypatch):
    match = sports.parse_event(event(), '360', 'Premier League')
    match['time_tbd'] = True
    monkeypatch.setattr(sports, 'fetch_schedule', lambda metadata: {'upcoming': [match], 'last_result': None, 'live': [], 'league': 'Premier League'})
    evidence = sports.schedule_evidence({'name': 'Manchester United', 'metadata': {'team_id': '360', 'league_slug': 'eng.1'}}, lambda date: '2030-01-02 18:00 UTC')[0]
    assert 'Time TBD' in evidence['content']
    assert '18:00 UTC' not in evidence['content']
    assert evidence['sports_schedule']['lines']
