import time

from ipv8.peerdiscovery.discovery import DiscoveryStrategy


MAX_ROOTS = 30
MAX_EDGE_LENGTH = 6
MAX_SIMILARITY = 0.05
NODE_TIMEOUT = 5.0
STEP_DELAY = 0.1
GC_DELAY = 10.0


class CustomWalk(DiscoveryStrategy):

    def __init__(self, overlay):
        super(CustomWalk, self).__init__(overlay)

        self.roots = []
        self.ping_times = {}
        self.last_step = 0.0
        self.last_gc = 0.0

        self.ancestry = {} # Peer introduced by Peer (or None)
        self.leaves = [] # Current edges' HEAD Peer objects

        overlay.max_peers = MAX_ROOTS * MAX_EDGE_LENGTH

    def get_ancestry(self):
        return self.ancestry

    def get_root_address(self):
        self.overlay.bootstrap()
        for address in self.overlay.get_walkable_addresses():
            introducer, service = self.overlay.network._all_addresses[address]
            if introducer not in [p.mid for p in self.overlay.network.verified_peers] and address not in self.roots:
                # Bootstrapped peer, not in use
                self.roots.append(address)
                return
        self.roots = [root for root in self.roots if root in self.overlay.network._all_addresses]
        return

    def do_ping(self, address):
        if address not in self.ping_times:
            self.overlay.walk_to(address)
            self.ping_times[address] = (time.time(), None)
            return None
        elif not self.ping_times[address][1]:
            rootp = self.overlay.network.get_verified_by_address(address)
            if rootp:
                self.ping_times[address] = (self.ping_times[address][0], time.time())
                self.leaves.append(rootp)
            elif time.time() - self.ping_times[address][0] > NODE_TIMEOUT:
                # Check for unreachable
                if address in self.roots:
                    self.roots.remove(address)
                self.ping_times.pop(address)
                self.leaves = [leaf for leaf in self.leaves if leaf.address != address]
                to_remove = None
                for key in self.ancestry:
                    if key.address == address:
                        to_remove = key
                        if self.ancestry.get(key, None):
                            self.leaves.append(self.ancestry[key])
                if to_remove:
                    self.ancestry.pop(to_remove)
                self.overlay.network.remove_by_address(address)
                return None
            return rootp

    def get_granular_ping(self, peer):
        if not peer or not peer.pings or len(peer.pings) < peer.pings.maxlen:
            self.overlay.send_ping(peer)
            return None
        return peer.get_median_ping()

    def take_step(self):
        with self.walk_lock:
            # 1. Pick peer introduced by bootstrap
            if len(self.roots) < MAX_ROOTS:
                self.get_root_address()

            if time.time() - self.last_step < STEP_DELAY:
                return
            self.last_step = time.time()

            # Measure ping in roots, remove dead roots
            for root in self.roots:
                self.do_ping(root)

            # 2. For each edge < MAX_EDGE_LENGTH: grow edge based on last peer on edge
            removed_leafs = []
            for leaf in self.leaves:
                depth = 0
                previous = leaf
                leaf_pings = []
                while previous:
                    depth += 1
                    pingtime = self.get_granular_ping(previous)
                    previous = self.ancestry.get(previous, None)
                    if pingtime is None:
                        continue
                    leaf_pings.append(pingtime)
                if depth < MAX_EDGE_LENGTH:
                    self.overlay.send_introduction_request(leaf)

                # 3. On response: if MYKA allowed (<> MAX_SIMILARITY) add to edge
                introductions = self.overlay.network.get_introductions_from(leaf)
                for introduction in introductions:
                    ipeer = self.overlay.network.get_verified_by_address(introduction)
                    if ipeer and ipeer not in self.ancestry:
                        ipingtime = self.get_granular_ping(ipeer)
                        if ipingtime is None:
                            continue
                        unique = True
                        for ptime in leaf_pings:
                            if ptime - MAX_SIMILARITY <= ipingtime <= ptime + MAX_SIMILARITY:
                                unique = False
                                break
                        if unique:
                            removed_leafs.append(leaf)
                            self.leaves.append(ipeer)
                            self.ancestry[ipeer] = leaf
                            for other_intro in introductions:
                                if other_intro != introduction:
                                    self.overlay.network.remove_by_address(other_intro)
                    else:
                        if ipeer:
                            self.get_granular_ping(ipeer)
                        self.overlay.walk_to(introduction)
            self.leaves = [leaf for leaf in self.leaves if leaf not in removed_leafs]

            self.overlay.peer_ranking = [a[1] for a in sorted((self.get_granular_ping(p), p) for p in self.ancestry)]

            if time.time() - self.last_gc >= GC_DELAY:
                self.last_gc = time.time()
                to_remove = [peer for peer in self.overlay.get_peers() if peer not in self.ancestry]
                for peer in to_remove:
                    self.overlay.network.remove_peer(peer)
