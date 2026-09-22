"""Blind projections deliberately exclude labels, filenames and other investigators' notes."""

def neutral_event(event):
    return {'id': event['id'], 'observation': 'Recorded event available for independent review.'}
