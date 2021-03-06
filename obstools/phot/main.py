"""
Main photometry routine for SALTICAM slotmode
"""

# std libs
import os
import sys
import time
import socket
import logging
import itertools as itt
import multiprocessing as mp
from multiprocessing.managers import SyncManager
from pathlib import Path
from collections import defaultdict, OrderedDict

# ===============================================================================
# Check input file | doing this before all the slow imports
if __name__ == '__main__':
    import argparse

    # how many cores?!?
    ncpus = os.cpu_count()

    # parse command line args
    parser = argparse.ArgumentParser(
            'phot',  # fromfile_prefix_chars='@',
            description='Parallelized generic time-series photometry routines')

    parser.add_argument('data_file', type=str,  # type=FitsCube,
                        help='filename of fits data cube to process.')
    parser.add_argument('-ch', '--channel', type=int,  # type=FitsCube,
                        help='amplifier channel', )
    # required=True)
    # TODO: if not given, do all channels!!
    # TODO: process many files / channels at once
    parser.add_argument(
            '-n', '--subset', nargs='*', default=(None,),
            help=(
                "Data subset to process. Useful for testing/debugging."
                """\
                Arguments are as follows:
                    If not given, entire list of files will be used. 
                    If a single integer `k`, first `k` files will be used.
                    If 2 integers (k,  l), all files starting at `k` and ending at `l-1`
                    will be used."""))
    parser.add_argument(
            '-j', '--n_processes', type=int, default=ncpus,
            help='Number of worker processes running concurrently in the pool.'
                 'Default is the value returned by `os.cpu_count()`: %i.'
                 % ncpus)
    parser.add_argument(
            '-k', '--clobber', action='store_true',
            help='Whether to resume computation, or start afresh. Note that the'
                 ' frames specified by the `-n` argument will be recomputed if '
                 'overlapping with previous computation irrespective of the '
                 'value of `--clobber`.')

    parser.add_argument(
            '-a', '--apertures', default='circular',
            choices=['c', 'cir', 'circle', 'circular',
                     'e', 'ell', 'ellipse', 'elliptical'],
            help='Aperture specification')
    # TODO: option for opt

    # plotting
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--plot', action='store_true', default=True,
                       help='Do plots')
    group.add_argument('--no-plots', dest='plot', action='store_false',
                       help="Don't do plots")

    parser.add_argument('--verbose', '-v', action='count')
    parser.add_argument('--version', action='version',
                        version='%(prog)s %s')
    args = parser.parse_args(sys.argv[1:])

    data_path = Path(args.data_file)
    path = data_path.parent
    if not data_path.exists():
        raise IOError('File does not exist: %s' % args.data_file)

    # setup logging processes
    from obstools.phot import log

    # do this here, so we catch external loggers

    # output folders (will be created upon initialization of shared memory)
    # resultsPath = data_path.with_suffix(f'.ch{args.channel}.proc')  #
    resultsPath = data_path.parent / f'ch{args.channel}'
    logPath = resultsPath / 'logs'

    logQ = mp.Queue()  # The logging queue for workers
    # TODO: open logs in append mode if resume
    config_main, config_listener, config_worker = log.config(logPath, logQ)
    logging.config.dictConfig(config_main)

    # raise SystemExit
# ===============================================================================

# execution time stamps
from motley.profiler.timers import Chrono

chronos = Chrono()
# TODO: option for active reporting; inherit from LoggingMixin, make Singleton
chronos.mark('start')

# third-party libs
chronos.mark('Imports: 3rd party')
import addict
import numpy as np
import more_itertools as mit
from joblib.pool import MemmappingPool
# from astropy.io import fits
from IPython import embed

# local libs
chronos.mark('Imports: Local')
import motley
from salticam import slotmode
from salticam.slotmode.tracking import SlotModeTracker
from salticam.slotmode.modelling.image import (FrameTransferBleed,
                                               SlotModeBackground, FTB_WIDTH)
from graphical.imagine import ImageDisplay, VideoDisplay
from graphical.multitab import MplMultiTab
from recipes.dict import AttrReadItem
from recipes.io import WarningTraceback
from recipes.interactive import is_interactive
from recipes.parallel.synced import SyncedCounter, SyncedArray

from obstools.phot.utils import ImageSampler
from obstools.phot.proc import TaskExecutor, FrameProcessor
from obstools.phot.segmentation import SegmentationHelper, detect_loop
from obstools.modelling.utils import load_memmap, load_memmap_nans
from obstools.phot.utils import shift_combine
from salticam.slotmode.modelling.image import MedianEstimator
from obstools.modelling.image import SegmentedImageModel
from salticam.slotmode.imaging import display_slot_image
from recipes.io import save_pickle, load_pickle
from obstools.fastfits import FitsCube

from IPython.core import ultratb

# ipython style syntax highlighting for exceptions
sys.excepthook = ultratb.ColorTB()

# version
__version__ = 3.14519

wtb = WarningTraceback()
wtb.on()


def GUESS_KNOTS():
    """special sentinel triggering knot guessing algorithm"""


def OPT_KNOTS():
    """special sentinel triggering knot optimization algorithm"""


class MiddleFinger(Exception):
    def __init__(self, msg=u"\U0001F595", *args):
        super().__init__(msg, *args)


def load_data(args):
    subset = slice(*args.subset)
    filename = args.data_file
    if filename.endswith('fits'):
        logger.info('Loading FITS file: %s', filename)
        args.data_file = FitsCube(filename)
        data = args.data_file.data
        header = args.data_file.header

        # print observation / object / ccd / PI info
        slotmode._pprint_header(header, n=len(data))
    else:
        # load image data (memmap shape (n, r, c))
        args.data_file = data = np.lib.format.open_memmap(filename)
        header = None

    if data.ndim == 4:
        if args.channel is None:
            'TODO: do all channels'
            raise ValueError('Please give channel')
    else:
        if args.channel is None:
            raise ValueError('Need to know which channel this image stack '
                             'corresponds to!')
    args.channel =
    return data[subset], header, subset.indices(len(data))


# seq = functools.partial(seq_repr_trunc, max_items=3)


# TODO: colourful logs - like daquiry / technicolor

# TODO: for slotmode: if stars on other amplifiers, can use these to get sky
# variability and decorellate TS

# todo: these samples can be done with Mixin class for FitsCube
#  think `cube.sample(100, interval=(2e3, 3e3).median()`         # :))

# ===============================================================================
# def create_sample_image(interval, ncomb):
#     image = sampler.median(ncomb, interval)
#     scale = nd_sampler(image, np.median, 100)
#     mimage = np.ma.MaskedArray(image, BAD_PIXEL_MASK, copy=True)
#     # copy here prevents bad_pixel_mask to be altered (only important if
#     # processing is sequential)
#     return mimage / scale, scale

def create_sample_image(i, image_sampler, interval, sample_size, output,
                        scale=None):
    img = image_sampler.median(sample_size, interval)
    if scale is not None:
        s = np.ma.median(img)  # nd_sampler(img, np.median, 500)
        img = img / s
        scale[i] = s

    output[i] = img


# def rescale_image(i, images, scales, statistic=np.ma.median):
#     scales[i] = s = statistic(images[i])
#     images[i] /= s
#     return images[i]  # return useful for case array not memory map
#
#
# def prepare_image_fit(i, tracker, modelled_images, ij0, scales=None):
#     image = modelled_images[i]
#     image = np.ma.MaskedArray(image,
#                               tracker.get_object_mask(ij0, ij0 + image.shape))
#     if scales is not None:
#         scales[i] = s = np.ma.median(image)
#         modelled_images[i] /= s
#     return image


def detect_with_model(i, image, model, seg_data, params, residuals):
    # median scale image for better convergence statistics
    scale = np.ma.median(np.ma.MaskedArray(image, BAD_PIXEL_MASK))

    # Multi-threshold blob detection with bg model
    seg, groups, info, result, residual = \
        detect_loop(image / scale,
                    BAD_PIXEL_MASK,
                    SNR,
                    dilate=DILATE,
                    max_iter=1,
                    bg_model=model,
                    opt_kws=dict(method='BFGS'),
                    report=True)

    seg_data[i] = seg.data
    residuals[i] = residual
    params[i] = result

    return seg, groups, info, result, residual


# def prepare_image(i, images):
#     tracker.prepare_image(images[i])


def detect_measure(i, image, seg_data):
    mask = False
    seg = SegmentationHelper.detect(image, mask, None, NCOMB, SNR, NPIXELS[0],
                                    DILATE[0])

    seg_data[i] = seg.data
    counts = seg.sum(image) - seg.median(image, [0]) * seg.areas
    return seg, seg.com_bg(image), counts


def init_mem_modelling(model, folder, n, n_knots, n_bright, n_resi=None,
                       fill=np.nan, clobber=False, **filenames):
    """
    Initialize shared memory for modelling run

    Parameters
    ----------
    model
    folder
    n
    fill
    clobber

    Returns
    -------

    """
    # default filenames
    folder = Path(folder)
    filenames_ = dict(params='bg.par',
                      # scales='sample_median.dat',
                      knots='knots.dat',
                      bleeding='bleeding.dat',
                      residuals='residuals.dat',
                      # TODO: FITS HERE!!!! + add header info on bg sub
                      gof='chi2r.dat')
    filenames_.update(filenames)
    filenames_ = AttrReadItem({_: folder / fn for _, fn in filenames_.items()})

    if n_resi is None:
        n_resi = n

    shared_memory = addict.Dict()
    shared_memory.params = model._init_mem(filenames_.params,
                                           n, fill, clobber=clobber)
    # shared_memory.params = load_memmap(
    #         filenames_.params,
    #         (n, model.dof), float, fill, clobber)

    # shared_memory.scales = load_memmap(filenames_.scales,
    #                                        n, clobber=clobber)

    dtype = list(zip('yx', [int] * 2, zip(model.n_knots)))
    shared_memory.knots = load_memmap(filenames_.knots,
                                      n_knots, dtype, 0, clobber)

    # dtype = np.dtype([('chi2r', float), ('aic', float)]),
    shared_memory.gof = load_memmap_nans(filenames_.gof,
                                         n,
                                         clobber=clobber)

    # TODO: merge into single image model
    shared_memory.bleeding = load_memmap(filenames_.bleeding,
                                         (n_resi, n_bright, FTB_WIDTH),
                                         float, fill, clobber)

    shared_memory.residuals = load_memmap(filenames_.residuals,
                                          (n_resi,) + model.segm.shape,
                                          float, 0,
                                          clobber)

    return AttrReadItem(shared_memory)


def guess_knots(i, spline, image, knots):
    knots[i] = spline.guess_knots(image, args.channel, edges=False)


def get_knots_from_mem(knot_mmap, i, edges):
    knots_mem = knot_mmap[i]
    n_knots = np.add(list(map(len, knots_mem)), 2)
    knots = np.zeros((), list(zip('yx', [int] * 2, n_knots)))
    knots['y'][-1], knots['x'][-1] = edges
    knots['y'][1:-1], knots['x'][1:-1] = knots_mem
    return knots.tolist()


# def prep_mask(obj_mask, xy_off):
#     # note: replicates tracker.get_object_mask
#     ij0 = i0, j0 = xy_off
#     i1, j1 = ij0 + ishape
#     # print( i0, j0, i1, j1)
#     return obj_mask[i0:i1, j0:j1] | BAD_PIXEL_MASK


def spline_fit(i, image, spline, shared_memory, do_knot_search,
               index_knots, **opt_kws):
    # median rescaled image
    scale = np.ma.median(image)  # scale = nd_sampler(data, np.median, 100)
    image_scaled = image / scale

    # optimize knots
    if do_knot_search:
        r_best = spline.optimize_knots(image_scaled, info=f'frame {i}',
                                       **opt_kws)
        # print('setting knots %i, %s', ik, spline.knots)
        shared_memory.knots[index_knots]['y'] = spline.knots.y[1:-1]
        shared_memory.knots[index_knots]['x'] = spline.knots.x[1:-1]

    # fit background
    p = spline.fit(image_scaled, **opt_kws)
    shared_memory.params[i] = tuple(r * scale for r in p.tolist())
    # p = shared_memory.params[i]

    # todo: need in-group evaluation for the statement below to work for the
    #  hierarchical group model
    # use only fitted data to compute GoF
    labels_bg = list(spline.models.keys())
    mask = spline.segm.mask_segments(image, ignore_labels=labels_bg)
    shared_memory.gof[i] = spline.redchi(p, mask)

    # TODO: sky measure overall noise with Gaussian fit ?
    return i


def update_model_segments(tracker, models, ij_start, ishape):
    # set spline knots
    # since pickled clones of the model are used in each forked process when
    # doing optimization, the knot values are not preserved. we need to set
    # the knots
    # ishape = data.shape[-2:]

    spline, ftb = models

    # knots = get_knots_from_mem(shared_memory.knots, ik, ishape)
    spline.set_knots(spline.knots, preserve_labels=False)

    # update segmentation for objects (camera offset)
    seg = tracker.get_segments(ij_start, ishape)
    # FIXME: ftb regions may be wrong if over global seg boundary ....

    _, new_labels = spline.segm.add_segments(seg)

    # todo: better way - optimize!!!
    new_groups = {g: l + spline.nmodels for g, l in tracker.groups.items()}

    # update streak labels
    ftb.set_models(dict(zip(new_groups['streaks'], ftb.models.values())))
    return seg


def bgw(i, data, section, ij_start, tracker, models, shared_memory,
        knots, index_knots, bad_pix, opt_kws=None):
    """"""
    # todo: rename i - index_params
    #
    opt_kws = opt_kws or {}

    # get image stack
    subset = data[section]

    # get sample background image (median filter across frames)
    msub = np.ma.array(subset, ndmin=3)
    image = np.ma.median(msub, 0)
    if bad_pix is not None:
        image[bad_pix] = np.ma.masked

    # models
    spline, ftb = models

    # deal with knots
    do_knot_search = False
    if knots is GUESS_KNOTS:
        knots = spline.guess_knots(image, 1)  # args.channel
        shared_memory.knots[index_knots]['y'] = knots[0][1:-1]
        shared_memory.knots[index_knots]['x'] = knots[1][1:-1]
        spline.set_knots(knots, preserve_labels=True)
    elif knots is OPT_KNOTS:
        do_knot_search = True
    elif knots is not None:
        spline.set_knots(knots, preserve_labels=True)

    # if do_update_segments:
    # note need to ensure knots have been set else fails below
    ishape = data.shape[-2:]
    # TODO: don not have to recompute if ij_start same. memoize
    # update segmentation for camera position
    seg = update_model_segments(tracker, models, ij_start, ishape)

    # fit vignetting
    q = spline_fit(i, image, spline, shared_memory, do_knot_search,
                   index_knots, **opt_kws)

    if q is not None:
        resi = background_subtract(i, msub, section, models, shared_memory,
                                   bad_pix)

    return q


def aggregate_flat(flat, data, interval, tracker, start):
    # NOTE: this estimator is not that great.
    subset = data[slice(*interval)]
    mask = tracker.select_overlap(tracker.cal_mask, start, data.shape[-2:])
    mask = mask | tracker.mask.bad_pixels
    flat.aggregate(subset, mask)


def background_subtract(i, data, section, models, shared_memory, bad_pix):
    #
    spline, ftb = models

    shared_memory.residuals[section] = spline.residuals(
            shared_memory.params[i], data)

    # remove frame transfer streaks
    if bad_pix is not None:
        data[..., bad_pix] = np.ma.masked

    shared_memory.bleeding[section], resi = \
        ftb.fit(shared_memory.residuals[section], reduce=True, keepdims=True)
    shared_memory.residuals[section] = resi
    return resi


def background_loop(interval, data, tracker, ij_start, models,
                    shared_memory, n_comb, knot_search_every, bad_pixel_mask,
                    opt_kws=None):
    # TODO: maybe add data to shared memory container ???
    opt_kws = opt_kws or {}
    i0, i1 = interval

    # first round take the start indices as that of the nearest sample image

    # do_update_segments = True
    knots = GUESS_KNOTS
    for i in range(i0, i1, n_comb):
        if (i % 500) == 0:
            print(i)

        # knots = k_opts[(i % knot_search_every) == 0]
        if (i % knot_search_every) == 0:
            # do knot search
            knots = OPT_KNOTS

        section = slice(i, i + n_comb)
        # print('ij_start', ij_start)

        # if np.isnan(np.hstack(shared_memory.params[ix])).any():
        # bgFitTask
        # ij_start = tracker.xy_offsets[i].round().astype(int)
        bgw(i // n_comb, data, section, ij_start, tracker, models,
            shared_memory, knots, i // knot_search_every,
            bad_pixel_mask, opt_kws)

        # knots will not be updated unless knot search is run
        knots = None

        # track on residuals
        tracker.track_loop(range(i, i + n_comb), shared_memory.residuals)
        # do_update_segments = np.any(tracker.current_offset != ij_start)
        # ij_start = tracker.current_start


def deep_detect(images, tracker, xy_offsets, indices_use, bad_pixels,
                report=True):
    # combine residuals
    mr = np.ma.array(images)
    mr.mask = bad_pixels  # BAD_PIXEL_MASK
    xy_off = xy_offsets[indices_use]
    mean_residuals = shift_combine(mr, xy_off, 'median', extend=True)
    # better statistic at edges with median

    # run deep detection on mean residuals
    FTB_THRESH_COUNTS = 3e4
    NPIXELS = (5, 3, 2)
    DILATE = (2, 1)
    seg_deep, groups_, info_, _, _ = \
        detect_loop(mean_residuals,
                    dilate=DILATE,
                    npixels=NPIXELS,
                    report=True)

    # merge detection groups
    groups = defaultdict(list)
    for inf, grp in zip(info_, groups_):
        groups[str(inf)].extend(grp)

    # relabel bright stars
    counts = seg_deep.count_sort(mean_residuals)
    bright = np.where(counts > FTB_THRESH_COUNTS)[0]

    ng = 2
    g = groups_[:ng]
    labels_bright = np.hstack(g)
    last = labels_bright[-1]
    cxx = seg_deep.com(mean_residuals, labels_bright)

    if report:
        from motley.table import Table
        from recipes.pprint import numeric_array

        gn = []
        for i, k in enumerate(map(len, g)):
            gn.extend([i] * k)

        cc = numeric_array(counts[:last], precision=1, significant=3,
                           switch=4).astype('O')
        cc[bright] = list(map(motley.yellow, cc[bright]))
        tbl = Table(np.column_stack([labels_bright, gn, cxx, cc]),
                    title=(f'{last} brightest objects'
                           '\nmean residual image'),
                    col_headers=['label', 'group', 'y', 'x', 'counts'],
                    minimalist=True, align=list('<<>>>'))

        logger = logging.getLogger('root')
        logger.info('\n' + str(tbl))

    # return seg_deep, mean_residuals

    # xy_track = tracker.seg.com(labels=tracker.use_labels)
    # # ix_track = tuple(xy_track.round().astype(int).T)
    # ix_track = tuple(np.round(xy_track + indices_start.min(0)).astype(int).T)
    # old_labels = seg_deep.data[ix_track]
    # new_labels = np.arange(1, old_labels.max() + 1)
    # missing = set(new_labels) - set(old_labels)
    # old_labels = np.hstack([old_labels, list(missing)])

    # return seg_deep, old_labels, new_labels
    # seg_deep.relabel_many(old_labels, new_labels)

    # update tracker segments
    # todo: let tracker keep track of minimal / maximal offsets
    ranges = [np.floor(xy_off.min(0)) - np.floor(xy_offsets.min(0)),
              np.ceil(xy_off.max(0)) - np.ceil(xy_offsets.max(0)) +
              tracker.segm.shape]
    section = tuple(map(slice, *np.array(ranges, int)))

    # get new segments (tracker)
    new_seg = np.zeros_like(tracker.segm.data)
    new_seg[section] = seg_deep.data

    # add ftb regions
    new_seg, labels_streaks = FrameTransferBleed.adapt_segments(
            new_seg, bright + 1)

    # update tracker
    tracker.segm.data = new_seg.data

    # get new groups
    new_groups = OrderedDict(bright=bright + 1)
    new_groups.update(groups)
    new_groups['streaks'] = labels_streaks
    tracker.groups.update(new_groups)

    return new_seg, mean_residuals, counts, tbl


def phot_worker(i, proc, data, residue, tracker,
                p0ap, sky_width, sky_buf):
    coords = tracker.get_coord(i)
    proc.optimal_aperture_photometry(i, data, residue, coords, tracker,
                                     p0ap, sky_width, sky_buf)


def photometry(interval, proc, data, residue, tracker, p0ap,
               sky_width, sky_buf):
    # main routine for image processing for frames from data in interval
    logger = logging.getLogger()
    logger.info('Starting frame processing for interval %s', interval)

    for i in range(*interval):
        # photTask
        phot_worker(i, proc, data, residue, tracker,
                    p0ap, sky_width, sky_buf)


def flat_field_copy_mmap(data, ff, region, loc):
    output = np.lib.format.open_memmap(loc, 'w+', shape=data.shape)
    # note: the following 2 lines very slow (minutes for large data sets)
    # copy data
    output[:] = data
    output[:, region] /= ff[region]
    return output


def display(image, title=None, ui=None, **kws):  # display_image ??
    if isinstance(image, SegmentationHelper):
        im = image.display(**kws)
    else:
        im = ImageDisplay(image, **kws)

    if title:
        im.ax.set_title(title)

    if args.live:
        idisplay(im.figure)
    return im


from graphical.imagine import VideoDisplayA


# class MyManager(Manager):
#     pass


# MyManager.register('ProgressBar', SyncedProgressLogger)


def Manager():
    m = SyncManager()
    m.start()
    return m


def task(size, max_fail=None, time=False):
    # a little task factory
    counter = manager.Counter()
    fail_counter = manager.Counter()
    return TaskExecutor(size, counter, fail_counter, max_fail, time)


class FlatFieldEstimator(object):
    def __init__(self, folder, pixel_mask, lock, stat=np.ma.median,
                 clobber=True):
        #
        self.use = pixel_mask
        self.shape = pixel_mask.shape
        size = pixel_mask.sum()
        self.stat = stat

        # persistent shared mem
        self.sum = load_memmap(folder / 'sum.dat', size, float, 0,
                               clobber=clobber)
        self.count = load_memmap(folder / 'count.dat', size, int, 0,
                                 clobber=clobber)
        # sync lock
        self.lock = lock

    def aggregate(self, data, ignore_pix, neighbourhood=7):
        # update flat field data
        mdat = np.ma.MaskedArray(data)
        mdat[..., ignore_pix] = np.ma.masked

        neighbours = slotmode.view_neighbours(mdat, neighbourhood)
        leading_dim = (slice(None),) * (data.ndim - 2)
        use = leading_dim + (self.use,)
        #
        ratio = data[use] / self.stat(neighbours[use], (-1, -2))
        counts = np.logical_not(ratio.mask).sum(0)

        # update flat field
        with self.lock:
            # these operations not atomic
            self.sum += ratio.sum(0)
            self.count += counts

    def finalize(self):
        ff = np.ones(self.shape)
        ff[self.use] = self.sum / self.count
        return ff


if __name__ == '__main__':
    #
    chronos.mark('Main start')

    # say hello
    header = motley.banner('⚡ ObsTools Photometry ⚡', align='^')
    header = header + '\nv%f\n' % __version__
    print(header)

    # add some args manually
    args.live = is_interactive()

    # file path container
    # ==========================================================================
    # output folders (will be created upon initialization of shared memory)
    # TODO: parent directory for all channel reductions
    suffix = 'proc'
    ch = args.channel
    clobber = args.clobber

    paths = addict.Dict()
    paths.input = Path(args.data_file)
    paths.results = resultsPath  # = paths.input.parent / f'ch{ch}'
    # data_path.with_suffix(f'.ch{ch}.{suffix}')  #
    paths.timestamps = paths.input.with_suffix('.time')

    paths.modelling = modellingPath = resultsPath / 'modelling'
    paths.models = paths.modelling / 'models.pkl'
    paths.tracking = resultsPath / 'tracking'
    paths.tracker = paths.tracking / 'tracker.pkl'
    paths.detection = resultsPath / 'detection'
    paths.sample = paths.detection / 'sample'
    paths.modelling0 = paths.detection / 'modelling'
    paths.start_idx = paths.modelling0 / 'start_idx.dat'  # todo: eliminate

    paths.calib = resultsPath / 'calib'
    paths.flat = paths.calib / 'flat.npz'
    # TODO: maybe flat.image.npz and flat.pixels.npz

    paths.phot = photPath = resultsPath / 'photometry'
    paths.photometry.opt_stat = photPath / 'opt.stat'

    paths.log = resultsPath / 'logs'
    paths.figures = resultsPath / 'plots'

    # create logging directory
    if not paths.log.exists():
        paths.log.mkdir(parents=True)

    # create directory for plots
    if not paths.figures.exists():
        paths.figures.mkdir()

    # ===============================================================================
    # Decide how to log based on where we're running
    logging.captureWarnings(True)

    if socket.gethostname().startswith('mensa'):
        plot_lightcurves = plot_diagnostics = False
        print_progress = False
        log_progress = True
    else:
        plot_lightcurves = plot_diagnostics = args.plot
        print_progress = True
        log_progress = False

    if args.live:  # turn off logging when running interactively (debug)
        from recipes.interactive import exit_register
        from IPython.display import display as idisplay

        log_progress = print_progress = False
        monitor_mem = False
        monitor_cpu = False
        # monitor_qs = False
    else:
        from atexit import register as exit_register
        from recipes.io.utils import WarningTraceback

        # check_mem = True    # prevent execution if not enough memory available
        monitor_mem = False  # True
        monitor_cpu = False  # True  # True
        # monitor_qs = True  # False#

        # setup warnings to print full traceback
        wtb = WarningTraceback()

    # print section timing report at the end
    exit_register(chronos.report)

    # create log listener process
    logger = logging.getLogger()
    logger.info('Creating log listener')
    stop_logging_event = mp.Event()
    logListener = mp.Process(target=log.listener_process, name='logListener',
                             args=(logQ, stop_logging_event, config_listener))
    logListener.start()
    logger.info('Log listener active')
    #
    chronos.mark('Logging setup')

    # ==========================================================================

    # # check for calibrated cube
    # ccPath = paths.results / 'cube.ff.npy'
    # is_calibrated = ccPath.exists()
    # if is_calibrated:
    #     cube = np.lib.format.open_memmap(ccPath)
    # else:
    #     cube = cube4[:, ch]

    # # check / resolve options
    # clobber = args.clobber
    # # subset of frames for compute
    # if args.subset is None:
    #     subset = (0, len(cube))
    # elif len(args.subset) == 1:
    #     subset = (0, min(args.subset[0], len(cube)))
    # elif len(args.subset) == 2:
    #     subset = args.subset
    # else:
    #     raise ValueError('Invalid subset: %s' % args.subset)
    # # number of frames to process
    # subsize = np.ptp(subset)

    data, header, subset = load_data(args)
    subsize = np.ptp(subset)
    n = len(data)
    ishape = data.shape[-2:]

    chix = int(ch) if ch else ...
    frame0 = data[0, chix]

    # TODO ---------------------------------------------------------------------
    #  do for many channels!!!!!!!!!!!!!
    #  -------------------------------------------------------------------------

    #
    # calibration (flat fielding)
    # -----------
    is_calibrated = True  # FIXME: HACK.  this should be done in parallel
    if not is_calibrated:
        if paths.flat.exists():
            # Some of the bad pixels can be flat fielded out
            logger.info('Loading flat field image from %r', paths.flat.name)
            ff = np.load(paths.flat)['arr_0']  # FIXME
            # bad pixels
            BAD_PIXEL_MASK = np.zeros(ishape, bool)
            BAD_PIXEL_MASK[:, 0] = True  # FIXME

            FLAT_PIXEL_MASK = slotmode.get_bad_pixel_mask(frame0, ch)
            FLAT_PIXEL_MASK[:, 0] = False  # FIXME

            # WARNING: very slow! # TODO: parallelize
            cube = flat_field_copy_mmap(cube4[:, ch], ff, FLAT_PIXEL_MASK,
                                        ccPath)
        else:
            raise NotImplementedError('Optionally create flat field image')
            # also save calibrated cube

    else:
        BAD_PIXEL_MASK = slotmode.get_bad_pixel_mask(frame0, ch)

        # construct flat field for known bad pixels by computing the ratio
        # between the median pixel value and the median of it's neighbours

    # ==========================================================================
    # Image Processing setup
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # helper objects
    proc = FrameProcessor()
    image_sampler = ImageSampler(data)

    # ֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍
    if args.plot and data.ndim == 4:
        # plot quick-look image for all 4 amplifier channels
        idisplay(display_slot_image(data[np.random.randint(0, n, 1)], ch))
    # ֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍

    # FIXME: any Exception that happens below will stall the log listner indefinitely

    # TODO: plot bad pixels!!

    # calib = (None, None)

    # TODO: save this somewhere so it's quicker to resume
    # TODO: same for all classes here

    # estimate maximal positional shift of stars by running detection loop on
    # maximal image of 1000 frames evenly distributed across the cube
    # mxshift, maxImage, segImx = check_image_drift(cube, 1000, bad_pixel_mask,
    #                                               snr=5)

    # create psf models
    # models = EllipticalGaussianPSF(),
    # models = ()
    # create image modeller
    # mdlr = ImageModeller(tracker.seg, models, mdlBG,
    #                      use_labels=tracker.use_labels)

    # create object that generates the apertures from modelling results
    # cmb = AperturesFromModel(3, (8, 12))

    chronos.mark('Pre-compute')
    # input('Musical interlude')

    # ===============================================================================
    # create shared memory
    # aperture positions / radii / angles
    # nstars = tracker.nsegs
    # # ngroups = tracker.ngroups
    # naps = 1  # number of apertures per star
    #
    #
    # # create frame processor
    # proc = FrameProcessor()
    # proc.init_mem(n, nstars, ngroups, naps, resultsPath, clobber=clobber)
    # # TODO: folder structure for multiple aperture types circular /
    # # elliptical / optimal

    # chronos.mark('Memory alloc')

    # ===============================================================================
    # main compute
    # synced counter to keep track of how many jobs have been completed
    manager = Manager()

    # task executor  # there might be a better one in joblib ??
    # Task = task(subsize)  # PhotometryTask

    # worker = Task(proc.process)

    # setup
    # --------------------------------------------------------------------------
    # split work
    N_DETECT_PER_PROCESS = 3
    # todo: instead, continue measuring until accurate positions found
    # TODO: ALSO, can get even more accurate positions by using bright stars
    #  in other channels

    N_FIT_PER_PROCESS = 1
    n_fit = N_FIT_PER_PROCESS * args.n_processes
    n_detect = round(N_DETECT_PER_PROCESS * args.n_processes)
    frames_per_process = subsize // args.n_processes

    chunks = mit.divide(n_detect, range(*subset))
    pairs = list(mit.pairwise(next(zip(*chunks)) + (subset[1],)))

    # global parameters for object detection
    NCOMB = 10
    SNR = 3
    NPIXELS = (5, 3, 2)
    DILATE = (2, 1)

    # global background subtraction parameters
    SPLINE_ORDERS = (5, 1, 5), (1, 5)
    KNOT_SEARCH_EVERY = 5 * NCOMB
    n_bg = (subsize // NCOMB) + 1
    n_ks = subsize // KNOT_SEARCH_EVERY
    #

    # counts threshold for frame transfer bleed
    FTB_THRESH_COUNTS = 3e4  # total object counts in electrons
    # stars below this threshold will not be used to track camera movement
    # TRACKING_SNR_THRESH = 1.25

    # acceptance fraction for valid detection across sample images
    SEG_MERGE_ACCEPT = 0  # .15
    # dilate final (global) segmentation image by this much
    POST_MERGE_DILATE = 3

    # task allocation
    # detectionTask = task(n_detect, '30%', time=True)(detect_with_model)

    # note TaskExecutor instances can be accessed via `task.__self__`
    #  attribute of the `catch` method returned by the `task` decorator

    try:
        # TODO: check existing sample images, models, segmentation, tracker,
        #  etc for hot start

        # Fork the worker processes to perform computation concurrently
        logger.info('About to fork into %i processes', args.n_processes)

        # initialize worker pool
        pool = MemmappingPool(args.n_processes, initializer=log.worker_init,
                              initargs=(config_worker,))

        if paths.tracker.exists() and not clobber:
            # can load segmentation from previous detection run!
            logger.info('Loading tracker & models from previous run.')  #
            # todo: date.  do_version_check !

            tracker = load_pickle(paths.tracker)
            models = model, ftb = load_pickle(paths.models)
            start = load_pickle(paths.start_idx)
            # need also to set a few variables
            n_bright = len(tracker.groups.bright)

            # TODO: plot the things!!

        else:
            logger.info(f'Creating {n_detect} sample images: '
                        f'median combine ({NCOMB} / {subsize // n_detect})')

            # ᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏ
            sample_dims = (n_detect,) + tuple(ishape)
            sample_images = load_memmap(
                    paths.sample / 'images.dat',
                    sample_dims,
                    clobber=clobber)
            seg_data = load_memmap(paths.sample / 'segmentations.dat',
                                   # todo tmp
                                   sample_dims,
                                   int, 0,
                                   clobber=clobber)
            # FIXME: this doesn't really need to persist if you have global seg
            # ᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏ

            # //////////////////////////////////////////////////////////////////////
            # create sample images
            pool.starmap(create_sample_image,
                         ((i, image_sampler, interval, NCOMB, sample_images,
                           None)
                          for i, interval in enumerate(pairs)))

            # ֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍
            # Plot one of the sample images per channel
            if args.plot:
                t_exp = header['EXPTIME']
                im = display(sample_images[0],
                             (f"Sample image "
                              f"(median {NCOMB} images:"
                              f" {t_exp * NCOMB} s exposure)"))
                # not plotting positions on image since positions are
                # relative to global segmentattion
            # ֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍

            # detect stars (initial)
            segmentations, coms, counts = zip(
                    *pool.starmap(detect_measure, ((i, im, seg_data) for
                                                   i, im in
                                                   enumerate(sample_images))))

            # //////////////////////////////////////////////////////////////////////
            # init tracker
            tracker, xy, centres, xy_offsets, counts_med = \
                SlotModeTracker.from_measurements(seg_data, coms, counts,
                                                  SEG_MERGE_ACCEPT,
                                                  POST_MERGE_DILATE,
                                                  0.5,
                                                  # required_positional_accuracy
                                                  BAD_PIXEL_MASK,
                                                  FTB_THRESH_COUNTS,
                                                  FTB_WIDTH)
            # TODO: print some info about the model: dof etc



            n_bright = len(tracker.groups.bright)
            # n_track = tracker.nlabels

            # get indices for section of the extended segmentation
            start = np.abs(
                    (xy_offsets + tracker.zero_point).round().astype(int))
            stop = start + ishape

            # create masks
            tracker.masks.prepare()  # FIXME: do you even need this???

            # ֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍
            # TODO: separate Process for the plotting
            if args.plot:
                from obstools.phot.diagnostics import plot_position_measures

                # positions
                fig, axes = plot_position_measures(xy, centres, xy_offsets)
                fig.suptitle('Position Measurements')

                # segmentation
                im = tracker.segm.display()
                im.ax.set_title('Global segmentation (round 0)')
                im.ax.plot(*(centres - tracker.zero_point).T[::-1], 'gx')

                if args.live:
                    idisplay(fig)
                    idisplay(im.figure)

            # ֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍

            # init background model todo:  method from_cube here ??
            sample_images_masked = np.ma.array(sample_images)
            sample_images_masked[:, BAD_PIXEL_MASK] = np.ma.masked
            mean_image = shift_combine(sample_images_masked, xy_offsets)
            model, _ = SlotModeBackground.from_image(mean_image,
                                                     args.channel,
                                                     SPLINE_ORDERS, )
            # restrict model parameter space for now
            corner_labels = [5, 6]
            for l in corner_labels:
                m = model.models[l]
                m.free[:] = False
                m.free[2, 2:] = True
                m.free[2:, 2] = True
                # model.diagonal_freedom()

            # disable checks for nan/inf
            model.do_checks = False

            # start = (xy_offsets - xy_offsets.min(0)).round().astype(int)
            # start = -xy_offsets.round().astype(int)

            ix_ok, = np.where(~start.mask.any(1))
            ix_use = np.random.choice(ix_ok, n_fit, replace=False)
            ix_use.sort()
            sample_images_to_model = sample_images[ix_use]
            indices_start = start[ix_use]
            indices_stop = indices_start + ishape

            # add object detections
            ext_image_section = tuple(
                    map(slice, indices_start[0], indices_stop[0]))
            # seg_data = tracker.seg.data[ext_image_section]
            _, new_labels = model.segm.add_segments(
                    tracker.segm.data[ext_image_section])
            new_groups = {g: l + model.nmodels for g, l in
                          tracker.groups.items()}
            # model.groups.update(new_groups)

            # Frame transfer bleeding model
            ftb = FrameTransferBleed(model.segm, new_groups['streaks'])
            ftb.do_checks = False

            models = (model, ftb)

            # ᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏ
            # create shared memory (pre run)
            shared_memory = init_mem_modelling(model, paths.modelling0, n_fit,
                                               n_fit,
                                               n_bright, clobber=clobber)
            # shared_memory.residuals[:] = sample_images[ix_use]
            # ᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏ

            # raise SystemExit

            # //////////////////////////////////////////////////////////////////
            # mask stars
            # modelled_images = pool.starmap(
            #         tracker.prepare_image,
            #         zip(sample_images[ix_use], indices_start))

            # rescale images
            # modelled_images = np.ma.array(modelled_images)  # copy
            # modelled_images = pool.starmap(
            #         rescale_image, ((i, modelled_images, shared_memory.scales)
            #                         for i in range(n_fit)))
            # estimate knot positions
            # pool.starmap(guess_knots,
            #              ((i, model, image, shared_memory.knots)
            #               for i, image in enumerate(sample_images_to_model)))

            # /////////////////////////////////////////////////////////////////

            method = 'BFGS'
            # note: using th BFGS algorithm has a number of advantages:
            #  1: Less sensitivity to outliers
            #  2: Less likely to generating spurious high background that may be
            #  detected as objects upon subsequent iterations
            #  3: Can still yield reasonable solutions even when dof exceeds ndata
            #  Disadvantages:
            #   Considerably slower convergence rates

            # wrap task execution
            preFitTask = task(n_fit, '30%')(bgw)
            #

            gofs = []
            knots = [GUESS_KNOTS] * n_fit
            p0 = [None] * n_fit
            counter = itt.count()

            while True:
                t0 = time.time()
                count = next(counter)
                logger.info(f'Deep detect round {count}')

                if count > 0:
                    # once we have isolated background region, expect sky
                    # distribution to be gaussian and we can safely switch to
                    # leastsq and enjoy a significant performance boost
                    method = 'leastsq'
                    # note: leastsq (Levenberg-Marquad) is ~4x faster than other
                    #  minimizers. This is a good option to choose when fitting
                    #  the sample images that are relatively smooth due to the
                    #  noise filtering effect of averaging multiple frames
                    #  together.  However, the algorithm is exquisitely sensitive
                    #  to outliers such as can be introduced by cosmic ray hits.
                    #  For subtracting the background on individual frames it is
                    #  far better to choose BFGS fitting algorithm that is more
                    #  robust against outliers.

                    # expand search to full model parameter space
                    # model.full_freedom()

                    # load previous parameters here for performance gain
                    # knots = pool.starmap(get_knots_from_mem,
                    #                      ((shared_memory.knots, i, ishape)
                    #                       for i in range(n_fit)))
                    knots = [OPT_KNOTS] * n_fit
                    p0 = shared_memory.params

                # reset counters for new loop
                preFitTask.__self__.reset()
                # fit background
                logger.info('Fitting sample images')
                # do_knot_search = (count == 0)
                # //////////////////////////////////////////////////////////////////
                successful = pool.starmap(
                        preFitTask,
                        ((i, sample_images_to_model, i, indices_start[i],
                          tracker, models, shared_memory, knots[i], i,
                          BAD_PIXEL_MASK,
                          dict(method=method, p0=p0[i]))
                         for i in range(n_fit)))
                successful = [_ for _ in successful if _ is not None]
                # //////////////////////////////////////////////////////////////////

                # Detect objects in residual image
                seg_deep, mean_residuals, counts, tbl = deep_detect(
                        shared_memory.residuals[successful],
                        tracker, xy_offsets, ix_use[successful],
                        BAD_PIXEL_MASK)

                # TODO: detect_loop can report GoF

                # ֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍
                if args.plot:
                    display(seg_deep, f'Segmentation (round {count})')
                    display(mean_residuals, f'Residuals (round {count})')

                # ֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍

                gofs.append(np.array(shared_memory.gof))

                # TODO: print specs for these detections
                # nsp = tracker.groups[3][-1]
                # lbls = np.hstack(tracker.groups[2:4])
                # cxx = seg_deep.com(mean_residuals,  lbls)
                # gn = []
                # for i, k in enumerate(tracker.groups.sizes[2:4]):
                #     gn.extend([i] * k)

                # print('counts', counts[:np])
                print('gof', np.transpose(gofs))
                print('round', count, 'took:', time.time() - t0)
                # todo: measure locations, offsets again ????

                # break

                if count >= 3:  # TODO: decide based on GOF!
                    break

                # break

                # if np.equal(mask_all, tracker.mask_all).all():
                #     break

            # TODO: at this point a order search for splines would be justifiable

            # save the tracker & models for quick startup
            save_pickle(paths.tracker, tracker)
            save_pickle(paths.models, models)
            save_pickle(paths.start_idx, start)  # todo: eliminate

            # ֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍
            # # plot results of sample fits
            if args.plot:
                # TODO: plots in thread , so they actually draw while main
                #  compute is running

                # initial diagnostic images (for the modelled sample image)
                logger.info('Plotting individual model fits')

                # embed plots in multi tab window
                ui = MplMultiTab()
                for i, (ij0, image, params) in enumerate(
                        zip(indices_start, sample_images_to_model,
                            shared_memory.params)):
                    #
                    knots = get_knots_from_mem(shared_memory.knots, i, ishape)
                    model.set_knots(knots, preserve_labels=False)
                    seg, _ = model.segm.add_segments(
                            tracker.get_segments(ij0, ishape),
                            copy=True)
                    mimage = tracker.prepare_image(image, ij0)

                    # TODO: include ftb model here

                    fig = model.plot_fit_results(mimage, params, True, seg)
                    ui.add_tab(fig, '%i:%s' % (i, pairs[i]))

                ui.show()
            # ֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍֍

        # raise SystemExit

        # input('Musical interlude')
        # ᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏ
        # create shared memory
        # tracking data
        tracker.init_mem(subsize, paths.tracking, clobber=False)
        # note overwrite here since order of stars may change run-to-run
        # modelling results
        shared_memory = init_mem_modelling(model, paths.modelling, n_bg,
                                           n_ks, n_bright, n,
                                           clobber=clobber)
        # ᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏ

        # tracking camera movement
        # todo: print some initial info for tracking setup
        do_bg_sub = False
        if do_bg_sub:
            # global background subtraction
            # -----------------------------
            msg = f"""
            {motley.underline('Global background subtraction:')}
            Fit: Median images\t{NCOMB} frames per sample\t({n_bg} total)
            Knot optimization:\tEvery {KNOT_SEARCH_EVERY} frames\t\t({n_ks} total)
            """
            logger.info(msg)

            # note: since the shape of the data changes here from above, and the
            #  MedianEstimator model cannot handle this dynamically, need to
            #  manually change dof which is a bit hacky
            #  -todo: overwrite fit method??
            me = next(iter(ftb.models.values()))
            me.dof = (NCOMB, FTB_WIDTH)

            # since we are tracking on residuals, disable snr weighting scheme
            tracker.snr_weighting = False
            tracker._weights = None  # todo: automatically following line above
            tracker.snr_cut = 0

            # initialize sync
            tracker.counter = manager.Counter()
            tracker.sigma_rvec = manager.Array(tracker.sigma_rvec)
            # ensure recompute relative positions

            # //////////////////////////////////////////////////////////////////
            # background subtraction
            bgFitTask = task(n_bg, 3)(bgw)
            opt_kws = dict(method='leastsq')

            intervals = (np.array(pairs) / NCOMB).round().astype(int) * NCOMB
            intervals[0, 0] = 1  # handle frame zero independently
            intervals[-1, -1] = subset[1]  # last frame to process

            # # list(
            pool.starmap(background_loop,
                         ((interval, cube, tracker, start[i],
                           models, shared_memory, NCOMB, KNOT_SEARCH_EVERY,
                           BAD_PIXEL_MASK, opt_kws)
                          for i, interval in enumerate(intervals)))
            # )
            # //////////////////////////////////////////////////////////////////

        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        do_flat = False
        if do_flat:
            # flat field estimate
            label_faintest = tracker.groups[-1][0]
            segd = tracker.segm.data
            mask = (segd == 0) | (segd > label_faintest)
            tracker.cal_mask = ndimage.dilate(mask, 1)

            # fixable = BAD_PIXEL_MASK.copy()
            # fixable[:, 0] = False
            # flat = FlatFieldEstimator(paths.calib, fixable, manager.RLock(),
            #                           clobber=clobber)

            # //////////////////////////////////////////////////////////////////
            pool.starmap(aggregate_flat,
                         ((flat, cube, interval, tracker, start[i])
                          for i, interval in enumerate(pairs)))
            # //////////////////////////////////////////////////////////////////

            # add pixels from tail section of the cube (off target!)
            # l = np.isnan(tracker.xy_offsets).all(-1)
            # l[0] = False
            #
            # flat.aggregate(cube[l], BAD_PIXEL_MASK)
            # ff = flat.finalize()

        # TODO: log some stuff!!
        # if args.plot:
        # TODO: plot some results from the background fitting ....

        # todo groups in tracker actually for optimal_aperture_photometry. move?
        # OPT_SNR_BINS = [np.inf, 3, 1, -np.inf]
        # gi = np.digitize(snr_stars, OPT_SNR_BINS) - 1
        # groups = defaultdict(list)
        # for g, lbl in zip(gi, sh.labels):
        #     groups['stars%i' % g].append(lbl)
        # ngroups = len(groups)

        # exclude FTB regions
        g1 = tracker.groups[2]  # highest snr stars auto group
        group2 = np.setdiff1d(g1, tracker.groups.bright)

        tracker.masks.prepare(g1, tracker.groups.streaks)
        nstars = len(g1)

        gx = tracker.groups.copy()
        auto_groups = dict(zip(list(gx.keys())[2:], gx[2:]))
        tracker.groups = {'bright': tracker.groups.bright,
                          }  # 'meh': group2

        # tracker.masks.prepare(tracker.labels.bright)

        # TODO: set p0ap from image
        sky_width, sky_buf = 12, 2
        if args.apertures.startswith('c'):
            p0ap = (3,)
        else:
            p0ap = (3, 3, 0)

        # ᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏ
        # create shared memory      aperture photometry
        ngroups = 2
        proc.init_mem(n, nstars, ngroups, photPath, clobber=clobber)
        # ᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏᨏ

        # intervals[0, 0] = 0  # start from frame 0!!

        # //////////////////////////////////////////////////////////////////
        # photTask = task(subsize, '1%')(phot_worker)
        # pool.starmap(photTask,
        #              ((i, proc, cube, shared_memory.residuals, tracker,
        #                p0ap, sky_width, sky_buf)
        #               for i in range(*subset)))

        # //////////////////////////////////////////////////////////////////

        # THIS IS FOR DEBUGGING PICKLING ERRORS
        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        # import pickle
        # clone = pickle.loads(pickle.dumps(mdlr))
        #
        # for i in range(1000):
        #     if i % 10:
        #         print(i)
        #     proc.process(i, cube, calib, residue, coords, opt_stat,
        #                  tracker, clone, p0bg, p0ap, sky_width, sky_buf)
        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

        # rng = next(pairs)
        # proc_(rng, cube, residue, coords, opt_stat,tracker, mdlr, p0bg, p0ap, sky_width, sky_buf)

        # raise SystemExit

        # NOTE: This is for testing!!
        # with MemmappingPool(args.n_processes, initializer=log.worker_init,
        #                     initargs=(config_worker, )) as pool:
        #     results = pool.map(Task(test), range(*subset))

        # NOTE: This is for tracking!!
        # with MemmappingPool(args.n_processes, initializer=log.worker_init,
        #                     initargs=(config_worker, )) as pool:
        #     results = pool.starmap(bg_sub,
        #         ((chunk, cube.data, residue, coords, tracker, mdlr)
        #             for chunk in chunks))

        # NOTE: This is for photometry!
        # with MemmappingPool(args.n_processes, initializer=log.worker_init,
        #                     initargs=(config_worker,)) as pool:
        #     results = pool.starmap(
        #             Task(proc.proc1),
        #             ((i, cube.data, residue, coords, tracker, optstat,
        #               p0ap, sky_width, sky_buf)
        #              for i in range(*subset)))

        # from IPython import embed
        # embed()
        # raise SystemExit

        # NOTE: chunked sequential mapping (doesn't work if there are frame shifts)
        # chunks = mit.divide(args.n_processes, range(*subset))
        # with MemmappingPool(args.n_processes, initializer=log.worker_init,
        #                     initargs=(config_worker,)) as pool:
        #     results = pool.starmap(proc_,
        #             ((chunk, cube, residue, coords, opt_stat,
        #               tracker, mdlr, p0bg, p0ap,
        #               sky_width, sky_buf)
        #                 for chunk in chunks))

        # from IPython import embed
        # embed()
        #
        # raise SystemExit
        #
        # with MemmappingPool(args.n_processes, initializer=log.worker_init,
        #                     initargs=(config_worker,)) as pool:
        #     results = pool.starmap(proc_,
        #                            ((rng, cube, calib, residue, coords, opt_stat,
        #                              tracker, mdlr, p0bg, p0ap, sky_width,
        #                              sky_buf)
        #                             for rng in pairs))

        # with MemmappingPool(args.n_processes, initializer=log.worker_init,
        #                     initargs=(config_worker, )) as pool:
        #     results = pool.starmap(
        #         proc, ((i, cube.data, coords,
        #                 tracker, mdlr, cmb,
        #                 successes, failures,
        #                 counter, prgLog)
        #                 for i in range(*subset)))

        # get frame numbers of successes and failures

    except Exception as err:
        # catch errors so we can safely shut down the listeners
        logger.exception('Exception during parallel loop.')
        plot_diagnostics = False
        plot_lightcurves = False
    else:
        # put code here that that must be executed if the try clause does
        # not raise an exception
        # The use of the else clause is better than adding additional code to
        # the try clause because it avoids accidentally catching an exception
        # that wasn’t raised by the code being protected by the try … except
        # statement.

        # Hang around for the workers to finish their work.
        pool.close()
        pool.join()
        logger.info('Workers done')  # Logging in the parent still works
        chronos.mark('Main compute')

        # Workers all done, listening can now stop.
        logger.info('Telling listener to stop ...')
        stop_logging_event.set()
        logListener.join()
    finally:
        # A finally clause is always executed before leaving the try statement,
        # whether an exception has occurred or not.
        # any unhandled exceptions will be raised after finally clause,
        # basically only KeyboardInterrupt for now.

        # check task status
        # failures = Task.report()  # FIXME:  we sometimes get stuck here
        # TODO: print opt failures

        chronos.mark('Process shutdown')

        # diagnostics
        if plot_diagnostics:
            # TODO: GUI
            # TODO: if interactive dock figs together
            # dock for figures
            # connect ts plots with frame display

            from obstools.phot.diagnostics import new_diagnostics, save_figures
            from obstools.phot.gui import ApertureVizGui

            coords = tracker.get_coords()
            figs = new_diagnostics(coords, tracker.rcoo[tracker.ir],
                                   proc.appars, proc.status)
            if args.live:
                for fig, name in figs.items():
                    idisplay(fig)

            save_figures(figs, paths.figures)
            #
            #     # GUI
            #     from obstools.phot.gui_dev import FrameProcessorGUI
            #
            #     gui = FrameProcessorGUI(cube, coords, tracker, mdlr, proc.Appars,
            #                             residue, clim_every=1e6)

            v = ApertureVizGui(residue, tracker,
                               proc.Appars.stars, proc.Appars.sky)

        #
        if plot_lightcurves:
            from obstools.phot.diagnostics import plot_aperture_flux

            figs = plot_aperture_flux(data_path, proc, tracker)
            save_figures(figs, paths.figures)

            # write light curves to ascii
            # obj_name = 'J061451.7-272535'
            # timePath = data_path.with_suffix('.time')
            # timeData = np.rec.array(
            #         np.genfromtxt(timePath, dtype=None, names=True)
            # )
            #
            # meta = {'Timing info': dict(BJD=timeData.bjd[0])}
            # sidsec = timeData.lmst * 3600
            #
            # lcPath = photPath / 'lc.dat'
            # proc.write_lightcurve_ascii(sidsec, None, meta, obj_name )

        chronos.mark('Diagnostics')
        chronos.report()  # TODO: improve report formatting

        if not args.live:
            # try:
            # from _qtconsole import qtshell  # FIXME
            # qtshell(vars())
            # except Exception as err:
            from IPython import embed

            embed()

    # with mp.Pool(10, worker_logging_init, (config_worker, )) as pool:   # , worker_logging_init, (q, logmix)
    #     results = pool.starmap(
    #         work, ((i, counter, prgLog)
    #                for i in range(n)))

    # #
    # import sys
    # from recipes.io.utils import TracePrints
    # sys.stdout = TracePrints()

    # n = 50
    # with Parallel(n_jobs=8, verbose=0, initializer=worker_logging_init,
    #               initargs=(counter, config_worker)) as parallel: #)) as parallel:#
    #     results = parallel(
    #         delayed(work)(i)#, cube.data, tracker, mdlr, counter, residue)
    #         for i in range(n))

    # sys.stdout = sys.stdout.stdout

# if __name__ == '__main__':
#     main()
# ⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡
