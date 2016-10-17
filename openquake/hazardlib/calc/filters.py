# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (C) 2012-2016 GEM Foundation
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
"""
Module :mod:`~openquake.hazardlib.calc.filters` contain filter functions for
calculators.

Filters are functions (or other callable objects) that should take generators
and return generators. There are two different kinds of filter functions:

1. Source-site filters. Those functions take a generator of two-item tuples,
   each pair consists of seismic source object (that is, an instance of
   a subclass of :class:`~openquake.hazardlib.source.base.BaseSeismicSource`)
   and a site collection (instance of
   :class:`~openquake.hazardlib.site.SiteCollection`).
2. Rupture-site filters. Those also take a generator of pairs, but in this
   case the first item in the pair is a rupture object (instance of
   :class:`~openquake.hazardlib.source.rupture.Rupture`). The second element in
   generator items is still site collection.

The purpose of both kinds of filters is to limit the amount of calculation
to be done based on some criteria, like the distance between the source
and the site. So common design feature of all the filters is the loop over
pairs of the provided generator, filtering the sites collection, and if
there are no items left in it, skipping the pair and continuing to the next
one. If some sites need to be considered together with that source / rupture,
the pair gets generated out, with a (possibly) :meth:`limited
<openquake.hazardlib.site.SiteCollection.filter>` site collection.

Consistency of filters' input and output stream format allows several filters
(obviously, of the same kind) to be chained together.

Filter functions should not make assumptions about the ordering of items
in the original generator or draw more than one pair at once. Ideally, they
should also perform reasonably fast (filtering stage that takes longer than
the actual calculation on unfiltered collection only decreases performance).

Module :mod:`openquake.hazardlib.calc.filters` exports one distance-based
filter function of each kind (see :func:`SourceSitesFilter` and
:func:`RuptureSitesFilter`) as well as "no operation" filters
(:func:`source_site_noop_filter` and :func:`rupture_site_noop_filter`).
"""
import sys
import logging
from contextlib import contextmanager
import numpy
try:
    import rtree
except ImportError:
    rtree = None
from openquake.baselib.python3compat import raise_
from openquake.hazardlib.site import FilteredSiteCollection
from openquake.hazardlib.geo.utils import fix_lons_idl


@contextmanager
def context(src):
    """
    Used to add the source_id to the error message. To be used as

    with context(src):
        operation_with(src)

    Typically the operation is filtering a source, that can fail for
    tricky geometries.
    """
    try:
        yield
    except:
        etype, err, tb = sys.exc_info()
        msg = 'An error occurred with source id=%s. Error: %s'
        msg %= (src.source_id, err)
        raise_(etype, msg, tb)


def filter_sites_by_distance_to_rupture(rupture, integration_distance, sites):
    """
    Filter out sites from the collection that are further from the rupture
    than some arbitrary threshold.

    :param rupture:
        Instance of :class:`~openquake.hazardlib.source.rupture.Rupture`
        that was generated by :meth:
        `openquake.hazardlib.source.base.BaseSeismicSource.iter_ruptures`
        of an instance of this class.
    :param integration_distance:
        Threshold distance in km.
    :param sites:
        Instance of :class:`openquake.hazardlib.site.SiteCollection`
        to filter.
    :returns:
        Filtered :class:`~openquake.hazardlib.site.SiteCollection`.

    This function is similar to :meth:`openquake.hazardlib.source.base.BaseSeismicSource.filter_sites_by_distance_to_source`.
    The same notes about filtering criteria apply. Site
    should not be filtered out if it is not further than the integration
    distance from the rupture's surface projection along the great
    circle arc (this is known as Joyner-Boore distance, :meth:`
    openquake.hazardlib.geo.surface.base.BaseQuadrilateralSurface.get_joyner_boore_distance`).
    """
    jb_dist = rupture.surface.get_joyner_boore_distance(sites.mesh)
    return sites.filter(jb_dist <= integration_distance)


class SourceSitesFilter(object):
    """
    Source-sites filter based on the integration distance. Used as follows::

      ss_filter = SourceSitesFilter(integration_distance)
      for src, affected_sites in ss_filter(sources, sites):
         do_something(...)

    As a side effect, sets the `.nsites` attribute of the source, i.e. the
    number of sites within the integration distance.

    :param integration_distance:
        Threshold distance in km, this value gets passed straight to
        :meth:`openquake.hazardlib.source.base.BaseSeismicSource.filter_sites_by_distance_to_source`
        which is what is actually used for filtering.
    """
    def __init__(self, integration_distance):
        assert integration_distance, 'Must be set'
        self.integration_distance = integration_distance

    def affected(self, source, sites):
        """
        Returns the sites within the integration distance from the source,
        or None.
        """
        source_sites = list(self([source], sites))
        if source_sites:
            return source_sites[0][1]

    def __call__(self, sources, sites):
        for source in sources:
            if hasattr(self.integration_distance, '__getitem__'):
                # a dictionary trt -> distance
                trt = source.tectonic_region_type
                integration_distance = self.integration_distance[trt]
            else:  # just a distance in km
                integration_distance = self.integration_distance
            with context(source):
                s_sites = source.filter_sites_by_distance_to_source(
                    integration_distance, sites)
            if s_sites is not None:
                source.nsites = len(s_sites)
                yield source, s_sites


class RtreeFilter(object):
    """
    The RtreeFilter uses the rtree library on PointSources and our own
    SourceSitesFilter on other source typologies. The index is generated
    at instantiation time and kept in memory, so the filter should be
    instantiated only once per calculation, after the site collection is
    known. It should be used as follows::

      ss_filter = RtreeFilter(sitecol, integration_distance)
      for src, sites in ss_filter(sources):
         do_something(...)

    As a side effect, sets the `.nsites` attribute of the source, i.e. the
    number of sites within the integration distance.

    :param sitecol:
        :class:`openquake.hazardlib.site.SiteCollection` instance
    :param integration_distance:
        Threshold distance in km, this value gets passed straight to
        :meth:`openquake.hazardlib.source.base.BaseSeismicSource.filter_sites_by_distance_to_source`
        which is what is actually used for filtering.
    """
    def __init__(self, sitecol, integration_distance):
        assert integration_distance, 'Must be set'
        self.integration_distance = integration_distance
        self.sitecol = sitecol
        if rtree:
            fixed_lons, self.idl = fix_lons_idl(sitecol.lons)
            if self.idl:  # longitudes -> longitudes + 360 degrees
                sitecol.complete.lons[sitecol.sids] = fixed_lons
            self.index = rtree.index.Index()
            for sid, lon, lat in zip(sitecol.sids, sitecol.lons, sitecol.lats):
                self.index.insert(sid, (lon, lat, lon, lat))
        else:
            logging.warn('Cannot find the rtree module, using slow filtering')

    def get_affected_box(self, src):
        """
        Get the enlarged bounding box of a source.

        :param src: a source object
        :returns: a bounding box (min_lon, min_lat, max_lon, max_lat)
        """
        maxdist = self.integration_distance[src.tectonic_region_type]
        min_lon, min_lat, max_lon, max_lat = src.get_bounding_box(maxdist)
        if self.idl:  # apply IDL fix
            if min_lon < 0 and max_lon > 0:
                return max_lon, min_lat, min_lon + 360, max_lat
            elif min_lon < 0 and max_lon < 0:
                return min_lon + 360, min_lat, max_lon + 360, max_lat
            elif min_lon > 0 and max_lon > 0:
                return min_lon, min_lat, max_lon, max_lat
            elif min_lon > 0 and max_lon < 0:
                return max_lon + 360, min_lat, min_lon, max_lat
        else:
            return min_lon, min_lat, max_lon, max_lat

    def get_rectangle(self, src):
        """
        :param src: a source object
        :returns: ((min_lon, min_lat), width, height), useful for plotting
        """
        min_lon, min_lat, max_lon, max_lat = self.get_affected_box(src)
        return (min_lon, min_lat), max_lon - min_lon, max_lat - min_lat

    def affected(self, source):
        """
        Returns the sites within the integration distance from the source,
        or None.
        """
        source_sites = list(self([source]))
        if source_sites:
            return source_sites[0][1]

    def __call__(self, sources, sites=None):
        if sites is None:
            sites = self.sitecol
        for source in sources:
            if rtree:  # Rtree filtering
                box = self.get_affected_box(source)
                sids = numpy.array(sorted(self.index.intersection(box)))
                if len(sids):
                    source.nsites = len(sids)
                    yield source, FilteredSiteCollection(sids, sites.complete)
            else:  # normal filtering
                with context(source):
                    s_sites = source.filter_sites_by_distance_to_source(
                        self.integration_distance[source.tectonic_region_type],
                        sites)
                if s_sites is not None:
                    source.nsites = len(s_sites)
                    yield source, s_sites


def source_site_noop_filter(sources, sites=None):
    """
    Transparent source-site "no-op" filter -- behaves like a real filter
    but never filters anything out and doesn't have any overhead.
    """
    return ((src, sites) for src in sources)
source_site_noop_filter.affected = lambda src, sites=None: sites
source_site_noop_filter.integration_distance = None
