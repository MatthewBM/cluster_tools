import os
from concurrent import futures
from itertools import product

import numpy as np
import imageio
from z5py.shape_utils import normalize_slices


class KnossosDataset(object):
    block_size = 128

    @staticmethod
    def _chunks_dim(dim_root):
        files = os.listdir(dim_root)
        files = [f for f in files if os.path.isdir(os.path.join(dim_root, f))]
        return len(files)

    def get_shape_and_grid(self):
        cx = self._chunks_dim(self.path)
        y_root = os.path.join(self.path, 'x0000')
        cy = self._chunks_dim(y_root)
        z_root = os.path.join(y_root, 'y0000')
        cz = self._chunks_dim(z_root)

        grid = (cz, cy, cx)
        shape = tuple(sh * self.block_size for sh in grid)
        return shape, grid

    def __init__(self, path, file_prefix, load_png):
        self.path = path
        self.ext = 'png' if load_png else 'jpg'
        self.file_prefix = file_prefix

        self._ndim = 3
        self._chunks = self._ndim * (self.block_size,)
        self._shape, self._grid = self.get_shape_and_grid()
        self.n_threads = 1

    @property
    def dtype(self):
        return 'uint8'

    @property
    def ndim(self):
        return self._ndim

    @property
    def chunks(self):
        return self._chunks

    @property
    def shape(self):
        return self._shape

    def load_block(self, grid_id):
        # NOTE need to reverse grid id, because knossos folders are stored in x, y, z order
        block_path = ['%s%04i' % (dim, gid) for dim, gid in zip(('x', 'y', 'z'),
                                                                grid_id[::-1])]
        dim_str = '_'.join(block_path)
        fname = '%s_%s.%s' % (self.file_prefix, dim_str, self.ext)
        block_path.append(fname)
        path = os.path.join(self.path, *block_path)
        data = np.array(imageio.imread(path)).reshape(self._chunks)
        return data

    def coords_in_roi(self, grid_id, roi):
        # block begins and ends
        block_begin = [gid * self.block_size for gid in grid_id]
        block_end = [beg + ch for beg, ch in zip(block_begin, self.chunks)]

        # get roi begins and ends
        roi_begin = [rr.start for rr in roi]
        roi_end = [rr.stop for rr in roi]

        tile_bb, out_bb = [], []
        # iterate over dimensions and find the bb coordinates
        for dim in range(3):
            # calculate the difference between the block begin / end
            # and the roi begin / end
            off_diff = block_begin[dim] - roi_begin[dim]
            end_diff = roi_end[dim] - block_end[dim]

            # if the offset difference is negative, we are at a starting block
            # that is not completely overlapping
            # -> set all values accordingly
            if off_diff < 0:
                begin_in_roi = 0  # start block -> no local offset
                begin_in_block = -off_diff
                # if this block is the beginning block as well as the end block,
                # we need to adjust the local shape accordingly
                shape_in_roi = block_end[dim] - roi_begin[dim]\
                    if block_end[dim] <= roi_end[dim] else roi_end[dim] - roi_begin[dim]

            # if the end difference is negative, we are at a last block
            # that is not completely overlapping
            # -> set all values accordingly
            elif end_diff < 0:
                begin_in_roi = block_begin[dim] - roi_begin[dim]
                begin_in_block = 0
                shape_in_roi = roi_end[dim] - block_begin[dim]

            # otherwise we are at a completely overlapping block
            else:
                begin_in_roi = block_begin[dim] - roi_begin[dim]
                begin_in_block = 0
                shape_in_roi = self.chunks[dim]

            # append to bbs
            tile_bb.append(slice(begin_in_block, begin_in_block + shape_in_roi))
            out_bb.append(slice(begin_in_roi, begin_in_roi + shape_in_roi))

        return tuple(tile_bb), tuple(out_bb)

    def _load_roi(self, roi):
        # snap roi to grid
        ranges = [range(rr.start // self.block_size,
                        rr.stop // self.block_size if
                        rr.stop % self.block_size == 0 else rr.stop // self.block_size + 1)
                  for rr in roi]
        grid_points = product(*ranges)

        # init data (dtype is hard-coded to uint8)
        roi_shape = tuple(rr.stop - rr.start for rr in roi)
        data = np.zeros(roi_shape, dtype='uint8')

        def load_tile(grid_id):
            tile_data = self.load_block(grid_id)
            tile_bb, out_bb = self.coords_in_roi(grid_id, roi)
            data[out_bb] = tile_data[tile_bb]

        if self.n_threads > 1:
            with futures.ThreadPoolExecutor(self.n_threads) as tp:
                tasks = [tp.submit(load_tile, sp) for sp in grid_points]
                [t.result() for t in tasks]
        else:
            [load_tile(sp) for sp in grid_points]
        #
        return data

    def __getitem__(self, index):
        roi = normalize_slices(index, self.shape)
        return self._load_roi(roi)


class KnossosFile(object):
    """ Wrapper for knossos file structure
    """
    def __init__(self, path, load_png=True):
        if not os.path.exists(os.path.join(path, 'mag1')):
            raise RuntimeError("Not a knossos file structure")
        self.path = path
        self.load_png = load_png
        self.file_name = os.path.split(self.path)[1]

    def __getitem__(self, key):
        ds_path = os.path.join(self.path, key)
        if not os.path.exists(ds_path):
            raise ValueError("Invalid key %s" % key)
        file_prefix = '%s_%s' % (self.file_name, key)
        return KnossosDataset(ds_path, file_prefix, self.load_png)
