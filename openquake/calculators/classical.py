# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (C) 2014-2018 GEM Foundation
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake. If not, see <http://www.gnu.org/licenses/>.
import logging
import operator
import numpy

from openquake.baselib import parallel, hdf5, datastore
from openquake.baselib.python3compat import encode
from openquake.baselib.general import AccumDict
from openquake.hazardlib.contexts import FEWSITES
from openquake.hazardlib.calc.hazard_curve import classical, ProbabilityMap
from openquake.hazardlib.stats import compute_pmap_stats
from openquake.commonlib import calc, util
from openquake.calculators import getters
from openquake.calculators import base

U16 = numpy.uint16
U32 = numpy.uint32
F32 = numpy.float32
F64 = numpy.float64
weight = operator.attrgetter('weight')
grp_source_dt = numpy.dtype([('grp_id', U16), ('source_id', hdf5.vstr),
                             ('source_name', hdf5.vstr)])
source_data_dt = numpy.dtype(
    [('taskno', U16), ('nsites', U32), ('nruptures', U32), ('weight', F32)])


def get_src_ids(sources):
    """
    :returns:
       a string with the source IDs of the given sources, stripping the
       extension after the colon, if any
    """
    src_ids = []
    for src in sources:
        long_src_id = src.source_id
        try:
            src_id, ext = long_src_id.rsplit(':', 1)
        except ValueError:
            src_id = long_src_id
        src_ids.append(src_id)
    return ' '.join(set(src_ids))


@base.calculators.add('classical')
class ClassicalCalculator(base.HazardCalculator):
    """
    Classical PSHA calculator
    """
    core_task = classical
    accept_precalc = ['psha']

    def agg_dicts(self, acc, dic):
        """
        Aggregate dictionaries of hazard curves by updating the accumulator.

        :param acc: accumulator dictionary
        :param dic: dictionary with keys pmap, calc_times, eff_ruptures
        """
        with self.monitor('aggregate curves', autoflush=True):
            acc.eff_ruptures += dic['eff_ruptures']
            for grp_id, pmap in dic['pmap'].items():
                if pmap:
                    acc[grp_id] |= pmap
                self.nsites.append(len(pmap))
            for grp_id, data in dic['rup_data'].items():
                if len(data):
                    self.datastore.extend('rup/grp-%02d' % grp_id, data)
        self.calc_times += dic['calc_times']
        return acc

    def acc0(self):
        """
        Initial accumulator, a dict grp_id -> ProbabilityMap(L, G)
        """
        csm_info = self.csm.info
        zd = AccumDict()
        num_levels = len(self.oqparam.imtls.array)
        for grp in self.csm.src_groups:
            num_gsims = len(csm_info.gsim_lt.get_gsims(grp.trt))
            zd[grp.id] = ProbabilityMap(num_levels, num_gsims)
        zd.eff_ruptures = AccumDict()  # grp_id -> eff_ruptures
        return zd

    def execute(self):
        """
        Run in parallel `core_task(sources, sitecol, monitor)`, by
        parallelizing on the sources according to their weight and
        tectonic region type.
        """
        oq = self.oqparam
        if oq.hazard_calculation_id and not oq.compare_with_classical:
            parent = datastore.read(self.oqparam.hazard_calculation_id)
            self.csm_info = parent['csm_info']
            parent.close()
            self.calc_stats(parent)  # post-processing
            return {}
        with self.monitor('managing sources', autoflush=True):
            smap = parallel.Starmap(
                self.core_task.__func__, monitor=self.monitor())
            source_ids = []
            data = []
            for i, args in enumerate(self.gen_args()):
                smap.submit(*args)
                source_ids.append(get_src_ids(args[0]))
                for src in args[0]:  # collect source data
                    data.append((i, src.nsites, src.num_ruptures, src.weight))
            self.datastore['task_sources'] = encode(source_ids)
            self.datastore.extend(
                'source_data', numpy.array(data, source_data_dt))
        self.nsites = []
        self.calc_times = AccumDict(accum=numpy.zeros(3, F32))
        try:
            acc = smap.reduce(self.agg_dicts, self.acc0())
            self.store_rlz_info(acc.eff_ruptures)
        finally:
            with self.monitor('store source_info', autoflush=True):
                self.store_source_info(self.calc_times)
            self.calc_times.clear()  # save a bit of memory
        if not self.nsites:
            raise RuntimeError('All sources were filtered out!')
        logging.info('Effective sites per task: %d', numpy.mean(self.nsites))
        return acc

    def gen_args(self):
        """
        Used in the case of large source model logic trees.
        :yields: (sources, sites, gsims) triples
        """
        oq = self.oqparam
        opt = self.oqparam.optimize_same_id_sources
        param = dict(
            truncation_level=oq.truncation_level, imtls=oq.imtls,
            filter_distance=oq.filter_distance, reqv=oq.get_reqv(),
            pointsource_distance=oq.pointsource_distance)
        num_tasks = 0
        num_sources = 0

        if self.csm.has_dupl_sources and not opt:
            logging.warning('Found %d duplicated sources',
                            self.csm.has_dupl_sources)

        for trt, sources in self.csm.get_trt_sources():
            gsims = self.csm.info.gsim_lt.get_gsims(trt)
            num_sources += len(sources)
            if hasattr(sources, 'atomic') and sources.atomic:
                yield sources, self.src_filter, gsims, param
                num_tasks += 1
            else:  # regroup the sources in blocks
                for block in self.block_splitter(sources):
                    yield block, self.src_filter, gsims, param
                    num_tasks += 1
        logging.info('Sent %d sources in %d tasks', num_sources, num_tasks)

    def save_hazard_stats(self, acc, pmap_by_kind):
        """
        Works by side effect by saving statistical hcurves and hmaps on the
        datastore.

        :param acc: ignored
        :param pmap_by_kind: a dictionary of ProbabilityMaps

        kind can be ('hcurves', 'mean'), ('hmaps', 'mean'),  ...
        """
        with self.monitor('saving statistics', autoflush=True):
            for kind in pmap_by_kind:  # i.e. kind == 'hcurves-stats'
                pmaps = pmap_by_kind[kind]
                if kind == 'rlz_by_sid':  # pmaps is actually a rlz_by_sid
                    for sid, rlz in pmaps.items():
                        self.datastore['best_rlz'][sid] = rlz
                elif kind in ('hmaps-rlzs', 'hmaps-stats'):
                    # pmaps is a list of R pmaps
                    dset = self.datastore.getitem(kind)
                    for r, pmap in enumerate(pmaps):
                        for s in pmap:
                            dset[s, r] = pmap[s].array  # shape (M, P)
                elif kind in ('hcurves-rlzs', 'hcurves-stats'):
                    dset = self.datastore.getitem(kind)
                    for r, pmap in enumerate(pmaps):
                        for s in pmap:
                            dset[s, r] = pmap[s].array[:, 0]  # shape L
            self.datastore.flush()

    def post_execute(self, pmap_by_grp_id):
        """
        Collect the hazard curves by realization and export them.

        :param pmap_by_grp_id:
            a dictionary grp_id -> hazard curves
        """
        oq = self.oqparam
        csm_info = self.datastore['csm_info']
        trt_by_grp = csm_info.grp_by("trt")
        grp_source = csm_info.grp_by("name")
        if oq.disagg_by_src:
            src_name = {src.src_group_id: src.name
                        for src in self.csm.get_sources()}
        data = []
        with self.monitor('saving probability maps', autoflush=True):
            for grp_id, pmap in pmap_by_grp_id.items():
                if pmap:  # pmap can be missing if the group is filtered away
                    base.fix_ones(pmap)  # avoid saving PoEs == 1
                    key = 'poes/grp-%02d' % grp_id
                    self.datastore[key] = pmap
                    self.datastore.set_attrs(key, trt=trt_by_grp[grp_id])
                    if oq.disagg_by_src:
                        data.append(
                            (grp_id, grp_source[grp_id], src_name[grp_id]))
                    if 'rup' in set(self.datastore):
                        self.datastore.set_nbytes('rup/grp-%02d' % grp_id)
        if oq.hazard_calculation_id is None and 'poes' in self.datastore:
            self.datastore.set_nbytes('poes')
            if oq.disagg_by_src and csm_info.get_num_rlzs() == 1:
                # this is useful for disaggregation, which is implemented
                # only for the case of a single realization
                self.datastore['disagg_by_src/source_id'] = numpy.array(
                    sorted(data), grp_source_dt)

            # save a copy of the poes in hdf5cache
            with hdf5.File(self.hdf5cache) as cache:
                cache['oqparam'] = oq
                self.datastore.hdf5.copy('poes', cache)
            self.calc_stats(self.hdf5cache)

    def calc_stats(self, parent):
        oq = self.oqparam
        hstats = oq.hazard_stats()
        # initialize datasets
        N = len(self.sitecol.complete)
        L = len(oq.imtls.array)
        P = len(oq.poes)
        M = len(oq.imtls)
        R = len(self.rlzs_assoc.realizations)
        S = len(hstats)
        if R > 1 and oq.individual_curves or not hstats:
            self.datastore.create_dset('hcurves-rlzs', F32, (N, R, L))
            if oq.poes:
                self.datastore.create_dset('hmaps-rlzs', F32, (N, R, M, P))
        if hstats:
            self.datastore.create_dset('hcurves-stats', F32, (N, S, L))
            if oq.poes:
                self.datastore.create_dset('hmaps-stats', F32, (N, S, M, P))
        if 'mean' in dict(hstats) and R > 1 and N <= FEWSITES:
            self.datastore.create_dset('best_rlz', U32, (N,))
        logging.info('Building hazard statistics')
        ct = oq.concurrent_tasks
        iterargs = (
            (getters.PmapGetter(parent, self.rlzs_assoc, t.sids, oq.poes),
             N, hstats, oq.individual_curves)
            for t in self.sitecol.split_in_tiles(ct))
        parallel.Starmap(build_hazard_stats, iterargs, self.monitor()).reduce(
            self.save_hazard_stats)


@base.calculators.add('preclassical')
class PreCalculator(ClassicalCalculator):
    """
    Calculator to filter the sources and compute the number of effective
    ruptures
    """
    def execute(self):
        eff_ruptures = AccumDict(accum=0)
        calc_times = AccumDict(accum=numpy.zeros(3, F32))  # w, n, t
        for src in self.csm.get_sources():
            for grp_id in src.src_group_ids:
                eff_ruptures[grp_id] += src.num_ruptures
                calc_times[src.id] += numpy.array(
                    [src.weight, src.nsites, 0], F32)
        self.store_rlz_info(eff_ruptures)
        self.store_source_info(calc_times)
        return {}


def build_hazard_stats(pgetter, N, hstats, individual_curves, monitor):
    """
    :param pgetter: an :class:`openquake.commonlib.getters.PmapGetter`
    :param N: the total number of sites
    :param hstats: a list of pairs (statname, statfunc)
    :param individual_curves: if True, also build the individual curves
    :param monitor: instance of Monitor
    :returns: a dictionary kind -> ProbabilityMap

    The "kind" is a string of the form 'rlz-XXX' or 'mean' of 'quantile-XXX'
    used to specify the kind of output.
    """
    with monitor('combine pmaps'):
        pgetter.init()  # if not already initialized
        try:
            pmaps = pgetter.get_pmaps()
        except IndexError:  # no data
            return {}
        if sum(len(pmap) for pmap in pmaps) == 0:  # no data
            return {}
    R = len(pmaps)
    imtls, poes, weights = pgetter.imtls, pgetter.poes, pgetter.weights
    pmap_by_kind = {}
    hmaps_stats = []
    hcurves_stats = []
    with monitor('compute stats'):
        for statname, stat in hstats.items():
            pmap = compute_pmap_stats(pmaps, [stat], weights, imtls)
            hcurves_stats.append(pmap)
            if pgetter.poes:
                hmaps_stats.append(
                    calc.make_hmap(pmap, pgetter.imtls, pgetter.poes))
            if statname == 'mean' and R > 1 and N <= FEWSITES:
                pmap_by_kind['rlz_by_sid'] = rlz = {}
                for sid, pcurve in pmap.items():
                    rlz[sid] = util.closest_to_ref(
                        [pm[sid].array for pm in pmaps], pcurve.array)['rlz']
    if hcurves_stats:
        pmap_by_kind['hcurves-stats'] = hcurves_stats
    if hmaps_stats:
        pmap_by_kind['hmaps-stats'] = hmaps_stats
    if R > 1 and individual_curves or not hstats:
        pmap_by_kind['hcurves-rlzs'] = pmaps
        if pgetter.poes:
            with monitor('build individual hmaps'):
                pmap_by_kind['hmaps-rlzs'] = [
                    calc.make_hmap(pmap, imtls, poes) for pmap in pmaps]
    return pmap_by_kind
