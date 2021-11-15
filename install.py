# -*- coding: utf-8 -*-
"""
    WakaTime Plugin Installer for Wing IDE
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Downloads and installs the WakaTime Plugin for Wing IDE, Personal, 101.
    :copyright: (c) 2017 Alan Hamlett.
    :license: BSD, see LICENSE for more details.
"""

import contextlib
import json
import os
import platform
import re
import ssl
import subprocess
import sys
import traceback
from subprocess import PIPE
from zipfile import ZipFile

try:
    import ConfigParser as configparser
except ImportError:
    import configparser
try:
    from urllib2 import urlopen, urlretrieve, ProxyHandler, build_opener, install_opener, HTTPError
except ImportError:
    from urllib.request import urlopen, urlretrieve, ProxyHandler, build_opener, install_opener
    from urllib.error import HTTPError


GITHUB_RELEASES_STABLE_URL = 'https://api.github.com/repos/wakatime/wakatime-cli/releases/latest'
GITHUB_DOWNLOAD_PREFIX = 'https://github.com/wakatime/wakatime-cli/releases/download'
ROOT_URL = 'https://raw.githubusercontent.com/wakatime/wing-wakatime/master/'
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
FILE = 'wakatime.py'
PLUGIN = 'wing'

is_py2 = (sys.version_info[0] == 2)
is_py3 = (sys.version_info[0] == 3)
is_win = platform.system() == 'Windows'

CONFIG_DIRS = []
if is_win:
    CONFIG_DIRS.append(os.path.join(os.getenv('APPDATA'), 'Wing IDE 6', 'scripts'))
    CONFIG_DIRS.append(os.path.join(os.getenv('APPDATA'), 'Wing IDE 6.0', 'scripts'))
    CONFIG_DIRS.append(os.path.join(os.getenv('APPDATA'), 'Wing Personal 6.0', 'scripts'))
    CONFIG_DIRS.append(os.path.join(os.getenv('APPDATA'), 'Wing Personal 6', 'scripts'))
    CONFIG_DIRS.append(os.path.join(os.getenv('APPDATA'), 'Wing 101 6', 'scripts'))
    CONFIG_DIRS.append(os.path.join(os.getenv('APPDATA'), 'Wing 101 6.0', 'scripts'))
else:
    CONFIG_DIRS.append(os.path.join(os.path.expanduser('~'), '.wingide6', 'scripts'))
    CONFIG_DIRS.append(os.path.join(os.path.expanduser('~'), '.wingpersonal6', 'scripts'))
    CONFIG_DIRS.append(os.path.join(os.path.expanduser('~'), '.wing101-6', 'scripts'))

HOME_FOLDER = None
CONFIGS = None
INTERNAL_CONFIGS = None


if is_py2:
    import codecs
    open = codecs.open
    input = raw_input  # noqa: F821

    def u(text):
        if text is None:
            return None
        if isinstance(text, unicode):  # noqa: F821
            return text
        try:
            return text.decode('utf-8')
        except:
            try:
                return text.decode(sys.getdefaultencoding())
            except:
                try:
                    return unicode(text)  # noqa: F821
                except:
                    try:
                        return text.decode('utf-8', 'replace')
                    except:
                        try:
                            return unicode(str(text))  # noqa: F821
                        except:
                            return unicode('')  # noqa: F821

elif is_py3:
    def u(text):
        if text is None:
            return None
        if isinstance(text, bytes):
            try:
                return text.decode('utf-8')
            except:
                try:
                    return text.decode(sys.getdefaultencoding())
                except:
                    pass
        try:
            return str(text)
        except:
            return text.decode('utf-8', 'replace')

else:
    raise Exception('Unsupported Python version: {0}.{1}.{2}'.format(
        sys.version_info[0],
        sys.version_info[1],
        sys.version_info[2],
    ))


def main(home=None):
    global CONFIGS, HOME_FOLDER

    if home:
        HOME_FOLDER = home

    CONFIGS = parseConfigFile(getConfigFile())

    # download wakatime-cli
    if not isCliLatest():
        downloadCLI()

    # download plugin
    contents = get_file_contents(FILE)
    if not contents:
        return

    # add plugin to config folders
    for folder in CONFIG_DIRS:
        if os.path.exists(os.path.dirname(folder)):
            if not os.path.exists(folder):
                os.mkdir(folder)
            save_file(os.path.join(folder, FILE), contents)

    print('Installed. You may now restart Wing.')
    if platform.system() == 'Windows':
        input('Press [Enter] to exit...')


class Popen(subprocess.Popen):
    """Patched Popen to prevent opening cmd window on Windows platform."""

    def __init__(self, *args, **kwargs):
        startupinfo = kwargs.get('startupinfo')
        if is_win or True:
            try:
                startupinfo = startupinfo or subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            except AttributeError:
                pass
        kwargs['startupinfo'] = startupinfo
        super(Popen, self).__init__(*args, **kwargs)


def parseConfigFile(configFile):
    """Returns a configparser.SafeConfigParser instance with configs
    read from the config file. Default location of the config file is
    at ~/.wakatime.cfg.
    """

    configs = configparser.SafeConfigParser()
    try:
        with open(configFile, 'r', encoding='utf-8') as fh:
            try:
                configs.readfp(fh)
                return configs
            except configparser.Error:
                print(traceback.format_exc())
                return None
    except IOError:
        return configs


def log(message, *args, **kwargs):
    if not CONFIGS.has_option('settings', 'debug') or CONFIGS.get('settings', 'debug') != 'true':
        return
    msg = message
    if len(args) > 0:
        msg = message.format(*args)
    elif len(kwargs) > 0:
        msg = message.format(**kwargs)
    try:
        print('[WakaTime] {msg}'.format(msg=msg))
    except UnicodeDecodeError:
        print(u('[WakaTime] {msg}').format(msg=u(msg)))


def getHomeFolder():
    global HOME_FOLDER

    if not HOME_FOLDER:
        if len(sys.argv) == 2:
            HOME_FOLDER = sys.argv[-1]
        else:
            HOME_FOLDER = os.path.realpath(os.environ.get('WAKATIME_HOME') or os.path.expanduser('~'))

    return HOME_FOLDER


def getResourcesFolder():
    return os.path.join(getHomeFolder(), '.wakatime')


def getConfigFile(internal=None):
    if internal:
        return os.path.join(getHomeFolder(), '.wakatime-internal.cfg')
    return os.path.join(getHomeFolder(), '.wakatime.cfg')


def downloadCLI():
    log('Downloading wakatime-cli...')

    if not os.path.exists(getResourcesFolder()):
        os.makedirs(getResourcesFolder())

    if isCliInstalled():
        try:
            os.remove(getCliLocation())
        except:
            log(traceback.format_exc())

    try:
        url = cliDownloadUrl()
        log('Downloading wakatime-cli from {url}'.format(url=url))
        zip_file = os.path.join(getResourcesFolder(), 'wakatime-cli.zip')
        download(url, zip_file)

        log('Extracting wakatime-cli...')
        with contextlib.closing(ZipFile(zip_file)) as zf:
            zf.extractall(getResourcesFolder())

        if not is_win:
            os.chmod(getCliLocation(), 509)  # 755

        try:
            os.remove(os.path.join(getResourcesFolder(), 'wakatime-cli.zip'))
        except:
            log(traceback.format_exc())
    except:
        log(traceback.format_exc())

    log('Finished extracting wakatime-cli.')


WAKATIME_CLI_LOCATION = None


def getCliLocation():
    global WAKATIME_CLI_LOCATION

    if not WAKATIME_CLI_LOCATION:
        binary = 'wakatime-cli-{osname}-{arch}{ext}'.format(
            osname=platform.system().lower(),
            arch=architecture(),
            ext='.exe' if is_win else '',
        )
        WAKATIME_CLI_LOCATION = os.path.join(getResourcesFolder(), binary)

    return WAKATIME_CLI_LOCATION


def architecture():
    arch = platform.machine() or platform.processor()
    if arch == 'armv7l':
        return 'arm'
    if arch == 'aarch64':
        return 'arm64'
    if 'arm' in arch:
        return 'arm64' if sys.maxsize > 2**32 else 'arm'
    return 'amd64' if sys.maxsize > 2**32 else '386'


def isCliInstalled():
    return os.path.exists(getCliLocation())


def isCliLatest():
    if not isCliInstalled():
        return False

    args = [getCliLocation(), '--version']
    try:
        stdout, stderr = Popen(args, stdout=PIPE, stderr=PIPE).communicate()
    except:
        return False
    stdout = (stdout or b'') + (stderr or b'')
    localVer = extractVersion(stdout.decode('utf-8'))
    if not localVer:
        log('Local wakatime-cli version not found.')
        return False

    log('Current wakatime-cli version is %s' % localVer)
    log('Checking for updates to wakatime-cli...')

    remoteVer = getLatestCliVersion()

    if not remoteVer:
        return True

    if remoteVer == localVer:
        log('wakatime-cli is up to date.')
        return True

    log('Found an updated wakatime-cli %s' % remoteVer)
    return False


LATEST_CLI_VERSION = None


def getLatestCliVersion():
    global LATEST_CLI_VERSION

    if LATEST_CLI_VERSION:
        return LATEST_CLI_VERSION

    configs, last_modified, last_version = None, None, None
    try:
        configs = parseConfigFile(getConfigFile(True))
        if configs:
            if configs.has_option('internal', 'cli_version'):
                last_version = configs.get('internal', 'cli_version')
            if last_version and configs.has_option('internal', 'cli_version_last_modified'):
                last_modified = configs.get('internal', 'cli_version_last_modified')
    except:
        log(traceback.format_exc())

    try:
        headers, contents, code = request(GITHUB_RELEASES_STABLE_URL, last_modified=last_modified)

        log('GitHub API Response {0}'.format(code))

        if code == 304:
            LATEST_CLI_VERSION = last_version
            return last_version

        data = json.loads(contents.decode('utf-8'))

        ver = data['tag_name']
        log('Latest wakatime-cli version from GitHub: {0}'.format(ver))

        if configs:
            last_modified = headers.get('Last-Modified')
            if not configs.has_section('internal'):
                configs.add_section('internal')
            configs.set('internal', 'cli_version', ver)
            configs.set('internal', 'cli_version_last_modified', last_modified)
            with open(getConfigFile(True), 'w', encoding='utf-8') as fh:
                configs.write(fh)

        LATEST_CLI_VERSION = ver
        return ver
    except:
        log(traceback.format_exc())
        return None


def extractVersion(text):
    pattern = re.compile(r"([0-9]+\.[0-9]+\.[0-9]+)")
    match = pattern.search(text)
    if match:
        return 'v{ver}'.format(ver=match.group(1))
    return None


def cliDownloadUrl():
    osname = platform.system().lower()
    arch = architecture()

    validCombinations = [
      'darwin-amd64',
      'darwin-arm64',
      'freebsd-386',
      'freebsd-amd64',
      'freebsd-arm',
      'linux-386',
      'linux-amd64',
      'linux-arm',
      'linux-arm64',
      'netbsd-386',
      'netbsd-amd64',
      'netbsd-arm',
      'openbsd-386',
      'openbsd-amd64',
      'openbsd-arm',
      'openbsd-arm64',
      'windows-386',
      'windows-amd64',
      'windows-arm64',
    ]
    check = '{osname}-{arch}'.format(osname=osname, arch=arch)
    if check not in validCombinations:
        reportMissingPlatformSupport(osname, arch)

    version = getLatestCliVersion()

    return '{prefix}/{version}/wakatime-cli-{osname}-{arch}.zip'.format(
        prefix=GITHUB_DOWNLOAD_PREFIX,
        version=version,
        osname=osname,
        arch=arch,
    )


def reportMissingPlatformSupport(osname, arch):
    url = 'https://api.wakatime.com/api/v1/cli-missing?osname={osname}&architecture={arch}&plugin={plugin}'.format(
        osname=osname,
        arch=arch,
        plugin=PLUGIN,
    )
    request(url)


def request(url, last_modified=None):
    proxy = CONFIGS.get('settings', 'proxy') if CONFIGS.has_option('settings', 'proxy') else None
    if proxy:
        opener = build_opener(ProxyHandler({
            'http': proxy,
            'https': proxy,
        }))
    else:
        opener = build_opener()

    headers = [('User-Agent', f'github.com/wakatime/{PLUGIN}-wakatime')]
    if last_modified:
        headers.append(('If-Modified-Since', last_modified))

    opener.addheaders = headers

    install_opener(opener)

    try:
        resp = urlopen(url)
        headers = dict(resp.getheaders()) if is_py2 else resp.headers
        return headers, resp.read(), resp.getcode()
    except HTTPError as err:
        if err.code == 304:
            return None, None, 304
        if is_py2:
            ssl._create_default_https_context = ssl._create_unverified_context
            try:
                resp = urlopen(url)
                headers = dict(resp.getheaders()) if is_py2 else resp.headers
                return headers, resp.read(), resp.getcode()
            except HTTPError as err2:
                if err2.code == 304:
                    return None, None, 304
                log(err.read().decode())
                log(err2.read().decode())
                raise
            except IOError:
                raise
        log(err.read().decode())
        raise
    except IOError:
        if is_py2:
            ssl._create_default_https_context = ssl._create_unverified_context
            try:
                resp = urlopen(url)
                headers = dict(resp.getheaders()) if is_py2 else resp.headers
                return headers, resp.read(), resp.getcode()
            except HTTPError as err:
                if err.code == 304:
                    return None, None, 304
                log(err.read().decode())
                raise
            except IOError:
                raise
        raise


def get_file_contents(filename):
    """Get file contents from local folder or GitHub repo."""

    if os.path.exists(os.path.join(SRC_DIR, filename)):
        with open(os.path.join(SRC_DIR, filename), 'r', encoding='utf-8') as fh:
            return fh.read()
    else:
        url = ROOT_URL + filename
        localfile = os.path.join(getResourcesFolder(), filename)
        download(url, localfile)
        with open(localfile, 'r', encoding='utf-8') as fh:
            contents = fh.read()
        os.remove(localfile)
        return contents


def download(url, filePath):
    proxy = CONFIGS.get('settings', 'proxy') if CONFIGS.has_option('settings', 'proxy') else None
    if proxy:
        opener = build_opener(ProxyHandler({
            'http': proxy,
            'https': proxy,
        }))
    else:
        opener = build_opener()
    opener.addheaders = [('User-Agent', f'github.com/wakatime/{PLUGIN}-wakatime')]

    install_opener(opener)

    try:
        urlretrieve(url, filePath)
    except IOError:
        if is_py2:
            ssl._create_default_https_context = ssl._create_unverified_context
            urlretrieve(url, filePath)
        raise


def save_file(filename, contents):
    """Saves contents to filename."""

    with open(filename, 'w', encoding='utf-8') as fh:
        fh.write(contents)


if __name__ == '__main__':
    main()
    sys.exit(0)
