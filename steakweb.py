#!/usr/bin/env python3

from aiohttp import web
import aiohttp
import aiohttp_jinja2
import aiohttp_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
import asyncio
import asyncpg
import jinja2
import json
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser
import os
import random
import socket
import stat
import string
import time

dbconn = None

with open('config.json', 'r') as configfile:
    config = json.load(configfile)

SAML_SETTINGS = config['saml_settings']
saml_req_data = config['saml_req_data']
socketpath = config['socket_path']
dbconnstr = config['dbconnstr']
cookiekey = config['cookiekey']
IDP_METADATA = config['idp_metadata']

### utility functions

def send_to_idp():
    raise web.HTTPFound(OneLogin_Saml2_Auth(saml_req_data, old_settings=SAML_SETTINGS).login())

def check_session_exp(session):
    if not 'iat' in session or session['iat'] + (60 * 20) < time.time():
        # session is expired, raise an exception to send through saml
        send_to_idp()

def check_auth_isadmin(session):
    # Check for "Extension Admins" group in Authentik
    attrs = session.get('attributes', None)
    if attrs:
        groups = attrs.get('http://schemas.xmlsoap.org/claims/Group', None)
        if groups:
            return 'Extension Admins' in groups
    return False

def gen_sip_pw(length=24):
    characters = string.ascii_letters + string.digits + '_-+!@#$%^&*()='
    return ''.join(random.choice(characters) for _ in range(length))

### get request handlers

async def homepage(request):
    # figure out who's calling and list the extensions they can control
    session = await aiohttp_session.get_session(request)
    check_session_exp(session)
    if dbconn is None:
        await init_db_pool()
    rows = None
    if check_auth_isadmin(session):
        rows = await dbconn.fetch("SELECT extn, name, switch IS NOT NULL AS prov, auth_code, publish FROM registered_extensions WHERE provisioned = 't' ORDER BY extn")
    else:
        rows = await dbconn.fetch("SELECT extn, name, switch IS NOT NULL AS prov, auth_code, publish FROM registered_extensions WHERE userid = $1 ORDER BY extn", int(session['uid']))

    # render the template with the list and the status of the last request (from the session)
    context = { 'extensions': rows, 'error': session.get('error', None), 'attributes': session.get('attributes', None) }
    r = aiohttp_jinja2.render_template('homepage.html', request, context)

    # clear the status
    session['error'] = None

    return r

async def directory(request):
    # display all published extensions
    session = await aiohttp_session.get_session(request)
    check_session_exp(session)
    if dbconn is None:
        await init_db_pool()
    rows = None
    rows = await dbconn.fetch("SELECT extn, name FROM registered_extensions WHERE publish = 't'")

    # render the template with the list and the status of the last request (from the session)
    context = { 'extensions': rows, 'error': session.get('error', None), 'attributes': session.get('attributes', None) }
    r = aiohttp_jinja2.render_template('homepage.html', request, context)

    # clear the status
    session['error'] = None

    return r

### post request handlers

async def rename_extn(request):
    # Just set the name
    data = await request.post()
    session = await aiohttp_session.get_session(request)
    check_session_exp(session)
    if dbconn is None:
        await init_db_pool()

    n = None
    if check_auth_isadmin(session):
        n = await dbconn.execute('UPDATE registered_extensions SET name = $1 WHERE extn = $2', data['name'], int(data['extn']))
    else:
        n = await dbconn.execute('UPDATE registered_extensions SET name = $1 WHERE extn = $2 AND userid = $3', data['name'], int(data['extn']), int(session['uid']))

    if n != 'UPDATE 1':
        session['error'] = 'Could not change directory name; contact support'
        print(f'While updating extension name: {n}')

    raise web.HTTPFound('/')

async def delete_extn(request):
    # delete it where it doesn't have a physical circuit
    # note, sip happens automatically
    data = await request.post()
    session = await aiohttp_session.get_session(request)
    check_session_exp(session)
    if dbconn is None:
        await init_db_pool()

    n = None
    if check_auth_isadmin(session):
        n = await dbconn.execute('DELETE FROM registered_extensions WHERE switch IS NULL AND extn = $1', int(data['extn']))
    else:
        n = await dbconn.execute('DELETE FROM registered_extensions WHERE switch IS NULL AND extn = $1 AND userid = $2', data['name'], int(data['extn']), int(session['uid']))

    if n != 'DELETE 1':
        session['error'] = 'Could not unsubscribe service; contact support'
        print(f'While deleting extension: {n}')

    raise web.HTTPFound('/')

async def create_extn(request):
    # make a new extension with a random auth_code
    # if the DB doesn't like it, give the error in session[error]
    data = await request.post()
    session = await aiohttp_session.get_session(request)
    check_session_exp(session)

    extnum = int(data[extn])
    if extnum < 2000 or extnum >= 7000:
        session['error'] = 'Invalid extension number'
        raise web.HTTPFound('/')

    if dbconn is None:
        await init_db_pool()

    authcode = ''.join([str(random.randint(0, 9)) for _ in range(12)])
    n = await dbconn.execute('INSERT INTO registered_extensions (extn, name, userid, auth_code, publish) VALUES ($1, $2, $3, $4, $5)', data[extn], data[name], int(session['uid']), authcode, data[publish])
    if n != 'INSERT 0 1':
        session['error'] = 'Could not subscribe service; contact support'
        print(f'While creating extension: {n}')

    raise web.HTTPFound('/')

async def publish_extn(request):
    # just set the published flag
    data = await request.post()
    session = await aiohttp_session.get_session(request)
    check_session_exp(session)
    if dbconn is None:
        await init_db_pool()

    n = None
    if check_auth_isadmin(session):
        n = await dbconn.execute("UPDATE registered_extensions SET publish = 't' WHERE extn = $1", int(data['extn']))
    else:
        n = await dbconn.execute("UPDATE registered_extensions SET publish = 't' WHERE extn = $1 AND userid = $2", int(data['extn']), int(session['uid']))

    if n != 'UPDATE 1':
        session['error'] = 'Could not change directory name; contact support'
        print(f'While publishing extension: {n}')

    raise web.HTTPFound('/')

async def unpublish_extn(request):
    # just unset the publish flag
    data = await request.post()
    session = await aiohttp_session.get_session(request)
    check_session_exp(session)
    if dbconn is None:
        await init_db_pool()

    n = None
    if check_auth_isadmin(session):
        n = await dbconn.execute("UPDATE registered_extensions SET publish = 'f' WHERE extn = $1", int(data['extn']))
    else:
        n = await dbconn.execute("UPDATE registered_extensions SET publish = 'f' WHERE extn = $1 AND userid = $2", int(data['extn']), int(session['uid']))

    if n != 'UPDATE 1':
        session['error'] = 'Could not change directory name; contact support'
        print(f'While unpublishing extension: {n}')

    raise web.HTTPFound('/')

async def prov_to_sip(request):
    # if it doesn't have a physical circuit:
    # choose a random password
    # set the SIP password, and the switch ID to 11
    # maybe in a retry loop, tell the activation server to resync that extension
    data = await request.post()
    session = await aiohttp_session.get_session(request)
    check_session_exp(session)
    if dbconn is None:
        await init_db_pool()

    n = None
    if check_auth_isadmin(session):
        n = await dbconn.execute("UPDATE registered_extensions SET auth_code = $2, switch = 11 WHERE extn = $1", int(data['extn']), gen_sip_pw())
    else:
        n = await dbconn.execute("UPDATE registered_extensions SET auth_code = $2, switch = 11 WHERE extn = $1 AND userid = $3", int(data['extn']), gen_sip_pw(), int(session['uid']))

    if n != 'UPDATE 1':
        session['error'] = 'Could not change directory name; contact support'
        print(f'While applying SIP: {n}')

    raise web.HTTPFound('/')

async def saml_acs(request):
    req_data = saml_req_data.copy()
    req_data['get_data'] = dict(request.query)
    req_data['post_data'] = dict(await request.post())
    print(f'SAML response was {req_data}')
    auth = OneLogin_Saml2_Auth(req_data, old_settings=SAML_SETTINGS)
    auth.process_response()
    errors = auth.get_errors()
    if errors:
        return web.Response(text=f"SAML errors: {errors}, {auth.get_last_error_reason()}", status=400)
    if not auth.is_authenticated():
        return web.Response(text="Not authenticated", status=403)

    session = await aiohttp_session.new_session(request)
    session['uid'] = auth.get_nameid()
    session['attributes'] = auth.get_attributes()
    session['iat'] = time.time()
    print(f'Logged in user {session}')

    raise web.HTTPFound("/")

async def init_db_pool():
    global dbconn
    dbconn = await asyncpg.create_pool(dsn=dbconnstr)
    print(f'dbconn: {dbconn}')

async def init_saml_settings():
    global SAML_SETTINGS
    remote_md = OneLogin_Saml2_IdPMetadataParser.parse_remote(IDP_METADATA)
    del remote_md['sp']
    SAML_SETTINGS.update(remote_md)
    print(f'samlsettings: {SAML_SETTINGS}')

if __name__ == '__main__':
    app = web.Application()
    aiohttp_session.setup(app, EncryptedCookieStorage(
        cookiekey,
        cookie_name='session',
        secure=True,
        samesite='strict'
    ))

    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(os.path.join(os.getcwd(), 'templates')))

    app.add_routes([web.post('/saml/acs', saml_acs)])
    #app.add_routes([web.get('/saml/service-provider-metadata', saml_metadata)])

    app.add_routes([web.get('/', homepage)])
    app.add_routes([web.get('/directory', directory)])

    app.add_routes([web.post('/rename_extn', rename_extn)])
    app.add_routes([web.post('/delete_extn', delete_extn)])
    app.add_routes([web.post('/create_extn', create_extn)])
    app.add_routes([web.post('/publish_extn', publish_extn)])
    app.add_routes([web.post('/unpublish_extn', publish_extn)])
    app.add_routes([web.post('/prov_to_sip', prov_to_sip)])

    app.add_routes([web.static('/static', os.path.join(os.getcwd(), 'static'))])

    asyncio.run(init_saml_settings())

    try:
        os.unlink(socketpath)
    except:
        pass
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(socketpath)
    os.chmod(socketpath, 0o666)
    web.run_app(app, sock=sock)

# vim: set ts=4 sw=4 expendtab
