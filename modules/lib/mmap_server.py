import json
import os
import os.path
import threading
import types
import time

import flask
from flask import request
from werkzeug.middleware.shared_data import SharedDataMiddleware
from wsgiref.simple_server import make_server


app = flask.Flask(__name__)

DOC_DIR = os.path.join(os.path.dirname(__file__), 'mmap_app')

app.wsgi_app = SharedDataMiddleware(
  app.wsgi_app,
  {'/': DOC_DIR})


@app.route('/')
def index_view():
  return flask.redirect('/index.html')


@app.route('/mavlink/<msgtypes>')
def mavlink_view(msgtypes):
  mtypes = msgtypes.split('+')
  msgs = app.module_state.messages
  results = {}
  # Treat * as a wildcard.
  if mtypes == ['*']:
    mtypes = msgs.message_types()
  for mtype in mtypes:
    if msgs.has_message(mtype):
      (t, n, m) = msgs.get_message(mtype)
      results[mtype] = response_dict_for_message(m, t, n)
  return flask.jsonify(results)


@app.route('/command', methods=['POST'])
def command_handler():
  # FIXME: I couldn't figure out how to get jquery to send a
  # Content-Type: application/json, which would have let us use
  # request.json.  And for some reason the data is in the key name.

  body = next(iter(request.form.keys()))
  body_obj = json.loads(body)
  app.module_state.command(body_obj)
  return 'OK'


def nul_terminate(s):
  nul_pos = s.find('\0')
  if nul_pos >= 0:
    return s[:nul_pos]
  else:
    return s


def response_dict_for_message(msg, time, index):
  mdict = msg.to_dict()
  for key, value in list(mdict.items()):
    if isinstance(value, (str,)):
      mdict[key] = nul_terminate(value)
    resp = {
      'time_usec': time,
      'index': index,
      'msg': mdict
      }
  return resp


class _ServerWrapper(threading.Thread):
  """Runs the Flask application in a background thread."""

  def __init__(self, host, port):
    threading.Thread.__init__(self)
    self.daemon = True
    self.server = make_server(host, port, app)

  def run(self):
    self.server.serve_forever()

  def terminate(self):
    self.server.shutdown()


def start_server(address, port, module_state):
  app.module_state = module_state
  srv = _ServerWrapper(address, port)
  srv.start()
  return srv


if __name__ == '__main__':
  # Simple entry point for running the server directly in development.
  class _State(object):
    messages = None

  start_server('127.0.0.1', 9999, module_state=_State())
  try:
    while True:
      time.sleep(1)
  except KeyboardInterrupt:
    pass
