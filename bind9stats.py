#!/usr/bin/env python

"""
Munin plug-in for BIND9 DNS statistics server, written in Python.
Based on the perl plug-in by George Kargiotakis <kargig[at]void[dot]gr>
Tested with a BIND 9.9 statistics server exporting version 2.2 of
th statistics.

Author: Shumon Huque <shuque - @ - upenn.edu>

Copyright (c) 2013, Shumon Huque. All rights reserved.  
This program is free software; you can redistribute it and/or modify 
it under the same terms as Python itself.
"""

import os, sys, time
import xml.etree.ElementTree as et
import urllib2, httplib

HOST = os.environ.get('HOST', "127.0.0.1")
PORT = os.environ.get('PORT', "8053")
BINDSTATS_URL = "http://%s:%s" % (HOST, PORT)

Path_base = "bind/statistics"
Path_views = "bind/statistics/views/view"

GraphCategoryName = "bind_dns"

GraphConfig = (

    ('dns_queries_in',
     dict(title='DNS Queries In',
          enable=True,
          args='-l 0',
          vlabel='Queries/sec',
          location='server/queries-in/rdtype',
          config=dict(type='DERIVE', min=0, draw='AREASTACK'))),

    ('dns_server_stats',
     dict(title='DNS Server Stats',
          enable=True,
          args='-l 0',
          vlabel='Queries/sec',
          location='server/nsstat',
          fields=("Requestv4", "Requestv6", "ReqEdns0", "ReqTCP", "Response",
                  "TruncatedResp", "RespEDNS0", "QrySuccess", "QryAuthAns",
                  "QryNoauthAns", "QryReferral", "QryNxrrset", "QrySERVFAIL",
                  "QryFORMERR", "QryNXDOMAIN", "QryRecursion", "QryDuplicate",
                  "QryDropped", "QryFailure"),
          config=dict(type='DERIVE', min=0))),

    ('dns_opcode_in',
     dict(title='DNS Opcodes In',
          enable=True,
          args='-l 0',
          vlabel='Queries/sec',
          location='server/requests/opcode',
          config=dict(type='DERIVE', min=0, draw='AREASTACK'))),

    ('dns_queries_out',
     dict(title='DNS Queries Out',
          enable=True,
          args='-l 0',
          vlabel='Count/sec',
          view='_default',
          location='rdtype',
          config=dict(type='DERIVE', min=0, draw='AREASTACK'))),

    ('dns_cachedb',
     dict(title='DNS CacheDB RRsets',
          enable=True,
          args='-l 0',
          vlabel='Count/sec',
          view='_default',
          location='cache/rrset',
          config=dict(type='DERIVE', min=0))),

    ('dns_resolver_stats',
     dict(title='DNS Resolver Stats',
          enable=True,
          args='-l 0',
          vlabel='Count/sec',
          view='_default',
          location='resstat',
          config=dict(type='DERIVE', min=0))),

    ('dns_socket_stats',
     dict(title='DNS Socket Stats',
          enable=True,
          args='-l 0',
          vlabel='Count/sec',
          location='server/sockstat',
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

    ('dns_zone_stats',
     dict(title='DNS Zone Maintenance',
          enable=True,
          args='-l 0',
          vlabel='Count/sec',
          location='server/zonestat',
          config=dict(type='DERIVE', min=0))),

)


def getstatsversion(etree):
    """return version of BIND statistics"""
    return tree.findall("%s[1]" % Path_base)[0].attrib['version']


def getkeyvals(path, location, getvals=False):
    result = []
    for stat in path.findall(location):
        key = stat.findtext('name')
        if getvals:
            value = stat.findtext('counter')
            result.append((key,value))
        else:
            result.append(key)
    return result


def getdata(graph, etree, getvals=False):
    view = graph[1].get('view', None)
    if view:
        xmlpath = Path_views
        for stat in etree.findall(xmlpath):
            if stat.findtext('name') == view:
                return getkeyvals(stat, graph[1]['location'], getvals)
    else:
        xmlpath = "%s/%s" % (Path_base, graph[1]['location'])
        return getkeyvals(etree, xmlpath, getvals)


def validkey(graph, key):
    fieldlist = graph[1].get('fields', None)
    if fieldlist and (key not in fieldlist):
        return False
    else:
        return True


def get_etree_root(url):
    """Return the root of an ElementTree structure populated by
    parsing BIND9 statistics obtained at the given URL"""

    data = urllib2.urlopen(url)
    return et.parse(data).getroot()


def muninconfig(etree):
    """Generate munin config for the BIND stats plugin"""

    for g in GraphConfig:
        if not g[1]['enable']:
            continue
        print "multigraph %s" % g[0]
        print "graph_title %s" % g[1]['title']
        print "graph_args %s" % g[1]['args']
        print "graph_vlabel %s" % g[1]['vlabel']
        print "graph_category %s" % GraphCategoryName

        data = getdata(g, etree, getvals=False)
        for key in data:
            if validkey(g, key):
                print "%s.label %s" % (key, key)
                if g[1]['config'].has_key('draw'):
                    print "%s.draw %s" % (key, g[1]['config']['draw'])
                print "%s.min %s" % (key, g[1]['config']['min'])
                print "%s.type %s" % (key, g[1]['config']['type'])
        print


def munindata(etree):
    """Generate munin data for the BIND stats plugin"""

    for g in GraphConfig:
        if not g[1]['enable']:
            continue
        print "multigraph %s" % g[0]
        data = getdata(g, etree, getvals=True)
        for (key, value) in data:
            if validkey(g, key):
                print "%s.value %s" % (key, value)
        print


if __name__ == '__main__':

    tree = get_etree_root(BINDSTATS_URL)

    if len(sys.argv) == 2 and sys.argv[1] == "config":
        muninconfig(tree)
    else:
        munindata(tree)

    sys.exit(0)
