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
import calendar
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

# Hash table specifying which metric types to export.
METRICS = {
    'auth': False,
    'res': False,
    'bind': False,
    'zone': False,
    'memory': False,
    'socket': False,
}

class Prefs:
    """General Preferences"""
    DEBUG = False                                      # -d: True
    DAEMON = True                                      # -f: foreground
    WORKDIR = "/"                                      # Fixed
    SEND = False                                       # -s: Send to Graphite
    METRICS = "auth,res,bind,zone,memory"              # -m: metric types
    HOSTNAME = socket.gethostname().split('.')[0]      # -n to change
    SYSLOG_FAC = syslog.LOG_DAEMON                     # Syslog facility
    SYSLOG_PRI = syslog.LOG_INFO                       # Syslog priority
    POLL_INTERVAL = 60                                 # in secs (-p)
    BIND9_HOST = os.environ.get('BIND9_HOST', DEFAULT_BIND9_HOST)
    BIND9_PORT = os.environ.get('BIND9_PORT', DEFAULT_BIND9_PORT)
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
    -m metrics     Comma separated metric types
                   (default: {1})
                   (supported: auth,res,bind,zone,memory,socket)
    -n name        Specify server name (default: 1st component of hostname)
    -i interval    Polling interval in seconds (default: {2} sec)
    -s server      Graphite server IP address (default: {3})
    -p port        Graphite server port (default: {4})
    -r             Really send data to Graphite (default: don't)
""".format(PROGNAME, Prefs.METRICS, Prefs.POLL_INTERVAL,
           DEFAULT_GRAPHITE_HOST, DEFAULT_GRAPHITE_PORT))
    sys.exit(1)


def process_args(arguments):
    """Process command line arguments"""
    try:
        (options, args) = getopt.getopt(arguments, 'hdfm:n:i:s:p:r')
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
        elif opt == "-m":
            Prefs.METRICS = optval
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

    for metric in Prefs.METRICS.split(','):
        if metric in METRICS:
            METRICS[metric] = True
        else:
            usage("{} is not a valid metric.".format(metric))
    return


class Graphs:

    def __init__(self, metrics_dict):
        self.metrics = metrics_dict

        self.params = [

            ('dns_opcode_in',
             dict(enable=self.metrics['auth'] or self.metrics['res'],
                  stattype='counter',
                  metrictype='DERIVE',
                  location="server/counters[@type='opcode']/counter")),

            ('dns_qtypes_in',
             dict(enable=self.metrics['auth'] or self.metrics['res'],
                  stattype='counter',
                  metrictype='DERIVE',
                  location="server/counters[@type='qtype']/counter")),

            ('dns_server_stats',
             dict(enable=self.metrics['auth'] or self.metrics['res'],
                  stattype='counter',
                  metrictype='DERIVE',
                  location="server/counters[@type='nsstat']/counter")),

            ('dns_cachedb',
             dict(enable=self.metrics['res'],
                  stattype='cachedb',
                  metrictype='GAUGE',
                  location="views/view[@name='_default']/cache[@name='_default']/rrset")),

            ('dns_resolver_stats',
             dict(enable=False,                         # appears to be empty
                  stattype='counter',
                  metrictype='DERIVE',
                  location="server/counters[@type='resstat']/counter")),

            ('dns_resolver_stats_qtype',
             dict(enable=self.metrics['res'],
                  stattype='counter',
                  metrictype='DERIVE',
                  location="views/view[@name='_default']/counters[@type='resqtype']/counter")),

            ('dns_resolver_stats_defview',
             dict(enable=self.metrics['res'],
                  stattype='counter',
                  metrictype='DERIVE',
                  location="views/view[@name='_default']/counters[@type='resstats']/counter")),

            ('dns_cachestats',
             dict(enable=self.metrics['res'] and self.metrics['memory'],
                  stattype='counter',
                  metrictype='DERIVE',
                  location="views/view[@name='_default']/counters[@type='cachestats']/counter")),

            ('dns_cache_mem',
             dict(enable=self.metrics['res'] and self.metrics['memory'],
                  stattype='counter',
                  metrictype='GAUGE',
                  location="views/view[@name='_default']/counters[@type='cachestats']/counter")),

            ('dns_socket_activity',
             dict(enable=self.metrics['socket'],
                  stattype='counter',
                  metrictype='GAUGE',
                  location="server/counters[@type='sockstat']/counter")),

            ('dns_socket_stats',
             dict(enable=self.metrics['socket'],
                  stattype='counter',
                  metrictype='DERIVE',
                  location="server/counters[@type='sockstat']/counter")),

            ('dns_zone_stats',
             dict(enable=self.metrics['auth'],
                  stattype='counter',
                  metrictype='DERIVE',
                  location="server/counters[@type='zonestat']/counter")),

            ('dns_memory_usage',
             dict(enable=(self.metrics['auth'] or self.metrics['res']) \
                  and self.metrics['memory'],
                  stattype='memory',
                  metrictype='GAUGE',
                  location='memory/summary')),

            ('dns_adbstat',
             dict(enable=False,
                  stattype='counter',
                  metrictype='GAUGE',
                  location="views/view[@name='_default']/counters[@type='adbstat']/counter")),

        ]


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
        self.g_timestamp_last = None
        self.adjust = ''
        self.last_poll = None
        self.time_delta = None

    def poll(self):
        """Poll BIND stats and record timestamp and time delta"""
        self.timestamp = time.time()
        self.compute_graphite_timestamp()
        self.tree, self.poll_duration = get_xml_etree_root(self.url, self.timeout)
        if self.tree is not None:
            if self.last_poll is not None:
                self.time_delta = self.timestamp - self.last_poll
            self.last_poll = self.timestamp

    def compute_graphite_timestamp(self):
        self.adjust = ''
        self.g_timestamp = round(self.timestamp/self.poll_interval) \
            * self.poll_interval
        if self.g_timestamp_last is not None:
            difference = self.g_timestamp - self.g_timestamp_last
            if difference == 0:
                self.g_timestamp += self.poll_interval
                self.adjust = '+'
            elif difference == self.poll_interval:
                pass
            elif difference == (2 * self.poll_interval):
                self.g_timestamp -= self.poll_interval
                self.adjust = '-'
            else:
                self.adjust = '?'
        self.g_timestamp_last = self.g_timestamp

    def timestamp2string(self):
        """Convert timestamp into human readable string"""
        return datetime.fromtimestamp(self.timestamp).strftime(
            "%Y-%m-%dT%H:%M:%S.%f")[:-3]

    def timestring2since(self, tstring):
        """Convert bind9 stats time string to seconds since current time"""
        try:
            return self.timestamp - calendar.timegm(time.strptime(
                tstring.split('.')[0], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            return 'nan'

    def getdata(self, graphconfig):

        stattype = graphconfig['stattype']
        location = graphconfig['location']

        if stattype == 'memory':
            return self.getdata_memory(graphconfig)
        elif stattype == 'cachedb':
            return self.getdata_cachedb(graphconfig)

        results = []
        counters = self.tree.findall(location)

        if counters is None:
            return results

        for c in counters:
            key = c.attrib['name']
            val = c.text
            results.append((key, val))
        return results

    def getdata_memory(self, graphconfig):

        location = graphconfig['location']

        results = []
        counters = self.tree.find(location)

        if counters is None:
            return results

        for c in counters:
            key = c.tag
            val = c.text
            results.append((key, val))
        return results

    def getdata_cachedb(self, graphconfig):

        location = graphconfig['location']

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
            if gvalue < 0:
                ## negative increment. Probably BIND server restart
                gvalue = 'nan'
        self.statsdb[name] = val
        return gvalue

    def add_metric(self, category, stat, value):
        metricpath = '{}.{}.{}'.format(self.name, category, stat)
        out = '{} {} {}\r\n'.format(metricpath, value, self.stats.g_timestamp)
        self.graphite_data += out.encode()

    def generate_bind_data(self):
        category = 'bind_info'
        self.add_metric(category, 'boot-time',
                        self.stats.timestring2since(
                            self.stats.tree.find('server/boot-time').text))
        self.add_metric(category, 'config-time',
                        self.stats.timestring2since(
                            self.stats.tree.find('server/config-time').text))

    def generate_zone_data(self):
        category = "bind_zones"
        for zone in self.stats.tree.find("views/view[@name='_default']/zones"):
            ztype = zone.find('type').text
            if ztype != 'builtin':
                zonename = dot2underscore(zone.attrib['name'])
                zserial = zone.find('serial').text
                statname = "{}.{}".format(category, zonename)
                serial_increment = self.compute_statvalue(statname, zserial)
                self.add_metric(category, zonename, serial_increment)

    def generate_graph_data(self):
        for (graphname, graphconfig) in graphs.params:
            if not graphconfig['enable']:
                continue
            data = self.stats.getdata(graphconfig)
            if data is None:
                continue
            for (key, value) in data:
                statname = "{}.{}".format(graphname, key)
                if graphconfig['metrictype'] != 'DERIVE':
                    gvalue = value
                else:
                    gvalue = self.compute_statvalue(statname, value)
                self.add_metric(graphname, key, gvalue)

    def generate_all_data(self):
        self.reset()
        if graphs.metrics['bind']:
            self.generate_bind_data()
        if graphs.metrics['zone']:
            self.generate_zone_data()
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
        compensation_time = 0
        if self.stats.time_delta is not None:
            if self.stats.time_delta > self.poll_interval:
                compensation_time = 2 * (self.stats.time_delta % self.poll_interval)
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
                time_delta = "{:.3f}".format(self.stats.time_delta) \
                    if self.stats.time_delta is not None else "null"
                log_message("{} {:.3f} {} elapsed={:.3f} delta={} adj={}".format(
                    self.stats.timestamp2string(),
                    self.stats.timestamp,
                    self.stats.g_timestamp,
                    elapsed,
                    time_delta,
                    self.stats.adjust))
                elapsed = time.time() - time_start
            time.sleep(self.sleep_time(elapsed))


if __name__ == '__main__':

    process_args(sys.argv[1:])

    if Prefs.DAEMON:
        daemon(dirname=Prefs.WORKDIR)
    log_message("starting with host {}, graphite server: {},{}".format(
        Prefs.HOSTNAME, Prefs.GRAPHITE_HOST, Prefs.GRAPHITE_PORT))

    graphs = Graphs(METRICS)

    b9_stats = Bind9Stats(Prefs.BIND9_HOST, Prefs.BIND9_PORT, Prefs.TIMEOUT,
                          poll_interval=Prefs.POLL_INTERVAL)

    Bind2Graphite(b9_stats,
                  Prefs.GRAPHITE_HOST, Prefs.GRAPHITE_PORT,
                  name=Prefs.HOSTNAME,
                  timeout=Prefs.TIMEOUT,
                  poll_interval=Prefs.POLL_INTERVAL,
                  debug=Prefs.DEBUG).run()
