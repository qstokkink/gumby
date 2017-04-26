#!/usr/bin/env python2
import os
import sys

from experiments.dispersy.extract_dispersy_statistics import AbstractHandler, ExtractStatistics


class PeerTrustListHandler(AbstractHandler):

    def __init__(self):
        super(PeerTrustListHandler, self).__init__()
        self.output = {}

    def filter_line(self, node_nr, line_nr, timestamp, timeoffset, key):
        return key == "trust"

    def handle_line(self, node_nr, line_nr, timestamp, timeoffset, key, json):
        for myid, trust_dict in json.iteritems():
            for mid, trust in trust_dict.iteritems():
                self.output.update({(myid, mid): int(trust) + self.output.get(mid, 0)})

    def all_files_done(self, extract_statistics):
        with open(os.path.join(extract_statistics.node_directory, "trust.csv"), "w+") as h_trust:
            print >> h_trust, "mid1,mid2,trust"
            for (mid1, mid2) in self.output:
                print >> h_trust, '"%s","%s",%s' % (mid1.replace('"', '""'),
                                                    mid2.replace('"', '""'),
                                                    str(self.output[(mid1, mid2)]))


class LiveEdgeHandler(AbstractHandler):

    def __init__(self):
        super(LiveEdgeHandler, self).__init__()
        self.output = {}

    def filter_line(self, node_nr, line_nr, timestamp, timeoffset, key):
        return key == "live_edges"

    def handle_line(self, node_nr, line_nr, timestamp, timeoffset, key, json):
        if node_nr not in self.output:
            self.output[node_nr] = []
        for edge_id, edge in json.iteritems():
            self.output[node_nr].append(edge)

    def all_files_done(self, extract_statistics):
        with open(os.path.join(extract_statistics.node_directory, "live_edges.csv"), "w+")\
                as h_live_edges:
            print >> h_live_edges, "mid0,mid1,mid2,mid3,mid4"
            for node_nr, edges in self.output.iteritems():
                for mids in edges:
                    mid0 = mids[0].replace('"', '""') if len(mids) > 0 and mids[0] != '?' else ''
                    mid1 = mids[1].replace('"', '""') if len(mids) > 1 and mids[1] != '?' else ''
                    mid2 = mids[2].replace('"', '""') if len(mids) > 2 and mids[2] != '?' else ''
                    mid3 = mids[3].replace('"', '""') if len(mids) > 3 and mids[3] != '?' else ''
                    mid4 = mids[4].replace('"', '""') if len(mids) > 4 and mids[4] != '?' else ''
                    print >> h_live_edges, '"%s","%s","%s","%s","%s"' % (mid0, mid1, mid2, mid3, mid4)

if __name__ == "__main__":
    e = ExtractStatistics(os.path.abspath(sys.argv[1]))
    e.add_handler(PeerTrustListHandler())
    e.add_handler(LiveEdgeHandler())
    e.parse()
