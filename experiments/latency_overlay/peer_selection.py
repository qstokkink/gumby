from __future__ import division

import math
from collections import namedtuple
from random import shuffle


Option = namedtuple('Option', ['value', 'obj'])
ReferenceFuncPoint = namedtuple('ReferenceFuncPoint', ['x', 'y'])


def unweigthed_pdf(x, X, bandwidth):
    return sum((math.sqrt(2*math.pi*bandwidth**2)**-1) * math.exp(-((x - x_i)**2)/(2*bandwidth**2)) for x_i in X)


def weighted_pdf(x, X, falloff):
    return unweigthed_pdf(x, X, falloff)/unweigthed_pdf(x, [x], falloff)


def get_error(references, included, option, falloff=0.2):
    errors = []
    for i in range(len(references)):
        x, y = references[i]
        d = weighted_pdf(x, included + ([option.value] if option is not None else []), falloff)
        e = y - d
        if d > y:
            e *= -2
        errors.append(e)
    return sum(errors)


def optimal_choice(references, included, options, falloff=0.2):
    best_option = None
    best_mse = None
    for option in [None] + options:
        mse = get_error(references, included, option, falloff)
        if best_mse is None or mse < best_mse or (best_option is None and mse == best_mse):
            best_option = option
            best_mse = mse
    return best_option


def generate_reference(func, x_coords, peer_count):
    modifier = peer_count/sum(func(x) for x in x_coords)
    return [ReferenceFuncPoint(x, modifier * func(x)) for x in x_coords]


class PeerSelector(object):

    def __init__(self, reference_points, included=None):
        if not included:
            self.included = []
            self._included_values = []
        else:
            self.included = included
            self._included_values = [option.value for option in included]
        self.reference = reference_points

    def decide(self, options):
        shuffle(options)
        choice = optimal_choice(self.reference, self._included_values, options)
        if choice is not None:
            self.included.append(choice)
            self._included_values.append(choice.value)
        return choice

    def current_worst(self):
        current_worst = None
        current_worst_mse = None
        for option in self.included:
            if option is None:
                continue
            values = [self.included[i].value for i in range(len(self.included))
                      if (i != self.included.index(option) and option is not None)]
            mse = get_error(self.reference, values, option)
            if current_worst is None or mse > current_worst_mse:
                current_worst = option
                current_worst_mse = mse
        return current_worst
