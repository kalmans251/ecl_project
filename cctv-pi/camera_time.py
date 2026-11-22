"""Optional, local ONVIF clock repair. Never participates in the video lease."""
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import logging
import os
import subprocess
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

LOG = logging.getLogger('camera.time')
SOAP = 'http://www.w3.org/2003/05/soap-envelope'
DEVICE = 'http://www.onvif.org/ver10/device/wsdl'
SCHEMA = 'http://www.onvif.org/ver10/schema'
NS = {'s': SOAP, 'd': DEVICE, 't': SCHEMA}


def validate_config(config):
    settings = config.get('time_sync', {})
    if not isinstance(settings, dict) or type(settings.get('enabled', False)) is not bool:
        raise ValueError('Invalid time_sync settings')
    if not settings.get('enabled', False):
        return
    endpoint = urlsplit(settings.get('device_url', ''))
    camera = urlsplit(config['camera_url'])
    if (endpoint.scheme not in ('http', 'https') or not endpoint.hostname
            or endpoint.hostname != camera.hostname or endpoint.username or endpoint.password
            or endpoint.query or endpoint.fragment or not endpoint.path):
        raise ValueError('ONVIF device_url must use the RTSP camera host without credentials')
    # Access port now, so malformed ports fail before background work starts.
    endpoint.port
    for key in ('username', 'password'):
        if not isinstance(settings.get(key), str) or not settings[key]:
            raise ValueError('ONVIF requires a separate username and password')
    if settings.get('timezone', 'KST-9') != 'KST-9':
        raise ValueError('This deployment uses ONVIF POSIX timezone KST-9 (UTC+09:00)')


def pi_clock_ready():
    """Do not propagate a plausible but unsynchronised boot clock to a camera."""
    try:
        result = subprocess.run(
            ['timedatectl', 'show', '-p', 'NTPSynchronized', '--value'],
            capture_output=True, text=True, timeout=3, check=True)
        return result.stdout.strip() == 'yes' and datetime.now(timezone.utc).year >= 2024
    except (OSError, subprocess.SubprocessError):
        return False


def camera_datetime(root):
    value = root.find('.//t:UTCDateTime', NS)
    if value is None:
        raise ValueError('Camera did not return UTC time')
    parts = [int(value.findtext(path, namespaces=NS)) for path in
             ('t:Date/t:Year', 't:Date/t:Month', 't:Date/t:Day',
              't:Time/t:Hour', 't:Time/t:Minute', 't:Time/t:Second')]
    return datetime(*parts, tzinfo=timezone.utc)


def security_header(username, password, created):
    nonce = os.urandom(20)
    stamp = created.strftime('%Y-%m-%dT%H:%M:%SZ')
    digest = base64.b64encode(hashlib.sha1(nonce + stamp.encode() + password.encode()).digest()).decode()
    base = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-'
    return (f'<s:Header><wsse:Security xmlns:wsse="{base}wssecurity-secext-1.0.xsd" '
            f'xmlns:wsu="{base}wssecurity-utility-1.0.xsd"><wsse:UsernameToken>'
            f'<wsse:Username>{escape(username)}</wsse:Username>'
            f'<wsse:Password Type="{base}username-token-profile-1.0#PasswordDigest">{digest}</wsse:Password>'
            f'<wsse:Nonce EncodingType="{base}soap-message-security-1.0#Base64Binary">'
            f'{base64.b64encode(nonce).decode()}</wsse:Nonce><wsu:Created>{stamp}</wsu:Created>'
            '</wsse:UsernameToken></wsse:Security></s:Header>')


def call(session, settings, operation, payload='', created=None):
    header = security_header(settings['username'], settings['password'], created) if created else ''
    body = (f'<s:Envelope xmlns:s="{SOAP}" xmlns:d="{DEVICE}" xmlns:t="{SCHEMA}">'
            f'{header}<s:Body><d:{operation}>{payload}</d:{operation}></s:Body></s:Envelope>')
    response = session.post(settings['device_url'], data=body.encode(),
                            headers={'Content-Type': f'application/soap+xml; charset=utf-8; action="{DEVICE}/{operation}"'},
                            timeout=(3, 3), allow_redirects=False, stream=True)
    with response:
        if response.status_code != 200:
            raise ValueError('ONVIF request rejected')
        data = bytearray()
        for chunk in response.iter_content(4096):
            data.extend(chunk)
            if len(data) > 65536:
                raise ValueError('ONVIF response too large')
    # Only small SOAP responses from the configured camera are accepted.
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('Unsupported XML declarations')
    root = ET.fromstring(data)
    if root.find('.//s:Fault', NS) is not None:
        raise ValueError('ONVIF SOAP fault')
    if root.find(f'.//d:{operation}Response', NS) is None:
        raise ValueError('Invalid ONVIF response')
    return root


def sync_once(settings):
    if not pi_clock_ready():
        return 'waiting for Pi NTP synchronization'
    import requests
    from requests.auth import HTTPDigestAuth
    with requests.Session() as session:
        session.trust_env = False
        session.auth = HTTPDigestAuth(settings['username'], settings['password'])
        # PRE_AUTH read is essential: a 1970 clock would reject a WSSE token
        # stamped with today's time. Sign the write with the camera's own clock.
        observed = call(session, settings, 'GetSystemDateAndTime')
        camera_now = camera_datetime(observed)
        now = datetime.now(timezone.utc)
        zone = observed.findtext('.//t:TimeZone/t:TZ', namespaces=NS)
        daylight = observed.findtext('.//t:DaylightSavings', namespaces=NS)
        if abs((now - camera_now).total_seconds()) <= 5 and zone == 'KST-9' and daylight in ('false', '0'):
            return 'camera clock verified'
        payload = ('<d:DateTimeType>Manual</d:DateTimeType><d:DaylightSavings>false</d:DaylightSavings>'
                   '<d:TimeZone><t:TZ>KST-9</t:TZ></d:TimeZone><d:UTCDateTime>'
                   f'<t:Time><t:Hour>{now.hour}</t:Hour><t:Minute>{now.minute}</t:Minute>'
                   f'<t:Second>{now.second}</t:Second></t:Time><t:Date><t:Year>{now.year}</t:Year>'
                   f'<t:Month>{now.month}</t:Month><t:Day>{now.day}</t:Day></t:Date></d:UTCDateTime>')
        call(session, settings, 'SetSystemDateAndTime', payload, created=camera_now)
        confirmed = call(session, settings, 'GetSystemDateAndTime')
        if abs((datetime.now(timezone.utc) - camera_datetime(confirmed)).total_seconds()) > 5:
            raise ValueError('Camera clock verification failed')
        if (confirmed.findtext('.//t:TimeZone/t:TZ', namespaces=NS) != 'KST-9'
                or confirmed.findtext('.//t:DaylightSavings', namespaces=NS) not in ('false', '0')):
            raise ValueError('Camera timezone verification failed')
        return 'camera time synchronized and verified (UTC+09:00)'


async def time_sync_loop(config):
    settings = config.get('time_sync', {})
    if not settings.get('enabled', False):
        return
    last = None
    while True:
        try:
            status = await asyncio.to_thread(sync_once, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not log exception text: HTTP/XML errors may include credentials.
            status = 'time sync failed; check ONVIF port, permissions and camera settings'
        if status != last:
            LOG.info('%s', status)
            last = status
        await asyncio.sleep(60)
