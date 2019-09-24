#!/usr/bin/env python3

"""
bind9stats-graphite.py

A version of bind9stats that works with Graphite+Grafana.

Query the XML/HTTP statistics channel for a BIND9 server, at regular
intervals, pick out useful statistics, and send them to a Graphite/Carbon
server (the default backend for the Graphana visualization dashboard among
other things).

A little bit of a work in progress, but does the job for now.

Author: Shumon Huque <shuque@gmail.com>

"""

import os
import sys
import time
import socket
import getopt
import syslog
import xml.etree.ElementTree as et
from urllib.request import urlopen
from urllib.error import URLError

PROGNAME = os.path.basename(sys.argv[0])
VERSION = "0.1"


DEFAULT_BIND9_HOST = '127.0.0.1'
DEFAULT_BIND9_PORT = '8053'
DEFAULT_GRAPHITE_HOST = '127.0.0.1'
DEFAULT_GRAPHITE_PORT = '2003'


class Prefs:
    """General Preferences"""
    DAEMON = True                                      # -f: foreground
    WORKDIR = "/"                                      # Fixed
    SEND = False                                       # -s: Send to Graphite
    HOSTNAME = socket.gethostname().split('.')[0]      # -n to change
    SYSLOG_FAC = syslog.LOG_DAEMON                     # Syslog facility
    SYSLOG_PRI = syslog.LOG_INFO                       # Syslog priority
    POLL_INTERVAL = 60                                 # in secs (-p)
    BIND9_HOST = os.environ.get('BIND9_HOST', DEFAULT_BIND9_HOST)
    BIND9_PORT = os.environ.get('BIND9_PORT', DEFAULT_BIND9_PORT)
    INSTANCE = os.environ.get('INSTANCE', "")
    BIND9_STATS_TYPE = "xml"
    GRAPHITE_HOST = os.environ.get('GRAPHITE_HOST', DEFAULT_GRAPHITE_HOST)
    GRAPHITE_PORT = int(os.environ.get('GRAPHITE_PORT', DEFAULT_GRAPHITE_PORT))
    TIMEOUT = 5


def usage(msg=None):
    """Print Usage string"""
    if msg is not None:
        print(msg)
    print("""\
\nUsage: {0} [Options]

    Options:
    -h             Print this usage message
    -f             Stay in foreground (default: become daemon)
    -n name        Specify server name (default: 1st component of hostname)
    -i interval    Polling interval in seconds (default: {1} sec)
    -s server      Graphite server IP address (default: {2})
    -p port        Graphite server port (default: {3})
    -r             Really send data to Graphite (default: don't)

""".format(PROGNAME, Prefs.POLL_INTERVAL,
           DEFAULT_GRAPHITE_HOST, DEFAULT_GRAPHITE_PORT))
    sys.exit(1)


def process_args(arguments):
    """Process command line arguments"""
    try:
        (options, args) = getopt.getopt(arguments, 'hfn:i:s:p:r')
    except getopt.GetoptError:
        usage("Argument processing error.")
    if args:
        usage("Too many arguments provided.")

    for (opt, optval) in options:
        if opt == "-h":
            usage()
        elif opt == "-f":
            Prefs.DAEMON = False
        elif opt == "-n":
            Prefs.HOSTNAME = optval
        elif opt == "-i":
            Prefs.POLL_INTERVAL = int(optval)
        elif opt == "-s":
            Prefs.GRAPHITE_HOST = optval
        elif opt == "-p":
            Prefs.GRAPHITE_PORT = int(optval)
        elif opt == "-r":
            Prefs.SEND = True
    return


def bindstats_url():
    """Return URL for BIND statistics"""
    return "http://{}:{}/{}".format(
        Prefs.BIND9_HOST, Prefs.BIND9_PORT, Prefs.BIND9_STATS_TYPE)


# Hash Table to store results of previous stats
STATS_DB = {}


GraphConfig = (

    ('dns_opcode_in' + Prefs.INSTANCE,
     dict(title='BIND [00] Opcodes In',
          enable=True,
          stattype='counter',
          args='-l 0',
          vlabel='Queries/sec',
          location="server/counters[@type='opcode']/counter",
          config=dict(type='DERIVE', min=0, draw='AREASTACK'))),

    ('dns_qtypes_in' + Prefs.INSTANCE,
     dict(title='BIND [01] Query Types In',
          enable=True,
          stattype='counter',
          args='-l 0',
          vlabel='Queries/sec',
          location="server/counters[@type='qtype']/counter",
          config=dict(type='DERIVE', min=0, draw='AREASTACK'))),

    ('dns_server_stats' + Prefs.INSTANCE,
     dict(title='BIND [02] Server Stats',
          enable=False,
          stattype='counter',
          args='-l 0',
          vlabel='Queries/sec',
          location="server/counters[@type='nsstat']/counter",
          fields=("Requestv4", "Requestv6", "ReqEdns0", "ReqTCP", "ReqTSIG",
                  "Response", "TruncatedResp", "RespEDNS0", "RespTSIG",
                  "QrySuccess", "QryAuthAns", "QryNoauthAns", "QryReferral",
                  "QryNxrrset", "QrySERVFAIL", "QryFORMERR", "QryNXDOMAIN",
                  "QryRecursion", "QryDuplicate", "QryDropped", "QryFailure",
                  "XfrReqDone", "UpdateDone", "QryUDP", "QryTCP"),
          config=dict(type='DERIVE', min=0))),

    ('dns_cachedb' + Prefs.INSTANCE,
     dict(title='BIND [03] CacheDB RRsets',
          enable=False,
          stattype='cachedb',
          args='-l 0',
          vlabel='Count',
          location="views/view[@name='_default']/cache[@name='_default']/rrset",
          config=dict(type='GAUGE', min=0))),

    ('dns_resolver_stats' + Prefs.INSTANCE,
     dict(title='BIND [04] Resolver Stats',
          enable=False,                         # appears to be empty
          stattype='counter',
          args='-l 0',
          vlabel='Count/sec',
          location="server/counters[@type='resstat']/counter",
          config=dict(type='DERIVE', min=0))),

    ('dns_resolver_stats_qtype' + Prefs.INSTANCE,
     dict(title='BIND [05] Resolver Outgoing Queries',
          enable=False,
          stattype='counter',
          args='-l 0',
          vlabel='Count/sec',
          location="views/view[@name='_default']/counters[@type='resqtype']/counter",
          config=dict(type='DERIVE', min=0))),

    ('dns_resolver_stats_view' + Prefs.INSTANCE,
     dict(title='BIND [06] Resolver Stats',
          enable=False,
          stattype='counter',
          args='-l 0',
          vlabel='Count/sec',
          location="views/view[@name='_default']/counters[@type='resstats']/counter",
          config=dict(type='DERIVE', min=0))),

    ('dns_cachestats' + Prefs.INSTANCE,
     dict(title='BIND [07] Resolver Cache Stats',
          enable=False,
          stattype='counter',
          args='-l 0',
          vlabel='Count/sec',
          location="views/view[@name='_default']/counters[@type='cachestats']/counter",
          fields=("CacheHits", "CacheMisses", "QueryHits", "QueryMisses",
                  "DeleteLRU", "DeleteTTL"),
          config=dict(type='DERIVE', min=0))),

    ('dns_cache_mem' + Prefs.INSTANCE,
     dict(title='BIND [08] Resolver Cache Memory Stats',
          enable=False,
          stattype='counter',
          args='-l 0 --base 1024',
          vlabel='Memory In-Use',
          location="views/view[@name='_default']/counters[@type='cachestats']/counter",
          fields=("TreeMemInUse", "HeapMemInUse"),
          config=dict(type='GAUGE', min=0))),

    ('dns_socket_activity' + Prefs.INSTANCE,
     dict(title='BIND [09] Socket Activity',
          enable=False,
          stattype='counter',
          args='-l 0',
          vlabel='Active',
          location="server/counters[@type='sockstat']/counter",
          fields=("UDP4Active", "UDP6Active",
                  "TCP4Active", "TCP6Active",
                  "UnixActive", "RawActive"),
          config=dict(type='GAUGE', min=0))),

    ('dns_socket_stats' + Prefs.INSTANCE,
     dict(title='BIND [10] Socket Rates',
          enable=False,
          stattype='counter',
          args='-l 0',
          vlabel='Count/sec',
          location="server/counters[@type='sockstat']/counter",
          fields=("UDP4Open", "UDP6Open",
                  "TCP4Open", "TCP6Open",
                  "UDP4OpenFail", "UDP6OpenFail",
                  "TCP4OpenFail", "TCP6OpenFail",
                  "UDP4Close", "UDP6Close",
                  "TCP4Close", "TCP6Close",
                  "UDP4BindFail", "UDP6BindFail",
                  "TCP4BindFail", "TCP6BindFail",
                  "UDP4ConnFail", "UDP6ConnFail",
                  "TCP4ConnFail", "TCP6ConnFail",
                  "UDP4Conn", "UDP6Conn",
                  "TCP4Conn", "TCP6Conn",
                  "TCP4AcceptFail", "TCP6AcceptFail",
                  "TCP4Accept", "TCP6Accept",
                  "UDP4SendErr", "UDP6SendErr",
                  "TCP4SendErr", "TCP6SendErr",
                  "UDP4RecvErr", "UDP6RecvErr",
                  "TCP4RecvErr", "TCP6RecvErr"),
          config=dict(type='DERIVE', min=0))),

    ('dns_zone_stats' + Prefs.INSTANCE,
     dict(title='BIND [11] Zone Maintenance',
          enable=True,
          stattype='counter',
          args='-l 0',
          vlabel='Count/sec',
          location="server/counters[@type='zonestat']/counter",
          config=dict(type='DERIVE', min=0))),

    ('dns_memory_usage' + Prefs.INSTANCE,
     dict(title='BIND [12] Memory Usage',
          enable=True,
          stattype='memory',
          args='-l 0 --base 1024',
          vlabel='Memory In-Use',
          location='memory/summary',
          fields=("ContextSize", "BlockSize", "Lost", "InUse"),
          config=dict(type='GAUGE', min=0))),

    ('dns_adbstat' + Prefs.INSTANCE,
     dict(title='BIND [13] adbstat',
          enable=False,
          stattype='counter',
          args='-l 0',
          vlabel='Count',
          location="views/view[@name='_default']/counters[@type='adbstat']/counter",
          config=dict(type='GAUGE', min=0))),

)


def daemon(dirname=None, syslog_fac=syslog.LOG_DAEMON, umask=0o022):

    """Become daemon: fork, go into background, create new session"""

    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as einfo:
        print("fork() failed: %s" % einfo)
        sys.exit(1)
    else:
        if dirname:
            os.chdir(dirname)
        os.umask(umask)
        os.setsid()

        for fd in range(0, os.sysconf("SC_OPEN_MAX")):
            try:
                os.close(fd)
            except OSError:
                pass
        syslog.openlog(PROGNAME, syslog.LOG_PID, syslog_fac)

        return


def log_message(msg):

    """log message to syslog if daemon, otherwise print"""
    if Prefs.DAEMON:
        syslog.syslog(Prefs.SYSLOG_PRI, msg)
    else:
        print(msg)


def getstatsversion(etree):

    """return version of BIND statistics"""
    return etree.attrib['version']


def getdata(graph, etree, getvals=False):

    stattype = graph[1]['stattype']
    location = graph[1]['location']

    if stattype == 'memory':
        return getdata_memory(graph, etree, getvals)
    elif stattype == 'cachedb':
        return getdata_cachedb(graph, etree, getvals)

    results = []
    counters = etree.findall(location)

    if counters is None:                     # empty result
        return results

    for c in counters:
        key = c.attrib['name']
        val = c.text
        if getvals:
            results.append((key, val))
        else:
            results.append(key)
    return results


def getdata_memory(graph, etree, getvals=False):

    location = graph[1]['location']

    results = []
    counters = etree.find(location)

    if counters is None:                     # empty result
        return results

    for c in counters:
        key = c.tag
        val = c.text
        if getvals:
            results.append((key, val))
        else:
            results.append(key)
    return results


def getdata_cachedb(graph, etree, getvals=False):

    location = graph[1]['location']

    results = []
    counters = etree.findall(location)

    if counters is None:                     # empty result
        return results

    for c in counters:
        key = c.find('name').text
        val = c.find('counter').text
        if getvals:
            results.append((key, val))
        else:
            results.append(key)
    return results


def validkey(graph, key):

    """Are we interested in this key?"""

    fieldlist = graph[1].get('fields', None)
    if fieldlist and (key not in fieldlist):
        return False
    return True


def get_etree_root(url):

    """Return the root of an ElementTree structure populated by
    parsing BIND9 statistics obtained at the given URL. And also
    the elapsed time."""

    time_start = time.time()
    try:
        rawdata = urlopen(url, Prefs.TIMEOUT)
    except URLError as e:
        log_message("Error reading {}: {}".format(url, e))
        return None, None
    outdata = et.parse(rawdata).getroot()
    elapsed = time.time() - time_start
    return outdata, elapsed


def compute_statvalue(name, val, time_delta):

    """Compute statistic value for counter/derive types"""

    if name not in STATS_DB:
        gvalue = 'nan'
    else:
        gvalue = (float(val) - float(STATS_DB[name])) / time_delta
    STATS_DB[name] = val
    return gvalue


def graphite_data(etree, time_delta):

    """Generate BIND9stats data in form suitable to send to Graphite"""

    outdata = b""

    for g in GraphConfig:
        if not g[1]['enable']:
            continue
        data = getdata(g, etree, getvals=True)
        if data is None:
            continue
        for (key, value) in data:
            if not validkey(g, key):
                continue
            statname = "{}.{}.{}".format(Prefs.HOSTNAME, g[0], key)
            if g[1]['config']['type'] != 'DERIVE':
                gvalue = value
            else:
                gvalue = compute_statvalue(statname, value, time_delta)
            outdata += "{} {} {}\r\n".format(
                statname,
                gvalue,
                timestamp).encode()
    return outdata


def connect_host(host, port, timeout):

    """Connect with TCP to given host, port and return socket"""

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
    except OSError as e:
        log_message("connect() to {},{} failed: {}".format(
            host, port, e))
        sys.exit(1)
    return s


def send_socket(s, message):
    """Send message on a connected socket"""
    try:
        octetsSent = 0
        while octetsSent < len(message):
            sentn = s.send(message[octetsSent:])
            log_message("DEBUG: sendSocket: sent {} octets.".format(sentn))
            octetsSent += sentn
    except OSError as e:
        log_message("send_socket exception: {}".format(e))
        return False
    else:
        return True


if __name__ == '__main__':


    process_args(sys.argv[1:])

    if Prefs.DAEMON:
        daemon(dirname=Prefs.WORKDIR)
    log_message("starting with host {}".format(Prefs.HOSTNAME))

    if Prefs.SEND:
        sock = connect_host(Prefs.GRAPHITE_HOST, Prefs.GRAPHITE_PORT,
                            Prefs.TIMEOUT)

    while True:

        tree, duration = get_etree_root(bindstats_url())
        if tree is None:
            log_message("No statistics data found. Sleeping till next poll.")
            time.sleep(Prefs.POLL_INTERVAL)
            continue
        timestamp = int(time.time())
        next_poll_interval = Prefs.POLL_INTERVAL - duration
        gdata = graphite_data(tree, next_poll_interval)
        log_message("DEBUG: data of length: {} octets. {:.2f}s".format(
            len(gdata), duration))
        if Prefs.SEND:
            if not send_socket(sock, gdata):
                # Send failed, commonly broken connection etc. Reconnect,
                # and wait for next polling cycle to resume data send.
                log_message("DEBUG: reconnecting socket ..")
                sock.close()
                sock = connect_host(Prefs.GRAPHITE_HOST, Prefs.GRAPHITE_PORT,
                                    Prefs.TIMEOUT)
        else:
            print(gdata.decode())
        time.sleep(next_poll_interval)
