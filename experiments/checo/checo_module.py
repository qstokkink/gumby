from binascii import unhexlify
from hashlib import sha256
from random import choice, randint, seed
import math
import struct
import time

import networkx as nx

from twisted.internet.task import LoopingCall

from gumby.experiment import experiment_callback
from gumby.modules.community_experiment_module import IPv8OverlayExperimentModule
from gumby.modules.community_launcher import IPv8CommunityLauncher
from gumby.modules.experiment_module import static_module

from Tribler.pyipv8.ipv8.community import Community, DEFAULT_MAX_PEERS
from Tribler.pyipv8.ipv8.lazy_community import lazy_wrapper
from Tribler.pyipv8.ipv8.messaging.lazy_payload import VariablePayload
from Tribler.pyipv8.ipv8.peer import Peer
from Tribler.pyipv8.ipv8.peerdiscovery.discovery import RandomWalk


def d(id, i, T):
    seed((id << 32) + i)  # 64 bits
    prng = randint(0, 4294967294)  # 64 bits
    rh = sha256(T).digest()[-8:]
    h = struct.unpack(">Q", rh)[0]
    diff = prng ^ h
    return len([x for x in bin(diff) if x == '1'])


def tt(D, t):
    return t * (64 - D)


def f(id, i, D, T, t):
    return d(id, i, T) < tt(D, t)


class TransactionPayload(VariablePayload):

    format_list = ['I', '74s', '74s', 'B']
    names = ['round', 'partya', 'partyb', 'weight']


class ChecoCommunity(Community):

    master_peer = Peer(unhexlify("4c69624e61434c504b3a77b9bdc445f07b8bac1905da102d421bb8224fd2f4b3908c59917"
                                 "aa2bde6007c89b302315c5657ec0ff2ed74277b0434144f53877fd1996da6caf41d446d9a32"))

    def __init__(self, my_peer, endpoint, network, max_peers=DEFAULT_MAX_PEERS):
        super(ChecoCommunity, self).__init__(my_peer, endpoint, network, max_peers)
        self.add_message_handler(1, self.on_transaction)

        self.transactions = {}
        self.scores = {}
        print "Started with", my_peer

    def send_transaction_to(self, round, weight, facilitator, counterparty):
        payload = TransactionPayload(round, self.my_peer.public_key.key_to_bin(),
                                     counterparty.public_key.key_to_bin(), weight)
        self.endpoint.send(counterparty.address, self.ezr_pack(1,payload))
        self.endpoint.send(facilitator.address, self.ezr_pack(1,payload))

    @lazy_wrapper(TransactionPayload)
    def on_transaction(self, peer, payload):
        newdict = self.transactions.get(payload.round, {})
        newdict[(payload.partya, payload.partyb)] = payload.weight
        self.transactions[payload.round] = newdict

    def calculate_scores(self):
        G = nx.DiGraph()
        nodes = set()

        for round, items in self.transactions.items():
            for peers, weight in self.transactions[round].items():
                pubkey_requester, pubkey_responder = peers

                G.add_edge(pubkey_requester, pubkey_responder, contribution=weight)
                G.add_edge(pubkey_responder, pubkey_requester, contribution=weight)

                nodes.add(pubkey_requester)
                nodes.add(pubkey_responder)

            try:
                result = nx.pagerank_scipy(G, weight='contribution')
            except nx.NetworkXException:
                self._logger.info("Empty Temporal PageRank, returning empty scores")
                print "No nodes with exception"
                continue

            sums = {}
            ncount = len(G.nodes())/2

            for interaction in result.keys():
                sums[interaction] = min((sums.get(interaction, 0) + result[interaction]) * ncount, 1.0)

            self.scores[round] = sums

    def deduplicate(self):
        self.calculate_scores()
        my_key = self.my_peer.public_key.key_to_bin()
        output = {}

        for round, items in self.transactions.items():
            replicas = 0

            for peers, weight in self.transactions[round].items():
                pubkey_requester, pubkey_responder = peers

                if pubkey_requester == my_key or pubkey_responder == my_key:
                    replicas += 1
                    continue

                aid = struct.unpack(">I", pubkey_requester[-4:])[0]
                H = 64
                Nl = len(items)
                D = min(0.0, math.ceil(H * math.sqrt(2/Nl) - 1))
                should_drop = f(aid, round, D, pubkey_requester + pubkey_responder + str(weight),
                                self.scores[round].get(my_key, 0.0))

                if not should_drop:
                    replicas += 1
                    continue

            output[round] = (replicas, len(items))

        return output


class ChecoCommunityLauncher(IPv8CommunityLauncher):

    def get_overlay_class(self):
        return ChecoCommunity

    def get_my_peer(self, ipv8, session):
        return Peer(session.trustchain_keypair)

    def get_walk_strategies(self):
        return [(RandomWalk, {'timeout': 1.0}, -1)]

    def get_kwargs(self, session):
        return {}


@static_module
class ChecoModule(IPv8OverlayExperimentModule):

    def __init__(self, experiment):
        super(ChecoModule, self).__init__(experiment, ChecoCommunity)
        self._overlay = None
        self.total_nodes = 1
        self.facilitator_count = 1
        self.max_rounds = 1
        self.transactions_lc = None
        self.round = 0
        self.round_timestamps = {}
        self.ipv8_community_loader.set_launcher(ChecoCommunityLauncher())

    def on_id_received(self):
        super(ChecoModule, self).on_id_received()
        self.tribler_config.set_popularity_community_enabled(False)
        self.tribler_config.set_trustchain_enabled(False)

        self.autoplot_create("replicas")
        self.autoplot_create("items")

    @experiment_callback
    def set_node_count(self, total_nodes, facilitator_count, max_rounds):
        self.total_nodes = int(total_nodes)
        self.facilitator_count = int(facilitator_count)
        self.max_rounds = int(max_rounds)

    def on_ipv8_available(self, ipv8):
        super(ChecoModule, self).on_ipv8_available(ipv8)

    def get_facilitator_ids(self, round):
        base = round*self.facilitator_count
        return [(i % self.total_nodes) + 1 for i in xrange(base, base + self.facilitator_count)]

    def get_facilitators(self, round):
        return [self.get_peer(str(i)) for i in self.get_facilitator_ids(round)]

    def get_random_counterparty(self):
        counterparty = self.my_id
        while counterparty == self.my_id:
            counterparty = str(randint(1, self.total_nodes))
        return self.get_peer(counterparty)

    def transact(self):
        if self.round >= self.max_rounds:
            return
        self.round_timestamps[self.round] = time.time()
        facilitator = choice(self.get_facilitators(self.round))
        weight = randint(0, 255)
        counterparty = self.get_random_counterparty()
        self.overlay.send_transaction_to(self.round, weight, facilitator, counterparty)
        self.round += 1

    @experiment_callback
    def start_transactions(self, rate):
        self.transactions_lc = LoopingCall(self.transact)
        self.transactions_lc.start(float(rate), True)

    @experiment_callback
    def stop_transactions(self):
        print "STOPPING TRANSACTIONS AT ROUND", self.round
        self.transactions_lc.stop()

    @experiment_callback
    def deduplicate(self):
        replicas = self.overlay.deduplicate()

        for round, value in replicas.items():
            replicas, items = value
            with open('autoplot/replicas.csv', 'a') as output_file:
                output_file.write("%f,%d,%d\n" % (self.round_timestamps[round], self.my_id, replicas))
            with open('autoplot/items.csv', 'a') as output_file:
                output_file.write("%f,%d,%d\n" % (self.round_timestamps[round], self.my_id, items))
