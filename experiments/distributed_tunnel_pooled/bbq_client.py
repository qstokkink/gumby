#!/usr/bin/env python2

import logging

from os import environ, path
from sys import path as pythonpath

from twisted.internet import reactor, threads
from twisted.internet.defer import Deferred

from gumby.experiments.dispersy_community_syncer import DispersyCommunitySyncer
from gumby.experiments.dispersyclient import main
from gumby.experiments.TriblerDispersyClient import BASE_DIR, TriblerDispersyExperimentScriptClient

# TODO(emilon): Fix this crap
pythonpath.append(path.abspath(path.join(path.dirname(__file__), '..', '..', '..', "./tribler")))

logging.basicConfig(level=logging.WARNING)

class BBQNakedClient(TriblerDispersyExperimentScriptClient):

    def __init__(self, *argv, **kwargs):
        from Tribler.community.tunnel.pooled_tunnel_community import PooledTunnelCommunity
        super(BBQNakedClient, self).__init__(*argv, **kwargs)
        self.community_class = PooledTunnelCommunity
        self.candidate_ips = []
        self.seeders = {}
        self.download = None
        self.download_infohash = ""
        self.testfilesize = 1024
        self.speed_download = {'download': 0}
        self.speed_upload = {'upload': 0}
        self.progress = {'progress': 0}
        self.peer_count = 2  # TODO
        self.dcs = DispersyCommunitySyncer(self.peer_count)
        self.dcs.conditions["SEEDING_PORT"] = (self.seeder_registered, Deferred())
        self.dcs.conditions["FILE_INFOHASH"] = (self.infohash_updated, Deferred())

    def get_my_member(self):
        return self._dispersy.get_new_member(u"curve25519")

    def log_progress_stats(self, ds):
        new_speed_download = {'download': ds.get_current_speed('down')}
        self.speed_download = self.print_on_change("speed-download",
                                                   self.speed_download,
                                                   new_speed_download)

        new_progress = {'progress': ds.get_progress() * 100}
        self.progress = self.print_on_change("progress-percentage",
                                             self.progress,
                                             new_progress)

        new_speed_upload = {'upload': ds.get_current_speed('up')}
        self.speed_upload = self.print_on_change("speed-upload",
                                                 self.speed_upload,
                                                 new_speed_upload)

    def init_community(self, become_exitnode=None, no_crypto=None):
        become_exitnode = become_exitnode == 'exit'
        no_crypto = no_crypto == 'no_crypto'

        from Tribler.community.tunnel.tunnel_community import TunnelSettings
        tunnel_settings = TunnelSettings()

        tunnel_settings.become_exitnode = become_exitnode
        logging.error("This peer is exit node: %s" % ('Yes' if become_exitnode else 'No'))

        tunnel_settings.socks_listen_ports = [23000 + (10 * self.scenario_runner._peernumber) + i for i in range(5)]

        tunnel_settings.max_traffic = 1024 * 1024 * 1024 * 1024

        tunnel_settings.min_circuits = 3
        tunnel_settings.max_circuits = 5

        logging.error("My wan address is %s" % repr(self._dispersy._wan_address[0]))

        logging.error("Crypto on tunnels: %s" % ('Disabled' if no_crypto else 'Enabled'))
        if no_crypto:
            from Tribler.community.tunnel.crypto.tunnelcrypto import NoTunnelCrypto
            tunnel_settings.crypto = NoTunnelCrypto()

        self.set_community_kwarg('tribler_session', self.session)
        self.set_community_kwarg('settings', tunnel_settings)

    def registerCallbacks(self):
        super(BBQNakedClient, self).registerCallbacks()
        self.scenario_runner.register(self.collect_peers, 'collect_peers')
        self.scenario_runner.register(self.start_download, 'start_download')
        self.scenario_runner.register(self.init_community, 'init_community')

    def collect_peers(self):
        def wait_for_members():
            candidates = threads.blockingCallFromThread(reactor, self.dcs.start)
            self.candidate_ips = [c.sock_addr[0] for c in candidates]
            logging.critical("GOT CANDIDATE IPS: " + str(self.candidate_ips))

        reactor.callInThread(wait_for_members)

    def setup_session_config(self):
        config = super(BBQNakedClient, self).setup_session_config()

        config.set_tunnel_community_enabled(False)

        return config

    def create_test_torrent(self, filename=''):
        from Tribler.Core.TorrentDef import TorrentDefNoMetainfo
        tdef = TorrentDefNoMetainfo(self.download_infohash, filename)
        return tdef

    def fake_create_introduction_point(self, info_hash):
        logging.error("Fake creating introduction points, to prevent this download from messing other experiments")
        pass

    def update_seed_peers(self):
        if self.download:
            for seeder, port in self.seeders.iteritems():
                addr = (seeder.sock_addr[0], port)
                logging.critical("ADDING PEER TO DOWNLOAD: " + str(addr))
                self.download.add_peer(addr)

    def seeder_registered(self, value_dict):
        self.seeders = value_dict
        self.update_seed_peers()

    def infohash_updated(self, value_dict):
        self.download_infohash = value_dict.values()[0].decode("HEX")

    def start_download(self, filename, hops=1):
        hops = int(hops)
        self.annotate('start downloading %d hop(s)' % hops)
        from Tribler.Core.DownloadConfig import DefaultDownloadStartupConfig
        defaultDLConfig = DefaultDownloadStartupConfig.getInstance()
        dscfg = defaultDLConfig.copy()
        dscfg.set_hops(hops)
        dscfg.set_dest_dir(path.join(BASE_DIR, 'tribler', 'download-%s-%d' % (self.session.get_dispersy_port(), hops)))

        def cb_start_download():
            from Tribler.Core.simpledefs import dlstatus_strings
            tdef = self.create_test_torrent(filename)

            def cb(ds):
                logging.error('Download infohash=%s, hops=%d, down=%s, up=%d, progress=%s, status=%s, peers=%s, cand=%d' %
                              (tdef.get_infohash().encode('hex')[:5],
                               hops,
                               ds.get_current_speed('down'),
                               ds.get_current_speed('up'),
                               ds.get_progress(),
                               dlstatus_strings[ds.get_status()],
                               sum(ds.get_num_seeds_peers()),
                               sum(1 for _ in self._community.dispersy_yield_verified_candidates())))

                self.log_progress_stats(ds)

                return 1.0, False

            self.download = self.session.start_download_from_tdef(tdef, dscfg)
            self.download.set_state_callback(cb)
            self.update_seed_peers()

        reactor.callInThread(cb_start_download)

if __name__ == '__main__':
    BBQNakedClient.scenario_file = environ.get('SCENARIO_FILE', 'bbq_tunnel_pooled.scenario')
    main(BBQNakedClient)