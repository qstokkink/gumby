from pony.orm import db_session, count

from ipv8 import community

from gumby.experiment import experiment_callback
from gumby.modules.community_experiment_module import IPv8OverlayExperimentModule
from gumby.modules.experiment_module import static_module

from tribler_core.modules.popularity.popularity_community import PopularityCommunity


REAL_BOOTSTRAP_SERVERS = community._DEFAULT_ADDRESSES


@static_module
class WildPopularityModule(IPv8OverlayExperimentModule):

    def __init__(self, experiment):
        super(WildPopularityModule, self).__init__(experiment, PopularityCommunity)

    def on_id_received(self):
        super(WildPopularityModule, self).on_id_received()

        self.tribler_config.set_tunnel_community_enabled(False)
        self.tribler_config.set_trustchain_enabled(False)
        self.tribler_config.set_market_community_enabled(False)
        self.tribler_config.set_bootstrap_enabled(False)

        self.tribler_config.set_popularity_community_enabled(True)
        self.tribler_config.set_torrent_checking_enabled(True)
        self.tribler_config.set_ipv8_enabled(True)
        self.tribler_config.set_libtorrent_enabled(True)
        self.tribler_config.set_dht_enabled(True)
        self.tribler_config.set_chant_enabled(True)

        self.autoplot_create("total_torrents", "total")
        self.autoplot_create("alive_torrents", "alive")

    @experiment_callback
    def start_check(self, interval):
        community._DEFAULT_ADDRESSES.extend(REAL_BOOTSTRAP_SERVERS)
        self.session.popularity_community.register_task("check", self.check, interval=float(interval))

    @db_session
    def get_torrents_info_tuple(self):
        return count(ts for ts in self.session.mds.TorrentState), \
               count(ts for ts in self.session.mds.TorrentState if ts.seeders > 0)

    def check(self):
        torrents_total, torrents_with_seeders = self.get_torrents_info_tuple()

        self.autoplot_add_point("total_torrents", torrents_total)
        self.autoplot_add_point("alive_torrents", torrents_with_seeders)
