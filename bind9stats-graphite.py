#!/usr/bin/env python3

"""
bind9stats-graphite.py

A version of bind9stats that works with Graphite+Grafana.

Query the XML/HTTP statistics channel for a BIND9 server, at regular
intervals, pick out useful statistics, and send them to a Graphite/Carbon
server (the default backend for the Graphana visualization dashboard among
other things).

Author: Shumon Huque <shuque@gmail.com>

"""

import os
import sys
import time
import socket
import getopt
import syslog
try:
    import lxml.etree as et
except ImportError:
    import xml.etree.ElementTree as et
from urllib.request import urlopen
from urllib.error import URLError


PROGNAME = os.path.basename(sys.argv[0])
VERSION = "0.20"

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


GraphConfig = (

    ('dns_opcode_in' + Prefs.INSTANCE,
     dict(enable=True,
          stattype='counter',
          metrictype='DERIVE',
          location="server/counters[@type='opcode']/counter")),

    ('dns_qtypes_in' + Prefs.INSTANCE,
     dict(enable=True,
          stattype='counter',
          metrictype='DERIVE',
          location="server/counters[@type='qtype']/counter")),

    ('dns_server_stats' + Prefs.INSTANCE,
     dict(enable=True,
          stattype='counter',
          metrictype='DERIVE',
          location="server/counters[@type='nsstat']/counter")),

    ('dns_cachedb' + Prefs.INSTANCE,
     dict(enable=True,
          stattype='cachedb',
          metrictype='GAUGE',
          location="views/view[@name='_default']/cache[@name='_default']/rrset")),

    ('dns_resolver_stats' + Prefs.INSTANCE,
     dict(enable=True,                         # appears to be empty
          stattype='counter',
          metrictype='DERIVE',
          location="server/counters[@type='resstat']/counter")),

    ('dns_resolver_stats_qtype' + Prefs.INSTANCE,
     dict(enable=True,
          stattype='counter',
          metrictype='DERIVE',
          location="views/view[@name='_default']/counters[@type='resqtype']/counter")),

    ('dns_resolver_stats_defview' + Prefs.INSTANCE,
     dict(enable=True,
          stattype='counter',
          metrictype='DERIVE',
          location="views/view[@name='_default']/counters[@type='resstats']/counter")),

    ('dns_cachestats' + Prefs.INSTANCE,
     dict(enable=True,
          stattype='counter',
          metrictype='DERIVE',
          location="views/view[@name='_default']/counters[@type='cachestats']/counter")),

    ('dns_cache_mem' + Prefs.INSTANCE,
     dict(enable=True,
          stattype='counter',
          metrictype='GAUGE',
          location="views/view[@name='_default']/counters[@type='cachestats']/counter",
          fields=("TreeMemInUse", "HeapMemInUse"))),

    ('dns_socket_activity' + Prefs.INSTANCE,
     dict(enable=True,
          stattype='counter',
          metrictype='GAUGE',
          location="server/counters[@type='sockstat']/counter")),

    ('dns_socket_stats' + Prefs.INSTANCE,
     dict(enable=False,
          stattype='counter',
          metrictype='DERIVE',
          location="server/counters[@type='sockstat']/counter")),

    ('dns_zone_stats' + Prefs.INSTANCE,
     dict(enable=True,
          stattype='counter',
          metrictype='DERIVE',
          location="server/counters[@type='zonestat']/counter")),

    ('dns_memory_usage' + Prefs.INSTANCE,
     dict(enable=True,
          stattype='memory',
          metrictype='GAUGE',
          location='memory/summary',
          fields=("ContextSize", "BlockSize", "Lost", "InUse"))),

    ('dns_adbstat' + Prefs.INSTANCE,
     dict(enable=True,
          stattype='counter',
          metrictype='GAUGE',
          location="views/view[@name='_default']/counters[@type='adbstat']/counter")),

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


def dot2underscore(instring):
    """replace periods with underscores in given string"""
    return instring.replace('.', '_')


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


def get_xml_etree_root(url, timeout):

    """Return the root of an ElementTree structure populated by
    parsing XML statistics obtained at the given URL. And also
    the elapsed time."""

    time_start = time.time()
    try:
        rawdata = urlopen(url, timeout=timeout)
    except URLError as e:
        log_message("Error reading {}: {}".format(url, e))
        return None, None
    outdata = et.parse(rawdata).getroot()
    elapsed = time.time() - time_start
    return outdata, elapsed


def timestring2epoch(tstring):
    """Convert bind9 stats time string to epoch value"""
    try:
        return time.mktime(time.strptime(tstring.split('.')[0],
                                         "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return 'nan'


def connect_host(host, port, timeout):

    """Connect with TCP to given host, port and return socket"""

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
    except OSError as e:
        log_message("connect() to {},{} failed: {}".format(
            host, port, e))
        return None
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


class Bind9Stats:

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.url = "http://{}:{}/xml".format(host, port)
        self.tree = None
        self.poll_duration = None
        self.timestamp = None
        self.timestamp_int = None
        self.last_poll = None
        self.time_delta = None

    def poll(self):
        self.timestamp = time.time()
        self.timestamp_int = round(self.timestamp)
        self.tree, self.poll_duration = get_xml_etree_root(self.url, self.timeout)
        if self.tree is not None:
            if self.last_poll is not None:
                self.time_delta = self.timestamp - self.last_poll
            self.last_poll = self.timestamp


class Bind2Graphite:

    def __init__(self, stats, host, port, timeout=5, poll_interval=None):
        self.stats = stats
        self.host = host
        self.port = port
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.statsdb = {}              # stores (derive) stats from previous run
        self.graphite_data = None
        self.socket = None

    def reset(self):
        self.graphite_data = b''

    def compute_statvalue(self, name, val):
        if name not in self.statsdb:
            gvalue = 'nan'
        else:
            gvalue = (float(val) - float(self.statsdb[name])) / self.stats.time_delta
        self.statsdb[name] = val
        return gvalue

    def add_metric_line(self, category, stat, value):
        out = '{}.{}.{} {} {}\r\n'.format(
            Prefs.HOSTNAME, category, stat, value, self.stats.timestamp_int)
        self.graphite_data += out.encode()

    def generate_server_data(self):
        category = 'bind_info'
        self.add_metric_line(category, 'boot-time',
                             timestring2epoch(
                                 self.stats.tree.find('server/boot-time').text))
        self.add_metric_line(category, 'config-time',
                             timestring2epoch(
                                 self.stats.tree.find('server/config-time').text))

        category = "bind_zones"
        for z in self.stats.tree.find("views/view[@name='_default']/zones"):
            ztype = z.find('type').text
            if ztype != 'builtin':
                zonename = dot2underscore(z.attrib['name'])
                zserial = z.find('serial').text
                self.add_metric_line(category, zonename, zserial)

    def generate_graph_data(self):

        for g in GraphConfig:
            if not g[1]['enable']:
                continue
            data = getdata(g, self.stats.tree, getvals=True)
            if data is None:
                continue
            for (key, value) in data:
                if not validkey(g, key):
                    continue
                statname = "{}.{}".format(g[0], key)
                if g[1]['metrictype'] != 'DERIVE':
                    gvalue = value
                else:
                    gvalue = self.compute_statvalue(statname, value)
                self.add_metric_line(g[0], key, gvalue)
        log_message("DEBUG: datalen={}, gentime={:.2f}s, {}".format(
            len(self.graphite_data),
            self.stats.poll_duration,
            time.ctime(self.stats.timestamp_int)))

    def generate_all_data(self):
        self.reset()
        ##self.generate_server_data()
        self.generate_graph_data()

    def connect_graphite(self):
        self.socket = connect_host(self.host, self.port, self.timeout)

    def send_graphite(self):
        if self.socket is None:
            self.connect_graphite()
        if self.socket is None:
            return
        if not send_socket(self.socket, self.graphite_data):
            log_message("DEBUG: reconnecting socket ..")
            self.socket.close()
            time.sleep(0.2)
            self.connect_graphite()
            if self.socket is None:
                return
            if not send_socket(self.socket, self.graphite_data):
                log_message("DEBUG: send() failed. Sleeping till next poll.")

    def single_run(self):
        self.stats.poll()
        if self.stats.tree is None:
            log_message("No statistics data found. Sleeping till next poll.")
            return
        self.generate_all_data()
        if Prefs.SEND:
            self.send_graphite()
        else:
            print(self.graphite_data.decode())

    def sleep_time(self, elapsed):
        if elapsed <= self.poll_interval:
            return self.poll_interval - elapsed
        return self.poll_interval - (elapsed % self.poll_interval)

    def run(self):
        while True:
            time_start = time.time()
            self.single_run()
            elapsed = time.time() - time_start
            time.sleep(self.sleep_time(elapsed))


if __name__ == '__main__':

    process_args(sys.argv[1:])
    if Prefs.DAEMON:
        daemon(dirname=Prefs.WORKDIR)
    log_message("starting with host {}".format(Prefs.HOSTNAME))

    b9_stats = Bind9Stats(Prefs.BIND9_HOST, Prefs.BIND9_PORT, Prefs.TIMEOUT)
    Bind2Graphite(b9_stats,
                  Prefs.GRAPHITE_HOST, Prefs.GRAPHITE_PORT,
                  Prefs.TIMEOUT, poll_interval=Prefs.POLL_INTERVAL).run()
