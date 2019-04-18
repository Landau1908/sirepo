# -*- coding: utf-8 -*-
u"""Authentication

:copyright: Copyright (c) 2018-2019 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from pykern.pkdebug import pkdc, pkdlog, pkdp
from pykern import pkcollections
from pykern import pkconfig
from pykern import pkinspect
from sirepo import api_perm
from sirepo import cookie
from sirepo import http_reply
import flask
import importlib


#: what routeName to return in the event user is logged out in require_user
LOGIN_ROUTE_NAME = 'login'

#: key for logged in
_COOKIE_STATE = 'sras'

#: key for auth method for login state
_COOKIE_METHOD = 'sram'

#: Identifies the user in the cookie
_COOKIE_USER = 'sru'

#: oauth._COOKIE_STATE migrated to  _COOKIE_METHOD and _COOKIE_LOGIN_SESSION
_COOKIE_SESSION_DEPRECATED = 'sros'

#: formerly used in the cookie but no longer so is removed below
_REMOVED_COOKIE_NAME = 'sron'

#: registered module
_METHOD_CLASS = pkcollections.Dict()

#: Identifies the user in uWSGI logging (read by uwsgi.yml.jinja)
_UWSGI_LOG_KEY_USER = 'sirepo_user'

#: uwsgi object for logging
_uwsgi = None

_BEAKER_COMPAT_MAP = pkcollections.Dict({
    'anonymous': 'a',
    'logged_in': 'li',
    'logged_out': 'lo',
})

@api_perm.require_user
def api_authCompleteRegistration():
    data = http_request.parse_json(assert_sim_type=False)
    dn = _parse_display_name(data)
    uid = get_user()
    assert is_logged_in(), \
        'user is not logged in, uid={}'.format(uid)
    with user_db.thread_lock:
        u = User.search_by(uid=uid)
        if not u:
            # first time for this user
            u = User(uid=uid)
        u.display_name = dn
        u.save()
    return http_reply.gen_json_ok()


@api_perm.allow_visitor
def api_authState():
    a = cookie.unchecked_get_value(_COOKIE_METHOD, _AUTH_METHOD_ANONYMOUS_COOKIE_VALUE)
    s = cookie.unchecked_get_value(_COOKIE_LOGIN_SESSION, _LOGGED_OUT)
    v = pkcollections.Dict(
        user_state = pkcollections.Dict(
            authMethod=_AUTH_METHOD_ANONYMOUS_MODULE_NAME,
            displayName=None,
            loginSession=_LOGIN_SESSION_MAP[s],
            userName=None,
        ),
        is_logged_out=s == _LOGGED_OUT,
    )
    if login_module:
        v.user_state.authMethod = login_module.AUTH_METHOD
        if pkconfig.channel_in('dev'):
            # useful for testing/debugging
            v.user_state.uid  = cookie.unchecked_get_user()
        if a == login_module.AUTH_METHOD_COOKIE_VALUE and s == _LOGGED_IN:
            u = login_module.UserModel.search_by(uid=get_user())
            if u:
                v.user_state.update(
                    displayName=u.display_name,
                    userName=u.user_name,
                )
    return http_reply.render_static('user-state', 'js', v)


@api_perm.allow_visitor
def api_logout(simulation_type):
    """Set the current user as logged out.
    """
    if has_user_value():
        logout()
    return flask.redirect('/{}'.format(simulation_type))


def has_user_value():
    return bool(cookie.has_key(_COOKIE_USER) and get_value(_COOKIE_USER))


def init_mock(uid='invalid-uid'):
    """A mock user for pkcli"""
    cookie.init_mock()
    set_user(uid)


def init_apis(app, uwsgi):
    global _uwsgi
    from sirepo import uri_router

    assert not _METHOD_CLASS
    _uwsgi = uwsgi
    p = pkinspect.this_module().__name__
    for n in cfg.allowed_methods + cfg.deprecated_methods:
        m = importlib.import_module(pkinspect.module_name_join(p, n))
        uri_router.register_api_module(m)
        _METHOD_CLASS[n] = m.AuthClass()
    uri_router.register_api_module()

    from sirepo import beaker_compat
    beaker_compat.auth_hook = _beaker_compat_hook


def login_as_user(user, module):
    prev_uid = unchecked_get_user()
    if prev_uid and prev_uid != user.uid:
        # check if prev_uid is already in the
        # user database, if not, copy over simulations
        # from anonymous to this user.
        if not user.search_by(uid=prev_uid):
            simulation_db.move_user_simulations(
                prev_uid,
                user.uid,
            )
        set_user(user.uid)
    _update_session(_LOGGED_IN, module.AUTH_METHOD_COOKIE_VALUE)


def logout_as_user(module):
    _update_session(_LOGGED_OUT, module.AUTH_METHOD_COOKIE_VALUE)


def process_request(unit_test=None):
    cookie.process_header(unit_test)
    _migrate_cookie_keys()
    if has_user_value():
        set_log_user(unchecked_get_user())


def require_user():
    s = cookie.unchecked_get_value(_COOKIE_STATE)
    e = None
    r = None
    if s is None:
        e = 'never been logged in'
    elif s == _STATE_LOGGED_IN:
        m = cookie.get_value(_COOKIE_METHOD)
        if m in cfg.allowed_methods:
            return None
        u = get_user()
        if m in cfg.deprecated_methods:
            e = 'deprecated'
        else:
            clear_user()
            e = 'invalid'
        e = 'method={} is deprecated, forcing login: uid='.format(m, get_user())
    elif s == _STATE_LOGGED_OUT:
        e = 'logged out user={}'.format(get_user())
    elif s == _STATE_COMPLETE_REGISTRATION:
        r = COMPLETE_REGISTRATION_ROUTE_NAME
        e = 'uid={} needs to complete registration'.format(get_user())
    else:
        # dump cookie values
        # cookie.reset()
        raise AssertionError('state={} invalid, cannot continue'.format(s))
    return (r or LOGIN_ROUTE_NAME, e)


def clear_user():
    set_log_user(None)
    unchecked_remove(_COOKIE_USER)


def get_user():
    return _get_user(True)


def set_user(uid):
    assert uid
    cookie.set_value(_COOKIE_USER, uid)
    set_log_user(uid)


def unchecked_get_user():
    _get_user(False)


def user_not_found(uid):
    no directory or not found in db?
    Force user to logout and log back in
    force a logout by throwing an srexception?


def _beaker_compat_hook(key_map):
    key_map['key']['oauth_login_state'] = _COOKIE_SESSION_DEPRECATED
    key_map['value'] = dict(_BEAKER_COMPAT_MAP)


def _get_user(checked=True):
    if not cookie.has_sentinel():
        util.raise_unauthorized('Missing sentinel, cookies may be disabled')
    return cookie.get_value(_COOKIE_USER) if checked else cookie.unchecked_get_value(_COOKIE_USER)


def _migrate_cookie_keys():
    if cookie.has_key(_COOKIE_METHOD):
        return
    # cookie_name is no longer used so clean up
    cookie.unchecked_remove(_REMOVED_COOKIE_NAME)
    if not cookie.has_sentinel():
        # not initialized
        return
    if not cookie.has_key(_COOKIE_SESSION_DEPRECATED):
        _update_session(
            _LOGGED_IN if cookie.has_user_value() else _LOGGED_OUT,
            _AUTH_METHOD_ANONYMOUS_COOKIE_VALUE,
        )
        return
    os = cookie.unchecked_remove(_COOKIE_SESSION_DEPRECATED)
    if os == _AUTH_METHOD_ANONYMOUS_MODULE_NAME:
        _update_session(_LOGGED_OUT, _AUTH_METHOD_ANONYMOUS_COOKIE_VALUE)
    eoauth_anonymous
    anonymous login module needs to be there.
    if no cookie whatsoever
    set auth method and to do


def _set_log_user(uid):
    if not _uwsgi:
        # Only works for uWSGI (service.uwsgi). sirepo.service.http uses
        # the limited http server for development only. This uses
        # werkzeug.serving.WSGIRequestHandler.log which hardwires the
        # common log format to: '%s - - [%s] %s\n'. Could monkeypatch
        # but we only use the limited http server for development.
        return
    u = 'li-' + uid if uid else '-'
    _uwsgi.set_logvar(_UWSGI_LOG_KEY_USER, u)


def _update_session(login_state, auth_method):
    cookie.set_value(_COOKIE_LOGIN_SESSION, login_state)
    cookie.set_value(_COOKIE_METHOD, auth_method)


cfg = pkconfig.init(
    allowed_methods=(('guest',), tuple, 'for logging in'),
    deprecated_methods=(tuple(), tuple, 'for migrating to allowed_methods'),
)
