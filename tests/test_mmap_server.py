import json
import types
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import modules.lib.mmap_server as mmap_server

class DummyMessage:
    def __init__(self, data):
        self._data = data
    def to_dict(self):
        return self._data

class DummyMessages:
    def __init__(self, messages):
        # messages: dict of mtype -> (time,index,message)
        self._messages = messages
    def message_types(self):
        return list(self._messages.keys())
    def has_message(self, mtype):
        return mtype in self._messages
    def get_message(self, mtype):
        return self._messages[mtype]

class DummyModuleState:
    def __init__(self):
        msg = DummyMessage({'value': 42})
        self.messages = DummyMessages({'TEST': (100, 1, msg)})
        self.command_body = None
    def command(self, body):
        self.command_body = body

def setup_module(module):
    mmap_server.app.module_state = DummyModuleState()

@pytest.fixture
def client():
    return mmap_server.app.test_client()

def test_index_redirect(client):
    resp = client.get('/')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/index.html')

def test_mavlink_endpoint(client):
    resp = client.get('/mavlink/TEST')
    assert resp.status_code == 200
    assert resp.get_json() == {
        'TEST': {
            'time_usec': 100,
            'index': 1,
            'msg': {'value': 42}
        }
    }

def test_command_endpoint(client):
    payload = {'cmd': 'arm'}
    resp = client.post('/command', data=json.dumps(payload))
    assert resp.status_code == 200
    assert resp.data == b'OK'
    assert mmap_server.app.module_state.command_body == payload
