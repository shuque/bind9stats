#!/usr/bin/env python

"""
Munin monitoring plug-in for BIND9 DNS statistics server. Tested
with BIND 9.10, 9.11, and 9.12, exporting version 3.x of the XML
statistics.

Copyright (c) 2013-2015, Shumon Huque. All rights reserved.
This program is free software; you can redistribute it and/or modify
it under the same terms as Python itself.
"""

import os, sys
import xml.etree.ElementTree as et
try:
    from urllib2 import urlopen                  # for Python 2
except ImportError:
    from urllib.request import urlopen           # for Python 3

VERSION = "0.31"

HOST = os.environ.get('HOST', "127.0.0.1")
PORT = os.environ.get('PORT', "8053")
INSTANCE = os.environ.get('INSTANCE', "")
SUBTITLE = os.environ.get('SUBTITLE', "")

STATS_TYPE = "xml"                           # will support json later
BINDSTATS_URL = "http://%s:%s/%s" % (HOST, PORT, STATS_TYPE)

if SUBTITLE != '':
    SUBTITLE = ' ' + SUBTITLE

GraphCategoryName = "dns_bind"

# Note: munin displays these graphs ordered alphabetically by graph title

GraphConfig = (

    ('dns_opcode_in' + INSTANCE,
     dict(title='BIND [00] Opcodes In',
          enable=True,
          stattype='counter',
          args='-l 0',
          vlabel='Queries/sec',
          location="server/counters[@type='opcode']/counter",
          config=dict(type='DERIVE', min=0, draw='AREASTACK'))),

    ('dns_qtypes_in' + INSTANCE,
     dict(title='BIND [01] Query Types In',
          enable=True,
          stattype='counter',
          args='-l 0',
          vlabel='Queries/sec',
          location="server/counters[@type='qtype']/counter",
          config=dict(type='DERIVE', min=0, draw='AREASTACK'))),

    ('dns_server_stats' + INSTANCE,
     dict(title='BIND [02] Server Stats',
          enable=True,
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

    ('dns_cachedb' + INSTANCE,
     dict(title='BIND [03] CacheDB RRsets',
          enable=True,
          stattype='cachedb',
          args='-l 0',
          vlabel='Count',
          location="views/view[@name='_default']/cache[@name='_default']/rrset",
          config=dict(type='GAUGE', min=0))),

    ('dns_resolver_stats' + INSTANCE,
     dict(title='BIND [04] Resolver Stats',
          enable=False,                         # appears to be empty
          stattype='counter',
          args='-l 0',
          vlabel='Count/sec',
          location="server/counters[@type='resstat']/counter",
          config=dict(type='DERIVE', min=0))),

    ('dns_resolver_stats_qtype' + INSTANCE,
     dict(title='BIND [05] Resolver Outgoing Queries',
          enable=True,
          stattype='counter',
          args='-l 0',
          vlabel='Count/sec',
          location="views/view[@name='_default']/counters[@type='resqtype']/counter",
          config=dict(type='DERIVE', min=0))),

    ('dns_resolver_stats_view' + INSTANCE,
     dict(title='BIND [06] Resolver Stats',
          enable=True,
          stattype='counter',
          args='-l 0',
          vlabel='Count/sec',
          location="views/view[@name='_default']/counters[@type='resstats']/counter",
          config=dict(type='DERIVE', min=0))),

    ('dns_cachestats' + INSTANCE,
     dict(title='BIND [07] Resolver Cache Stats',
          enable=True,
          stattype='counter',
          args='-l 0',
          vlabel='Count/sec',
          location="views/view[@name='_default']/counters[@type='cachestats']/counter",
          fields=("CacheHits", "CacheMisses", "QueryHits", "QueryMisses",
                  "DeleteLRU", "DeleteTTL"),
          config=dict(type='DERIVE', min=0))),

    ('dns_cache_mem' + INSTANCE,
     dict(title='BIND [08] Resolver Cache Memory Stats',
          enable=True,
          stattype='counter',
          args='-l 0 --base 1024',
          vlabel='Memory In-Use',
          location="views/view[@name='_default']/counters[@type='cachestats']/counter",
          fields=("TreeMemInUse", "HeapMemInUse"),
          config=dict(type='GAUGE', min=0))),

    ('dns_socket_activity' + INSTANCE,
     dict(title='BIND [09] Socket Activity',
          enable=True,
          stattype='counter',
          args='-l 0',
          vlabel='Active',
          location="server/counters[@type='sockstat']/counter",
          fields=("UDP4Active", "UDP6Active",
                  "TCP4Active", "TCP6Active",
                  "UnixActive", "RawActive"),
          config=dict(type='GAUGE', min=0))),

    ('dns_socket_stats' + INSTANCE,
     dict(title='BIND [10] Socket Rates',
          enable=True,
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

    ('dns_zone_stats' + INSTANCE,
     dict(title='BIND [11] Zone Maintenance',
          enable=False,
          stattype='counter',
          args='-l 0',
          vlabel='Count/sec',
          location="server/counters[@type='zonestat']/counter",
          config=dict(type='DERIVE', min=0))),

    ('dns_memory_usage' + INSTANCE,
     dict(title='BIND [12] Memory Usage',
          enable=True,
          stattype='memory',
          args='-l 0 --base 1024',
          vlabel='Memory In-Use',
          location='memory/summary',
          fields=("ContextSize", "BlockSize", "Lost", "InUse"),
          config=dict(type='GAUGE', min=0))),

    ('dns_adbstat' + INSTANCE,
     dict(title='BIND [13] adbstat',
          enable=True,
          stattype='counter',
          args='-l 0',
          vlabel='Count',
          location="views/view[@name='_default']/counters[@type='adbstat']/counter",
          config=dict(type='GAUGE', min=0))),

)


def unsetenvproxy():
    """Unset HTTP Proxy environment variables that might interfere"""
    for proxyvar in [ 'http_proxy', 'HTTP_PROXY' ]:
        os.unsetenv(proxyvar)
    return


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
    fieldlist = graph[1].get('fields', None)
    if fieldlist and (key not in fieldlist):
        return False
    else:
        return True


def get_etree_root(url):
    """Return the root of an ElementTree structure populated by
    parsing BIND9 statistics obtained at the given URL"""

    data = urlopen(url)
    return et.parse(data).getroot()


def muninconfig(etree):
    """Generate munin config for the BIND stats plugin"""

    for g in GraphConfig:
        if not g[1]['enable']:
            continue
        print("multigraph %s" % g[0])
        print("graph_title %s" % g[1]['title'] + SUBTITLE)
        print("graph_args %s" % g[1]['args'])
        print("graph_vlabel %s" % g[1]['vlabel'])
        print("graph_category %s" % GraphCategoryName)

        data = getdata(g, etree, getvals=False)
        if data != None:
            for key in data:
                if validkey(g, key):
                    print("%s.label %s" % (key, key))
                    if 'draw' in g[1]['config']:
                        print("%s.draw %s" % (key, g[1]['config']['draw']))
                    print("%s.min %s" % (key, g[1]['config']['min']))
                    print("%s.type %s" % (key, g[1]['config']['type']))
        print('')


def munindata(etree):
    """Generate munin data for the BIND stats plugin"""

    for g in GraphConfig:
        if not g[1]['enable']:
            continue
        print("multigraph %s" % g[0])
        data = getdata(g, etree, getvals=True)
        if data != None:
            for (key, value) in data:
                if validkey(g, key):
                    print("%s.value %s" % (key, value))
        print('')


def usage():
    """Print plugin usage"""
    print("""\
\nUsage: bind9stats.py [config|statsversion]\n""")
    sys.exit(1)


if __name__ == '__main__':

    tree = get_etree_root(BINDSTATS_URL)

    args = sys.argv[1:]
    argslen = len(args)
    unsetenvproxy()

    if argslen == 0:
        munindata(tree)
    elif argslen == 1:
        if args[0] == "config":
            muninconfig(tree)
        elif args[0] == "statsversion":
            print("bind9stats %s version %s" % (STATS_TYPE, getstatsversion(tree)))
        else:
            usage()
    else:
        usage()
