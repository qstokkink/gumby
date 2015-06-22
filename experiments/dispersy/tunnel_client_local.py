#!/usr/bin/env python

# Code:
import sys
import random
import string
import yappi
import os
import logging

from os import path
from random import choice
from string import letters
from struct import pack
from sys import path as pythonpath
from tempfile import gettempdir
from time import time
from threading import Event

from twisted.internet import reactor
from twisted.internet.task import LoopingCall
from twisted.python.log import msg

from gumby.experiments.dispersyclient import DispersyExperimentScriptClient, main
from gumby.experiments.TriblerDispersyClient import TriblerDispersyExperimentScriptClient,\
    BASE_DIR
from hiddenservices_client import HiddenServicesClient

# TODO(emilon): Fix this crap
pythonpath.append(path.abspath(path.join(path.dirname(__file__), '..', '..', '..', "./tribler")))

from Tribler.community.tunnel.tunnel_community import TunnelCommunity, TunnelSettings
from Tribler.Core.DownloadConfig import DownloadStartupConfig
from Tribler.Core.TorrentDef import TorrentDef

from Tribler.dispersy.candidate import Candidate
from Tribler.dispersy.endpoint import TUNNEL_PREFIX
from Tribler.community.tunnel.Socks5 import conversion

class TunnelClient(HiddenServicesClient):

    def __init__(self, *argv, **kwargs): 
        """Initialize the local Tunnel client
        """
        from Tribler.community.tunnel.hidden_community import HiddenTunnelCommunity
        HiddenServicesClient.__init__(self, *argv, **kwargs)

    def registerCallbacks(self):
        """Scenario callbacks:
                - build_circuits:   set the amount hops and circuits
                - reset_circuits:   kill all circuits
                - send_packets:     create the torrent to be seeded by client 0
                - download:         start downloading the torrent for client 1
        """
        HiddenServicesClient.registerCallbacks(self)

        self.scenario_runner.register(self.build_circuits, 'build_circuits')
        self.scenario_runner.register(self.reset_circuits, 'reset_circuits')
        self.scenario_runner.register(self.send_packets, 'send_packets')
        self.scenario_runner.register(self.start_profiling, 'start_profiling')
        self.scenario_runner.register(self.stop_profiling, 'stop_profiling')
        self.scenario_runner.register(self.init_community, 'init_community')
        self.scenario_runner.register(self.identify, 'identify')

    def init_community(self):
        if self.is_exit_node():
            HiddenServicesClient.init_community(self, True)
        else:
            HiddenServicesClient.init_community(self, False)

        tunnel_settings = self.community_kwargs['settings']
        tunnel_settings.max_packets_without_reply = 10000000

        logging.error("I became seednode: %s" % ('True' if self.is_head_node() else 'False'))
        logging.error("I became downloadnode: %s" % ('True' if self.is_dl_node() else 'False'))

    def is_head_node(self):
        """Is this node the main seeding node"""
        return self.scenario_runner._peernumber == 1

    def is_exit_node(self):
        """Is this node the designated exit node"""
        return self.scenario_runner._peernumber == 2

    def is_dl_node(self):
        """Is this node the downloading node"""
        return self.scenario_runner._peernumber == 3

    def identify(self):
        """Create a file that describes this node, with its name"""
        output = ""
        if self.is_head_node():
            output += "HEAD"
        if self.is_exit_node():
            output += "EXIT"
        if self.is_dl_node():
            output += "DL"
        output += ".id"
        open(output, 'w').close()

    def build_circuits(self, hops=3, count=4):
        """Increase the number of circuits to a certain count  
        """

        icount = int(count)
        ihops = int(hops)

        self.hops = ihops

        # Only the downloading node needs to actually build the circuits
        if self.is_dl_node():
            self._community.settings.circuit_length = icount

            for x in range(0, icount):
                self._community.create_circuit(ihops)

        if self.is_head_node():
            self.setup_seeder()

    def reset_circuits(self):
        """Force kill all circuits, relays and peers"""
        # Kill downloads
        downloads = self.session.get_downloads()
        for download in downloads:
            self.session.remove_download(download)

        # Kill circuits
        keys = self._community.circuits.keys()
        for key in keys:
            self._community.remove_circuit(key, 'experiment reset')
        keys = self._community.relay_from_to.keys()
        for key in keys:
            self._community.remove_relay(key, 'experiment reset', both_sides=False)
        keys = self._community.exit_sockets.keys()
        for key in keys:
            self._community.remove_exit_socket(key, 'experiment reset')

        self._community.settings.circuit_length = 0
        self._community._statistics.msg_statistics.total_received_count = 0

    def send_packets(self):
        """Only peer 3 downloads (from peer 1)
        """
        if self.is_dl_node():
            self.start_download(self.hops)

    def start_download(self, hops):
        from Tribler.Main.globals import DefaultDownloadStartupConfig
        defaultDLConfig = DefaultDownloadStartupConfig.getInstance()
        dscfg = defaultDLConfig.copy()
        dscfg.set_hops(0) # DEBUG << hops
        dscfg.set_dest_dir(path.join(os.getcwd(), 'downloader%s' % self.session.get_dispersy_port()))

        def cb_start_download():
            from Tribler.Core.TorrentDef import TorrentDef
            from Tribler.Core.simpledefs import dlstatus_strings
            tdef = TorrentDef.load(path.join(BASE_DIR, "output", "gen.torrent"))
            # Ports defined in HiddenServicesClient as:
            # [23000 + (100 * self.scenario_runner._peernumber) + i for i in range(5)]
            # Seeder has peer number 1, therefore ranges on port 23100 ~ 23104
            tdef.set_initial_peers([("127.0.0.1", 23100),("127.0.0.1", 23101),("127.0.0.1", 23102),("127.0.0.1", 23103),("127.0.0.1", 23104)])

            def cb(ds):
                logging.error('Download infohash=%s, down=%s, progress=%s, status=%s, seedpeers=%s, candidates=%d' %
                    (tdef.get_infohash().encode('hex')[:10],
                     ds.get_current_speed('down'),
                     ds.get_progress(),
                     dlstatus_strings[ds.get_status()],
                     sum(ds.get_num_seeds_peers()),
                     sum(1 for _ in self._community.dispersy_yield_verified_candidates())))
                return 1.0, False

            download = self.session.start_download(tdef, dscfg, 3, True)
            download.set_state_callback(cb, delay=1)

        self.session.uch.perform_usercallback(cb_start_download)

    def setup_seeder(self):

        def cb_seeder_download():
            logging.error("Create an anonymous torrent")
            from Tribler.Core.TorrentDef import TorrentDef
            from Tribler.Core.simpledefs import dlstatus_strings
            tdef = TorrentDef()
            tdef.add_content(path.join(BASE_DIR, "tribler", "Tribler", "Test", "data", "video.avi"))
            tdef.set_tracker("http://fake.net/announce")
            tdef.set_private()  # disable dht
            tdef.set_anonymous(True)
            tdef.finalize()
            tdef_file = path.join(BASE_DIR, "output", "gen.torrent")
            tdef.save(tdef_file)

            logging.error("Start seeding")
            from Tribler.Main.globals import DefaultDownloadStartupConfig
            defaultDLConfig = DefaultDownloadStartupConfig.getInstance()
            dscfg = defaultDLConfig.copy()
            dscfg.set_dest_dir(path.join(BASE_DIR, "tribler", "Tribler", "Test", "data"))
            dscfg.set_hops(0)

            def cb(ds):
                logging.error('Seed infohash=%s, up=%s, progress=%s, status=%s, seedpeers=%s, candidates=%d' %
                    (tdef.get_infohash().encode('hex')[:10],
                     ds.get_current_speed('up'),
                     ds.get_progress(),
                     dlstatus_strings[ds.get_status()],
                     sum(ds.get_num_seeds_peers()),
                     sum(1 for _ in self._community.dispersy_yield_verified_candidates())))
                return 1.0, False

            download = self.session.start_download(tdef, dscfg)
            download.set_state_callback(cb, delay=1)

        logging.error("Call to cb_seeder_download")
        reactor.callInThread(cb_seeder_download)

        # Wait for the introduction point to announce itself to the DHT
        dht = Event()

        def dht_announce(info_hash, community):
            from Tribler.Core.DecentralizedTracking.pymdht.core.identifier import Id

            def cb_dht(info_hash, peers, source):
                self._logger.debug("announced %s to the DHT", info_hash.encode('hex'))
                dht.set()
            port = community.session.get_dispersy_port()
            community.session.lm.mainline_dht.get_peers(info_hash, Id(info_hash), cb_dht, bt_port=port)

        self._community.dht_announce = lambda ih, com = self._community: dht_announce(ih, com)

    def start_profiling(self, outputName=""):
        """Start profiling tunnel functions"""
        self.outputfile = open("profiling" + outputName + ".log", 'w')
        yappi.start() 

    def stop_profiling(self):
        """Stop profiling tunnel functions"""
        yappi.stop()
        yappi_stats = yappi.get_func_stats()
        yappi_stats.sort("tsub")
        for func_stat in filter( lambda x: "Tribler/community/tunnel" in x.module, yappi_stats):
            self.outputfile.write("%10dx  %10.3fs %s\n" % (func_stat.ncall, func_stat.tsub, func_stat.full_name))
        self.outputfile.close()

if __name__ == '__main__':
    TunnelClient.scenario_file = 'tunnel_performance.scenario'
    main(TunnelClient)
