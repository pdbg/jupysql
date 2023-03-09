import itertools
import shlex
import subprocess
import sys
from os.path import expandvars

from six.moves import configparser as CP
from sqlalchemy.engine.url import URL
from IPython.core.magic_arguments import parse_argstring
from sshtunnel import SSHTunnelForwarder


def _get_secrets(path: str) -> str:
    try:
        response = subprocess.run(
            ['pass', path],
            encoding='utf-8',
            capture_output=True,
            check=True
        )
        return '[DEFAULT]\npass=' + response.stdout
    except subprocess.CalledProcessError as e:
        print('Unable to get secrets from {}'.format(path), file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        raise Exception('Unable to retrieve database details from secret')


def _establish_ssl_tunnel(cfg: dict[str, str]) -> dict[str, str]:
    ssh_keys = ('ssh_host', 'ssh_user', 'ssh_key_file')
    for key in ssh_keys:
        if key not in cfg:
            return cfg
    server = SSHTunnelForwarder(
        (cfg['ssh_host'], int(cfg.get('ssh_port', '22'))),
        ssh_username=cfg['ssh_user'],
        ssh_pkey=cfg['ssh_key_file'],  # or ssh_password.
        remote_bind_address=(cfg['host'], int(cfg['port']))
    )
    server.start()
    cfg['host'] = server.local_bind_host
    cfg['port'] = server.local_bind_port
    return cfg


def connection_from_secrets(path: str):
    parser = CP.ConfigParser(interpolation=None)
    parser.read_string(_get_secrets(path))
    cfg_dict = dict(parser.items('DEFAULT'))
    if 'password' not in cfg_dict:
        cfg_dict['password'] = cfg_dict['pass']
    cfg_dict = _establish_ssl_tunnel(cfg_dict)
    cfg_dict = {
        key: value for key, value in cfg_dict.items() if key in (
            'drivername',
            'host',
            'username',
            'password',
            'database',
            'port'
        )
    }
    return str(URL.create(**cfg_dict))


def connection_from_dsn_section(section, config):
    parser = CP.ConfigParser()
    parser.read(config.dsn_filename)
    cfg_dict = dict(parser.items(section))
    return str(URL(**cfg_dict))


def _connection_string(s, config):
    s = expandvars(s)  # for environment variables
    if "@" in s or "://" in s:
        return s
    if s.startswith("[") and s.endswith("]"):
        section = s.lstrip("[").rstrip("]")
        parser = CP.ConfigParser()
        parser.read(config.dsn_filename)
        cfg_dict = dict(parser.items(section))
        return str(URL(**cfg_dict))
    return ""


def parse(cell, config):
    """Extract connection info and result variable from SQL

    Please don't add any more syntax requiring
    special parsing.
    Instead, add @arguments to SqlMagic.execute.

    We're grandfathering the
    connection string and `<<` operator in.
    """

    result = {"connection": "", "sql": "", "result_var": None}

    pieces = cell.split(None, 1)
    if not pieces:
        return result
    result["connection"] = _connection_string(pieces[0], config)
    if result["connection"]:
        if len(pieces) == 1:
            return result
        cell = pieces[1]

    pieces = cell.split(None, 2)
    if len(pieces) > 1 and pieces[1] == "<<":
        result["result_var"] = pieces[0]
        if len(pieces) == 2:
            return result
        cell = pieces[2]

    result["sql"] = cell
    return result


def _option_strings_from_parser(parser):
    """Extracts the expected option strings (-a, --append, etc) from argparse parser

    Thanks Martijn Pieters
    https://stackoverflow.com/questions/28881456/how-can-i-list-all-registered-arguments-from-an-argumentparser-instance

    :param parser: [description]
    :type parser: IPython.core.magic_arguments.MagicArgumentParser
    """
    opts = [a.option_strings for a in parser._actions]
    return list(itertools.chain.from_iterable(opts))


def without_sql_comment(parser, line):
    """Strips -- comment from a line

    The argparser unfortunately expects -- to precede an option,
    but in SQL that delineates a comment.  So this removes comments
    so a line can safely be fed to the argparser.

    :param line: A line of SQL, possibly mixed with option strings
    :type line: str
    """

    args = _option_strings_from_parser(parser)
    result = itertools.takewhile(
        lambda word: (not word.startswith("--")) or (word in args),
        shlex.split(line, posix=False),
    )
    return " ".join(result)


def magic_args(magic_execute, line):
    line = without_sql_comment(parser=magic_execute.parser, line=line)
    return parse_argstring(magic_execute, line)
