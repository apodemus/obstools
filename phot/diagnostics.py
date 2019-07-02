import numbers

from IPython import embed

import logging
import warnings
import itertools as itt
from pathlib import Path
import multiprocessing as mp

import more_itertools as mit
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.cm import get_cmap
from matplotlib import ticker

from graphical.ts import TSplotter
from graphical.imagine import ImageDisplay
# from obstools.psf.psf import GaussianPSF
# from obstools.modelling.psf.models_lm import EllipticalGaussianPSF
from obstools.phot.utils import duplicate_if_scalar
from motley.profiler.timers import timer
from motley.table import Table
from recipes.misc import is_interactive
from mpl_toolkits.axes_grid1 import make_axes_locatable

from graphical.formatters import LinearRescaleFormatter

SECONDS_PER_DAY = 86400
DEFAULT_CMAP = 'jet'
KNOWN_TESSELLATIONS = ('hex', 'rect')

tsplt = TSplotter()  # fixme Singleton YUCK!!!

logger = logging.getLogger('diagnostics')


def _sanitize_data(data, allow_dim):
    # sanitize data
    data = np.asanyarray(data).squeeze()
    assert data.size > 0, 'No data!'
    assert data.ndim == allow_dim
    assert data.shape[-1] == 2

    # mask nans
    data = np.ma.MaskedArray(data, np.isnan(data))
    return data


# def nans_to_masked(data):


def plot_position_measures(coords, centres, shifts, labels=None, min_count=5,
                           pixel_grid=None):
    """
    For sets of measurements (m, n, 2), plot each (m, 2) feature set as on
    its own axes as scatter / density plot.  Additionally plot the shifted
    points in the same axes, as well as in separate axes below the axes with
    the raw measurements optionally marking an inset region in the top axes
    corresponding to the range of the bottom axes

    Parameters
    ----------
    coords
    centres
    shifts
    labels

    Returns
    -------

    """
    n_stars = len(centres)
    if n_stars > 10:
        raise NotImplementedError('Plotting %i in a figure is probably not a '
                                  'great idea....' % n_stars)

    from matplotlib.patches import Rectangle
    from matplotlib.lines import Line2D

    def _on_first_draw(event):
        # have to draw rectangle inset lines after first draw else they point
        # to wrong locations on the edges of the lower axes
        add_rectangle_inset()
        for ax in event.canvas.figure.axes[:n_stars]:
            rotate_labels(ax)
        for ax in event.canvas.figure.axes[n_stars:]:
            rotate_labels(ax, 'y')
        fig.canvas.mpl_disconnect(cid)  # disconnect so this only runs once

    def add_rectangle_inset():
        # add rectangle to indicate size of lower axes on upper
        for j, ax in enumerate(axes[1]):
            bbox = ax.viewLim
            xyr = np.array([bbox.x0, bbox.y0])
            r = Rectangle(xyr, bbox.width, bbox.height,
                          fc='none', ec=ec, lw=1.5)
            ax_up = axes[0, j]
            ax_up.add_patch(r)

            # add lines for aesthetic
            # get position of upper edges of lower axes in data
            # coordinates of upper axes
            trans = ax.transAxes + ax_up.transData.inverted()
            xy = trans.transform([[0, 1], [1, 1]])

            ax_up.plot(*np.array([xyr, xy[0]]).T,
                       color=ec, clip_on=False)
            ax_up.plot(*np.array([xyr + (bbox.width, 0), xy[1]]).T,
                       color=ec, clip_on=False)

    def rotate_labels(ax, which='xy', angle=45):
        for xy in which:
            ticklabels = getattr(ax, f'{xy}axis').get_majorticklabels()
            # if len(ticklabels[-1].get_text()) < 3:
            #     return

            for label in ticklabels:
                label.set_rotation(angle)

    # clean data
    coords = _sanitize_data(coords, 3)

    # TODO: add cluster labels ?
    ignore_plot = coords.mask.all((0, 2))
    if ignore_plot.any():
        logger.info('All points are masked in feature(s): %s. Ignoring.',
                    np.where(ignore_plot)[0])
        coords = coords[:, ~ignore_plot]

    #
    ec = '0.6'
    # size figure according to data
    ax_size_inches = 2.5
    figsize = (n_stars * ax_size_inches, 2 * ax_size_inches)
    fig, axes = plt.subplots(2, n_stars, figsize=figsize,
                             gridspec_kw=dict(top=0.9,
                                              bottom=0.05,
                                              left=0.035,
                                              right=0.99,
                                              hspace=0.25,
                                              wspace=0.25))

    # plot raw measurements
    scatter_density_grid(coords[..., ::-1], axes=axes[0], min_count=min_count,
                         scatter_kws=dict(mfc='none', label='measured'),
                         centre_label='mean')

    # decide if we should make axes ticks match pixel boundaries
    # all axes ranges should match
    if pixel_grid is None:
        low, high = np.ceil(axes[0, 0].viewLim.get_points()).astype(int)
        pixel_grid = max(high - low) < 25
        # drawing gets very slow with too many grid lines

    # shifted coordinates (global)
    yx = (coords - shifts[:, None])[..., ::-1]

    # align raw and shifted cluster centroids
    # yx -= shifts.mean(0)
    for i, ax_row in enumerate(axes):
        scatter_density_grid(yx, None, ax_row, False, bool(i),
                             min_count=np.inf,
                             scatter_kws=dict(marker='.', color='maroon',
                                              label='recentred'),
                             )

        for j, ax in enumerate(ax_row):
            ax.plot(*centres[j, ::-1], 'm*', label='Geometric median')

            # set grid density to match pixel density
            if i == 0 and pixel_grid:
                low, high = np.ceil(ax.viewLim.get_points()).astype(int)
                xy_ticks = np.ogrid[tuple(map(slice, low, high))]
                for k, (xy, ticks) in enumerate(zip('xy', xy_ticks)):
                    if ticks.size != 0:
                        ax.set(**{f'{xy}ticks': ticks.squeeze(int(not k))})

            if j == 0:
                ax.set(xlabel='x', ylabel='y')

            if i == 1:
                # TODO: rotate these labels also???
                ax.grid(ls=':')

                # draw rectangle indicating pixel size
                if not np.ma.is_masked(centres[j]):
                    xy = centres[j, ::-1] - 0.5
                    r = Rectangle(xy, 1, 1,
                                  fc='none', ec='k', lw=2, label='pixel')
                    ax.add_patch(r)

                    # ensure axes limits include pixel size
                    d = 0.05
                    xlim, ylim = np.transpose([xy - d, xy + d + 1])
                    ax.set(xlim=xlim, ylim=ylim)

            #     # FIXME: minor ticks not drawn if only one major tick
            #     axis = getattr(ax, f'{xy}axis')
            #     axis.set_minor_locator(ticker.AutoMinorLocator())
            #     axis.set_minor_formatter(ticker.ScalarFormatter())

    # TODO: better legend: 2 col?
    handles, labels = axes[0, 0].get_legend_handles_labels()
    # add proxy art for pixel size box
    handles.append(Line2D([], [], color='k', marker='s',
                          mfc='none', mew=2, ls='', markersize=15,
                          label='pixel size'))

    fig.legend(handles, labels, loc='upper left')

    # add callback for drawing rectangle inset and rotating tick labels
    cid = fig.canvas.mpl_connect('draw_event', _on_first_draw)
    fig.tight_layout()
    return fig, axes


def scatter_density_grid(features, centres=None, axes=None, auto_lim_axes=True,
                         show_centres=True, centre_func=np.mean,
                         centre_marker='*', centre_label='', bins=100,
                         min_count=3, tessellation='hex', scatter_kws=None,
                         density_kws=None):
    """

    Parameters
    ----------
    features
    centres
    axes
    auto_lim_axes
    show_centres
    centre_func
    centre_marker
    centre_label
    bins
    min_count
    tessellation
    scatter_kws
    density_kws

    Returns
    -------

    """
    # TODO: add cluster labels ?

    # clean data
    features = _sanitize_data(features, 3)

    n_clusters = features.shape[1]
    if axes is None:
        fig, axes = plt.subplots(1, n_clusters,
                                 figsize=(9.125, 4.25))

    if show_centres and centres is None:
        centres = centre_func(features, 0)

    # make axes scales the same
    if auto_lim_axes:
        # make the axes limits twice the 98 percentile range of the most
        # spread out data channel
        plims = (1, 99)
        Δ = np.nanpercentile(np.ma.filled(features, np.nan),
                             plims, 0).ptp(0).mean(0).max()
        xy_lims = centres[..., None] + np.multiply(Δ, [-1, 1])[None, None]

    for i, ax in enumerate(axes.ravel()):
        yx = features[:, i]

        # plot point cloud visualization
        scatter_density_plot(ax, yx, bins, min_count,
                             tessellation, scatter_kws, density_kws)

        if show_centres:
            ax.plot(*centres[i], centre_marker, label=centre_label)

        if auto_lim_axes and yx.size > 2:
            xlim, ylim = xy_lims[i]
            ax.set(xlim=xlim, ylim=ylim)

        ax.grid(True)
        ax.set_aspect('equal')

    ax.figure.tight_layout()
    return ax.figure, axes


def scatter_density_plot(ax, data, bins=100, min_count=3, tessellation='hex',
                         scatter_kws=None, density_kws=None, **kws):
    """
    Point cloud visualization with density map and scatter plot. Regions
    with high point density are plotted as a 2d histogram image using either
    rectangular or hexagonal binning.

    Parameters
    ----------
    ax
    data
    bins: int
    min_count: int
        point density threshold. Bins with more points than this number will
        be plotted as density map. Points not in dense regions will be
        plotted as actual markers. For pure scatter plot set this value `None`
        or `numpy.inf`.  For pure density map, set `min_count` to 0.
    tessellation
    kws

    Returns
    -------

    """

    data = _sanitize_data(data, 2)

    # default arg
    cmap = get_cmap(kws.get('cmap', DEFAULT_CMAP))
    scatter_kws = scatter_kws or {}
    density_kws = density_kws or {}

    if tessellation not in KNOWN_TESSELLATIONS:
        raise ValueError('Invalid tessellation %r: Valid choices are %s',
                         tessellation, KNOWN_TESSELLATIONS)

    # choose range todo: extent=
    # xyrange = np.array(
    #         [(np.floor(x_data.min()), np.ceil(x_data.max())),
    #          (np.floor(y_data.min()), np.ceil(y_data.max()))])

    # np.nanpercentile(, (0.01, 99.99), 0)

    if tessellation == 'rect':
        returns = hist2d_scatter(ax, data, bins, min_count, cmap,
                                 scatter_kws, density_kws)

    if tessellation == 'hex':
        returns = hexbin_scatter(ax, data, bins, min_count, cmap,
                                 scatter_kws, density_kws)

    # div = make_axes_locatable(ax)
    # cax = div.append_axes('right', '5%')
    # cbar = ax.figure.colorbar(im, cax)
    # cbar.ax.set_ylabel('Density')

    # ax.set_title('Coord scatter')
    # ax.set_xlabel('x')
    # ax.set_ylabel('y')
    ax.grid()

    return returns


def hist2d_scatter(ax, data, bins, min_count, cmap, scatter_kws=None,
                   density_kws=None):
    do_density_plot = (min_count is not None) and np.isfinite(min_count)
    if do_density_plot:
        density_kws = density_kws or {}
        bins = duplicate_if_scalar(bins)

        x_data, y_data = data.T
        # plot density map
        hvals, x_edges, y_edges, qmesh = ax.hist2d(x_data, y_data,
                                                   bins=bins, cmap=cmap,
                                                   **density_kws)
        # remove low density points
        fc = qmesh.get_facecolor()
        fc[np.ravel(hvals < min_count)] = 0
        qmesh.set_facecolor(fc)

        ix_x = np.digitize(x_data, x_edges)
        ix_y = np.digitize(y_data, y_edges)

        # select points within the range
        ind = (ix_x > 0) & (ix_x <= bins[0]) & (ix_y > 0) & (ix_y <= bins[1])
        # values of the histogram where there are enough points
        hhsub = hvals[ix_x[ind] - 1, ix_y[ind] - 1]
        x_scatter = x_data[ind][hhsub < min_count]  # low density points
        y_scatter = y_data[ind][hhsub < min_count]
    else:
        hvals = []
        qmesh = None
        x_scatter, y_scatter = data

    # plot scatter points
    scatter_kws = scatter_kws or {}
    scatter_kws.setdefault('color', cmap(0))
    scatter_kws.setdefault('marker', 'o')
    scatter_kws.setdefault('ls', '')

    points = ax.plot(x_scatter, y_scatter, **scatter_kws)

    return hvals, qmesh, points


def hexbin_scatter(ax, data, bins, min_count, cmap, scatter_kws=None,
                   density_kws=None):
    do_density_plot = (min_count is not None) and np.isfinite(min_count)
    if do_density_plot:
        density_kws = density_kws or {}
        sparse_point_indices = []

        def collect_indices(idx):
            counts = len(idx)
            if counts < min_count:
                sparse_point_indices.extend(idx)
            return counts

        def on_first_draw(_):
            fc = poly_coll.get_facecolor()
            fc[hvals < min_count] = 0
            poly_coll.set_facecolor(fc)

            # disconnect callback so this func only runs once
            fig.canvas.mpl_disconnect(cid)

        fig = ax.figure
        cid = fig.canvas.mpl_connect('draw_event', on_first_draw)

        # plot density map
        indices = np.arange(len(data))
        poly_coll = ax.hexbin(*data.T, indices,
                              gridsize=bins,
                              reduce_C_function=collect_indices,
                              cmap=cmap, **density_kws)
        hvals = poly_coll.get_array()
    else:
        sparse_point_indices = ...
        hvals = []
        poly_coll = None

    # plot scatter points
    scatter_kws = scatter_kws or {}
    scatter_kws.setdefault('color', cmap(0))
    scatter_kws.setdefault('marker', 'o')
    scatter_kws.setdefault('ls', '')
    points = ax.plot(*data[sparse_point_indices].T, **scatter_kws)

    return hvals, poly_coll, points


def new_diagnostics(coords, rcoo, Appars, optstat):
    figs = {}
    # coordinate diagnostics
    fig = plot_coord_moves(coords, rcoo)
    figs['coords.moves'] = fig

    # fig = plot_coord_scatter(coords, rcoo)
    # figs['coords.scatter'] = fig
    # fig = plot_coord_walk(coords)
    # figs['coords.walk'] = fig

    fig = plot_coord_jumps(coords)
    figs['coords.jump'] = fig

    # aperture diagnostics
    fig = ap_opt_stat_map(optstat)
    figs['opt.stat'] = fig
    fig = plot_appars_walk(Appars.stars, ('a', 'b', 'theta'), 'Star apertures')
    figs['aps.star.walk'] = fig
    fig = plot_appars_walk(Appars.sky, ('a_in', 'b_in', 'a_out'),
                           'Sky apertures')
    figs['aps.sky.walk'] = fig

    return figs


def ap_opt_stat_map(optstat):
    # TODO: clearer frame numbers for axes and format_coords
    # FIXME: use catagorical cmap

    nf, ng = optstat.shape
    #  nf - number of frames, ng - number of optimization groups;
    ngg = (ng + 1)  # + 1 for whitespace separator in image

    #     flags -
    #  1 : success
    #  0 : Optimization converged on boundary
    # -1 : no convergence
    # -2 : low SNR, skip
    # -3 : minimize subroutine exception

    nq = nf * ngg
    # make image twice as wide as is tall
    nc_by_ng = int(np.ceil(np.sqrt(2 * nq) / ngg))
    nc = nc_by_ng * ngg
    nr = int(np.ceil(nq / nc))
    padw = int(nc * nr / ngg - nf)

    z = np.full((nr * nc_by_ng, ngg), np.nan)
    # z[:nf, :ng] = optstat
    # zz = z.reshape(nc_by_ng, nr, ngg).swapaxes(0, 1).reshape((nr, -1)).T

    image = np.full((nr, nc), np.nan)
    j = 0
    for i in range(nr):
        if (i % ngg) == 2:
            continue

        image[i] = optstat[j:j + nc, i % 3]

        # print(i, image[i].shape, optstat[j:j+nc, i % 3].shape, j)

        if not (i % 3):
            j += nc % 3

    # extent = [0, nc, 0, nf] ; aspect=nc/nf

    im = ImageDisplay(image,
                      origin='upper', cmap='jet_r',
                      interval='minmax',
                      hist=False, sliders=False)
    im.imagePlot.set_clim(-3, 1)
    cmap = im.imagePlot.get_cmap()

    # hack the yscale
    fmt = LinearRescaleFormatter(nf / nr)
    im.ax.yaxis.set_major_formatter(fmt)
    #

    proxies = [Rectangle((0, 0), 1, 1, color=c)
               for c in cmap(np.linspace(0, 1, 5))]
    labels = ['error',
              'SNR < 1.2. skipped',
              'not converged',
              'on bound',
              'OK']
    im.ax.legend(proxies, labels, loc=2, bbox_to_anchor=(0, 1.2))
    im.figure.set_size_inches(14, 9)  # hack to prevent legend being cut off
    return im.figure


# TODO: plot best model balance for each star

# ====================================================================================================
@timer
def diagnostics(modelDb, locData):
    # np.isnan(flux_ap)
    # problematic = list(filter(None, res))

    # Npar = len(GaussianPSF.params)

    # Diagnostics
    # bad_aic = (np.isnan(AIC) | (abs(AIC) == np.inf))

    # Print fitting summary table
    # FIXME: error if not fitting
    # tbl = fit_summary(modelDb, locData)
    # print(tbl)

    # Check which model is preferred
    lbgb = modelDb.best.ix == modelDb._ix[
        modelDb.db.bg]  # this is where the pure bg model is the best fit

    badflux = np.isnan(modelDb.best.flux) | lbgb
    fpm = np.ma.masked_where(badflux, modelDb.best.flux)

    # NOTE: validation done individually in phot.psf.aux.StarFit
    par = modelDb.data[modelDb.db.elliptical].params
    alt = modelDb.data[modelDb.db.elliptical].alt

    # TODO: circular??

    badfits = np.isnan(par).any(-1) | np.isinf(par).any(-1)
    # ibad = np.where(badfits)

    pm = np.ma.array(par, copy=True)
    pm[badfits] = np.ma.masked

    paltm = np.ma.array(alt, mask=pm.mask[..., :6])

    return pm, paltm, fpm


# print('Unconvergent: {:%}'.format(np.isnan(psf_par).sum() / psf_par.size))


def fit_summary(modelDb, locData):
    names, tbl = [], []
    for model in modelDb.gaussians:
        par = modelDb.data[model].params
        badfits = np.isnan(par).any(-1)
        s = badfits.sum(0)  # number of bad fits per star
        f = (s / par.shape[0])  # percentage
        d = map('{:d} ({:.2%})'.format, s, f)
        tbl.append(list(d))
        names.append(modelDb.model_names[modelDb._ix[model]])

    # summary table
    coo = locData.rcoo[modelDb.ix_fit]
    col_headers = list(
            map('Star {0:d}: ({1[1]:3.1f}, {1[0]:3.1f})'.format, modelDb.ix_fit,
                coo))
    tbl = Table(tbl,
                title='Fitting summary: Unconvergent',
                title_props=dict(txt='bold', bg='m'),
                row_headers=names, col_headers=col_headers)

    return tbl


@timer
def diagnostic_figures(locData, apData, modelDb, fitspath=None, save=True):
    # labels for legends
    nstars = apData.bg.shape[-1]
    ix = modelDb.ix_fit or range(nstars)
    rcoo = locData.rcoo  # finder.Rcoo[ix]
    ir = locData.ir  # finder.ir
    w = locData.window  # finder.window
    star_labels = list(
            map('{0:d}: ({1[1]:3.1f}, {1[0]:3.1f})'.format, ix, rcoo))

    # #plot some statistics on the parameters!!
    # masked parameters, masked parameter variance
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')  # nans cause Runtimewarning
        pm, paltm, fpm = diagnostics(modelDb, locData)
    fitcoo = pm[..., 1::-1]  # - locData.rcoo[list(modelDb.ix_fit)]
    fitcoo -= np.nanmedian(fitcoo, 0)

    figs = {}
    # plot histograms of parameters
    if pm.size:
        pm[..., :2] -= pm[..., :2].mean(0)  # subtract mean coordinates
        fig = plot_param_hist(pm, EllipticalGaussianPSF.pnames_ordered)
        figs['p.hist.png'] = fig

        pnames = 'sigx, sigy, cov, theta, ellipticity, fwhm'.split(', ')
        fig = plot_param_hist(paltm, pnames)
        figs['p.alt.hist.png'] = fig

    if fitcoo.size:
        fig = plot_coord_scatter(fitcoo, rcoo[ir], w)
        figs['coo.fit.scatter.png'] = fig

        fig = plot_coord_jumps(fitcoo)
        figs['coo.fit.jump.png'] = fig
    elif not locData.find_with_fit:
        #
        fig = plot_coord_scatter(locData.coords, rcoo[ir], w)
        figs['coo.found.scatter.png'] = fig

        fig = plot_coord_jumps(locData.coords)
        figs['coo.found.jump.png'] = fig

    if fpm.size:
        fig = plot_lc_psf(fpm, star_labels)
        figs['lc.psf.png'] = fig

    *figs_lc, fig_bg = plot_lc_aps(apData, star_labels)
    for i, fig in enumerate(figs_lc):
        figs['lc.aps.%i.png' % i] = fig
    figs['lc.bg.png'] = fig_bg

    if save:
        save_figures(figs, fitspath)


@timer
def save_figures(figures, path):
    # create directory for figures to be saved
    # figdir = path.with_suffix('.figs')
    if not path.exists():
        path.mkdir()
    # NOTE existing files will be clobbered

    fnames = [(path / filename).with_suffix('.png')
              for filename in figures.keys()]
    figs = figures.values()

    if is_interactive():
        list(map(saver, figs, fnames))
    else:
        # TODO: figure out why this does not work in ipython
        pool = mp.Pool()
        pool.starmap(saver, zip(figs, fnames))
        pool.close()
        pool.join()


def saver(fig, filename):
    fig.savefig(str(filename))


@timer
def plot_param_hist(p, names):
    Nstars = p.shape[1]
    p = np.ma.array(p, mask=False)
    div, mod = divmod(p.shape[-1], 2)
    fig, axs = plt.subplots(sum((div, mod)), 2,
                            figsize=(12, 9))
    for i, ax in enumerate(axs.ravel()):
        if mod and i == p.shape[-1]:
            ax.remove()  # remove empty axis
            break

        for pp in p[..., i].T:
            stuff = ax.hist(pp[~pp.mask], bins=50, histtype='step', log=True)
        ax.grid()
        # title
        ax.text(0.5, 0.98, names[i],
                va='top', fontweight='bold', transform=ax.transAxes)
        if i == 1:
            ax.legend(range(Nstars), loc='upper right')
    fig.tight_layout()

    return fig


# @timer
def plot_coord_walk(ax, coords):  # coords
    from matplotlib.collections import LineCollection
    # coordinate walk
    # fig, ax = plt.subplots(figsize=(8, 8),
    #                        subplot_kw=dict(aspect='equal'))

    # segments = coords.reshape(-1, 1, 2)
    # segments[-1, -1] = None

    # z = np.random.randn(10,2)
    z = np.vstack([coords, [np.nan] * 2])
    segments = list(mit.pairwise(z))

    lcol = LineCollection(segments)
    lcol.set_array(np.arange(len(coords)))

    ax.add_collection(lcol)
    ax.autoscale_view()
    #
    div = make_axes_locatable(ax)
    cax = div.append_axes('right', '5%')
    cbar = ax.figure.colorbar(lcol, cax)
    cbar.ax.set_ylabel('Frame')

    ax.grid()
    ax.set(title='Coord walk',
           xlabel='x', ylabel='y')  # FIXME: wrong order

    # return fig  # , lcol


def plot_coord_moves(coords, rcoo):
    # fig = plt.figure(figsize=(18, 8))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 8),
                                   subplot_kw=dict(aspect='equal'))

    #
    scatter_density_plot(ax1, coords, rcoo)
    #
    plot_coord_walk(ax2, coords)

    xlim, ylim = (ax2.viewLim.get_points() - rcoo).T
    ax1.set(xlim=xlim, ylim=ylim)

    fig.tight_layout()

    return fig


# @timer
def plot_coord_jumps(coords):  # coords
    # coordinate jumps
    fig, ax = plt.subplots(figsize=(14, 8))
    coords_1 = np.roll(coords, -1, axis=0)
    jumps = np.sqrt(np.square(coords - coords_1).sum(-1))

    # index outliers
    l = jumps > 3
    if l.any():
        for w, j in zip(np.where(l)[0], jumps[l]):
            ax.text(w, j, str(w), fontsize=12)
            # FIXME: May have overlapping text here...

    # plot
    ax.plot(jumps, 'x')  # , alpha=0.75)
    # plot invalid
    xinv, = np.where(np.isnan(coords).any(1))
    ax.plot(xinv, np.zeros_like(xinv), 'rx')

    ax.set(title='Coordinate jumps',
           xlabel='frame', ylabel='$\Delta r$')
    ax.grid()
    # nstars = coords.shape[1]
    # ax.legend(range(nstars))

    fig.tight_layout()

    return fig


def plot_appars_walk(appars, names, title=None):
    # TODO: histogram ??

    nstars = appars.shape[1]
    fig, axes = plt.subplots(nstars, 1, sharex=True, figsize=(14, 8))
    if title:
        fig.suptitle(title)

    for i, (ax, pars) in enumerate(zip(axes, appars.swapaxes(0, 1))):
        for x in pars.T:
            ax.plot(x)
            ax.set_title('Group %i' % i)  # TODO add segment labels

        xinv, = np.where(np.isnan(pars).any(1))
        ax.plot(xinv, np.zeros_like(xinv), 'rx')

        ax.grid()
        ax.legend(names)

    return fig


def get_proxy_art(art):
    # TODO: maybe move to tsplt???
    proxies = []
    for a in art:
        clr = a.get_children()[0].get_color()
        r = Rectangle((0, 0), 1, 1, color=clr)
        proxies.append(r)
    return proxies


@timer
def plot_lc_psf(fpm, labels):
    # PSF photometry light curves
    fig, art, *rest = tsplt(fpm.T, title='psf flux',
                            draggable=False,
                            show_hist=True)

    # legend
    hax = fig.axes[1]
    proxies = []
    for a in art:
        clr = a.get_children()[0].get_color()
        r = Rectangle((0, 0), 1, 1, color=clr)
        proxies.append(r)
    hax.legend(proxies, labels, loc='upper right', markerscale=3)

    return fig


def plot_aperture_flux(fitspath, proc, tracker):
    from astropy.time import Time, TimeDelta

    # TODO: label top / right axes

    # timePath = next(fitspath.parent.glob('*.time'))
    timePath = fitspath.with_suffix('.time')
    timeData = np.genfromtxt(timePath, dtype=None, names=True)
    t = Time(timeData['utdate']) + TimeDelta(timeData['utsec'], format='sec')

    flux = proc.Flx.squeeze().T
    flxStd = proc.FlxStd.squeeze().T
    fluxBG = proc.FlxBG.T
    flxBGStd = proc.FlxBGStd.T
    star_labels = list(map('{0:d}: ({1[1]:3.1f}, {1[0]:3.1f})'.format,
                           tracker.segm.labels, tracker.rcoo))

    figs = {
        'lc.aps.opt': plot_lc(t, flux, flxStd, star_labels, '(Optimal)'),
        'lc.aps.bg': plot_lc(t, fluxBG, flxBGStd, star_labels, '(BG)')
    }

    return figs


def plot_lc(t, flux, flxStd, labels, description='', max_errorbars=200):
    logger.info('plotting lc aps: %s', description)

    # no more than 200 error bars so we don't clutter the plot
    error_every = flxStd.shape[1] // int(max_errorbars)
    title = 'Aperture flux %s' % description

    # plot with frame number at bottom
    t0 = t[0].to_datetime()
    δt = (t[1] - t[0]).to('s').value
    timescale = SECONDS_PER_DAY / δt

    fig, art, *rest = tsplt.plot(np.arange(len(t)), flux, flxStd,
                                 title=title,
                                 twinx='sexa',
                                 start=t0,
                                 timescale=timescale,
                                 errorbar=dict(errorevery=error_every),
                                 axlabels=('frame #', 'Flux (photons/pixel)'),
                                 draggable=True,  # FIXME: labels not shown
                                 show_hist=False)  # FIXME: fuckup with axes

    art.connect()

    # Plot with UT seconds on bottom
    # relative time in seconds
    # ts = (t - t[0]).to('s')
    # fig, art, *rest = tsplt.plot(ts, flux, flxStd,
    #                              title=title,
    #                              twinx='sexa',
    #                              start=t[0].to_datetime(),
    #                              errorbar=dict(errorevery=errorevery),
    #                              axlabels=('t (s)', 'Flux (photons/pixel)'),
    #                              draggable=False,
    #                              show_hist=True)
    # legend
    hax = fig.axes[1]
    proxies = get_proxy_art(art)
    hax.legend(proxies, labels, loc='upper right', markerscale=3)

    # date text
    date_string = t0.strftime('%Y-%m-%d')
    # %H:%M:%S') + ('%.3f' % (t0.microsecond / 1e6)).strip('0')
    ax = fig.axes[0]
    ax.text(0, ax.title.get_position()[1], date_string,
            transform=ax.transAxes, ha='left')

    # s = ax.text(1, 1.01, date_string, transform=ax.transAxes)

    return fig


# def plot_lc(args):
#     data, s, labels = args
#     print('plotting lc aps', s)
#     fig, art, *rest = tsplt.plot(data,
#                                  title='aperture flux (%.1f*fwhm)' % s,
#                                  draggable=False,
#                                  show_hist=True)
#     # legend
#     hax = fig.axes[1]
#     proxies = get_proxy_art(art)
#     hax.legend(proxies, labels, loc='upper right', markerscale=3)
#
#     return fig
#

@timer
def plot_lc_aps(apdata, labels):
    # from graphical.multitab import MplMultiTab
    ##ui = MplMultiTab()
    figs = []

    with mp.Pool() as pool:
        figs = pool.map(plot_lc,
                        zip(apdata.flux.T, apdata.scale, itt.repeat(labels)))

    # for i, s in enumerate(apdata.scale):
    #     print('plotting lc aps', i, s)
    #     fig, art, *rest = tsplt.plot(apdata.flux[...,i].T,
    #                              title='aperture flux (%.1f*fwhm)' %s,
    #                              draggable=False,
    #                              show_hist=True)
    #     # legend
    #     hax = fig.axes[1]
    #     proxies = get_proxy_art(art)
    #     hax.legend(proxies, labels, loc='upper right', markerscale=3)
    #
    #     figs.append(fig)
    # ui.add_tab(fig, 'Ap %i' %i)
    # ui.show()

    # Background light curves
    fig, art, *rest = tsplt.plot(apdata.bg.T,
                                 title='bg flux (per pix.)',
                                 draggable=False,
                                 show_hist=True)
    # legend
    hax = fig.axes[1]
    proxies = get_proxy_art(art)
    hax.legend(proxies, labels, loc='upper right', markerscale=3)

    pool.join()
    figs.append(fig)

    return figs


from obstools.aps import ApertureCollection


# ====================================================================================================
def from_params(model, params, scale=3, **kws):
    converged = ~np.isnan(params).any(1)
    ap_data = np.array([model.get_aperture_params(p) for p in params])
    coords = ap_data[converged, :2]  #::-1
    sigma_xy = ap_data[converged, 2:4]
    widths, heights = sigma_xy.T * scale * 2
    angles = np.degrees(ap_data[converged, -1])

    aps = ApertureCollection(coords=coords, widths=widths, heights=heights,
                             angles=angles, **kws)
    return aps, ap_data


# def window_panes(coords, window):
#     from matplotlib.patches import Rectangle
#     from matplotlib.collections import PatchCollection
#     from scipy.spatial.distance import cdist
#
#     sdist = cdist(coords, coords)
#     sdist[np.tril_indices(len(coords))] = np.inf  # since the distance matrix is symmetric, ignore lower half
#     ix = np.where(sdist < window / 2)
#     overlapped = np.unique(ix)
#
#     llc = coords[:, ::-1] - window / 2
#     patches = [Rectangle(coo, window, window) for coo in llc]
#     c = np.array(['g'] * len(coords))
#     c[overlapped] = 'r'
#     rcol = PatchCollection(patches, edgecolor=c, facecolor='none',
#                            lw=1, linestyle=':')
#     return rcol

# ====================================================================================================


from graphical.imagine import VideoDisplayA


# def foo(cube, coords, appars):


# def display_frame_coords(data, foundCoords, params=None, model=None, window=None,
#                          vectors=None, ref=None, outlines=None, save=False,
#                          **kws):
#
#     #imd = ImageDisplay(data, origin='llc')
#
#     if params is not None:
#
#
#
#
#     if window:
#
#
#     if outlines is not None:
#
#
#     if vectors is not None:
#
#
#     fig.tight_layout()
#     if save:
#         fig.savefig(save)
#
#     return fig


# ====================================================================================================
def plot_mean_residuals(modelDb):
    # Plot mean residuals
    from mpl_toolkits.axes_grid1 import AxesGrid

    db = modelDb
    names = {m: m.__class__.__bases__[0].__name__ for m in db.models}

    fig = plt.figure()
    fig.suptitle('Mean Residuals', fontweight='bold')
    grid_images = AxesGrid(fig, 111,  # similar to subplot(212)
                           nrows_ncols=(len(db.gaussians), len(db.ix_fit)),
                           axes_pad=0.1,
                           label_mode="L",  # THIS DOESN'T FUCKING WORK!
                           # share_all = True,
                           cbar_location="right",
                           cbar_mode="edge",
                           cbar_size="7.5%",
                           cbar_pad="0%")

    for i, model in enumerate(db.gaussians):
        name = names[model]
        for j, res in enumerate(db.resData[name]):
            ax = grid_images.axes_column[j][i]
            if i == 0:
                ax.set_title('Star %i' % db.ix_fit[i])
            im = ax.imshow(res)
            ax.set_ylabel(name)
        cbax = grid_images.cbar_axes[i]
        ax.figure.colorbar(im, cax=cbax)

    return fig


# ====================================================================================================
# TODO: plot class
@timer
def plot_q_mon(mon_q_file, save=False):  # fitspath
    from astropy.time import Time

    tq, *qsize = np.loadtxt(str(mon_q_file), delimiter=',', unpack=True)

    fig, ax = plt.subplots(figsize=(16, 8), tight_layout=True)
    # x.plot(tm, memo[0], label='free')
    labels = ['find', 'fit', 'bg', 'phot']
    for i, qs in enumerate(qsize):
        t = Time(tq, format='unix').plot_date
        ax.plot_date(t, qs, '-', label=labels[i])  # np.divide(qs, 5e3)
    ax.set_ylabel('Q size')
    ax.set_xlabel('UT')
    ax.grid()
    ax.legend()

    if save:
        filepath = Path(mon_q_file)
        outpath = filepath.with_suffix('.png')
        fig.savefig(str(outpath))

    return fig

    # plot queue occupancy if available


#    if monitor_qs:
#        plot_q_mon()


# if monitor_cpu:
# t, *occ = np.loadtxt(monitor, delimiter=',', unpack=True)
# fig, ax, *stuff = tsplt.plot(t, occ, errorbar={'ls':'-', 'marker':None},
# show_hist=True,
# labels=['cpu%d'%i for i in range(Ncpus)])
# fig.savefig(monitor+'.png')

@timer
def plot_monitor_data(mon_cpu_file, mon_mem_file):
    from astropy.time import Time

    fig, ax1 = plt.subplots(figsize=(16, 8))
    fig.subplots_adjust(top=0.94,
                        left=0.05,
                        right=0.85,
                        bottom=0.05)

    # plot CPU usage
    tc, *occ = np.loadtxt(str(mon_cpu_file), delimiter=',', unpack=True)
    Ncpus = len(occ)

    labels = ['cpu%i' % i for i in range(Ncpus)]
    cmap = plt.get_cmap('gist_heat')
    cols = cmap(np.linspace(0, 1, Ncpus))
    for i, o in enumerate(occ):
        t = Time(tc, format='unix').plot_date
        ax1.plot_date(t, o, '.', color=cols[i], label=labels[i],
                      lw=1)  # np.divide(qs, 5e3)
    ax1.plot(t, np.mean(occ, 0), 'k-', label='cpu mean')

    ax1.set_xlabel('UT')
    ax1.set_ylabel('Usage (%)')
    ax1.grid()
    leg1 = ax1.legend(bbox_to_anchor=(1.05, 1), loc=2,
                      borderaxespad=0., frameon=True)
    ax1.add_artist(leg1)

    # plot memory usage
    tm, *mem = np.loadtxt(str(mon_mem_file), delimiter=',', unpack=True)

    print('Max memory usage: %.3f Gb' % mem[0].ptp())

    ax2 = ax1.twinx()
    labels = ['used', 'free']
    cols = ['c', 'g']
    for i, m in enumerate(mem):
        t = Time(tm, format='unix').plot_date
        ax2.plot_date(t, m, '-', color=cols[i], label=labels[i])

    ax2.set_ylabel('RAM (Gb)')
    ax2.set_ylim(0)
    leg2 = ax2.legend(bbox_to_anchor=(1.05, 0), loc=3,
                      borderaxespad=0., frameon=True)

    # fig.savefig(monitor+'.png')
    return fig


# ====================================================================================================

if __name__ == '__main__':
    path = Path(
            '/home/hannes/work/mensa_sample_run4/')  # /media/Oceanus/UCT/Observing/data/July_2016/FO_Aqr/SHA_20160708.0041.log
    qfiles = list(path.rglob('phot.q.dat'))
    qfigs = list(map(plot_q_mon, qfiles))

    cpufiles, memfiles = zip(
            *zip(*map(path.rglob, ('phot.cpu.dat', 'phot.mem.dat'))))
    monfigs = list(map(plot_monitor_data, cpufiles, memfiles))
    nlabels = [f.parent.name for f in qfiles]
    wlabels = ['Queues', 'Performance']

    ui = MplMultiTab2D(figures=[qfigs, monfigs], labels=[wlabels, nlabels])
    ui.show()
