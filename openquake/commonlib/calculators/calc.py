#  -*- coding: utf-8 -*-
#  vim: tabstop=4 shiftwidth=4 softtabstop=4

#  Copyright (c) 2014, GEM Foundation

#  OpenQuake is free software: you can redistribute it and/or modify it
#  under the terms of the GNU Affero General Public License as published
#  by the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

#  OpenQuake is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.

#  You should have received a copy of the GNU Affero General Public License
#  along with OpenQuake.  If not, see <http://www.gnu.org/licenses/>.

import collections
import itertools
import operator
import random

import numpy

from openquake.hazardlib.calc import gmf, filters
from openquake.hazardlib.site import SiteCollection
from openquake.baselib.general import AccumDict
from openquake.commonlib.readinput import \
    get_gsim, get_rupture, get_correl_model, get_imts


MAX_INT = 2 ** 31 - 1  # this is used in the random number generator
# in this way even on 32 bit machines Python will not have to convert
# the generated seed into a long integer

############### utilities for the classical calculator ################

SourceRuptureSites = collections.namedtuple(
    'SourceRuptureSites',
    'source rupture sites')


def gen_ruptures(sources, site_coll, maximum_distance, monitor):
    """
    Yield (source, rupture, affected_sites) for each rupture
    generated by the given sources.

    :param sources: a sequence of sources
    :param site_coll: a SiteCollection instance
    :param maximum_distance: the maximum distance
    :param monitor: a Monitor object
    """
    filtsources_mon = monitor.copy('filtering sources')
    genruptures_mon = monitor.copy('generating ruptures')
    filtruptures_mon = monitor.copy('filtering ruptures')
    for src in sources:
        with filtsources_mon:
            s_sites = src.filter_sites_by_distance_to_source(
                maximum_distance, site_coll)
            if s_sites is None:
                continue

        with genruptures_mon:
            ruptures = list(src.iter_ruptures())
        if not ruptures:
            continue

        for rupture in ruptures:
            with filtruptures_mon:
                r_sites = filters.filter_sites_by_distance_to_rupture(
                    rupture, maximum_distance, s_sites)
                if r_sites is None:
                    continue
            yield SourceRuptureSites(src, rupture, r_sites)
    filtsources_mon.flush()
    genruptures_mon.flush()
    filtruptures_mon.flush()


def gen_ruptures_for_site(site, sources, maximum_distance, monitor):
    """
    Yield source, <ruptures close to site>

    :param site: a Site object
    :param sources: a sequence of sources
    :param monitor: a Monitor object
    """
    source_rupture_sites = gen_ruptures(
        sources, SiteCollection([site]), maximum_distance, monitor)
    for src, rows in itertools.groupby(
            source_rupture_sites, key=operator.attrgetter('source')):
        yield src, [row.rupture for row in rows]


############### utilities for the scenario calculators ################


def calc_gmfs_fast(oqparam, sitecol):
    """
    Build all the ground motion fields for the whole site collection in
    a single step.
    """
    max_dist = oqparam.maximum_distance
    correl_model = get_correl_model(oqparam)
    seed = getattr(oqparam, 'random_seed', 42)
    imts = get_imts(oqparam)
    gsim = get_gsim(oqparam)
    trunc_level = getattr(oqparam, 'truncation_level', None)
    n_gmfs = getattr(oqparam, 'number_of_ground_motion_fields', 1)
    rupture = get_rupture(oqparam)
    res = gmf.ground_motion_fields(
        rupture, sitecol, imts, gsim,
        trunc_level, n_gmfs, correl_model,
        filters.rupture_site_distance_filter(max_dist), seed)
    return {str(imt): matrix for imt, matrix in res.iteritems()}


def calc_gmfs(oqparam, sitecol):
    """
    Build all the ground motion fields for the whole site collection
    """
    correl_model = get_correl_model(oqparam)
    rnd = random.Random()
    rnd.seed(getattr(oqparam, 'random_seed', 42))
    imts = get_imts(oqparam)
    gsim = get_gsim(oqparam)
    trunc_level = getattr(oqparam, 'truncation_level', None)
    n_gmfs = getattr(oqparam, 'number_of_ground_motion_fields', 1)
    rupture = get_rupture(oqparam)
    computer = gmf.GmfComputer(rupture, sitecol, imts, gsim, trunc_level,
                               correl_model)
    seeds = [rnd.randint(0, MAX_INT) for _ in xrange(n_gmfs)]
    res = AccumDict()  # imt -> gmf
    for seed in seeds:
        for imt, gmfield in computer.compute(seed):
            res += {imt: [gmfield]}
    # res[imt] is a matrix R x N
    return {imt: numpy.array(matrix).T for imt, matrix in res.iteritems()}
