import os
import requests
import tempfile
import shutil
import logging

from PIL import Image

logger = logging.getLogger(__name__)


def _get_extension_from_content(chunk):
    logger.debug('checking format of {chunk}'.format(chunk=repr(chunk)))
    if chunk.startswith('\xff\xd8'):
        return '.jpg'
    if chunk.startswith('\x89PNG\r\n'):
        return '.png'
    if 'RIFF' in chunk and 'WEBP' in chunk:
        return '.webp'

    raise ValueError('cannot determine file format')


def fetch_cover(uri, directory):
    response = requests.get(uri, stream=True)
    response.raise_for_status()
    if response.status_code == 200:
        fd, tmp_name = tempfile.mkstemp()
        file_extension = None
        with open(tmp_name, 'wb') as f:
            for chunk in response.iter_content(1024):
                if file_extension is None:
                    file_extension = _get_extension_from_content(chunk)
                f.write(chunk)
        if file_extension == '.webp':
            img = Image.open(tmp_name).convert('RGB')
            img.save(tmp_name, 'png')
            file_extension = '.png'
        shutil.copy(tmp_name, os.path.join(directory, 'cover' + file_extension))
        os.close(fd)
        os.remove(tmp_name)