import io
import zipfile

import pytest

from voice import download_model as installer


def test_existing_model_needs_no_network(tmp_path, monkeypatch):
    model = tmp_path / installer.MODEL
    (model / 'am').mkdir(parents=True)
    (model / 'am' / 'final.mdl').touch()
    monkeypatch.setattr(installer.urllib.request, 'urlopen', lambda *args, **kwargs: pytest.fail('Unexpected download'))
    assert installer.download_model(tmp_path) == model


@pytest.mark.parametrize('member', [f'{installer.MODEL}/../../outside.txt', '/outside.txt'])
def test_download_rejects_paths_outside_model(tmp_path, monkeypatch, member):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(member, 'unexpected')
    monkeypatch.setattr(installer.urllib.request, 'urlopen', lambda *args, **kwargs: io.BytesIO(buffer.getvalue()))
    with pytest.raises(ValueError, match='Unexpected path'):
        installer.download_model(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_download_installs_valid_model(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(f'{installer.MODEL}/am/final.mdl', 'model data')
    monkeypatch.setattr(installer.urllib.request, 'urlopen', lambda *args, **kwargs: io.BytesIO(buffer.getvalue()))
    model = installer.download_model(tmp_path)
    assert (model / 'am' / 'final.mdl').read_text() == 'model data'
    assert list(tmp_path.iterdir()) == [model]
