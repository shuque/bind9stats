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
from datetime import datetime
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
    DEBUG = False                                      # -d: True
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
    -d             Generate some diagnostic messages
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
        (options, args) = getopt.getopt(arguments, 'hdfn:i:s:p:r')
    except getopt.GetoptError:
        usage("Argument processing error.")
    if args:
        usage("Too many arguments provided.")

    for (opt, optval) in options:
        if opt == "-h":
            usage()
        elif opt == "-d":
            Prefs.DEBUG = True
        elif opt == "-f":
            Prefs.DAEMON = False
        elif opt == "-n":
            Prefs.HOSTNAME = dot2underscore(optval)
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
        print("fork() failed: {}".format(einfo))
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
    except URLError as einfo:
        log_message("ERROR: Error reading {}: {}".format(url, einfo))
        return None, None
    outdata = et.parse(rawdata).getroot()
    elapsed = time.time() - time_start
    return outdata, elapsed


def connect_host(ipaddr, port, timeout):

    """Connect with TCP to given host, port and return socket"""

    family = socket.AF_INET6 if ipaddr.find(':') != -1 else socket.AF_INET

    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((ipaddr, port))
    except OSError as einfo:
        log_message("WARN: connect() to {},{} failed: {}".format(
            ipaddr, port, einfo))
        return None
    return sock


def send_socket(sock, message):
    """Send message on a connected socket"""
    try:
        octets_sent = 0
        while octets_sent < len(message):
            sentn = sock.send(message[octets_sent:])
            if sentn == 0:
                log_message("WARN: Broken connection. send() returned 0")
                return False
            octets_sent += sentn
    except OSError as einfo:
        log_message("WARN: send_socket exception: {}".format(einfo))
        return False
    else:
        return True


class Bind9Stats:

    """Class to poll BIND9 Statistics server and parse its data"""

    def __init__(self, host, port, timeout, poll_interval=60):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.url = "http://{}:{}/xml".format(host, port)
        self.tree = None
        self.poll_duration = None
        self.timestamp = None
        self.g_timestamp = None
        self.last_poll = None
        self.time_delta = None

    def poll(self):
        """Poll BIND stats and record timestamp and time delta"""
        self.timestamp = time.time()
        self.g_timestamp = round(self.timestamp/self.poll_interval) * self.poll_interval
        self.tree, self.poll_duration = get_xml_etree_root(self.url, self.timeout)
        if self.tree is not None:
            if self.last_poll is not None:
                self.time_delta = self.timestamp - self.last_poll
            self.last_poll = self.timestamp

    def timestamp2string(self):
        """Convert timestamp into human readable string"""
        return datetime.fromtimestamp(self.timestamp).strftime(
            "%Y-%m-%dT%H:%M:%S.%f")[:-3]

    def getdata(self, graph):

        stattype = graph[1]['stattype']
        location = graph[1]['location']

        if stattype == 'memory':
            return self.getdata_memory(graph)
        elif stattype == 'cachedb':
            return self.getdata_cachedb(graph)

        results = []
        counters = self.tree.findall(location)

        if counters is None:
            return results

        for c in counters:
            key = c.attrib['name']
            val = c.text
            results.append((key, val))
        return results

    def getdata_memory(self, graph):

        location = graph[1]['location']

        results = []
        counters = self.tree.find(location)

        if counters is None:
            return results

        for c in counters:
            key = c.tag
            val = c.text
            results.append((key, val))
        return results

    def getdata_cachedb(self, graph):

        location = graph[1]['location']

        results = []
        counters = self.tree.findall(location)

        if counters is None:
            return results

        for c in counters:
            key = c.find('name').text
            val = c.find('counter').text
            results.append((key, val))
        return results


class Bind2Graphite:

    """Functions to communicate BIND9 stats to a Graphite server"""

    def __init__(self, stats, host, port, name=None, timeout=5,
                 poll_interval=None, debug=False):
        self.stats = stats
        self.host = host
        self.port = port
        self.name = name
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.debug = debug
        self.statsdb = {}              # stores (derive) stats from previous run
        self.graphite_data = b''
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
        metricpath = '{}.{}.{}'.format(self.name, category, stat)
        out = '{} {} {}\r\n'.format(metricpath, value, self.stats.g_timestamp)
        self.graphite_data += out.encode()

    def generate_graph_data(self):
        for graph in GraphConfig:
            if not graph[1]['enable']:
                continue
            data = self.stats.getdata(graph)
            if data is None:
                continue
            for (key, value) in data:
                if not validkey(graph, key):
                    continue
                statname = "{}.{}".format(graph[0], key)
                if graph[1]['metrictype'] != 'DERIVE':
                    gvalue = value
                else:
                    gvalue = self.compute_statvalue(statname, value)
                self.add_metric_line(graph[0], key, gvalue)

    def generate_all_data(self):
        self.reset()
        self.generate_graph_data()

    def connect_graphite(self):
        self.socket = connect_host(self.host, self.port, self.timeout)

    def send_graphite(self):
        if self.socket is None:
            self.connect_graphite()
        if self.socket is None:
            return
        if not send_socket(self.socket, self.graphite_data):
            log_message("WARN: reconnecting socket ..")
            self.socket.close()
            time.sleep(0.2)
            self.connect_graphite()
            if self.socket is None:
                return
            if not send_socket(self.socket, self.graphite_data):
                log_message("WARN: send() failed. Sleeping till next poll.")

    def single_run(self):
        self.stats.poll()
        if self.stats.tree is None:
            log_message("WARN: No statistics found. Sleeping till next poll.")
            return
        self.generate_all_data()
        if Prefs.SEND:
            self.send_graphite()
        else:
            print(self.graphite_data.decode())

    def sleep_time(self, elapsed):
        if self.stats.time_delta is None:
            compensation_time = 0
        else:
            compensation_time = self.stats.time_delta - self.poll_interval
        if elapsed <= self.poll_interval:
            base_value = self.poll_interval - elapsed
        else:
            base_value = self.poll_interval - (elapsed % self.poll_interval)
        return base_value - compensation_time

    def run(self):
        while True:
            time_start = time.time()
            self.single_run()
            elapsed = time.time() - time_start
            if self.debug:
                log_message("{} {} elapsed={:.4f} data={}".format(
                    self.stats.timestamp2string(),
                    self.stats.g_timestamp,
                    elapsed,
                    len(self.graphite_data)))
                elapsed = time.time() - time_start
            time.sleep(self.sleep_time(elapsed))


if __name__ == '__main__':

    process_args(sys.argv[1:])

    if Prefs.DAEMON:
        daemon(dirname=Prefs.WORKDIR)
    log_message("starting with host {}, graphite server: {},{}".format(
        Prefs.HOSTNAME, Prefs.GRAPHITE_HOST, Prefs.GRAPHITE_PORT))

    b9_stats = Bind9Stats(Prefs.BIND9_HOST, Prefs.BIND9_PORT, Prefs.TIMEOUT,
                          poll_interval=Prefs.POLL_INTERVAL)

    Bind2Graphite(b9_stats,
                  Prefs.GRAPHITE_HOST, Prefs.GRAPHITE_PORT,
                  name=Prefs.HOSTNAME,
                  timeout=Prefs.TIMEOUT,
                  poll_interval=Prefs.POLL_INTERVAL,
                  debug=Prefs.DEBUG).run()
