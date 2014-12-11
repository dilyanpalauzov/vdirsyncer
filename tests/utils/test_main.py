# -*- coding: utf-8 -*-
'''
    tests.utils.test_main
    ~~~~~~~~~~~~~~~~~~~~~

    :copyright: (c) 2014 Markus Unterwaditzer & contributors
    :license: MIT, see LICENSE for more details.
'''

import click
import pytest

from click.testing import CliRunner
import os
import stat
import pytest
import requests

import vdirsyncer.utils as utils
import vdirsyncer.doubleclick as doubleclick
from vdirsyncer.utils.vobject import split_collection

from .. import blow_up, normalize_item, SIMPLE_TEMPLATE, BARE_EVENT_TEMPLATE


class EmptyNetrc(object):
    def __init__(self, file=None):
        self._file = file
    def authenticators(self, hostname):
        return None

class EmptyKeyring(object):
    def get_password(self, *a, **kw):
        return None


@pytest.fixture(autouse=True)
def empty_password_storages(monkeypatch):
    monkeypatch.setattr('netrc.netrc', EmptyNetrc)
    monkeypatch.setattr(utils, 'keyring', EmptyKeyring())


def test_parse_options():
    o = {
        'foo': 'yes',
        'hah': 'true',
        'bar': '',
        'baz': 'whatever',
        'bam': '123',
        'asd': 'off'
    }

    a = dict(utils.parse_options(o.items()))

    expected = {
        'foo': True,
        'hah': True,
        'bar': '',
        'baz': 'whatever',
        'bam': 123,
        'asd': False
    }

    assert a == expected

    for key in a:
        # Yes, we want a very strong typecheck here, because we actually have
        # to differentiate between bool and int, and in Python 2, bool is a
        # subclass of int.
        assert type(a[key]) is type(expected[key])  # flake8: noqa


def test_parse_config_value():
    with pytest.raises(ValueError):
        utils.parse_config_value('123  # comment!')

    assert utils.parse_config_value('"123  # comment!"') == '123  # comment!'
    assert utils.parse_config_value('True') is True
    assert utils.parse_config_value('False') is False
    assert utils.parse_config_value('Yes') is True
    assert utils.parse_config_value('3.14') == 3.14
    assert utils.parse_config_value('') == ''
    assert utils.parse_config_velue('""') == ''


def test_get_password_from_netrc(monkeypatch):
    username = 'foouser'
    password = 'foopass'
    resource = 'http://example.com/path/to/whatever/'
    hostname = 'example.com'

    calls = []

    class Netrc(object):
        def authenticators(self, hostname):
            calls.append(hostname)
            return username, 'bogus', password

    monkeypatch.setattr('netrc.netrc', Netrc)
    monkeypatch.setattr('getpass.getpass', blow_up)

    _password = utils.get_password(username, resource)
    assert _password == password
    assert calls == [hostname]


def test_get_password_from_system_keyring(monkeypatch):
    username = 'foouser'
    password = 'foopass'
    resource = 'http://example.com/path/to/whatever/'
    hostname = 'example.com'

    class KeyringMock(object):
        def get_password(self, resource, _username):
            assert _username == username
            assert resource == utils.password_key_prefix + hostname
            return password

    monkeypatch.setattr(utils, 'keyring', KeyringMock())

    monkeypatch.setattr('getpass.getpass', blow_up)

    _password = utils.get_password(username, resource)
    assert _password == password


def test_get_password_from_command(tmpdir):
    username = 'my_username'
    resource = 'http://example.com'
    password = 'testpassword'
    filename = 'command.sh'

    filepath = str(tmpdir) + '/' + filename
    f = open(filepath, 'w')
    f.write('#!/bin/sh\n'
        '[ "$1" != "my_username" ] && exit 1\n'
        '[ "$2" != "example.com" ] && exit 1\n'
        'echo "{}"'.format(password))
    f.close()

    st = os.stat(filepath)
    os.chmod(filepath, st.st_mode | stat.S_IEXEC)

    @doubleclick.click.command()
    @doubleclick.click.pass_context
    def fake_app(ctx):
        ctx.obj = {'config' : ({'passwordeval' : filepath},{},{})}
        _password = utils.get_password(username, resource)
        assert _password == password

    runner = CliRunner()
    result = runner.invoke(fake_app)
    assert not result.exception


def test_get_password_from_prompt():
    getpass_calls = []

    user = 'my_user'
    resource = 'http://example.com'

    @click.command()
    def fake_app():
        x = utils.get_password(user, resource)
        click.echo('Password is {}'.format(x))

    runner = CliRunner()
    result = runner.invoke(fake_app, input='my_password\n\n')
    assert not result.exception
    assert result.output.splitlines() == [
        'Server password for {} at host {}: '.format(user, 'example.com'),
        'Password is my_password'
    ]


def test_set_keyring_password(monkeypatch):
    class KeyringMock(object):
        def get_password(self, resource, username):
            assert resource == utils.password_key_prefix + 'example.com'
            assert username == 'foouser'
            return None

        def set_password(self, resource, username, password):
            assert resource == utils.password_key_prefix + 'example.com'
            assert username == 'foouser'
            assert password == 'hunter2'

    monkeypatch.setattr(utils, 'keyring', KeyringMock())

    @doubleclick.click.command()
    @doubleclick.click.pass_context
    def fake_app(ctx):
        ctx.obj = {}
        x = utils.get_password('foouser', 'http://example.com/a/b')
        click.echo('password is ' + x)

    runner = CliRunner()
    result = runner.invoke(fake_app, input='hunter2\ny\n')
    assert not result.exception
    assert result.output == (
        'Server password for foouser at host example.com: \n'
        'Save this password in the keyring? [y/N]: y\n'
        'password is hunter2\n'
    )


def test_get_password_from_cache(monkeypatch):
    user = 'my_user'
    resource = 'http://example.com'

    @doubleclick.click.command()
    @doubleclick.click.pass_context
    def fake_app(ctx):
        ctx.obj = {}
        x = utils.get_password(user, resource)
        click.echo('Password is {}'.format(x))
        monkeypatch.setattr(doubleclick.click, 'prompt', blow_up)

        assert (user, 'example.com') in ctx.obj['passwords']
        x = utils.get_password(user, resource)
        click.echo('Password is {}'.format(x))

    runner = CliRunner()
    result = runner.invoke(fake_app, input='my_password\n')
    assert not result.exception
    assert result.output.splitlines() == [
        'Server password for {} at host {}: '.format(user, 'example.com'),
        'Save this password in the keyring? [y/N]: ',
        'Password is my_password',
        'debug: Got password for my_user from internal cache',
        'Password is my_password'
    ]


def test_get_class_init_args():
    class Foobar(object):
        def __init__(self, foo, bar, baz=None):
            pass

    all, required = utils.get_class_init_args(Foobar)
    assert all == {'foo', 'bar', 'baz'}
    assert required == {'foo', 'bar'}


def test_get_class_init_args_on_storage():
    from vdirsyncer.storage.memory import MemoryStorage

    all, required = utils.get_class_init_args(MemoryStorage)
    assert all == set(['fileext', 'collection', 'read_only', 'instance_name'])
    assert not required


def test_request_ssl(httpsserver):
    sha1 = '94:FD:7A:CB:50:75:A4:69:82:0A:F8:23:DF:07:FC:69:3E:CD:90:CA'
    md5 = '19:90:F7:23:94:F2:EF:AB:2B:64:2D:57:3D:25:95:2D'

    httpsserver.serve_content('')  # we need to serve something

    with pytest.raises(requests.exceptions.SSLError) as excinfo:
        utils.request('GET', httpsserver.url)
    assert 'certificate verify failed' in str(excinfo.value)
    utils.request('GET', httpsserver.url, verify=False)
    utils.request('GET', httpsserver.url, verify=False,
                  verify_fingerprint=sha1)
    utils.request('GET', httpsserver.url, verify=False, verify_fingerprint=md5)
