#!/usr/bin/env python

"""
Munin plug-in for BIND9 DNS statistics server, written in Python.
Based on the perl plug-in by George Kargiotakis <kargig[at]void[dot]gr>
Shumon Huque <shuque - @ - upenn.edu>
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
          args='-l 0',
          vlabel='Queries/sec',
          location='server/queries-in/rdtype',
          config=dict(type='DERIVE', min=0, draw='AREASTACK'))),

    ('dns_server_stats',
     dict(title='DNS Server Stats',
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
          args='-l 0',
          vlabel='Queries/sec',
          location='server/requests/opcode',
          config=dict(type='DERIVE', min=0, draw='AREASTACK'))),

    ('dns_queries_out',
     dict(title='DNS Queries Out',
          args='-l 0',
          vlabel='Count/sec',
          view='_default',
          location='rdtype',
          config=dict(type='DERIVE', min=0))),

    ('dns_cachedb',
     dict(title='DNS CacheDB RRsets',
          args='-l 0',
          vlabel='Count/sec',
          view='_default',
          location='cache/rrset',
          config=dict(type='DERIVE', min=0))),

    ('dns_resolver_stats',
     dict(title='DNS Resolver Stats',
          args='-l 0',
          vlabel='Count/sec',
          view='_default',
          location='resstat',
          config=dict(type='DERIVE', min=0))),

    ('dns_socket_stats',
     dict(title='DNS Socket Stats',
          args='-l 0',
          vlabel='Count',
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

)


def getdata(graph, getvals=False):

    result = []
    view = graph[1].get('view', None)

    if view:
        xmlpath = Path_views
        for stat in tree.findall(xmlpath):
            if stat.findtext('name') == view:
                for s2 in stat.findall(graph[1]['location']):
                    key = s2.findtext('name')
                    if getvals:
                        value = s2.findtext('counter')
                        result.append((key,value))
                    else:
                        result.append(key)
    else:
        xmlpath = "%s/%s" % (Path_base, graph[1]['location'])
        for stat in tree.findall(xmlpath):
            key = stat.findtext('name')
            if getvals:
                value = stat.findtext('counter')
                result.append((key,value))
            else:
                result.append(key)

    return result


data = urllib2.urlopen(BINDSTATS_URL)
tree = et.parse(data).getroot()
data.close()

if len(sys.argv) == 2 and sys.argv[1] == "config":

    for g in GraphConfig:
        print "multigraph %s" % g[0]
        print "graph_title %s" % g[1]['title']
        print "graph_args %s" % g[1]['args']
        print "graph_vlabel %s" % g[1]['vlabel']
        print "graph_category %s" % GraphCategoryName

        data = getdata(g, getvals=False)
        for key in data:
            if (not g[1].has_key('fields')) or \
                    (g[1].has_key('fields') and (key in g[1]['fields'])):
                print "%s.label %s" % (key, key)
                if g[1]['config'].has_key('draw'):
                    print "%s.draw %s" % (key, g[1]['config']['draw'])
                print "%s.min %s" % (key, g[1]['config']['min'])
                print "%s.type %s" % (key, g[1]['config']['type'])
        print

else:

    for g in GraphConfig:
        print "multigraph %s" % g[0]
        data = getdata(g, getvals=True)
        for (key, value) in data:
            print "%s.value %s" % (key, value)
        print

sys.exit(0)
