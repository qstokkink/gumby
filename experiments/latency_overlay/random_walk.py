from ipv8.peerdiscovery.discovery import RandomWalk


MAX_ROOTS = 50
MAX_EDGE_LENGTH = 6


class CustomRandomWalk(RandomWalk):

    def __init__(self, overlay):
        super(CustomRandomWalk, self).__init__(overlay)
        overlay.max_peers = MAX_ROOTS * MAX_EDGE_LENGTH

    def get_granular_ping(self, peer):
        if not peer or not peer.pings or len(peer.pings) < peer.pings.maxlen:
            self.overlay.send_ping(peer)
            return None
        return peer.get_median_ping()

    def take_step(self):
        super(CustomRandomWalk, self).take_step()
        with self.walk_lock:
            self.overlay.peer_ranking = [a[1] for a in sorted((self.get_granular_ping(p), p)
                                                              for p in self.overlay.get_peers()
                                                              if self.get_granular_ping(p) is not None)]
