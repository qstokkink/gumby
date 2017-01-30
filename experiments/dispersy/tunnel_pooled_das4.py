#!/usr/bin/env python2

import logging

from os import path
from sys import path as pythonpath

from hiddenservices_client import HiddenServicesClient
from gumby.experiments.dispersyclient import main
from gumby.experiments.TriblerDispersyClient import BASE_DIR
from posix import environ


# TODO(emilon): Fix this crap
pythonpath.append(path.abspath(path.join(path.dirname(__file__), '..', '..', '..', "./tribler")))


class PoooledTunnelClient(HiddenServicesClient):

    def __init__(self, *argv, **kwargs):
        from Tribler.community.tunnel.pooled_tunnel_community import PooledTunnelCommunity
        super(PoooledTunnelClient, self).__init__(*argv, **kwargs)
        self.community_class = PooledTunnelCommunity

    def remove_download(self):
        from Tribler.Core.TorrentDef import TorrentDef
        tdef = TorrentDef()
        tdef_file = path.join(BASE_DIR, "output", "gen.torrent")
        if path.isfile(tdef_file):
            f_tdef = TorrentDef.load(tdef_file)
            infohash = f_tdef.get_infohash()
            if self.session.has_download(infohash):
                self.session.get_download(infohash).set_state_callback(lambda: None)
                self.session.remove_download_by_id(infohash, True, True)
            else:
                logging.error("Infohash not found: previous experiment seems to have crashed")
        else:
            logging.error("No torrent file to clean")

    def init_community(self, worker_count=-1, become_exitnode=None, no_crypto=None):
        if become_exitnode != 'not_exit':
            from Tribler.community.tunnel.hidden_community import HiddenTunnelCommunity
            self.community_class = HiddenTunnelCommunity
        super(PoooledTunnelClient, self).init_community(become_exitnode, no_crypto)
        if become_exitnode == 'not_exit':
            self.community_kwargs['settings'].workers = int(worker_count)

    def introduce_candidates(self):
        from twisted.internet import reactor, threads
        for member in threads.blockingCallFromThread(reactor, self.dcs.start):
            self.session.lm.tunnel_community.add_discovered_candidate(member.candidate)
            logging.error("Adding community member %s:%d" % (member.candidate.sock_addr[0], member.candidate.sock_addr[1]))

    def prepare_context(self, worker_count, hops=1):
        self.annotate('setup %s process(es)' % worker_count)
        # Remove previous download if it exists
        self.remove_download()
        # Set processes and circuits
        single_p_min_circuits = 3
        single_p_max_circuits = 5
        if hasattr(self._community, 'pool'):
            self._community.pool.set_worker_count(int(worker_count))
            self._community.settings.min_circuits = single_p_min_circuits*int(worker_count)
            self._community.settings.max_circuits = single_p_max_circuits*int(worker_count)
        # Create/assert circuits for hop count
        self._community.build_tunnels(int(hops))

    def registerCallbacks(self):
        super(PoooledTunnelClient, self).registerCallbacks()
        self.scenario_runner.register(self.prepare_context, 'prepare_context')
        self.scenario_runner.register(self.remove_download, 'remove_download')

if __name__ == '__main__':
    PoooledTunnelClient.scenario_file = environ.get('SCENARIO_FILE', 'pooled_tunnel_das4.scenario')
    main(PoooledTunnelClient)
