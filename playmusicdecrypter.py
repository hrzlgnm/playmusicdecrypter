#!/usr/bin/env python2

# playmusicdecrypter - decrypt MP3 files from Google Play Music offline storage (All Access)
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301  USA

__version__ = "2.0"

import os, sys, struct, re, glob, argparse, time, shutil, logging
import Crypto.Cipher.AES, Crypto.Util.Counter
import mutagen
import covers
from covers import downloader as downloader
from db import lists
from playlist import creator
import sqlite3

import superadb

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)-15s %(levelname)-9s {%(name)s} [%(module)s.%(funcName)s] %(message)s')

logger = logging.getLogger('main')


def normalize_filename(filename):
    """Remove invalid characters from filename"""
    result = unicode(re.sub(r'[<>:"/\\|?*]', " ", filename)).strip()
    while result.endswith('.'):
        result = result[:-1]
    return result


class PlayMusicDecrypter(object):
    """Decrypt MP3 file from Google Play Music offline storage (All Access)"""

    def __init__(self, db_conn, infile):
        # Open source file
        self.infile = infile
        self.source = open(infile, "rb")

        # Test if source file is encrypted
        start_bytes = self.source.read(4)
        self.is_encrypted = start_bytes == "\x12\xd3\x15\x27"

        # Get file info
        self.db = db_conn
        self.info = self.get_info()

    def decrypt(self):
        """Decrypt one block"""
        data = self.source.read(1024)
        if not data:
            return ""

        iv = data[:16]
        encrypted = data[16:]

        counter = Crypto.Util.Counter.new(64, prefix=iv[:8], initial_value=struct.unpack(">Q", iv[8:])[0])
        cipher = Crypto.Cipher.AES.new(self.info["CpData"], Crypto.Cipher.AES.MODE_CTR, counter=counter)

        return cipher.decrypt(encrypted)

    def get_decrypted_content(self, outfile=""):
        """Decrypt all blocks and write them to outfile (or to stdout if outfile in not specified)"""
        if self.is_encrypted:
            destination = open(outfile, "wb") if outfile else sys.stdout
            while True:
                decrypted = self.decrypt()
                if not decrypted:
                    break

                destination.write(decrypted)
                destination.flush()
        else:
            shutil.copy(self.infile, outfile)

    def get_info(self):
        """Returns informations about song from database"""
        cursor = self.db.cursor()

        cursor.execute("""SELECT Id, Title, Album, Artist, AlbumArtist, Composer, Genre, Year, Duration,
                                 TrackCount, TrackNumber, DiscCount, DiscNumber, Compilation, CpData, AlbumArtLocation
                          FROM music
                          WHERE LocalCopyPath = ?""", (os.path.basename(self.infile),))
        row = cursor.fetchone()
        if row:
            return dict(row)
        else:
            raise ValueError("Empty file info!")

    def get_outfile(self):
        """Returns output filename based on song informations"""
        destination_dir = os.path.join(normalize_filename(self.info["AlbumArtist"]).lower(),
                                       normalize_filename(self.info["Album"]).lower())
        filename = u"{TrackNumber:02d} - {Title}.mp3".format(**self.info)
        filename = filename.lower()
        return os.path.join(destination_dir, normalize_filename(filename))

    def update_id3(self, outfile):
        """Update ID3 tags in outfile"""
        audio = mutagen.File(outfile, easy=True)
        audio.add_tags()
        audio["title"] = self.info["Title"]
        audio["album"] = self.info["Album"]
        audio["artist"] = self.info["Artist"]
        audio["performer"] = self.info["AlbumArtist"]
        audio["composer"] = self.info["Composer"]
        audio["genre"] = self.info["Genre"]
        audio["date"] = str(self.info["Year"])
        audio["tracknumber"] = str(self.info["TrackNumber"])
        audio["discnumber"] = str(self.info["DiscNumber"])
        audio["compilation"] = str(self.info["Compilation"])
        audio.save()


def is_empty_file(filename):
    """Returns True if file doesn't exist or is empty"""
    return False if os.path.isfile(filename) and os.path.getsize(filename) > 0 else True


def pull_database(destination_dir=".", adb="adb"):
    """Pull Google Play Music database from device"""
    logger.info("Downloading Google Play Music database from device...")
    try:
        adb = superadb.SuperAdb(executable=adb)
    except RuntimeError:
        logger.info("Device is not connected! Exiting...")
        sys.exit(1)

    if not os.path.isdir(destination_dir):
        os.makedirs(destination_dir)

    db_file = os.path.join(destination_dir, "music.db")
    adb.pull("/data/data/com.google.android.music/databases/music.db", db_file)
    if is_empty_file(db_file):
        logger.info("Download failed! Exiting...")
        sys.exit(1)


def pull_library(source_dir="/data/data/com.google.android.music/files/music", destination_dir="encrypted", adb="adb"):
    """Pull Google Play Music library from device"""
    logger.info("Downloading encrypted MP3 files from device...")
    try:
        adb = superadb.SuperAdb(executable=adb)
    except RuntimeError:
        logger.error('Device is not connected! Exiting...')
        sys.exit(1)

    if not os.path.isdir(destination_dir):
        os.makedirs(destination_dir)

    files = [f for f in adb.ls(source_dir) if f.endswith(".mp3")]
    if files:
        start_time = time.time()
        for i, f in enumerate(files):
            source_file = os.path.join(source_dir, f)
            dest_file = os.path.join(destination_dir, f)
            if not os.path.isfile(dest_file):
                logger.debug('Downloading file {}/{}...'.format(i + 1, len(files)))
                adb.pull(source_file, dest_file)
            else:
                logger.debug(u'File {} already exists, skipping'.format(dest_file))

        logger.debug('All downloads finished ({:.1f}s)!'.format(time.time() - start_time))
    else:
        logger.error("No files found! Exiting...")
        sys.exit(1)


def decrypt_files(source_dir="encrypted", destination_dir=".", database="music.db", skip_existing_decrypted=False,
                  keep_encrypted_files=False, write_play_lists=False):
    """Decrypt all MP3 files in source directory and write them to destination directory
    :param write_play_lists:
    """
    logger.info("Decrypting MP3 files...")
    if not os.path.isdir(destination_dir):
        os.makedirs(destination_dir)

    files = glob.glob(os.path.join(source_dir, "*.mp3"))

    def remove_if_enabled(f_):
        if not keep_encrypted_files:
            logger.debug(u'removing {}'.format(f_))
            os.remove(f_)
        else:
            logger.debug(u'keeping {}'.format(f_))

    con = sqlite3.connect(database, detect_types=sqlite3.PARSE_DECLTYPES)
    con.row_factory = sqlite3.Row
    playlists = creator.PlayListCreator(destination_dir)

    if files:
        start_time = time.time()
        for f in files:
            try:
                decrypter = PlayMusicDecrypter(con, f)
                action = 'Decrypting' if decrypter.is_encrypted else 'Copying'
                logger.info(u"{} file {} -> {}".format(action, f, decrypter.get_outfile()))
            except ValueError as e:
                logger.warn(u"Skipping file {} ({})".format(f, e))
                continue

            outfile = os.path.join(destination_dir, decrypter.get_outfile())
            outfile_path = os.path.dirname(outfile)
            info = decrypter.get_info()
            playlists.add(lists.get(con, info['Id']),
                          {'len': info['Duration'] / 1000,
                           'name': u'{AlbumArtist} - {Title}'.format(**info),
                           'file_path': decrypter.get_outfile()})

            if not os.path.isdir(outfile_path):
                os.makedirs(outfile_path)

            remove_if_older(f, outfile)

            if not covers.has_cover(outfile_path):
                uri = info['AlbumArtLocation']
                if uri:
                    downloader.fetch_cover(uri, outfile_path)

            if os.path.isfile(outfile):
                if not skip_existing_decrypted:
                    logger.debug(u'removing previous file, skip existing is off')
                    os.remove(outfile)
                else:
                    remove_if_enabled(f)
                    logger.debug(u'skipping {}, {} already exists'.format(f, outfile))
                    continue

            decrypter.get_decrypted_content(outfile)
            decrypter.update_id3(outfile)
            remove_if_enabled(f)

        if write_play_lists:
            playlists.create_m3u()

        logger.info("Decryption finished ({:.1f}s)!".format(time.time() - start_time))
    else:
        logger.error("No files found! Exiting...")
        sys.exit(1)


def remove_if_older(infile, outfile):
    if os.path.isfile(outfile) and os.path.getctime(outfile) < os.path.getctime(infile):
        logger.debug(u'removing previous file {previous}, it is older than {new}'
                     .format(previous=outfile, new=infile))
        os.remove(outfile)


def main():
    # Parse command line options
    parser = argparse.ArgumentParser(
        description="Decrypt MP3 files from Google Play Music offline storage (All Access)",
        usage="usage: %(prog)s [-h] [options] [destination_dir]",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        version="%(prog)s {}".format(__version__))
    parser.add_argument("-a", "--adb", default="adb",
                        help="path to adb executable")
    parser.add_argument("-d", "--database",
                        help="local path to Google Play Music database file (will be downloaded from device via adb if not specified)")
    parser.add_argument("-l", "--library",
                        help="local path to directory with encrypted MP3 files (will be downloaded from device via adb if not specified")
    parser.add_argument("-r", "--remote", default="/data/data/com.google.android.music/files/music",
                        help="remote path to directory with encrypted MP3 files on device")
    parser.add_argument("-s", "--skip-existing", default=False, action='store_true',
                        help="skip existing decrypted files")
    parser.add_argument("-k", "--keep-encrypted", default=False, action='store_true',
                        help="keep encrypted files after decryption")
    parser.add_argument("-p", "--write_playlists", default=False, action='store_true',
                        help="Write Playlists as m3u into destination directory")
    parser.add_argument("destination_dir", default=".", help="destination directory for decrypted files")

    parsed_args = parser.parse_args()

    # Download Google Play Music database from device via adb
    if not parsed_args.database:
        parsed_args.database = os.path.join(parsed_args.destination_dir, "music.db")
        pull_database(parsed_args.destination_dir, adb=parsed_args.adb)

    # Download encrypted MP3 files from device via adb
    if not parsed_args.library:
        parsed_args.library = os.path.join(parsed_args.destination_dir, "encrypted")
        pull_library(parsed_args.remote, parsed_args.library, adb=parsed_args.adb)

    # Decrypt all MP3 files
    decrypt_files(parsed_args.library, parsed_args.destination_dir, parsed_args.database,
                  skip_existing_decrypted=parsed_args.skip_existing, keep_encrypted_files=parsed_args.keep_encrypted, write_play_lists=parsed_args.write_playlists)


if __name__ == "__main__":
    main()
