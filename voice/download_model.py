"""Download the default offline English speech model: python -m voice.download_model."""
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

MODEL = 'vosk-model-small-en-us-0.15'
URL = f'https://alphacephei.com/vosk/models/{MODEL}.zip'


def download_model(directory=None):
    directory = Path(directory or Path(__file__).parent / 'models').resolve()
    destination = directory / MODEL
    if (destination / 'am' / 'final.mdl').is_file():
        return destination
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        staging = Path(temporary)
        archive_path = staging / 'model.zip'
        print('Downloading the local English speech model (about 40 MB)…', flush=True)
        with urllib.request.urlopen(URL, timeout=60) as response, archive_path.open('wb') as output:
            shutil.copyfileobj(response, output)
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                target = (staging / member.filename).resolve()
                if not target.is_relative_to(staging / MODEL):
                    raise ValueError('Unexpected path in speech model archive.')
            archive.extractall(staging)
        extracted = staging / MODEL
        if not (extracted / 'am' / 'final.mdl').is_file():
            raise ValueError('The downloaded archive is missing its speech model.')
        if destination.exists():
            raise FileExistsError(f'Incomplete model already exists at {destination}; move it before retrying.')
        extracted.rename(destination)
    return destination


if __name__ == '__main__':
    print(f'Local speech model ready: {download_model()}')
