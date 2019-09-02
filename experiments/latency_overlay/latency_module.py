import os
from socket import gethostbyname

from twisted.internet.task import LoopingCall

from experiments.latency_overlay.community import LatencyCommunity
from experiments.latency_overlay.custom_walk import CustomWalk
from experiments.latency_overlay.random_walk import CustomRandomWalk
from gumby.experiment import experiment_callback
from gumby.modules.community_launcher import IPv8CommunityLauncher
from gumby.modules.community_experiment_module import IPv8OverlayExperimentModule
from gumby.modules.experiment_module import static_module


class IPv8DiscoveryCommunityLauncher(IPv8CommunityLauncher):

    def get_overlay_class(self):
        return LatencyCommunity

    def should_launch(self, session):
        return True

    def get_my_peer(self, ipv8, session):
        from ipv8.peer import Peer
        return Peer(session.trustchain_keypair)

    def get_kwargs(self, session):
        return {}

    def get_walk_strategies(self):
        return []


@static_module
class LatencyModule(IPv8OverlayExperimentModule):
    """
    This module contains code to manage experiments with the channels2 community.
    """

    def __init__(self, experiment):
        super(LatencyModule, self).__init__(experiment, LatencyCommunity)
        self.strategies['CustomWalk'] = CustomWalk
        self.strategies['CustomRandomWalk'] = CustomRandomWalk
        self.ipv8_community_loader.set_launcher(IPv8DiscoveryCommunityLauncher())
        self.head_host = '0.0.0.0'

    def on_id_received(self):
        super(LatencyModule, self).on_id_received()
        self.tribler_config.set_ipv8_discovery(False)
        self.tribler_config.set_trustchain_enabled(False)
        self.autoplot_create("ancestors")
        self.autoplot_create("peers")
        self.autoplot_create("partners")

        base_tracker_port = int(os.environ['TRACKER_PORT'])
        self.head_host = gethostbyname(os.environ['HEAD_HOST']) if 'HEAD_HOST' in os.environ else "127.0.0.1"
        port_range = range(base_tracker_port, base_tracker_port + 4)
        print "Using head host", self.head_host, port_range
        from ipv8 import community
        community._DEFAULT_ADDRESSES = [(self.head_host, port) for port in port_range]

    def on_ipv8_available(self, ipv8_instance):
        base_tracker_port = int(os.environ['TRACKER_PORT'])
        port_range = range(base_tracker_port, base_tracker_port + 4)
        for port in port_range:
            self.overlay.network.blacklist.append(("10.0.2.15", port))
            self.overlay.network.blacklist.append((self.head_host, port))
        LoopingCall(self.write_channels).start(5.0, True)

    @experiment_callback
    def dump_peer_graph(self):
        reverse_ids = {}
        for peer_id in self.all_vars:
            reverse_ids[self.all_vars[str(peer_id)]['port']] = peer_id
        with open("ancestry_%d.csv" % self.my_id, 'w') as f:
            f.write('ancestor,node,ping\n')
            for strategy_desc in self.ipv8.strategies:
                strategy, target_peers = strategy_desc
                if isinstance(strategy, CustomWalk):
                    ancestry = strategy.get_ancestry()
                    for ancestor in ancestry:
                        ancestor_id = reverse_ids[ancestor.address[1]]
                        node_id = reverse_ids[ancestry[ancestor].address[1]]
                        ping_time = str(ancestry[ancestor].get_median_ping() or '')
                        f.write(str(ancestor_id) + ',' + str(node_id) + ',' + ping_time + '\n')

    def write_channels(self):
        """
        Write information about all discovered channels away.
        """
        if self.overlay:
            self.autoplot_add_point("ancestors", len(self.overlay.peer_ranking))
            self.autoplot_add_point("peers", len(self.overlay.get_peers()))
            self.autoplot_add_point("partners", len(self.overlay.accepted_proposals))
        else:
            self.autoplot_add_point("ancestors", 0)
            self.autoplot_add_point("peers", 0)
            self.autoplot_add_point("partners", 0)
